"""Contract-test runner, shared by pytest (tests/contract) and the monitor.

A contract case passes when the adapter's ``fetch`` succeeds and the output
satisfies the declared row-count, column and value checks. Failures are
classified so needs-repair issues say *what kind* of breakage it is:

* ``network``  - DNS/TLS/timeout/connection refused (could be transient or allowlist)
* ``http``     - publisher returned an HTTP error (moved URL, removed dataset, 4xx/5xx)
* ``parse``    - response was not in the expected format
* ``empty``    - fewer rows than ``min_rows`` (dataset emptied or filter semantics changed)
* ``schema``   - required columns missing / renamed
* ``value``    - values out of the declared range/format (unit or coding change)
* ``filter``   - the adapter rejected its own contract filters (adapter bug)
* ``error``    - any other exception (adapter bug)
"""

from __future__ import annotations

import re
import time
import traceback
from dataclasses import asdict, dataclass

from .adapters import adapter_for
from .adapters.base import Check, ContractCase, FilterError
from .catalog import Catalog
from .http import SourceError


@dataclass
class CaseResult:
    source_id: str
    case: str
    passed: bool
    kind: str | None
    message: str
    seconds: float
    rows: int

    def as_dict(self) -> dict:
        return asdict(self)


def _num(v):
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return "NaN"


def check_rows(case: ContractCase, rows: list[dict]) -> tuple[str | None, str]:
    if len(rows) < case.min_rows:
        return "empty", f"expected >= {case.min_rows} rows, got {len(rows)}"
    if case.max_rows is not None and len(rows) > case.max_rows:
        return "value", f"expected <= {case.max_rows} rows, got {len(rows)}"
    cols = set()
    for r in rows:
        cols.update(r)
    missing = [c for c in case.required_columns if c not in cols]
    if missing:
        return "schema", f"missing columns {missing}; got {sorted(cols)[:60]}"
    for chk in case.checks:
        msg = _apply_check(chk, rows)
        if msg:
            return ("schema" if "not present" in msg else "value"), msg
    if case.custom:
        try:
            case.custom(rows)
        except AssertionError as e:
            return "value", f"custom check failed: {e}"
    return None, "ok"


def _apply_check(chk: Check, rows: list[dict]) -> str | None:
    if rows and not any(chk.column in r for r in rows):
        return f"column {chk.column!r} not present"
    vals = [r.get(chk.column) for r in rows]
    nonempty = [v for v in vals if v not in (None, "")]
    if chk.non_null and not nonempty:
        return f"column {chk.column!r} is empty in all {len(rows)} rows"
    if chk.numeric or chk.min is not None or chk.max is not None:
        nums = [_num(v) for v in nonempty]
        bad = [v for v, n in zip(nonempty, nums) if n == "NaN"]
        if bad:
            return f"column {chk.column!r} has non-numeric values, e.g. {bad[:3]}"
        nums = [n for n in nums if n is not None]
        if chk.min is not None and any(n < chk.min for n in nums):
            return f"column {chk.column!r} has values < {chk.min}: {sorted(nums)[:3]}"
        if chk.max is not None and any(n > chk.max for n in nums):
            return f"column {chk.column!r} has values > {chk.max}: {sorted(nums)[-3:]}"
    if chk.one_of is not None:
        allowed = {str(x) for x in chk.one_of}
        bad = sorted({str(v) for v in nonempty} - allowed)
        if bad:
            return f"column {chk.column!r} has unexpected values {bad[:5]}; expected one of {sorted(allowed)[:10]}"
    if chk.regex:
        rx = re.compile(chk.regex)
        bad = [v for v in nonempty if not rx.fullmatch(str(v))]
        if bad:
            return f"column {chk.column!r} values don't match /{chk.regex}/: {bad[:3]}"
    return None


def run_case(entry: dict, case: ContractCase) -> CaseResult:
    adapter = adapter_for(entry)
    t0 = time.time()
    rows: list[dict] = []
    try:
        out = adapter.fetch(entry, case.filters, limit=case.limit)
        rows = out["rows"]
        kind, msg = check_rows(case, rows)
    except FilterError as e:
        kind, msg = "filter", f"adapter rejected contract filters: {e}"
    except SourceError as e:
        kind, msg = e.kind, str(e)
    except Exception as e:  # noqa: BLE001 - we want every failure in the report
        kind, msg = "error", "".join(traceback.format_exception(e))[-4000:]
    return CaseResult(entry["id"], case.name, kind is None, kind, msg[:4000], round(time.time() - t0, 2), len(rows))


def run_source(entry: dict) -> list[CaseResult]:
    adapter = adapter_for(entry)
    if adapter is None:
        return []
    return [run_case(entry, c) for c in adapter.contract]


def run_many(cat: Catalog, source_ids: list[str]) -> list[CaseResult]:
    results: list[CaseResult] = []
    for sid in source_ids:
        results += run_source(cat.get(sid))
    return results
