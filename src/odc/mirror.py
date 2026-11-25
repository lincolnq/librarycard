"""Mirror ingest: download a source once per upstream release, partition it, and publish it to R2.

Why: serving `fetch` by streaming whole publisher files per request is slow and costly. Sources whose
license allows redistribution (`license.redistribution == "allowed"`) are mirrored; the production MCP
server (worker/) answers `fetch` by range-reading only the partitions a query needs.

R2 layout (bucket ODC_R2_BUCKET):
  mirror/<source_id>/current.json                       {"release": ..., "manifest": <key>}
  mirror/<source_id>/<release>/manifest.json            see build_manifest()
  mirror/<source_id>/<release>/pack-<n>.bin             concatenated gzip members, one per partition

A partition is a set of rows sharing the same values for the source's partition keys (e.g. table+geography+state).
Each partition is stored as one gzip member of newline-delimited JSON; the manifest records
(pack, offset, length, rows) so a reader can fetch exactly that byte range.

Adapters opt in by defining `mirror_plan()` (see base.SourceAdapter). Rows in the mirror are exactly the
rows the adapter's `fetch` returns, so describe/fetch semantics are identical between modes.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import shutil
import tempfile
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .adapters import adapter_for
from .adapters.base import SourceAdapter
from .catalog import Catalog
from .changes import fingerprint
from .r2 import R2

FORMAT = 1
PACK_TARGET_BYTES = 90_000_000      # stay under the R2 REST upload limit
MAX_PARTITION_ROWS = 100_000        # larger partitions are split into chunks (same key, several entries)
MAX_OPEN_FILES = 200
KEEP_RELEASES = 2
DISTINCT_LIMIT = 60


@dataclass
class MirrorUnit:
    """One slice of the dataset: fetch it with `filters`, label its rows with `partition`, and
    optionally sub-partition rows by the values of `split_by` columns."""
    partition: dict[str, str]
    filters: dict
    split_by: list[str] = field(default_factory=list)


def mirrorable(entry: dict) -> bool:
    if not entry.get("adapter") or entry["status"] not in ("healthy", "degraded"):
        return False
    if entry["license"]["redistribution"] != "allowed":
        return False
    a = adapter_for(entry)
    return type(a).mirror_plan is not SourceAdapter.mirror_plan


# ------------------------------------------------------------------ column stats

class ColumnStats:
    def __init__(self):
        self.types: set[str] = set()
        self.nulls = 0
        self.count = 0
        self.min: Any = None
        self.max: Any = None
        self.distinct: set = set()
        self.too_many = False

    def add(self, v: Any) -> None:
        self.count += 1
        if v is None or v == "":
            self.nulls += 1
            return
        t = ("boolean" if isinstance(v, bool) else "integer" if isinstance(v, int) else
             "number" if isinstance(v, float) else "string" if isinstance(v, str) else "json")
        self.types.add(t)
        if t in ("integer", "number", "string"):
            try:
                if self.min is None or v < self.min:
                    self.min = v
                if self.max is None or v > self.max:
                    self.max = v
            except TypeError:
                pass
        if not self.too_many and t != "json":
            self.distinct.add(v)
            if len(self.distinct) > DISTINCT_LIMIT:
                self.too_many = True
                self.distinct = set()

    def summary(self) -> dict:
        types = self.types or {"null"}
        t = "number" if types == {"integer", "number"} else (types.pop() if len(types) == 1 else "mixed")
        out: dict[str, Any] = {"type": t, "nulls": self.nulls}
        if self.min is not None and t in ("integer", "number", "string"):
            out["min"], out["max"] = self.min, self.max
        if not self.too_many and self.distinct:
            out["values"] = sorted(self.distinct, key=lambda x: (str(type(x)), x))
        return out


# ------------------------------------------------------------------ partition spooling

class Spool:
    """Append rows to one temp NDJSON file per partition key, with a bounded number of open handles."""

    def __init__(self, root: Path):
        self.root = root
        self.files: dict[str, Path] = {}
        self.keys: dict[str, dict] = {}
        self.counts: dict[str, int] = {}
        self.open: OrderedDict[str, Any] = OrderedDict()

    def write(self, key: dict, row: dict) -> None:
        k = json.dumps(key, sort_keys=True)
        if k not in self.files:
            self.files[k] = self.root / f"p{len(self.files)}.ndjson"
            self.keys[k] = key
            self.counts[k] = 0
        fh = self.open.get(k)
        if fh is None:
            if len(self.open) >= MAX_OPEN_FILES:
                _, old = self.open.popitem(last=False)
                old.close()
            fh = open(self.files[k], "a", encoding="utf-8")
            self.open[k] = fh
        else:
            self.open.move_to_end(k)
        fh.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False, default=str) + "\n")
        self.counts[k] += 1

    def close(self) -> None:
        for fh in self.open.values():
            fh.close()
        self.open.clear()


# ------------------------------------------------------------------ ingest

def ingest(entry: dict, out_dir: Path, log=print) -> dict:
    """Run the adapter's mirror plan and write packs + manifest into out_dir. Returns the manifest."""
    adapter = adapter_for(entry)
    release = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    started = time.time()
    upstream_fp, upstream_detail = None, None
    if entry["change_detection"]["method"] != "none":
        try:
            upstream_fp, upstream_detail = fingerprint(entry["change_detection"])
        except Exception as e:  # noqa: BLE001 - recorded, not fatal
            upstream_detail = f"fingerprint failed: {e}"
    work = Path(tempfile.mkdtemp(prefix="odc-mirror-"))
    spool = Spool(work)
    stats: dict[str, ColumnStats] = {}
    urls: list[str] = []
    notes: list[str] = []
    metadata: dict[str, Any] = {}
    partition_keys: list[str] = list(adapter.mirror_partition_keys)
    try:
        units = list(adapter.mirror_plan())
        for i, unit in enumerate(units, 1):
            t0 = time.time()
            rows, u_urls, u_notes, u_meta = adapter.mirror_rows(unit)
            n = 0
            for row in rows:
                key = dict(unit.partition)
                for c in unit.split_by:
                    v = row.get(c)
                    key[c] = "" if v is None else str(v)
                spool.write(key, row)
                for c, v in row.items():
                    stats.setdefault(c, ColumnStats()).add(v)
                n += 1
            urls += [u for u in u_urls if u not in urls]
            notes += [x for x in u_notes if x not in notes]
            _merge_meta(metadata, u_meta)
            log(f"  [{i}/{len(units)}] {unit.partition} -> {n} rows ({time.time() - t0:.1f}s)")
        spool.close()
        missing = [k for k in partition_keys if any(k not in key for key in spool.keys.values())]
        if missing:
            raise ValueError(f"mirror_partition_keys {missing} not set on every partition; fix mirror_plan/split_by")
        manifest = _pack(entry, adapter, spool, out_dir, release)
    finally:
        spool.close()
        shutil.rmtree(work, ignore_errors=True)
    lic = entry["license"]
    manifest.update({
        "upstream": {"urls": urls[:200], "fingerprint": upstream_fp, "detail": upstream_detail},
        "license": {k: lic[k] for k in ("name", "url", "redistribution", "commercial_use", "attribution")},
        "partition_keys": partition_keys,
        "required_filters": list(adapter.mirror_required),
        "semantics": dict(adapter.mirror_semantics),
        "columns": {c: s.summary() for c, s in stats.items()},
        "notes": notes,
        "metadata": metadata,
        "ingest_seconds": round(time.time() - started, 1),
    })
    (out_dir / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":"), default=str))
    return manifest


def _merge_meta(into: dict, new: dict) -> None:
    for k, v in (new or {}).items():
        if isinstance(v, dict) and isinstance(into.get(k), dict):
            into[k].update(v)
        elif k not in into:
            into[k] = v


def _pack(entry: dict, adapter: SourceAdapter, spool: Spool, out_dir: Path, release: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    packs: list[str] = []
    pack_fh = None
    pack_size = 0

    def new_pack():
        nonlocal pack_fh, pack_size
        if pack_fh:
            pack_fh.close()
        name = f"pack-{len(packs)}.bin"
        packs.append(name)
        pack_fh = open(out_dir / name, "wb")
        pack_size = 0

    new_pack()
    order = sorted(spool.files, key=lambda k: json.dumps(spool.keys[k], sort_keys=True))
    total = 0
    for k in order:
        with open(spool.files[k], encoding="utf-8") as fh:
            chunk: list[str] = []
            chunk_no = 0

            def flush():
                nonlocal pack_size, chunk_no, total
                if not chunk:
                    return
                blob = gzip.compress("".join(chunk).encode("utf-8"), compresslevel=6, mtime=0)
                if pack_size and pack_size + len(blob) > PACK_TARGET_BYTES:
                    new_pack()
                pack_fh.write(blob)
                parts.append({"k": spool.keys[k], "c": chunk_no, "p": len(packs) - 1, "o": pack_size,
                              "n": len(blob), "r": len(chunk)})
                pack_size += len(blob)
                total += len(chunk)
                chunk.clear()
                chunk_no += 1

            for line in fh:
                chunk.append(line)
                if len(chunk) >= MAX_PARTITION_ROWS:
                    flush()
            flush()
    pack_fh.close()
    return {
        "format": FORMAT,
        "source_id": entry["id"],
        "release": release,
        "ingested_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "adapter_version": adapter.version,
        "row_count": total,
        "packs": packs,
        "pack_bytes": [os.path.getsize(out_dir / p) for p in packs],
        "partitions": parts,
    }


# ------------------------------------------------------------------ publish

def publish(entry: dict, out_dir: Path, r2: R2, log=print) -> str:
    """Upload packs, then the manifest, then flip current.json (readers never see a half-written release)."""
    manifest = json.loads((out_dir / "manifest.json").read_text())
    sid, release = entry["id"], manifest["release"]
    prefix = f"mirror/{sid}/{release}/"
    for p in manifest["packs"]:
        r2.put(prefix + p, out_dir / p)
        log(f"  uploaded {prefix}{p} ({(out_dir / p).stat().st_size / 1e6:.1f} MB)")
    r2.put(prefix + "manifest.json", out_dir / "manifest.json", "application/json")
    current = {"release": release, "manifest": prefix + "manifest.json", "ingested_at": manifest["ingested_at"],
               "row_count": manifest["row_count"], "upstream_fingerprint": manifest["upstream"]["fingerprint"],
               "adapter_version": manifest["adapter_version"]}
    r2.put(f"mirror/{sid}/current.json", json.dumps(current).encode(), "application/json")
    _cleanup(sid, r2, log)
    return prefix


def _cleanup(sid: str, r2: R2, log=print) -> None:
    keys = r2.list(f"mirror/{sid}/")
    releases = sorted({k.split("/")[2] for k in keys if k.count("/") >= 3})
    for old in releases[:-KEEP_RELEASES]:
        for k in keys:
            if k.startswith(f"mirror/{sid}/{old}/"):
                r2.delete(k)
        log(f"  deleted old release {old}")


def current(sid: str, r2: R2) -> dict | None:
    raw = r2.get(f"mirror/{sid}/current.json")
    return json.loads(raw) if raw else None


def due(entry: dict, r2: R2, max_age_days: int = 30) -> tuple[bool, str]:
    """Is a (re-)ingest needed? Missing mirror, upstream fingerprint moved, adapter version changed, or too old."""
    cur = current(entry["id"], r2)
    if not cur:
        return True, "no mirror yet"
    if cur.get("adapter_version") != entry["adapter_version"]:
        return True, f"adapter version {cur.get('adapter_version')} -> {entry['adapter_version']}"
    age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(cur["ingested_at"])
    if age.days >= max_age_days:
        return True, f"mirror is {age.days} days old"
    if entry["change_detection"]["method"] != "none":
        try:
            fp, _ = fingerprint(entry["change_detection"])
        except Exception as e:  # noqa: BLE001
            return False, f"fingerprint failed ({e}); keeping current mirror"
        if fp != cur.get("upstream_fingerprint"):
            return True, "upstream changed"
    return False, "up to date"


def run(source_ids: list[str] | None, only_due: bool, dry_run: bool, out_root: Path | None = None, log=print) -> int:
    cat = Catalog.load()
    ids = source_ids or sorted(sid for sid, e in cat.entries.items() if mirrorable(e))
    r2 = None if dry_run else R2()
    failures = 0
    for sid in ids:
        e = cat.get(sid)
        if not mirrorable(e):
            log(f"skip {sid}: not mirrorable (needs adapter with mirror_plan, healthy/degraded, redistribution: allowed)")
            continue
        if only_due and r2 is not None:
            is_due, why = due(e, r2)
            if not is_due:
                log(f"skip {sid}: {why}")
                continue
            log(f"{sid}: due ({why})")
        out = (out_root or Path(tempfile.mkdtemp(prefix="odc-pack-"))) / sid
        try:
            log(f"ingest {sid}")
            m = ingest(e, out, log)
            log(f"  {m['row_count']} rows, {len(m['partitions'])} partitions, "
                f"{sum(m['pack_bytes']) / 1e6:.1f} MB in {m['ingest_seconds']}s")
            if not dry_run:
                publish(e, out, r2, log)
        except Exception as ex:  # noqa: BLE001 - keep going; the monitor reports failures
            failures += 1
            log(f"FAILED {sid}: {type(ex).__name__}: {ex}")
        finally:
            if out_root is None:
                shutil.rmtree(out.parent, ignore_errors=True)
    return 1 if failures else 0
