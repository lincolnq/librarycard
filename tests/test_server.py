"""Offline tests of the MCP tool layer (no publisher network calls)."""
import copy

import anyio
import pytest
from mcp import Client

from odc import server
from odc.adapters.base import ContractCase, FetchResult, FilterSpec, SourceAdapter
from odc.catalog import Catalog


class StubAdapter(SourceAdapter):
    source_id = "stub"
    version = "1.0.0"
    usage = "stub adapter for tests"
    filters = [FilterSpec("n", "integer", "number of rows to return", required=True)]
    contract = [ContractCase("c", {"n": 1})]

    def _fetch(self, f, limit, cache_allowed):
        return FetchResult([{"i": i} for i in range(min(f["n"], limit))], ["https://example.gov/data"], total_available=f["n"])


@pytest.fixture()
def patched(monkeypatch):
    cat = Catalog.load()
    base = copy.deepcopy(next(e for e in cat.entries.values() if e["adapter"]))
    entries = {}
    for sid, status in [("stub-healthy", "healthy"), ("stub-degraded", "degraded"), ("stub-quarantined", "quarantined")]:
        e = copy.deepcopy(base)
        e.update(id=sid, status=status, status_reason=f"test {status} reason text", adapter="stub")
        entries[sid] = e
    entries.update(cat.entries)
    fake = Catalog(entries)
    monkeypatch.setattr(server, "_catalog", fake)
    real = server.adapter_for
    monkeypatch.setattr(server, "adapter_for", lambda e: StubAdapter() if e.get("adapter") == "stub" else real(e))
    return fake


def test_fetch_healthy_has_provenance(patched):
    out = server.fetch("stub-healthy", {"n": 3}, limit=2)
    assert out["row_count"] == 2 and out["truncated"] is True
    p = out["provenance"]
    for k in ("source_id", "publisher", "retrieved_at", "request_urls", "license", "citation", "adapter_version"):
        assert k in p
    assert out["caveats"], "fetch must return caveats"


def test_fetch_degraded_warns(patched):
    out = server.fetch("stub-degraded", {"n": 1})
    assert any("DEGRADED" in w for w in out["warnings"])


def test_fetch_quarantined_refused(patched):
    out = server.fetch("stub-quarantined", {"n": 1})
    assert "error" in out and "quarantined" in out["error"]


def test_fetch_bad_filters(patched):
    out = server.fetch("stub-healthy", {"nope": 1})
    assert "error" in out and "fetch_parameters" in out


def test_unknown_source():
    assert "error" in server.describe_source("no-such-source")
    assert "error" in server.fetch("no-such-source")


def test_restricted_refused(cat):
    restricted = [sid for sid, e in cat.entries.items() if e["access"]["method"] == "restricted"]
    for sid in restricted:
        out = server.fetch(sid)
        assert "error" in out and "catalog-only" in out["error"]


def test_describe_has_fetch_parameters(cat):
    for sid, e in cat.entries.items():
        d = server.describe_source(sid)
        assert d["caveats"]
        if e["adapter"]:
            assert d["fetch_parameters"]["filters"]


def test_search_and_status(cat):
    res = server.search_catalog("disaster declarations")
    assert res["results"][0]["id"] == "fema-disaster-declarations"
    st = server.catalog_status_tool()
    assert st["total_sources"] == len(cat.entries)
    assert sum(st["counts_by_status"].values()) == len(cat.entries)


def test_mcp_protocol_roundtrip():
    async def go():
        async with Client(server.build_server()) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            assert set(tools) == {"search_catalog", "describe_source", "fetch", "catalog_status", "request_data", "report_issue"}
            assert "caveats" in tools["describe_source"].description.lower()
            assert "provenance" in tools["fetch"].description.lower()
            r = await c.call_tool("search_catalog", {"query": "county temperature"})
            assert not r.is_error
            assert r.structured_content["results"]
            r = await c.call_tool("catalog_status", {})
            assert r.structured_content["total_sources"] > 0
    anyio.run(go)


def test_request_data_link():
    from urllib.parse import parse_qs, urlparse
    out = server.request_data("County-level SNAP participation by month", "How did SNAP enrollment change after 2023?", geography="US counties")
    u = urlparse(out["issue_url"])
    q = parse_qs(u.query)
    assert u.path == "/lincolnq/librarycard/issues/new" and q["template"] == ["data-request.yml"]
    assert q["geography"] == ["US counties"] and q["title"][0].startswith("[data request] County-level SNAP")
    assert "error" in server.request_data("x", "y")


def test_report_issue_link():
    from urllib.parse import parse_qs, urlparse
    out = server.report_issue("census-pep", "County totals for 2025 look one year stale compared with the publisher page.")
    q = parse_qs(urlparse(out["issue_url"]).query)
    assert q["template"] == ["data-issue.yml"] and q["source_id"] == ["census-pep"]
    assert "error" in server.report_issue("no-such-source", "something looks wrong here")
