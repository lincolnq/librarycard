"""Federal Register documents via the FederalRegister.gov API v1. Catalog: catalog/federal-register-documents.yaml

Endpoint: GET https://www.federalregister.gov/api/v1/documents.json (no key)
  conditions[type][]=RULE|PRORULE|NOTICE|PRESDOCU, conditions[agencies][]=<agency slug>,
  conditions[publication_date][gte|lte]=YYYY-MM-DD, conditions[term]=<full text>,
  conditions[presidential_document_type][]=executive_order|proclamation|..., conditions[significant]=1,
  conditions[docket_id]=..., conditions[regulation_id_number]=..., fields[]=..., per_page (<=1000), order=newest|oldest.
  Response: {count, total_pages, next_page_url, results:[...]}. `count` is capped at 10,000 by the API, and
  pagination cannot reach beyond 10,000 results — narrow the filters for exhaustive pulls.
Agency slugs: GET /api/v1/agencies.json (e.g. environmental-protection-agency).
The HTML site (www.federalregister.gov/*) blocks non-browser clients with an "unblock" page; only /api/ works.
"""

from __future__ import annotations

import re

from .. import http
from ..http import SourceError
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

BASE = "https://www.federalregister.gov/api/v1"
DOC_TYPES = {"rule": "RULE", "proposed_rule": "PRORULE", "notice": "NOTICE", "presidential_document": "PRESDOCU"}
PRES_TYPES = ["determination", "executive_order", "memorandum", "notice", "proclamation", "presidential_order", "other"]
FIELDS = ["document_number", "publication_date", "type", "subtype", "title", "action", "abstract", "agencies",
          "citation", "volume", "start_page", "end_page", "page_length", "effective_on", "comments_close_on",
          "signing_date", "president", "executive_order_number", "presidential_document_number", "docket_ids",
          "regulation_id_numbers", "significant", "html_url", "pdf_url", "correction_of", "disposition_notes"]
DATE_RE = re.compile(r"\d{4}-\d\d-\d\d")
MAX_RESULTS = 10_000


def _flatten(d: dict) -> dict:
    out = {}
    for k in FIELDS:
        v = d.get(k)
        if k == "agencies":
            ags = v or []
            out["agency_names"] = "; ".join(a.get("name") or a.get("raw_name") or "" for a in ags) or None
            out["agency_slugs"] = "; ".join(a.get("slug") or "" for a in ags if a.get("slug")) or None
        elif k == "president":
            out["president"] = (v or {}).get("name") if isinstance(v, dict) else v
        elif isinstance(v, list):
            out[k] = "; ".join(str(x) for x in v) or None
        else:
            out[k] = v
    return out


class FederalRegisterDocuments(SourceAdapter):
    source_id = "federal-register-documents"
    version = "1.0.0"
    usage = ("One row per Federal Register document (rule, proposed rule, notice or presidential document) with its "
             "citation, dates, agencies, docket/RIN ids and links to the official PDF on govinfo. Filter by doc_type, "
             "agency slug (e.g. 'environmental-protection-agency'; list at /api/v1/agencies.json), publication date "
             "range and/or a full-text term. The API reports at most 10,000 matches per query — narrow the date range "
             "for exhaustive counts. Rows are document metadata, not full text (follow html_url/pdf_url).")
    filters = [
        FilterSpec("doc_type", "string_list", "Document types: rule, proposed_rule, notice, presidential_document.",
                   enum=sorted(DOC_TYPES), example=["rule"]),
        FilterSpec("agency", "string_list", "FederalRegister.gov agency slug(s), e.g. 'environmental-protection-agency', "
                   "'food-and-drug-administration'.", example=["environmental-protection-agency"]),
        FilterSpec("published_from", "string", "Publication date >= YYYY-MM-DD (data start 1994-01-01).", example="2023-01-01"),
        FilterSpec("published_to", "string", "Publication date <= YYYY-MM-DD.", example="2023-12-31"),
        FilterSpec("term", "string", "Full-text search term (FederalRegister.gov search syntax; quotes for phrases).",
                   example="\"greenhouse gas\""),
        FilterSpec("presidential_document_type", "string_list", "Presidential document subtype(s), e.g. executive_order, "
                   "proclamation, memorandum (implies doc_type presidential_document).", enum=PRES_TYPES),
        FilterSpec("significant", "boolean", "Only documents deemed significant under EO 12866 (rules/proposed rules; "
                   "flag available from 1994 on)."),
        FilterSpec("docket_id", "string", "Agency docket id, e.g. 'EPA-HQ-OAR-2021-0317'."),
        FilterSpec("regulation_id_number", "string", "Regulation Identifier Number (RIN), e.g. '2060-AV16'."),
        FilterSpec("document_number", "string_list", "Exact FR document number(s), e.g. ['2021-02252']."),
        FilterSpec("order", "string", "Sort order.", enum=["newest", "oldest", "relevance"], default="newest"),
    ]
    contract = [
        ContractCase(
            name="biden_first_executive_orders",
            filters={"presidential_document_type": ["executive_order"], "published_from": "2021-01-25",
                     "published_to": "2021-02-05"},
            min_rows=15, max_rows=40,
            required_columns=["document_number", "publication_date", "type", "subtype", "title", "citation",
                              "executive_order_number", "president", "pdf_url"],
            checks=[Check("subtype", one_of=["Executive Order"]), Check("type", one_of=["Presidential Document"]),
                    Check("executive_order_number", numeric=True, min=13950, max=14050),
                    Check("citation", regex=r"86 FR \d+")],
            limit=100,
        ),
        ContractCase(
            name="epa_rules_january_2023",
            filters={"doc_type": ["rule"], "agency": ["environmental-protection-agency"],
                     "published_from": "2023-01-01", "published_to": "2023-01-31"},
            min_rows=10,
            required_columns=["document_number", "agency_names", "agency_slugs", "publication_date"],
            checks=[Check("type", one_of=["Rule"]), Check("publication_date", regex=r"2023-01-\d\d"),
                    Check("document_number", regex=r"\d{4}-\d{5}")],
            limit=200,
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        params: list[tuple[str, str]] = []
        for k in ("published_from", "published_to"):
            if k in f and not DATE_RE.fullmatch(f[k]):
                raise FilterError(f"{k} must be YYYY-MM-DD")
        types = [DOC_TYPES[t] for t in f.get("doc_type", [])]
        for t in types:
            params.append(("conditions[type][]", t))
        for a in f.get("agency", []):
            if not re.fullmatch(r"[a-z0-9-]+", a):
                raise FilterError(f"agency must be a FederalRegister.gov slug like 'environmental-protection-agency', got {a!r}")
            params.append(("conditions[agencies][]", a))
        if "published_from" in f:
            params.append(("conditions[publication_date][gte]", f["published_from"]))
        if "published_to" in f:
            params.append(("conditions[publication_date][lte]", f["published_to"]))
        if f.get("term"):
            params.append(("conditions[term]", f["term"]))
        for p in f.get("presidential_document_type", []):
            params.append(("conditions[presidential_document_type][]", p))
        if f.get("significant"):
            params.append(("conditions[significant]", "1"))
        if f.get("docket_id"):
            params.append(("conditions[docket_id]", f["docket_id"]))
        if f.get("regulation_id_number"):
            params.append(("conditions[regulation_id_number]", f["regulation_id_number"]))
        for d in f.get("document_number", []):
            params.append(("conditions[document_numbers][]", d))
        params.append(("order", f.get("order", "newest")))
        for fld in FIELDS:
            params.append(("fields[]", fld))
        per_page = max(1, min(limit, 1000))
        params.append(("per_page", str(per_page)))

        rows: list[dict] = []
        urls: list[str] = []
        total = None
        url: str | None = f"{BASE}/documents.json"
        q: list[tuple[str, str]] | None = params
        while url and len(rows) < limit:
            try:
                r = http.request("GET", url, params=q)
            except SourceError as e:
                if e.status in (400, 422):
                    raise FilterError(f"Federal Register API rejected the query: {e}") from None
                raise
            urls.append(str(r.request.url))
            try:
                data = r.json()
            except ValueError:
                raise SourceError(f"non-JSON from {r.request.url}: {r.text[:200]}", kind="parse", url=str(r.request.url)) from None
            require("count" in data, f"Federal Register response lacks 'count'; keys={list(data)[:10]}")
            total = data["count"]
            res = data.get("results") or []
            for d in res:
                rows.append(_flatten(d))
            if not res:
                break
            url, q = data.get("next_page_url"), None
            if url and not url.startswith(BASE):
                raise SourceError(f"unexpected next_page_url host: {url}", kind="schema")
        notes = ["Document metadata from FederalRegister.gov (unofficial edition); the official legal text is the "
                 "govinfo PDF in pdf_url.",
                 "List-valued fields (agencies, docket_ids, regulation_id_numbers) are joined with '; '."]
        if total is not None and total >= MAX_RESULTS:
            notes.append("The API caps reported matches at 10,000 — total_rows_matching_at_source is a lower bound; "
                         "narrow the date range or filters.")
        return FetchResult(rows[:limit], urls, notes, total_available=total)


ADAPTER = FederalRegisterDocuments()
