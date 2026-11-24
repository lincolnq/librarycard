"""MCP server exposing the catalog.

Run:  odc-server            (stdio transport, for MCP clients)
      odc-server --http     (streamable HTTP on 127.0.0.1:8765/mcp)

Four tools, deliberately small and uniform: search_catalog, describe_source,
fetch, catalog_status. The server never answers questions itself; it finds
sources and fetches data with provenance.
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

from mcp.server.mcpserver import MCPServer

from .adapters import adapter_for
from .adapters.base import FilterError
from .catalog import Catalog, CatalogError, fetchable, status_report
from .http import SourceError

log = logging.getLogger("odc.server")

INSTRUCTIONS = """\
Open Data Catalog: a find-and-fetch layer over reputable public datasets (US policy domain:
elections, demographics/Census, economy, health, education, housing, public finance, legislation).
It does NOT answer questions or compute statistics; you do the analysis.

Workflow:
1. search_catalog to find candidate sources (results include status and whether they are fetchable).
2. describe_source BEFORE analysis: read `caveats` (weighting, margins of error, series breaks,
   suppression) and `fetch_parameters` (the filters fetch accepts).
3. fetch with narrow filters. Every response carries `provenance`; cite it (publisher, retrieved_at,
   request URL, license) whenever you report numbers derived from the data.
Sources with status 'quarantined' or 'retired' cannot be fetched; 'degraded' fetches carry warnings.
For national/international indicator time series also consider Google Data Commons (catalog id
`data-commons`), which has its own MCP server.
"""

_catalog: Catalog | None = None


def catalog() -> Catalog:
    global _catalog
    if _catalog is None:
        _catalog = Catalog.load()
    return _catalog


def _err(message: str, **extra: Any) -> dict:
    return {"error": message, **extra}


# --------------------------------------------------------------- tool logic
# Plain functions (easy to unit test); registered as MCP tools below.

def search_catalog(query: str, domain: str | None = None, geography: str | None = None,
                   time_range: str | None = None, limit: int = 10) -> dict:
    try:
        results = catalog().search(query, domain=domain, geography=geography, time_range=time_range, limit=max(1, min(limit, 50)))
    except CatalogError as e:
        return _err(str(e))
    return {
        "query": query,
        "results": results,
        "next_step": "Call describe_source(source_id) and read its caveats before fetching or analysing.",
    }


def describe_source(source_id: str) -> dict:
    try:
        e = catalog().get(source_id)
    except CatalogError as ex:
        return _err(str(ex))
    out = dict(e)
    out["fetchable"] = fetchable(e)
    adapter = adapter_for(e)
    if adapter is not None:
        out["fetch_parameters"] = adapter.describe_filters()
    elif e["access"]["method"] == "restricted":
        out["fetch_parameters"] = None
        out["how_to_access"] = (
            f"Not fetchable through this server: {e['access'].get('restricted_reason', 'restricted')}. "
            + (f"Publisher MCP server: {e['access']['mcp_server']['url']}. " if e["access"].get("mcp_server") else "")
            + f"See {e['homepage']}."
        )
    out["reminder"] = "Read `caveats` before analysis; cite `provenance` from fetch results."
    return out


def fetch(source_id: str, filters: dict | None = None, limit: int | None = None) -> dict:
    try:
        e = catalog().get(source_id)
    except CatalogError as ex:
        return _err(str(ex))
    if e["access"]["method"] == "restricted":
        return _err(f"{source_id} is a catalog-only entry ({e['access'].get('restricted_reason')}); it cannot be fetched here.",
                    homepage=e["homepage"], mcp_server=e["access"].get("mcp_server"))
    if e["status"] in ("quarantined", "retired"):
        return _err(f"{source_id} is {e['status']} and cannot be fetched: {e['status_reason']} (since {e['status_since']}).",
                    status=e["status"], homepage=e["homepage"])
    adapter = adapter_for(e)
    try:
        out = adapter.fetch(e, filters or {}, limit=limit)
    except FilterError as ex:
        return _err(f"Invalid filters: {ex}", fetch_parameters=adapter.describe_filters())
    except SourceError as ex:
        return _err(f"Publisher request failed ({ex.kind}): {ex}", status=e["status"],
                    hint="This may be transient. If it persists the monitor will open a needs-repair issue.")
    warnings = []
    if e["status"] == "degraded":
        warnings.append(f"Source is DEGRADED since {e['status_since']}: {e['status_reason']}. Verify results independently.")
    if out["truncated"]:
        warnings.append(f"Result truncated at limit={out['row_count']}. Narrow filters or raise limit (max 5000).")
    if e["license"]["redistribution"] == "link_only":
        warnings.append("License is link_only: use the data for analysis but do not republish it in bulk; link to the publisher.")
    out["warnings"] = warnings
    out["caveats"] = e["caveats"]
    return out


def catalog_status_tool(recent_days: int = 30) -> dict:
    return status_report(catalog(), recent_days=recent_days)


# --------------------------------------------------------------- MCP wiring

def build_server() -> MCPServer:
    mcp = MCPServer("open-data-catalog", instructions=INSTRUCTIONS, version="0.1.0")

    @mcp.tool(name="search_catalog")
    def _search_catalog(query: str, domain: str | None = None, geography: str | None = None,
                        time_range: str | None = None, limit: int = 10) -> dict[str, Any]:
        """Find public data sources that could answer a question. Returns ranked source summaries
        (id, publisher, coverage, access method, status, whether fetchable).

        Args:
            query: keywords, e.g. "county presidential election results" or "median household income tract".
            domain: optional exact domain filter, e.g. elections, demographics, economy, labor, health,
                education, housing, public_finance, income_poverty, politics_legislation.
            geography: optional, e.g. "county", "tract", "congressional_district", "Texas", "US".
            time_range: optional year or range, e.g. "2020" or "2010-2022"; keeps sources overlapping it.
            limit: max results (default 10, max 50).

        Always call describe_source on a candidate and read its caveats before analysis.
        """
        return search_catalog(query, domain, geography, time_range, limit)

    @mcp.tool(name="describe_source")
    def _describe_source(source_id: str) -> dict[str, Any]:
        """Full catalog entry for one source: description, coverage, key variables (with units),
        CAVEATS (methodology breaks, weighting, margins of error, suppression), license and required
        attribution, update cadence, status, and `fetch_parameters` (the filters `fetch` accepts).

        Read the caveats before analysing data from this source; naive use is often wrong.
        """
        return describe_source(source_id)

    @mcp.tool(name="fetch")
    def _fetch(source_id: str, filters: dict | None = None, limit: int | None = None) -> dict[str, Any]:
        """Fetch rows from the original publisher, on demand, with provenance attached.

        Args:
            source_id: id from search_catalog.
            filters: object of filter values; see describe_source(...).fetch_parameters for the
                accepted names, types, and required filters for this source.
            limit: max rows to return (default 500, max 5000). `truncated: true` means more exist.

        Returns {rows, columns, row_count, truncated, warnings, caveats, provenance}. Refuses
        quarantined/retired/restricted sources; warns on degraded ones. Check `caveats` before
        analysis and cite `provenance` (publisher, request URL, retrieved_at, license) in any output.
        """
        return fetch(source_id, filters, limit)

    @mcp.tool(name="catalog_status")
    def _catalog_status(recent_days: int = 30) -> dict[str, Any]:
        """Health of the catalog: number of sources by status (healthy/degraded/quarantined/retired),
        sources whose status changed in the last `recent_days`, catalog-only restricted entries,
        and entries not re-verified in 90 days."""
        return catalog_status_tool(recent_days)

    return mcp


def main() -> None:
    ap = argparse.ArgumentParser(description="Open Data Catalog MCP server")
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)  # keep stderr quiet; one line per request is noise
    catalog()  # fail fast on an invalid catalog
    server = build_server()
    if args.http:
        server.run("streamable-http", host=args.host, port=args.port)
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
