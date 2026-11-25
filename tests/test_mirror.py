"""Offline tests for the mirror ingest format (src/odc/mirror.py). worker/test/mirror.test.ts reads the same format."""
import copy
import gzip
import json

import pytest

from odc import mirror
from odc.adapters.base import ContractCase, FetchResult, FilterSpec, SourceAdapter


class StubAdapter(SourceAdapter):
    source_id = "stub"
    version = "1.0.0"
    usage = "stub adapter for mirror tests"
    filters = [FilterSpec("year", "integer", "year to fetch", required=True)]
    contract = [ContractCase("c", {"year": 2020})]
    mirror_partition_keys = ["year", "state"]
    mirror_semantics = {"state": "state_postal"}

    def _fetch(self, f, limit, cache_allowed):
        rows = [{"year": f["year"], "state": s, "value": i} for i, s in enumerate(["TX", "CA", "TX", None])]
        return FetchResult(rows, [f"https://example.gov/{f['year']}.csv"], notes=["n1"], metadata={"labels": {"value": "v"}})

    def mirror_plan(self):
        for y in (2019, 2020):
            yield mirror.MirrorUnit({"year": str(y)}, {"year": y}, split_by=["state"])


@pytest.fixture()
def stub_entry(cat, monkeypatch):
    e = copy.deepcopy(next(e for e in cat.entries.values() if e["license"]["redistribution"] == "allowed" and e["adapter"]))
    e.update(id="stub", adapter="stub")
    e["change_detection"] = {"method": "none", "poll_interval_days": 7}
    monkeypatch.setattr(mirror, "adapter_for", lambda entry: StubAdapter())
    return e


def read_part(out, m, p):
    with open(out / m["packs"][p["p"]], "rb") as fh:
        fh.seek(p["o"])
        return [json.loads(x) for x in gzip.decompress(fh.read(p["n"])).decode().splitlines()]


def test_ingest_roundtrip(stub_entry, tmp_path, monkeypatch):
    monkeypatch.setattr(mirror, "MAX_PARTITION_ROWS", 1)  # force chunking
    m = mirror.ingest(stub_entry, tmp_path, log=lambda *a: None)
    assert m["row_count"] == 8
    assert json.loads((tmp_path / "manifest.json").read_text())["release"] == m["release"]
    keys = {json.dumps(p["k"], sort_keys=True) for p in m["partitions"]}
    assert len(keys) == 6  # 2 years x {TX, CA, ""}
    tx2020 = [p for p in m["partitions"] if p["k"] == {"year": "2020", "state": "TX"}]
    assert [p["c"] for p in tx2020] == [0, 1], "TX has 2 rows -> 2 chunks of 1"
    rows = [r for p in tx2020 for r in read_part(tmp_path, m, p)]
    assert [r["value"] for r in rows] == [0, 2]
    assert m["columns"]["value"]["type"] == "integer" and m["columns"]["state"]["nulls"] == 2
    assert m["metadata"] == {"labels": {"value": "v"}} and m["notes"] == ["n1"]
    assert m["partition_keys"] == ["year", "state"] and m["semantics"] == {"state": "state_postal"}
    assert m["upstream"]["urls"] == ["https://example.gov/2019.csv", "https://example.gov/2020.csv"]


def test_pack_rollover(stub_entry, tmp_path, monkeypatch):
    monkeypatch.setattr(mirror, "PACK_TARGET_BYTES", 10)
    m = mirror.ingest(stub_entry, tmp_path, log=lambda *a: None)
    assert len(m["packs"]) > 1
    for p in m["partitions"]:
        assert read_part(tmp_path, m, p)


def test_overlapping_units_rejected(stub_entry, tmp_path, monkeypatch):
    monkeypatch.setattr(StubAdapter, "mirror_plan", lambda self: iter([mirror.MirrorUnit({"year": "1"}, {"year": 1}, ["state"])] * 2))
    with pytest.raises(ValueError, match="two units"):
        mirror.ingest(stub_entry, tmp_path, log=lambda *a: None)


def test_mirrorable_requires_allowed_license(cat):
    for sid, e in cat.entries.items():
        if mirror.mirrorable(e):
            assert e["license"]["redistribution"] == "allowed", sid


def test_resume_after_interruption(stub_entry, tmp_path, monkeypatch):
    full = mirror.ingest(stub_entry, tmp_path / "full", log=lambda *a: None)

    calls = {"n": 0}
    real = StubAdapter.mirror_rows

    def flaky(self, unit):
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt  # killed while ingesting the second unit
        return real(self, unit)

    out = tmp_path / "resumed"
    monkeypatch.setattr(StubAdapter, "mirror_rows", flaky)
    with pytest.raises(KeyboardInterrupt):
        mirror.ingest(stub_entry, out, log=lambda *a: None, resume=True)
    ckpt = json.loads((out / mirror.CHECKPOINT).read_text())
    assert ckpt["done"] == 1
    with open(out / "pack-0.bin", "ab") as fh:  # bytes written after the checkpoint must be dropped
        fh.write(b"partial")

    m = mirror.ingest(stub_entry, out, log=lambda *a: None, resume=True)
    assert calls["n"] == 3, "the finished unit is not re-run"
    assert not (out / mirror.CHECKPOINT).exists()
    assert m["release"] == ckpt["release"]
    assert m["row_count"] == full["row_count"] and m["columns"] == full["columns"]
    assert [p["k"] for p in m["partitions"]] == [p["k"] for p in full["partitions"]]
    assert m["pack_bytes"] == full["pack_bytes"]
    for p, q in zip(m["partitions"], full["partitions"]):
        assert read_part(out, m, p) == read_part(tmp_path / "full", full, q)
    # a finished out_dir is reused as is (lets a publish that was cut off be retried)
    assert mirror.ingest(stub_entry, out, log=lambda *a: None, resume=True)["release"] == m["release"]
    assert calls["n"] == 3
