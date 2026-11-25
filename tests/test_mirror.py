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
    assert all(p["u"] == ([1] if p["k"]["year"] == "2020" else [0]) for p in m["partitions"]), "per-partition source urls"


def test_chunks_split_by_uncompressed_bytes(stub_entry, tmp_path, monkeypatch):
    # wide rows: a chunk must stay small enough for the Worker to gunzip in memory
    monkeypatch.setattr(mirror, "MAX_CHUNK_BYTES", 1)
    m = mirror.ingest(stub_entry, tmp_path, log=lambda *a: None)
    tx2020 = [p for p in m["partitions"] if p["k"] == {"year": "2020", "state": "TX"}]
    assert [(p["c"], p["r"]) for p in tx2020] == [(0, 1), (1, 1)]
    assert m["row_count"] == 8


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


def test_publish_resume_skips_uploaded_packs(stub_entry, tmp_path, monkeypatch):
    monkeypatch.setattr(mirror, "PACK_TARGET_BYTES", 1)  # one pack per partition chunk
    m = mirror.ingest(stub_entry, tmp_path, log=lambda *a: None)
    assert len(m["packs"]) > 2

    class FakeR2:
        def __init__(self):
            self.objects, self.puts = {}, []

        def put(self, key, data, content_type="application/octet-stream"):
            self.puts.append(key)
            self.objects[key] = data

        def list(self, prefix):
            return [k for k in self.objects if k.startswith(prefix)]

        def delete(self, key):
            self.objects.pop(key, None)

        def get(self, key):
            return self.objects.get(key)

    r2 = FakeR2()
    prefix = f"mirror/stub/{m['release']}/"
    r2.objects[prefix + m["packs"][0]] = b"uploaded before the cut-off"
    mirror.publish(stub_entry, tmp_path, r2, log=lambda *a: None, resume=True)
    assert prefix + m["packs"][0] not in r2.puts
    assert [k for k in r2.puts if k.endswith(".bin")] == [prefix + p for p in m["packs"][1:]]
    assert r2.puts[-1] == "mirror/stub/current.json"
    r2.puts.clear()
    mirror.publish(stub_entry, tmp_path, r2, log=lambda *a: None)   # default: upload everything
    assert len([k for k in r2.puts if k.endswith(".bin")]) == len(m["packs"])


def test_private_columns_hide_example_values(stub_entry, tmp_path, monkeypatch):
    monkeypatch.setattr(StubAdapter, "mirror_private_columns", ["state"], raising=False)
    m = mirror.ingest(stub_entry, tmp_path, log=lambda *a: None)
    assert not {"min", "max", "values"} & set(m["columns"]["state"]), m["columns"]["state"]
    assert m["columns"]["state"]["type"] == "string"
    assert "min" in m["columns"]["value"]


def test_cleanup_never_deletes_live_release():
    """A resumed ingest can publish a release id that sorts before newer ones; it must survive cleanup."""
    class FakeR2:
        def __init__(self):
            self.objects = {f"mirror/s/{r}/manifest.json": b"{}" for r in ("20260101T000000Z", "20260201T000000Z", "20260301T000000Z")}
            self.objects["mirror/s/current.json"] = json.dumps({"release": "20260101T000000Z"}).encode()

        def list(self, prefix):
            return [k for k in self.objects if k.startswith(prefix)]

        def delete(self, key):
            self.objects.pop(key)

        def get(self, key):
            return self.objects.get(key)

    r2 = FakeR2()
    mirror._cleanup("s", r2, log=lambda *a: None)
    left = sorted(k.split("/")[2] for k in r2.objects if k.endswith("manifest.json"))
    assert left == ["20260101T000000Z", "20260301T000000Z"], left


def test_non_finite_floats_become_null(stub_entry, tmp_path, monkeypatch):
    """NaN/Infinity are not JSON; the Worker's JSON.parse would reject the partition (and a NaN min/max the manifest)."""
    def _fetch(self, f, limit, cache_allowed):
        return FetchResult([{"year": f["year"], "state": "TX", "value": float("nan")},
                            {"year": f["year"], "state": "TX", "value": float("inf")},
                            {"year": f["year"], "state": "TX", "value": 1.5}], ["https://example.gov/x.csv"])
    monkeypatch.setattr(StubAdapter, "_fetch", _fetch)
    m = mirror.ingest(stub_entry, tmp_path, log=lambda *a: None)
    raw = (tmp_path / "manifest.json").read_text()
    assert "NaN" not in raw and "Infinity" not in raw
    p = m["partitions"][0]
    with open(tmp_path / m["packs"][p["p"]], "rb") as fh:
        fh.seek(p["o"])
        text = gzip.decompress(fh.read(p["n"])).decode()
    assert "NaN" not in text and "Infinity" not in text
    assert [json.loads(x)["value"] for x in text.splitlines()] == [None, None, 1.5]
    assert m["columns"]["value"]["nulls"] == 4 and m["columns"]["value"]["min"] == 1.5


def test_publish_refuses_to_flip_to_incomplete_release(stub_entry, tmp_path):
    mirror.ingest(stub_entry, tmp_path, log=lambda *a: None)

    class LossyR2:
        """Drops pack uploads, as if a concurrent publisher's cleanup deleted them mid-upload."""
        def __init__(self):
            self.objects = {}

        def put(self, key, data, content_type="application/octet-stream"):
            if not key.endswith(".bin"):
                self.objects[key] = data

        def list(self, prefix):
            return [k for k in self.objects if k.startswith(prefix)]

        def delete(self, key):
            self.objects.pop(key, None)

        def get(self, key):
            return self.objects.get(key)

    r2 = LossyR2()
    with pytest.raises(Exception, match="missing"):
        mirror.publish(stub_entry, tmp_path, r2, log=lambda *a: None)
    assert "mirror/stub/current.json" not in r2.objects


def test_due_check_error_does_not_stop_the_run(cat, monkeypatch, tmp_path):
    ids = sorted(sid for sid, e in cat.entries.items() if mirror.mirrorable(e))[:2]
    assert len(ids) == 2
    monkeypatch.setattr(mirror, "R2", lambda: object())
    calls = []

    def fake_due(entry, r2):
        calls.append(entry["id"])
        if entry["id"] == ids[0]:
            raise RuntimeError("R2 GET -> 503")
        return False, "up to date"

    monkeypatch.setattr(mirror, "due", fake_due)
    rc = mirror.run(ids, only_due=True, dry_run=False, log=lambda *a: None, report_path=tmp_path / "r.json")
    report = json.loads((tmp_path / "r.json").read_text())
    assert rc == 1 and calls == ids
    assert [f["source_id"] for f in report["failed"]] == [ids[0]]
    assert [s["source_id"] for s in report["skipped"]] == [ids[1]]
