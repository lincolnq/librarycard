"""<Dataset name>. Catalog: catalog/<id>.yaml

Copy this file to src/odc/adapters/<id_with_underscores>.py. Document here: the endpoint(s), the file layout or
API shape, codes/sentinels, and anything a repair agent will need to know.
"""

from __future__ import annotations

from .. import http
from ._common import state_abbr  # noqa: F401  (see _common.py for census_api, socrata, scan_csv, dataverse_*, openfema)
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require  # noqa: F401

BASE = "https://api.example.gov/v1/data"


class TemplateAdapter(SourceAdapter):
    source_id = "publisher-dataset"
    version = "1.0.0"
    usage = "What one row is, the key filter(s), and one gotcha."
    filters = [
        FilterSpec("state", "string", "2-letter postal code or FIPS.", example="TX"),
        FilterSpec("year", "integer", "Reference year.", required=True, example=2022),
    ]
    contract = [
        ContractCase(
            name="stable_historical_slice",
            filters={"state": "TX", "year": 2020},
            min_rows=1,
            required_columns=["year", "value"],
            checks=[Check("value", numeric=True, min=0, max=1e9)],
            limit=50,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        params = {"year": f["year"], "limit": limit}
        if "state" in f:
            params["state"] = state_abbr(f["state"])
        r = http.request("GET", BASE, params=params)
        data = r.json()
        require(isinstance(data, list), f"expected a JSON list from {r.request.url}")
        return FetchResult(rows=data[:limit], request_urls=[str(r.request.url)], notes=[])


ADAPTER = TemplateAdapter()
