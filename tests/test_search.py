import json
from pathlib import Path

from odc.catalog import CatalogError

import pytest


def ids(results):
    return [r["id"] for r in results]


def test_keyword_ranking(cat):
    assert ids(cat.search("median household income tract"))[0] == "census-acs-summary-file"
    assert ids(cat.search("daily temperature heat county"))[0] == "noaa-nclimgrid-daily"


def test_filters(cat):
    assert all("disasters_emergency" in r["domains"] for r in cat.search("", domain="disasters_emergency", limit=100))
    assert "census-acs-summary-file" in ids(cat.search("", geography="tract", limit=100))
    assert "noaa-nclimgrid-daily" in ids(cat.search("", geography="Texas", limit=100))
    assert "noaa-nclimgrid-daily" not in ids(cat.search("", time_range="1900-1940", limit=100))


def test_bad_time_range(cat):
    with pytest.raises(CatalogError):
        cat.search("x", time_range="recent")


def test_summary_shape(cat):
    r = cat.search("census")[0]
    for k in ("id", "status", "fetchable", "access_method", "caveat_count"):
        assert k in r


# Natural-language queries an agent might send, with the source that must rank first.
# Shared with worker/test/search.test.ts. When you onboard a source, add a case to tests/search_cases.json.
TOP1 = json.loads((Path(__file__).parent / "search_cases.json").read_text())


@pytest.mark.parametrize("query,expected", sorted(TOP1.items()))
def test_top1(cat, query, expected):
    assert ids(cat.search(query, limit=3))[0] == expected
