"""OpenFEMA Disaster Declarations Summaries (v2). Catalog: catalog/fema-disaster-declarations.yaml"""

from __future__ import annotations

from ._common import odata_quote, openfema, state_abbr, state_fips
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter

DECL_TYPES = ["DR", "EM", "FM"]


class FemaDisasterDeclarations(SourceAdapter):
    source_id = "fema-disaster-declarations"
    version = "1.0.0"
    usage = ("One row per declared designated area (usually a county) per declaration. Filter by state and "
             "date range; a single disaster has many rows (one per county). Use disaster_number to group.")
    filters = [
        FilterSpec("state", "string", "2-letter postal code, e.g. 'TX'.", example="TX"),
        FilterSpec("county_fips", "string", "3-digit county FIPS within `state` (requires state), e.g. '201'."),
        FilterSpec("declaration_type", "string", "DR = major disaster, EM = emergency, FM = fire management.", enum=DECL_TYPES),
        FilterSpec("incident_type", "string", "e.g. 'Hurricane', 'Flood', 'Fire', 'Severe Storm', 'Biological'.", example="Hurricane"),
        FilterSpec("declared_from", "string", "ISO date; declarationDate >= this.", example="2020-01-01"),
        FilterSpec("declared_to", "string", "ISO date; declarationDate <= this.", example="2024-12-31"),
        FilterSpec("disaster_number", "integer", "FEMA disaster number, e.g. 4332 (Hurricane Harvey, TX)."),
    ]
    contract = [
        ContractCase(
            name="texas_harvey",
            filters={"disaster_number": 4332},
            min_rows=20,
            required_columns=["disasterNumber", "state", "declarationType", "declarationDate", "incidentType",
                              "fipsStateCode", "fipsCountyCode", "designatedArea"],
            checks=[Check("state", one_of=["TX"]), Check("incidentType", one_of=["Hurricane"]),
                    Check("fipsStateCode", one_of=["48"])],
            limit=200,
        ),
        ContractCase(
            name="recent_major_disasters",
            filters={"declaration_type": "DR", "declared_from": "2023-01-01", "declared_to": "2023-12-31"},
            min_rows=100,
            required_columns=["disasterNumber", "declarationDate"],
            checks=[Check("declarationType", one_of=["DR"]), Check("fyDeclared", numeric=True, min=2023, max=2024)],
            limit=500,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        clauses = []
        if "state" in f:
            clauses.append(f"state eq {odata_quote(state_abbr(f['state']))}")
        if "county_fips" in f:
            if "state" not in f:
                raise FilterError("county_fips requires state")
            cf = f["county_fips"].zfill(3)
            if len(cf) != 3 or not cf.isdigit():
                raise FilterError("county_fips must be 3 digits, e.g. '201'")
            clauses.append(f"fipsCountyCode eq {odata_quote(cf)} and fipsStateCode eq {odata_quote(state_fips(f['state']))}")
        if "declaration_type" in f:
            clauses.append(f"declarationType eq {odata_quote(f['declaration_type'])}")
        if "incident_type" in f:
            clauses.append(f"incidentType eq {odata_quote(f['incident_type'])}")
        if "declared_from" in f:
            clauses.append(f"declarationDate ge {odata_quote(f['declared_from'] + 'T00:00:00.000Z')}")
        if "declared_to" in f:
            clauses.append(f"declarationDate le {odata_quote(f['declared_to'] + 'T23:59:59.999Z')}")
        if "disaster_number" in f:
            clauses.append(f"disasterNumber eq {int(f['disaster_number'])}")
        rows, url, total = openfema("DisasterDeclarationsSummaries", 2, filter_expr=" and ".join(clauses) or None,
                                    limit=limit, orderby="declarationDate desc")
        for r in rows:
            r.pop("hash", None)
        return FetchResult(rows, [url], total_available=total)


ADAPTER = FemaDisasterDeclarations()
