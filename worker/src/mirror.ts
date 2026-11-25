// Read mirrored data from R2. Format is defined by src/odc/mirror.py (manifest "format": 1).

export interface Part { k: Record<string, string>; c: number; p: number; o: number; n: number; r: number }
export interface Manifest {
  format: number;
  source_id: string;
  release: string;
  ingested_at: string;
  adapter_version: string;
  row_count: number;
  packs: string[];
  partitions: Part[];
  partition_keys: string[];
  required_filters: string[];
  semantics: Record<string, string>;
  columns: Record<string, { type: string; nulls: number; min?: any; max?: any; values?: any[] }>;
  notes: string[];
  metadata: Record<string, any>;
  upstream: { urls: string[]; fingerprint: string | null; detail: string | null };
  license: Record<string, string>;
}

/** Minimal interface over an R2 bucket binding (lets tests substitute an in-memory store). */
export interface Store {
  get(key: string, opts?: { range?: { offset: number; length: number } }): Promise<{ arrayBuffer(): Promise<ArrayBuffer>; text(): Promise<string> } | null>;
}

export class QueryError extends Error {
  detail: Record<string, any>;
  constructor(message: string, detail: Record<string, any> = {}) {
    super(message);
    this.detail = detail;
  }
}

const MANIFEST_TTL_MS = 5 * 60 * 1000;
const cache = new Map<string, { at: number; m: Manifest | null }>();
export const MAX_SCAN_BYTES = 60_000_000; // compressed bytes read per request before we ask for narrower filters
export const MAX_LIMIT = 5000;
export const DEFAULT_LIMIT = 500;

export async function loadManifest(store: Store, sid: string): Promise<Manifest | null> {
  const hit = cache.get(sid);
  if (hit && Date.now() - hit.at < MANIFEST_TTL_MS) return hit.m;
  const cur = await store.get(`mirror/${sid}/current.json`);
  let m: Manifest | null = null;
  if (cur) {
    const pointer = JSON.parse(await cur.text());
    const obj = await store.get(pointer.manifest);
    if (obj) m = JSON.parse(await obj.text());
  }
  cache.set(sid, { at: Date.now(), m });
  return m;
}

export function clearCache() {
  cache.clear();
}

// ------------------------------------------------------------------ value normalisation

const STATE_FIPS: Record<string, string> = {
  AL: "01", AK: "02", AZ: "04", AR: "05", CA: "06", CO: "08", CT: "09", DE: "10", DC: "11", FL: "12", GA: "13",
  HI: "15", ID: "16", IL: "17", IN: "18", IA: "19", KS: "20", KY: "21", LA: "22", ME: "23", MD: "24", MA: "25",
  MI: "26", MN: "27", MS: "28", MO: "29", MT: "30", NE: "31", NV: "32", NH: "33", NJ: "34", NM: "35", NY: "36",
  NC: "37", ND: "38", OH: "39", OK: "40", OR: "41", PA: "42", RI: "44", SC: "45", SD: "46", TN: "47", TX: "48",
  UT: "49", VT: "50", VA: "51", WA: "53", WV: "54", WI: "55", WY: "56", PR: "72", AS: "60", GU: "66", MP: "69", VI: "78",
};
const FIPS_STATE: Record<string, string> = Object.fromEntries(Object.entries(STATE_FIPS).map(([a, f]) => [f, a]));

function normalize(semantic: string | undefined, v: any): any {
  if (v === null || v === undefined || !semantic) return v;
  const s = String(v).trim();
  if (semantic === "state_postal") {
    if (/^\d{1,2}$/.test(s) && FIPS_STATE[s.padStart(2, "0")]) return FIPS_STATE[s.padStart(2, "0")];
    return s.toUpperCase();
  }
  if (semantic === "state_fips") {
    if (STATE_FIPS[s.toUpperCase()]) return STATE_FIPS[s.toUpperCase()];
    return /^\d+$/.test(s) ? s.padStart(2, "0") : s;
  }
  if (semantic === "county_fips") return /^\d+$/.test(s) ? s.padStart(5, "0") : s;
  return v;
}

// ------------------------------------------------------------------ filters

type Cond = { kind: "in"; values: any[] } | { kind: "range"; gte?: any; lte?: any; gt?: any; lt?: any } | { kind: "contains"; value: string };

function parseCond(name: string, raw: any, semantic?: string): Cond {
  if (raw !== null && typeof raw === "object" && !Array.isArray(raw)) {
    const keys = Object.keys(raw);
    if (keys.length === 1 && keys[0] === "contains") return { kind: "contains", value: String(raw.contains).toLowerCase() };
    if (keys.length && keys.every((k) => ["gte", "lte", "gt", "lt"].includes(k))) {
      const c: any = { kind: "range" };
      for (const k of keys) c[k] = normalize(semantic, raw[k]);
      return c;
    }
    throw new QueryError(`filter '${name}': object conditions must use gte/lte/gt/lt or contains, got ${JSON.stringify(raw)}`);
  }
  const values = (Array.isArray(raw) ? raw : [raw]).map((v) => normalize(semantic, v));
  return { kind: "in", values };
}

function eq(a: any, b: any): boolean {
  if (a === null || a === undefined) return b === null;
  if (typeof a === "number" || typeof b === "number") {
    const na = Number(a), nb = Number(b);
    if (!Number.isNaN(na) && !Number.isNaN(nb) && String(b).trim() !== "") return na === nb;
  }
  if (typeof a === "boolean") return String(a) === String(b).toLowerCase();
  return String(a).toLowerCase() === String(b).toLowerCase();
}

function cmp(a: any, b: any): number {
  const sa = String(a).trim(), sb = String(b).trim();
  const na = Number(sa), nb = Number(sb);
  if (sa !== "" && sb !== "" && !Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
  return sa < sb ? -1 : sa > sb ? 1 : 0;
}

function test(c: Cond, v: any): boolean {
  if (c.kind === "in") return c.values.some((x) => eq(v, x));
  if (v === null || v === undefined || v === "") return false;
  if (c.kind === "contains") return String(v).toLowerCase().includes(c.value);
  if (c.gte !== undefined && cmp(v, c.gte) < 0) return false;
  if (c.gt !== undefined && cmp(v, c.gt) <= 0) return false;
  if (c.lte !== undefined && cmp(v, c.lte) > 0) return false;
  if (c.lt !== undefined && cmp(v, c.lt) >= 0) return false;
  return true;
}

// ------------------------------------------------------------------ describe

export function partitionValues(m: Manifest): Record<string, string[]> {
  const out: Record<string, Set<string>> = {};
  for (const k of m.partition_keys) out[k] = new Set();
  for (const p of m.partitions) for (const k of m.partition_keys) out[k].add(p.k[k]);
  return Object.fromEntries(Object.entries(out).map(([k, s]) => [k, [...s].sort()]));
}

export function fetchParameters(m: Manifest, keyVariables: any[] = []): Record<string, any> {
  const defs = Object.fromEntries(keyVariables.map((v) => [v.name, v]));
  const pv = partitionValues(m);
  return {
    mode: "mirror",
    release: m.release,
    ingested_at: m.ingested_at,
    row_count: m.row_count,
    how_to_filter:
      "filters is an object of {column: condition}. A condition is a value (exact match, case-insensitive), " +
      "a list of values (any of), {\"gte\":x,\"lte\":y} (range; also gt/lt), or {\"contains\":\"text\"}. " +
      "Partition keys select which slices are read, so always filter on them when you can. " +
      "Use `columns` to return a subset of columns.",
    partition_keys: m.partition_keys.map((k) => ({
      name: k,
      required: m.required_filters.includes(k),
      values: pv[k].length <= 300 ? pv[k] : [...pv[k].slice(0, 300), `... ${pv[k].length - 300} more`],
    })),
    columns: Object.entries(m.columns).map(([name, c]) => ({
      name,
      ...c,
      ...(m.semantics[name] ? { accepts: m.semantics[name] } : {}),
      ...(defs[name] ? { definition: defs[name].definition, unit: defs[name].unit } : {}),
    })),
    notes: m.notes,
    default_limit: DEFAULT_LIMIT,
    max_limit: MAX_LIMIT,
  };
}

// ------------------------------------------------------------------ query

export interface QueryResult {
  rows: Record<string, any>[];
  truncated: boolean;
  partitions_read: number;
  partitions_matched: number;
  bytes_read: number;
  scan_stopped_early: boolean;
}

export async function query(store: Store, m: Manifest, filters: Record<string, any>, columns: string[] | undefined, limit: number): Promise<QueryResult> {
  const known = new Set([...m.partition_keys, ...Object.keys(m.columns)]);
  const unknown = Object.keys(filters).filter((k) => !known.has(k));
  if (unknown.length) {
    throw new QueryError(`unknown filter column(s) ${JSON.stringify(unknown)}`, { available_columns: [...known] });
  }
  if (columns) {
    const bad = columns.filter((c) => !known.has(c));
    if (bad.length) throw new QueryError(`unknown column(s) in columns: ${JSON.stringify(bad)}`, { available_columns: [...known] });
  }
  const missing = m.required_filters.filter((k) => !(k in filters));
  if (missing.length) {
    throw new QueryError(`this source is large; filter on ${JSON.stringify(missing)} (see describe_source.fetch_parameters.partition_keys)`, {
      partition_values: Object.fromEntries(missing.map((k) => [k, partitionValues(m)[k].slice(0, 100)])),
    });
  }
  const conds: Record<string, Cond> = {};
  for (const [k, v] of Object.entries(filters)) conds[k] = parseCond(k, v, m.semantics[k]);
  const partConds = Object.entries(conds).filter(([k]) => m.partition_keys.includes(k));
  const parts = m.partitions.filter((p) => partConds.every(([k, c]) => test(c, p.k[k])));
  const rowConds = Object.entries(conds);
  const out: Record<string, any>[] = [];
  let bytes = 0;
  let read = 0;
  let stoppedEarly = false;
  for (const p of parts) {
    if (out.length > limit) break;
    if (bytes + p.n > MAX_SCAN_BYTES && read > 0) {
      stoppedEarly = true;
      break;
    }
    const key = `mirror/${m.source_id}/${m.release}/${m.packs[p.p]}`;
    const obj = await store.get(key, { range: { offset: p.o, length: p.n } });
    if (!obj) throw new Error(`missing pack object ${key}`);
    const text = await gunzip(await obj.arrayBuffer());
    bytes += p.n;
    read++;
    for (const line of text.split("\n")) {
      if (!line) continue;
      const row = JSON.parse(line);
      if (rowConds.every(([k, c]) => test(c, k in row ? row[k] : p.k[k]))) {
        out.push(columns ? Object.fromEntries(columns.map((c) => [c, row[c] ?? p.k[c] ?? null])) : row);
        if (out.length > limit) break;
      }
    }
  }
  return {
    rows: out.slice(0, limit),
    truncated: out.length > limit || stoppedEarly,
    partitions_read: read,
    partitions_matched: parts.length,
    bytes_read: bytes,
    scan_stopped_early: stoppedEarly,
  };
}

export async function gunzip(buf: ArrayBuffer): Promise<string> {
  const stream = new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip"));
  return await new Response(stream).text();
}
