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
import hashlib
import json
import math
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
from .http import SourceError
from .r2 import R2

FORMAT = 1
PACK_TARGET_BYTES = 90_000_000      # stay under the R2 REST upload limit
MAX_PARTITION_ROWS = 100_000        # larger partitions are split into chunks (same key, several entries)
MAX_CHUNK_BYTES = 16_000_000        # ...and so are chunks over this many uncompressed bytes: the Worker gunzips a whole
                                    # chunk in memory (128 MB isolate limit), so wide rows need smaller chunks
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

    def to_json(self) -> dict:
        return {"types": sorted(self.types), "nulls": self.nulls, "count": self.count, "min": self.min, "max": self.max,
                "distinct": list(self.distinct), "too_many": self.too_many}

    @classmethod
    def from_json(cls, d: dict) -> "ColumnStats":
        s = cls()
        s.types, s.nulls, s.count, s.min, s.max = set(d["types"]), d["nulls"], d["count"], d["min"], d["max"]
        s.distinct, s.too_many = set(d["distinct"]), d["too_many"]
        return s

    def summary(self) -> dict:
        types = self.types or {"null"}
        t = "number" if types == {"integer", "number"} else (types.pop() if len(types) == 1 else "mixed")
        out: dict[str, Any] = {"type": t, "nulls": self.nulls}
        if self.min is not None and t in ("integer", "number", "string"):
            out["min"], out["max"] = self.min, self.max
        if not self.too_many and self.distinct:
            out["values"] = sorted(self.distinct, key=lambda x: (str(type(x)), x))
        return out


def _private(summary: dict) -> dict:
    """Column summary without example values (min/max/values would expose individuals' names in describe_source)."""
    return {k: v for k, v in summary.items() if k not in ("min", "max", "values")}


# ------------------------------------------------------------------ partition spooling

class Spool:
    """Append rows to one temp NDJSON file per partition key, with a bounded number of open handles."""

    def __init__(self, root: Path):
        self.root = root
        self.files: dict[str, Path] = {}
        self.keys: dict[str, dict] = {}
        self.counts: dict[str, int] = {}
        self.open: OrderedDict[str, Any] = OrderedDict()

    def write(self, key: dict, row: dict) -> dict:
        """Spool one row; returns the row as stored (NaN/Infinity floats become null)."""
        try:
            line = json.dumps(row, separators=(",", ":"), ensure_ascii=False, default=str, allow_nan=False)
        except ValueError:
            # Python would write NaN/Infinity, which is not JSON: the Worker's JSON.parse would fail the whole fetch.
            row = {c: (None if isinstance(v, float) and not math.isfinite(v) else v) for c, v in row.items()}
            line = json.dumps(row, separators=(",", ":"), ensure_ascii=False, default=str, allow_nan=False)
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
        fh.write(line + "\n")
        self.counts[k] += 1
        return row

    def close(self) -> None:
        for fh in self.open.values():
            fh.close()
        self.open.clear()


# ------------------------------------------------------------------ ingest

CHECKPOINT = ".checkpoint.json"


def ingest(entry: dict, out_dir: Path, log=print, resume: bool = False) -> dict:
    """Run the adapter's mirror plan and write packs + manifest into out_dir. Returns the manifest.

    resume=True continues an interrupted ingest in the same out_dir: after each unit the state is saved to
    out_dir/.checkpoint.json, and a resumed run truncates the packs to that state and skips finished units.
    If out_dir already holds a finished manifest (and no checkpoint), it is returned as is."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = out_dir / CHECKPOINT
    if resume and not ckpt_path.exists() and (out_dir / "manifest.json").exists():
        log("  resume: ingest already finished, reusing manifest.json")
        return json.loads((out_dir / "manifest.json").read_text())
    ckpt = json.loads(ckpt_path.read_text()) if resume and ckpt_path.exists() else None
    adapter = adapter_for(entry)
    private = set(getattr(adapter, "mirror_private_columns", []))
    release = ckpt["release"] if ckpt else dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    started = time.time() - (ckpt["elapsed"] if ckpt else 0)
    upstream_fp, upstream_detail = (ckpt["upstream_fp"], ckpt["upstream_detail"]) if ckpt else (None, None)
    if not ckpt and entry["change_detection"]["method"] != "none":
        try:
            upstream_fp, upstream_detail = fingerprint(entry["change_detection"])
        except Exception as e:  # noqa: BLE001 - recorded, not fatal
            upstream_detail = f"fingerprint failed: {e}"
    work = Path(tempfile.mkdtemp(prefix="odc-mirror-"))
    spool = Spool(work)
    stats: dict[str, ColumnStats] = {c: ColumnStats.from_json(d) for c, d in ckpt["stats"].items()} if ckpt else {}
    urls: list[str] = ckpt["urls"] if ckpt else []
    notes: list[str] = ckpt["notes"] if ckpt else []
    metadata: dict[str, Any] = ckpt["metadata"] if ckpt else {}
    partition_keys: list[str] = list(adapter.mirror_partition_keys)
    packer = Packer(out_dir, resume=ckpt["packer"] if ckpt else None)
    seen_keys: set[str] = set(ckpt["seen_keys"]) if ckpt else set()
    try:
        units = list(adapter.mirror_plan())
        plan_id = fingerprint_plan(units)
        done = 0
        if ckpt:
            if ckpt["plan"] != plan_id:
                raise ValueError(f"mirror plan changed since the checkpoint in {out_dir}; delete it and start over")
            done = ckpt["done"]
            log(f"  resume: {done}/{len(units)} units already ingested")
        for i, unit in enumerate(units, 1):
            if i <= done:
                continue
            t0 = time.time()
            rows, u_urls, u_notes, u_meta = adapter.mirror_rows(unit)
            n = 0
            for row in rows:
                key = dict(unit.partition)
                for c in unit.split_by:
                    v = row.get(c)
                    key[c] = "" if v is None else str(v)
                row = spool.write(key, row)
                for c, v in row.items():
                    stats.setdefault(c, ColumnStats()).add(v)
                n += 1
            urls += [u for u in u_urls if u not in urls]
            notes += [x for x in u_notes if x not in notes]
            _merge_meta(metadata, u_meta)
            for k, key in spool.keys.items():
                missing = [pk for pk in partition_keys if pk not in key]
                if missing:
                    raise ValueError(f"partition {key} lacks mirror_partition_keys {missing}; fix mirror_plan/split_by")
                if k in seen_keys:
                    raise ValueError(f"partition {key} produced by two units; units must not overlap")
                seen_keys.add(k)
            first_new = len(packer.parts)
            packer.drain(spool)
            # Per-partition provenance: indices into upstream.urls of the files/requests this unit read.
            u_idx = sorted({urls.index(u) for u in u_urls if u in urls})
            for part in packer.parts[first_new:]:
                part["u"] = u_idx
            if resume:
                tmp = ckpt_path.with_suffix(".tmp")
                tmp.write_text(json.dumps({
                    "release": release, "plan": plan_id, "done": i, "elapsed": time.time() - started,
                    "upstream_fp": upstream_fp, "upstream_detail": upstream_detail, "packer": packer.state(),
                    "stats": {c: s.to_json() for c, s in stats.items()}, "urls": urls, "notes": notes,
                    "metadata": metadata, "seen_keys": sorted(seen_keys)}, default=str))
                tmp.replace(ckpt_path)
            log(f"  [{i}/{len(units)}] {unit.partition} -> {n} rows ({time.time() - t0:.1f}s, packs {sum((out_dir / p).stat().st_size for p in packer.packs) / 1e6:.1f} MB)")
        packer.close()
        manifest = {
            "format": FORMAT,
            "source_id": entry["id"],
            "release": release,
            "ingested_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "adapter_version": adapter.version,
            "row_count": packer.total,
            "packs": packer.packs,
            "pack_bytes": [os.path.getsize(out_dir / p) for p in packer.packs],
            "partitions": packer.parts,
        }
    finally:
        spool.close()
        packer.close()
        shutil.rmtree(work, ignore_errors=True)
    lic = entry["license"]
    manifest.update({
        "upstream": {"urls": urls, "fingerprint": upstream_fp, "detail": upstream_detail},
        "license": {k: lic[k] for k in ("name", "url", "redistribution", "commercial_use", "attribution")},
        "partition_keys": partition_keys,
        "required_filters": list(adapter.mirror_required),
        "semantics": dict(adapter.mirror_semantics),
        "columns": {c: _private(s.summary()) if c in private else s.summary() for c, s in stats.items()},
        "notes": notes,
        "metadata": metadata,
        "ingest_seconds": round(time.time() - started, 1),
    })
    (out_dir / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":"), default=str))
    ckpt_path.unlink(missing_ok=True)
    return manifest


def fingerprint_plan(units: list[MirrorUnit]) -> str:
    return hashlib.sha256(json.dumps([[u.partition, u.filters, u.split_by] for u in units], sort_keys=True,
                                     default=str).encode()).hexdigest()[:16]


def _merge_meta(into: dict, new: dict) -> None:
    for k, v in (new or {}).items():
        if isinstance(v, dict) and isinstance(into.get(k), dict):
            into[k].update(v)
        elif k not in into:
            into[k] = v


class Packer:
    """Appends gzip members to pack files (rolling over at PACK_TARGET_BYTES) and records partition offsets."""

    def __init__(self, out_dir: Path, resume: dict | None = None):
        self.out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        self.packs: list[str] = []
        self.parts: list[dict] = []
        self.fh = None
        self.size = 0
        self.total = 0
        if not resume:
            self._new()
            return
        # Continue from a checkpoint (Packer.state()): drop anything written after it.
        self.packs, self.parts, self.total = list(resume["packs"]), list(resume["parts"]), resume["total"]
        for name, size in zip(self.packs, resume["pack_bytes"]):
            with open(out_dir / name, "r+b") as fh:
                fh.truncate(size)
        for p in out_dir.glob("pack-*.bin"):
            if p.name not in self.packs:
                p.unlink()
        self.fh = open(out_dir / self.packs[-1], "ab")
        self.size = resume["pack_bytes"][-1]

    def state(self) -> dict:
        self.fh.flush()
        return {"packs": self.packs, "parts": self.parts, "total": self.total,
                "pack_bytes": [os.path.getsize(self.out_dir / p) for p in self.packs]}

    def _new(self) -> None:
        if self.fh:
            self.fh.close()
        name = f"pack-{len(self.packs)}.bin"
        self.packs.append(name)
        self.fh = open(self.out_dir / name, "wb")
        self.size = 0

    def add(self, key: dict, chunk_no: int, lines: list[str]) -> None:
        blob = gzip.compress("".join(lines).encode("utf-8"), compresslevel=6, mtime=0)
        if self.size and self.size + len(blob) > PACK_TARGET_BYTES:
            self._new()
        self.fh.write(blob)
        self.parts.append({"k": key, "c": chunk_no, "p": len(self.packs) - 1, "o": self.size, "n": len(blob), "r": len(lines)})
        self.size += len(blob)
        self.total += len(lines)

    def drain(self, spool: Spool) -> None:
        """Pack every spooled partition, then delete the spool files. Units never share partitions, so this is
        safe to call after each unit; it keeps peak disk use to one unit's raw rows."""
        spool.close()
        for k in sorted(spool.files, key=lambda k: json.dumps(spool.keys[k], sort_keys=True)):
            lines: list[str] = []
            size = 0
            chunk_no = 0
            with open(spool.files[k], encoding="utf-8") as fh:
                for line in fh:
                    lines.append(line)
                    size += len(line)
                    if len(lines) >= MAX_PARTITION_ROWS or size >= MAX_CHUNK_BYTES:
                        self.add(spool.keys[k], chunk_no, lines)
                        lines, size, chunk_no = [], 0, chunk_no + 1
            if lines:
                self.add(spool.keys[k], chunk_no, lines)
            spool.files[k].unlink(missing_ok=True)
        spool.files.clear()
        spool.keys.clear()
        spool.counts.clear()

    def close(self) -> None:
        if self.fh:
            self.fh.close()
            self.fh = None


# ------------------------------------------------------------------ publish

def publish(entry: dict, out_dir: Path, r2: R2, log=print, resume: bool = False) -> str:
    """Upload packs, then the manifest, then flip current.json (readers never see a half-written release).

    resume=True skips packs this release already has in R2 (an R2 PUT is atomic, so a listed object is complete);
    release ids are unique per ingest, so these can only come from an earlier, cut-off publish of the same packs."""
    manifest = json.loads((out_dir / "manifest.json").read_text())
    sid, release = entry["id"], manifest["release"]
    prefix = f"mirror/{sid}/{release}/"
    have = set(r2.list(prefix)) if resume else set()
    for p in manifest["packs"]:
        if prefix + p in have:
            log(f"  resume: {prefix}{p} already uploaded")
            continue
        r2.put(prefix + p, out_dir / p)
        log(f"  uploaded {prefix}{p} ({(out_dir / p).stat().st_size / 1e6:.1f} MB)")
    r2.put(prefix + "manifest.json", out_dir / "manifest.json", "application/json")
    # Another publisher of this source (an agent session racing the mirror workflow) may have cleaned this release up
    # mid-upload; never point current.json at a release with missing objects.
    uploaded = set(r2.list(prefix))
    missing = [k for k in [prefix + p for p in manifest["packs"]] + [prefix + "manifest.json"] if k not in uploaded]
    if missing:
        raise SourceError(f"{sid}: release {release} is missing {missing[:5]} after upload (concurrent cleanup?); "
                          "current.json not changed, rerun the publish", kind="http")
    current = {"release": release, "manifest": prefix + "manifest.json", "ingested_at": manifest["ingested_at"],
               "row_count": manifest["row_count"], "upstream_fingerprint": manifest["upstream"]["fingerprint"],
               "adapter_version": manifest["adapter_version"]}
    r2.put(f"mirror/{sid}/current.json", json.dumps(current).encode(), "application/json")
    _cleanup(sid, r2, log)
    return prefix


def _cleanup(sid: str, r2: R2, log=print) -> None:
    """Delete old releases, keeping the live one (whatever current.json points to) plus the newest others.

    Release ids sort by ingest start time, not publish time: a resumed ingest published late can be the live
    release while sorting before newer ones, so the live release is excluded explicitly."""
    keys = r2.list(f"mirror/{sid}/")
    releases = sorted({k.split("/")[2] for k in keys if k.count("/") >= 3})
    cur = current(sid, r2)
    live = cur["release"] if cur else None
    others = [r for r in releases if r != live]
    keep = set(others[-(KEEP_RELEASES - 1):]) if KEEP_RELEASES > 1 else set()
    for old in others:
        if old in keep:
            continue
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


def run(source_ids: list[str] | None, only_due: bool, dry_run: bool, out_root: Path | None = None, log=print,
        report_path: Path | None = None, resume: bool = False) -> int:
    cat = Catalog.load()
    ids = source_ids or sorted(sid for sid, e in cat.entries.items() if mirrorable(e))
    r2 = None if dry_run else R2()
    failures = 0
    report: dict[str, list] = {"published": [], "skipped": [], "failed": []}
    for sid in ids:
        e = cat.get(sid)
        if not mirrorable(e):
            log(f"skip {sid}: not mirrorable (needs adapter with mirror_plan, healthy/degraded, redistribution: allowed)")
            continue
        if only_due and r2 is not None:
            try:
                is_due, why = due(e, r2)
            except Exception as ex:  # noqa: BLE001 - e.g. an R2 5xx on one current.json must not stop the other sources
                failures += 1
                log(f"FAILED {sid}: due check: {type(ex).__name__}: {ex}")
                report["failed"].append({"source_id": sid, "kind": getattr(ex, "kind", "error"),
                                         "error": f"due check failed: {type(ex).__name__}: {ex}"[-4000:]})
                continue
            if not is_due:
                log(f"skip {sid}: {why}")
                report["skipped"].append({"source_id": sid, "reason": why})
                continue
            log(f"{sid}: due ({why})")
        out = (out_root or Path(tempfile.mkdtemp(prefix="odc-pack-"))) / sid
        try:
            log(f"ingest {sid}")
            m = ingest(e, out, log, resume=resume and out_root is not None)
            log(f"  {m['row_count']} rows, {len(m['partitions'])} partitions, "
                f"{sum(m['pack_bytes']) / 1e6:.1f} MB in {m['ingest_seconds']}s")
            if not dry_run:
                publish(e, out, r2, log, resume=resume and out_root is not None)
            report["published"].append({"source_id": sid, "release": m["release"], "rows": m["row_count"],
                                        "bytes": sum(m["pack_bytes"]), "seconds": m["ingest_seconds"]})
        except Exception as ex:  # noqa: BLE001 - keep going; failures become needs-repair issues
            import traceback
            failures += 1
            log(f"FAILED {sid}: {type(ex).__name__}: {ex}")
            report["failed"].append({"source_id": sid, "kind": getattr(ex, "kind", "error"),
                                     "error": "".join(traceback.format_exception(ex))[-4000:]})
        finally:
            if out_root is None:
                shutil.rmtree(out.parent, ignore_errors=True)
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2))
    return 1 if failures else 0
