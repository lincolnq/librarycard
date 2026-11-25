// Catalog search / summaries / status. A port of src/odc/catalog.py — keep the two in sync
// (test/search.test.ts runs the same TOP1 ranking cases as tests/test_search.py).

export type Entry = Record<string, any>;

const US_STATES = new Set([
  "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut", "delaware",
  "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
  "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
  "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey", "new mexico",
  "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
  "rhode island", "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
  "virginia", "washington", "west virginia", "wisconsin", "wyoming", "district of columbia",
  "puerto rico",
]);
const US_ALIASES = new Set(["us", "usa", "united states", "america", "u.s.", "u.s.a.", ...US_STATES]);
const STOP = new Set(["the", "a", "an", "of", "and", "or", "in", "for", "by", "to", "on", "data", "dataset",
  "what", "which", "how", "is", "are", "with", "at"]);
const WEIGHTS: Record<string, number> = {
  id_name: 5.0, tags: 4.0, publisher: 2.0, description: 2.0, variables: 1.5, coverage: 1.5, caveats: 0.3,
};

export function tokens(s: string): string[] {
  return ((s || "").toLowerCase().match(/[a-z0-9]+/g) || []).filter((t) => !STOP.has(t));
}

export function stem(t: string): string {
  for (const suf of ["ies", "es", "s"]) {
    if (t.length > 4 && t.endsWith(suf)) return t.slice(0, -suf.length) + (suf === "ies" ? "y" : "");
  }
  return t;
}

function fieldText(e: Entry): Record<string, string> {
  const kv = (e.key_variables || []).map((v: any) => `${v.name} ${v.label || ""} ${v.definition}`).join(" ");
  const cov = e.coverage;
  return {
    id_name: `${e.id.replaceAll("-", " ")} ${e.name}`,
    tags: [...e.tags, ...e.domains].join(" ").replaceAll("_", " ").replaceAll("-", " "),
    publisher: e.publisher.name,
    description: e.description,
    variables: kv,
    coverage: `${cov.geography} ${cov.geographic_granularity.join(" ")} ${cov.unit_of_observation}`.replaceAll("_", " "),
    caveats: (e.caveats || []).join(" "),
  };
}

const fieldCache = new WeakMap<Entry, Record<string, Set<string>>>();

function fieldsOf(e: Entry): Record<string, Set<string>> {
  let f = fieldCache.get(e);
  if (!f) {
    f = {};
    for (const [k, v] of Object.entries(fieldText(e))) f[k] = new Set(tokens(v).map(stem));
    fieldCache.set(e, f);
  }
  return f;
}

export function score(e: Entry, terms: string[]): number {
  const fields = fieldsOf(e);
  let s = 0;
  let matched = 0;
  for (const t of terms) {
    const st = stem(t);
    let hit = false;
    for (const [f, words] of Object.entries(fields)) {
      if (words.has(st)) {
        s += WEIGHTS[f];
        hit = true;
      } else if (st.length >= 4) {
        for (const w of words) {
          if (w.startsWith(st)) {
            s += WEIGHTS[f] * 0.4;
            hit = true;
            break;
          }
        }
      }
    }
    if (hit) matched++;
  }
  if (!matched) return 0;
  return s * (matched / terms.length);
}

function geoMatch(e: Entry, geography: string): boolean {
  const g = geography.trim().toLowerCase();
  const cov = e.coverage;
  const gran = new Set<string>(cov.geographic_granularity.map((x: string) => x.replaceAll("_", " ")));
  if (gran.has(g) || gran.has(g.replace(/s$/, "")) || cov.geographic_granularity.includes(g.replaceAll(" ", "_"))) return true;
  if (US_ALIASES.has(g) && cov.countries.includes("US")) return true;
  if (g.length === 2 && cov.countries.includes(g.toUpperCase())) return true;
  return cov.geography.toLowerCase().includes(g);
}

export function parseYearRange(s: string): [number, number] {
  const ys = (s.match(/\d{4}/g) || []).map(Number);
  if (!ys.length) throw new Error(`time_range '${s}' must contain a 4-digit year, e.g. '2020' or '2010-2020'`);
  return [Math.min(...ys), Math.max(...ys)];
}

function timeOverlap(e: Entry, tr: string): boolean {
  const [lo, hi] = parseYearRange(tr);
  const r = e.coverage.time_range;
  const start = Number(String(r.start).slice(0, 4));
  const end = r.end ? Number(String(r.end).slice(0, 4)) : new Date().getUTCFullYear();
  return start <= hi && lo <= end;
}

export function fetchable(e: Entry): boolean {
  return Boolean(e._mirrored) && ["healthy", "degraded"].includes(e.status);
}

export function summary(e: Entry, s?: number): Record<string, any> {
  const out: Record<string, any> = {
    id: e.id,
    name: e.name,
    publisher: e.publisher.name,
    description: e.description,
    domains: e.domains,
    geographic_granularity: e.coverage.geographic_granularity,
    time_range: e.coverage.time_range,
    access_method: e.access.method,
    status: e.status,
    fetchable: fetchable(e),
    redistribution: e.license.redistribution,
    caveat_count: e.caveats.length,
  };
  if (!out.fetchable) out.fetch_note = notFetchableReason(e);
  if (e.status !== "healthy") out.status_reason = e.status_reason;
  if (e.access.mcp_server) out.mcp_server = e.access.mcp_server.url;
  if (s !== undefined) out.score = Math.round(s * 1000) / 1000;
  return out;
}

export function notFetchableReason(e: Entry): string {
  if (e.access.method === "restricted") return `catalog-only: ${e.access.restricted_reason}`;
  if (["quarantined", "retired"].includes(e.status)) return `${e.status}: ${e.status_reason}`;
  if (e.license.redistribution !== "allowed")
    return "license is link_only, so this server does not mirror it; fetch from the publisher (see describe_source.how_to_access)";
  return "not yet mirrored";
}

export function search(entries: Entry[], query: string, opts: { domain?: string; geography?: string; time_range?: string; limit?: number; include_retired?: boolean } = {}) {
  const terms = tokens(query);
  const scored: [number, Entry][] = [];
  for (const e of entries) {
    if (e.status === "retired" && !opts.include_retired) continue;
    if (opts.domain && !e.domains.includes(opts.domain)) continue;
    if (opts.geography && !geoMatch(e, opts.geography)) continue;
    if (opts.time_range && !timeOverlap(e, opts.time_range)) continue;
    let s = terms.length ? score(e, terms) : 1.0;
    if (terms.length && s <= 0) continue;
    // Same nudge as the Python server: healthy adapter-backed sources rank above equally relevant broken ones.
    if (e.status === "healthy" && e.adapter) s *= 1.05;
    else if (["quarantined", "retired"].includes(e.status)) s *= 0.7;
    scored.push([s, e]);
  }
  scored.sort((a, b) => b[0] - a[0] || (a[1].id < b[1].id ? -1 : 1));
  return scored.slice(0, opts.limit ?? 10).map(([s, e]) => summary(e, s));
}

export function statusReport(entries: Entry[], recentDays = 30) {
  const counts: Record<string, number> = { healthy: 0, degraded: 0, quarantined: 0, retired: 0 };
  const today = Date.now();
  const days = (d: string) => (today - Date.parse(d)) / 86400000;
  for (const e of entries) counts[e.status] = (counts[e.status] || 0) + 1;
  return {
    total_sources: entries.length,
    counts_by_status: counts,
    fetchable: entries.filter(fetchable).length,
    link_only_not_mirrored: entries.filter((e) => e.adapter && e.license.redistribution !== "allowed").map((e) => e.id).sort(),
    catalog_only_restricted: entries.filter((e) => e.access.method === "restricted").map((e) => e.id).sort(),
    recently_changed_status: entries
      .filter((e) => days(e.status_since) <= recentDays)
      .map((e) => ({ id: e.id, status: e.status, status_since: e.status_since, status_reason: e.status_reason }))
      .sort((a, b) => (a.status_since < b.status_since ? 1 : -1)),
    not_verified_in_90_days: entries
      .filter((e) => e.status !== "retired" && days(e.last_verified) > 90)
      .map((e) => ({ id: e.id, last_verified: e.last_verified })),
    as_of: new Date().toISOString().slice(0, 10),
  };
}
