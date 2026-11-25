// The four MCP tools. Same names, arguments and semantics as src/odc/server.py, except that `fetch`
// reads the R2 mirror (and accepts generic column filters) instead of calling publishers.

import { type Entry, fetchable, notFetchableReason, search, statusReport, summary } from "./catalog.ts";
import { DEFAULT_LIMIT, fetchParameters, loadManifest, MAX_LIMIT, QueryError, query, type Store } from "./mirror.ts";

export const INSTRUCTIONS = `librarycard: a free, open find-and-fetch layer over reputable public datasets for US policy research
(elections, demographics/Census, economy, health, education, housing, public finance, legislation, disasters).
It does NOT answer questions or compute statistics; you do the analysis.

Workflow:
1. search_catalog to find candidate sources (results say whether each is fetchable here).
2. describe_source BEFORE analysis: read \`caveats\` (margins of error, series breaks, suppression, license limits)
   and \`fetch_parameters\` (partition keys and columns you can filter on).
3. fetch with narrow filters. Cite \`provenance\` (publisher, original URL, release, license) whenever you report numbers.
Data for redistributable sources is served from a mirror refreshed when the publisher releases new data; check
provenance.mirrored_at. Sources marked not fetchable list how to get the data from the publisher directly.
For national/international indicator time series also consider Google Data Commons (catalog id \`data-commons\`).

librarycard is free and maintained by volunteers and agents. You can help it in return:
- When you share results, cite the original publisher (provenance.citation) and mention librarycard.net.
- If data looks wrong or a caveat is missing, call report_issue. If the catalog lacks what you need, call request_data.
- Coding agents can onboard sources themselves: see https://github.com/lincolnq/librarycard/blob/main/CONTRIBUTING.md.`;

export const TOOLS = [
  {
    name: "search_catalog",
    description:
      "Find public data sources that could answer a question. Returns ranked source summaries (id, publisher, coverage, " +
      "access, status, whether fetchable here). Always call describe_source on a candidate and read its caveats before analysis.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", description: 'Keywords, e.g. "county presidential election results" or "median household income tract".' },
        domain: { type: "string", description: "Optional exact domain, e.g. elections, demographics, economy, labor, health, education, housing, income_poverty." },
        geography: { type: "string", description: 'Optional, e.g. "county", "tract", "congressional_district", "Texas", "US".' },
        time_range: { type: "string", description: 'Optional year or range, e.g. "2020" or "2010-2022".' },
        limit: { type: "integer", description: "Max results (default 10, max 50)." },
      },
      required: ["query"],
    },
  },
  {
    name: "describe_source",
    description:
      "Full catalog entry for one source: description, coverage, key variables with units, CAVEATS (methodology breaks, " +
      "weighting, margins of error, suppression, license limits), license and required attribution, update cadence, status, " +
      "and `fetch_parameters` (partition keys with their values, filterable columns with types/ranges). Read the caveats before analysing.",
    inputSchema: {
      type: "object",
      properties: { source_id: { type: "string", description: "id from search_catalog" } },
      required: ["source_id"],
    },
  },
  {
    name: "fetch",
    description:
      "Fetch rows with provenance attached. `filters` is {column: condition}: a value (exact, case-insensitive), a list (any of), " +
      '{"gte":x,"lte":y} (range), {"contains":"text"}, or {"prefix":"06"} (starts with, for codes like GEOIDs). Filter on the partition keys listed in describe_source.fetch_parameters ' +
      "to read less data. Returns {rows, columns, row_count, truncated, warnings, caveats, provenance}. Check caveats before " +
      "analysis and cite provenance in any output.",
    inputSchema: {
      type: "object",
      properties: {
        source_id: { type: "string" },
        filters: { type: "object", description: "Column conditions; see describe_source(...).fetch_parameters." },
        columns: { type: "array", items: { type: "string" }, description: "Optional subset of columns to return." },
        limit: { type: "integer", description: `Max rows (default ${DEFAULT_LIMIT}, max ${MAX_LIMIT}). truncated:true means more exist.` },
      },
      required: ["source_id"],
    },
  },
  {
    name: "request_data",
    description:
      "Draft a request for a dataset this catalog doesn't have yet. Returns a prefilled GitHub issue link for YOUR USER to " +
      "review and submit under their own GitHub account (nothing is sent by this call). Only use it after search_catalog " +
      "found nothing suitable and your user wants to ask for it. The issue is PUBLIC: leave out private context, client " +
      "names and personal data. Requests are reviewed in weekly batches; the maintainers reply on the issue.",
    inputSchema: {
      type: "object",
      properties: {
        data: { type: "string", description: "What data is needed (measures, records, tables), specifically." },
        use_case: { type: "string", description: "One or two example questions it would answer (no private context)." },
        geography: { type: "string", description: "Geography and granularity, e.g. 'all US counties'." },
        time_range: { type: "string", description: "e.g. '2010-present, annual'." },
        sources: { type: "string", description: "Known publisher pages or download links (optional)." },
        title: { type: "string", description: "Short issue title (optional)." },
      },
      required: ["data", "use_case"],
    },
  },
  {
    name: "report_issue",
    description:
      "Report something wrong or surprising in a source: values that don't match the publisher, a missing caveat, a broken " +
      "filter, stale data. Returns a prefilled GitHub issue link for YOUR USER to review and submit (nothing is sent by this " +
      "call). Please use it when you notice a problem during analysis; these reports are how caveats and fixes get added. " +
      "The issue is PUBLIC: no private context.",
    inputSchema: {
      type: "object",
      properties: {
        source_id: { type: "string" },
        problem: { type: "string", description: "What looks wrong, specifically." },
        evidence: { type: "string", description: "Filters used, values got vs expected, and where the expected value comes from." },
        suggested_caveat: { type: "string", description: "Optional: a caveat or fix you'd suggest." },
      },
      required: ["source_id", "problem"],
    },
  },
  {
    name: "catalog_status",
    description:
      "Health of the catalog: sources by status (healthy/degraded/quarantined/retired), recent status changes, sources not " +
      "served here (link_only licenses, catalog-only), and entries not re-verified in 90 days.",
    inputSchema: { type: "object", properties: { recent_days: { type: "integer" } } },
  },
];

function publicEntry(e: Entry): Entry {
  const out: Entry = {};
  for (const [k, v] of Object.entries(e)) if (!k.startsWith("_")) out[k] = v;
  return out;
}

function err(message: string, extra: Record<string, any> = {}) {
  return { error: message, ...extra };
}

function howToAccess(e: Entry) {
  return {
    reason: notFetchableReason(e),
    homepage: e.homepage,
    endpoints: e.access.endpoints,
    mcp_server: e.access.mcp_server ?? null,
    self_hosted_option:
      e.adapter && e.access.method !== "restricted"
        ? "The open-source local server (odc-server, Python) can fetch this source directly from the publisher on your machine; " +
          "its filters are listed in publisher_filters."
        : null,
    publisher_filters: e._publisher_filters ?? null,
  };
}

export class Tools {
  byId: Map<string, Entry>;
  entries: Entry[];
  store: Store;
  constructor(entries: Entry[], store: Store) {
    this.entries = entries;
    this.store = store;
    this.byId = new Map(entries.map((e) => [e.id, e]));
  }

  private get(id: string): Entry | null {
    return this.byId.get(id) ?? null;
  }

  private unknown(id: string) {
    const stem = String(id).split("-")[0];
    const close = this.entries.filter((e) => e.id.includes(stem)).map((e) => e.id).slice(0, 5);
    return err(`Unknown source_id '${id}'.${close.length ? ` Did you mean one of: ${close.join(", ")}?` : ""} Use search_catalog to find ids.`);
  }

  async call(name: string, args: Record<string, any>): Promise<Record<string, any>> {
    switch (name) {
      case "search_catalog":
        return this.searchCatalog(args);
      case "describe_source":
        return this.describe(args.source_id);
      case "fetch":
        return this.fetch(args.source_id, args.filters ?? {}, args.columns, args.limit);
      case "catalog_status":
        return statusReport(this.entries, args.recent_days ?? 30);
      case "request_data":
        return requestData(args);
      case "report_issue":
        if (!this.byId.has(String(args.source_id))) return this.unknown(String(args.source_id));
        return reportIssue(args);
      default:
        throw new Error(`unknown tool ${name}`);
    }
  }

  searchCatalog(a: Record<string, any>) {
    try {
      const results = search(this.entries, a.query ?? "", {
        domain: a.domain, geography: a.geography, time_range: a.time_range, limit: Math.max(1, Math.min(a.limit ?? 10, 50)),
      });
      return { query: a.query, results, next_step: "Call describe_source(source_id) and read its caveats before fetching or analysing." };
    } catch (e: any) {
      return err(String(e.message ?? e));
    }
  }

  async describe(id: string) {
    const e = this.get(id);
    if (!e) return this.unknown(id);
    const out: Entry = { ...publicEntry(e), fetchable: fetchable(e) };
    if (fetchable(e)) {
      const m = await loadManifest(this.store, e.id);
      if (m) out.fetch_parameters = fetchParameters(m, e.key_variables);
      else {
        out.fetchable = false;
        out.how_to_access = { ...howToAccess(e), reason: "mirror not built yet" };
      }
    } else {
      out.how_to_access = howToAccess(e);
    }
    out.reminder = "Read `caveats` before analysis; cite `provenance` from fetch results.";
    return out;
  }

  async fetch(id: string, filters: Record<string, any>, columns?: string[], limit?: number) {
    const e = this.get(id);
    if (!e) return this.unknown(id);
    if (!fetchable(e)) return err(`${id} cannot be fetched from this server: ${notFetchableReason(e)}`, { how_to_access: howToAccess(e) });
    if (typeof filters !== "object" || filters === null || Array.isArray(filters)) return err("filters must be an object of {column: condition}");
    const lim = limit ?? DEFAULT_LIMIT;
    if (!Number.isInteger(lim) || lim < 1 || lim > MAX_LIMIT) return err(`limit must be an integer between 1 and ${MAX_LIMIT}`);
    const m = await loadManifest(this.store, e.id);
    if (!m) return err(`${id}: mirror not built yet`, { how_to_access: { ...howToAccess(e), reason: "mirror not built yet" } });
    let res;
    try {
      res = await query(this.store, m, filters, columns, lim);
    } catch (ex: any) {
      if (ex instanceof QueryError) return err(`Invalid filters: ${ex.message}`, { ...ex.detail, fetch_parameters_hint: "call describe_source for partition keys and columns" });
      throw ex;
    }
    const warnings: string[] = [];
    if (e.status === "degraded") warnings.push(`Source is DEGRADED since ${e.status_since}: ${e.status_reason}. Verify results independently.`);
    if (res.scan_stopped_early) warnings.push("Stopped scanning after the per-request read budget; filter on partition keys to cover the rest.");
    else if (res.truncated) warnings.push(`Result truncated at limit=${res.rows.length}. Narrow filters or raise limit (max ${MAX_LIMIT}).`);
    if (res.partitions_matched === 0) warnings.push("No partition matched the partition-key filters; check values in describe_source.fetch_parameters.partition_keys.");
    const cols: string[] = [];
    for (const r of res.rows.slice(0, 50)) for (const k of Object.keys(r)) if (!cols.includes(k)) cols.push(k);
    const retrieved = new Date().toISOString().replace(/\.\d+Z$/, "Z");
    const lic = e.license;
    // Cite the files behind the rows returned when the manifest records them (format 1 + per-partition "u").
    const sourceUrls = res.source_urls.length ? res.source_urls : m.upstream.urls.slice(0, 20);
    const origin = sourceUrls[0] ?? e.homepage;
    return {
      source_id: id,
      row_count: res.rows.length,
      truncated: res.truncated,
      columns: cols,
      rows: res.rows,
      warnings,
      notes: m.notes,
      metadata: trimMetadata(m.metadata, cols),
      caveats: e.caveats,
      provenance: {
        source_id: id,
        source_name: e.name,
        publisher: e.publisher.name,
        homepage: e.homepage,
        original_urls: sourceUrls.slice(0, 20),
        mirrored_at: m.ingested_at,
        mirror_release: m.release,
        upstream_version: m.upstream.detail,
        served_at: retrieved,
        filters,
        adapter_version: m.adapter_version,
        catalog_status: e.status,
        license: { name: lic.name, url: lic.url, redistribution: lic.redistribution, commercial_use: lic.commercial_use },
        citation: `${lic.attribution} Original data from ${origin}; mirrored ${m.ingested_at.slice(0, 10)} and served by librarycard.net.`,
        scan: { partitions_matched: res.partitions_matched, partitions_read: res.partitions_read, bytes_read: res.bytes_read },
      },
    };
  }
}

export const REQUEST_REPO = "https://github.com/lincolnq/librarycard";
const FIELD_MAX = 1500;

/** Build a prefilled GitHub issue-form link. Nothing is stored or sent: the user submits it themselves. */
export function requestData(a: Record<string, any>) {
  const clean = (v: any) => String(v ?? "").trim().slice(0, FIELD_MAX);
  const data = clean(a.data);
  const useCase = clean(a.use_case);
  if (data.length < 10 || useCase.length < 10) return err("data and use_case are required (at least a sentence each)");
  const title = clean(a.title).slice(0, 120) || data.split(/[.\n]/)[0].slice(0, 100);
  const params = new URLSearchParams({ template: "data-request.yml", title: `[data request] ${title}`, data, use_case: useCase });
  for (const k of ["geography", "time_range", "sources"]) if (a[k]) params.set(k, clean(a[k]));
  const url = `${REQUEST_REPO}/issues/new?${params.toString()}`;
  return {
    issue_url: url,
    instructions:
      "Show this link to your user. Opening it shows a prefilled GitHub issue they can edit and submit under their own " +
      "account (a GitHub login is required). It is public. Requests are triaged weekly; check the issue for the decision.",
    existing_requests: `${REQUEST_REPO}/issues?q=is%3Aissue+label%3Adata-request`,
  };
}

/** Prefilled data-issue link (same pattern as requestData). */
export function reportIssue(a: Record<string, any>) {
  const clean = (v: any) => String(v ?? "").trim().slice(0, FIELD_MAX);
  const problem = clean(a.problem);
  if (problem.length < 10) return err("problem is required (at least a sentence)");
  const sid = clean(a.source_id).slice(0, 80);
  const params = new URLSearchParams({ template: "data-issue.yml", title: `[data issue] ${sid}: ${problem.split(/[.\n]/)[0].slice(0, 80)}`, source_id: sid, problem });
  if (a.evidence) params.set("evidence", clean(a.evidence));
  if (a.suggested_caveat) params.set("suggested_caveat", clean(a.suggested_caveat));
  return {
    issue_url: `${REQUEST_REPO}/issues/new?${params.toString()}`,
    instructions: "Show this link to your user; they review and submit it under their own GitHub account. It is public. Thank you for reporting.",
  };
}

/** metadata.variable_labels can cover thousands of columns (e.g. ACS); return only the labels of this result's columns. */
export function trimMetadata(meta: Record<string, any>, cols: string[]): Record<string, any> {
  const vl = meta?.variable_labels;
  if (!vl || typeof vl !== "object" || Array.isArray(vl)) return meta;
  const keep = new Set(cols);
  return { ...meta, variable_labels: Object.fromEntries(Object.entries(vl).filter(([k]) => keep.has(k))) };
}
