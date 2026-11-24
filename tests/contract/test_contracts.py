"""LIVE contract tests: hit each publisher and check the adapter still returns what we expect.

Run:  pytest -m live tests/contract            (all sources)
      pytest -m live tests/contract -k census  (subset)
      odc contract <source_id>                 (same checks, friendlier output)
"""
import pytest

from odc.adapters import adapter_for
from odc.catalog import Catalog
from odc.contracts import run_case

CAT = Catalog.load()
CASES = [
    (sid, case)
    for sid, e in sorted(CAT.entries.items())
    if e["adapter"] and e["status"] != "retired"
    for case in adapter_for(e).contract
]


@pytest.mark.live
@pytest.mark.parametrize("sid,case", CASES, ids=[f"{s}::{c.name}" for s, c in CASES])
def test_contract(sid, case):
    r = run_case(CAT.get(sid), case)
    assert r.passed, f"[{r.kind}] {r.message}"
