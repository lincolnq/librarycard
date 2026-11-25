// The four MCP tools. Same names, arguments and semantics as src/odc/server.py, except that `fetch`
// reads the R2 mirror (and accepts generic column filters) instead of calling publishers.

import { type Entry, fetchable, notFetchableReason, search, statusReport, summary } from "./catalog.ts";
import { DEFAULT_LIMIT, fetchParameters, loadManifest, MAX_LIMIT, QueryError, query, type Store } from "./mirror.ts";

export const INSTRUCTIONS = `librarycard: a find-and-fetch layer over reputable public datasets for US policy research
(elections, demographics/Census, economy, health, education, housing, public finance, legislation, disasters).
It does NOT answer questions or compute statistics; you do the analysis.

Workflow:
1. search_catalog to find candidate sources (results say whether each is fetchable here).
2. describe_source BEFORE analysis: read \`caveats\` (margins of error, series breaks, suppression, license limits)
   and \`fetch_parameters\` (partition keys and columns you can filter on).
3. fetch with narrow filters. Cite \`provenance\` (publisher, original URL, release, license) whenever you report numbers.
Data for redistributable sources is served from a mirror refreshed when the publisher releases new data; check
provenance.mirrored_at. Sources marked not fetchable list how to get the data from the publisher directly.
For national/international indicator time series also consider Google Data Commons (catalog id \`data-commons\`).`;

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
      '{"gte":x,"lte":y} (range), or {"contains":"text"}. Filter on the partition keys listed in describe_source.fetch_parameters ' +
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
    const origin = m.upstream.urls[0] ?? e.homepage;
    return {
      source_id: id,
      row_count: res.rows.length,
      truncated: res.truncated,
      columns: cols,
      rows: res.rows,
      warnings,
      notes: m.notes,
      metadata: m.metadata,
      caveats: e.caveats,
      provenance: {
        source_id: id,
        source_name: e.name,
        publisher: e.publisher.name,
        homepage: e.homepage,
        original_urls: m.upstream.urls.slice(0, 20),
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
