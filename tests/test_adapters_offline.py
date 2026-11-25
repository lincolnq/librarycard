"""Offline adapter checks: filter specs are well-formed and contract cases use valid filters."""
import pytest

from odc.adapters import adapter_for
from odc.adapters.base import FilterError, SourceAdapter
from odc.catalog import Catalog

CAT = Catalog.load()
ADAPTED = sorted(sid for sid, e in CAT.entries.items() if e["adapter"])


@pytest.mark.parametrize("sid", ADAPTED)
def test_contract_filters_validate(sid):
    a: SourceAdapter = adapter_for(CAT.get(sid))
    assert a.contract, "every adapter needs >= 1 contract case"
    for case in a.contract:
        a.validate_filters(case.filters)  # raises FilterError if the contract is out of sync with the spec


@pytest.mark.parametrize("sid", ADAPTED)
def test_unknown_filter_rejected(sid):
    a = adapter_for(CAT.get(sid))
    with pytest.raises(FilterError):
        a.validate_filters({"definitely_not_a_filter": 1})


@pytest.mark.parametrize("sid", ADAPTED)
def test_filter_specs_documented(sid):
    a = adapter_for(CAT.get(sid))
    assert a.usage, "set `usage` — it is shown to agents in describe_source"
    for f in a.filters:
        assert f.type in {"string", "integer", "number", "boolean", "string_list"}
        assert len(f.description) >= 10, f.name
    required = [f for f in a.filters if f.required]
    if required:
        with pytest.raises(FilterError):
            a.validate_filters({})


def test_census_cbp_upper_case_headers():
    """cbp15us.txt ships upper-case headers; rows are normalised so filters and shaping still work."""
    from odc.adapters.census_cbp import ADAPTER
    f = ADAPTER.validate_filters({"level": "us", "year": 2015, "naics": ["total"]})
    _, keep, shape, _, _ = ADAPTER._prepare(f)
    r = {"USCODE": "0", "NAICS": "------", "LFO": "-", "EMPFLAG": "", "EMP": "100", "EST": "5"}
    assert keep(r)
    out = shape(r)
    assert out["naics"] == "------" and out["emp"] == 100 and out["est"] == 5
