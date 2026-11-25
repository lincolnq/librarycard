import { test } from "node:test";
import assert from "node:assert/strict";
import { clearCache, type Manifest, type Store } from "../src/mirror.ts";
import { Tools } from "../src/tools.ts";
import { handleRpc } from "../src/index.ts";

async function gz(text: string): Promise<Uint8Array> {
  const s = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
  return new Uint8Array(await new Response(s).arrayBuffer());
}

// Build a tiny mirror for a fake entry, in the exact format src/odc/mirror.py writes.
async function fixture() {
  const rowsByState: Record<string, any[]> = {
    GA: [{ year: 2020, state_po: "GA", state_fips: "13", candidate: "BIDEN, JOSEPH R. JR", candidatevotes: 2473633 },
         { year: 2020, state_po: "GA", state_fips: "13", candidate: "TRUMP, DONALD J.", candidatevotes: 2461854 },
         { year: 2016, state_po: "GA", state_fips: "13", candidate: "TRUMP, DONALD J.", candidatevotes: 2089104 }],
    WY: [{ year: 2020, state_po: "WY", state_fips: "56", candidate: "TRUMP, DONALD J.", candidatevotes: 193559 }],
  };
  const chunks: Uint8Array[] = [];
  const partitions: any[] = [];
  let off = 0;
  for (const [st, rows] of Object.entries(rowsByState)) {
    const blob = await gz(rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
    partitions.push({ k: { state_po: st }, c: 0, p: 0, o: off, n: blob.length, r: rows.length });
    chunks.push(blob);
    off += blob.length;
  }
  const pack = new Uint8Array(off);
  let o = 0;
  for (const c of chunks) { pack.set(c, o); o += c.length; }
  const manifest: Manifest = {
    format: 1, source_id: "fake-src", release: "R1", ingested_at: "2026-11-25T00:00:00+00:00", adapter_version: "1.0.0",
    row_count: 4, packs: ["pack-0.bin"], partitions, partition_keys: ["state_po"], required_filters: [],
    semantics: { state_po: "state_postal", state_fips: "state_fips" },
    columns: { year: { type: "integer", nulls: 0, min: 2016, max: 2020 }, state_po: { type: "string", nulls: 0 },
               state_fips: { type: "string", nulls: 0 }, candidate: { type: "string", nulls: 0 }, candidatevotes: { type: "integer", nulls: 0 } },
    notes: ["note"], metadata: {}, upstream: { urls: ["https://example.gov/data.csv"], fingerprint: "x", detail: "v1" },
    license: {},
  };
  const objects: Record<string, Uint8Array | string> = {
    "mirror/fake-src/current.json": JSON.stringify({ release: "R1", manifest: "mirror/fake-src/R1/manifest.json" }),
    "mirror/fake-src/R1/manifest.json": JSON.stringify(manifest),
    "mirror/fake-src/R1/pack-0.bin": pack,
  };
  const reads: string[] = [];
  const store: Store = {
    async get(key, opts) {
      const v = objects[key];
      if (v === undefined) return null;
      reads.push(key + (opts?.range ? `@${opts.range.offset}+${opts.range.length}` : ""));
      const bytes = typeof v === "string" ? new TextEncoder().encode(v) : v;
      const slice = opts?.range ? bytes.slice(opts.range.offset, opts.range.offset + opts.range.length) : bytes;
      return { arrayBuffer: async () => slice.buffer.slice(slice.byteOffset, slice.byteOffset + slice.byteLength), text: async () => new TextDecoder().decode(slice) };
    },
  };
  const entry = {
    id: "fake-src", name: "Fake", publisher: { name: "Pub" }, homepage: "https://example.gov", description: "d",
    domains: ["elections"], tags: [], coverage: { geography: "US", countries: ["US"], geographic_granularity: ["state"], time_range: { start: "2016", end: "2020" }, unit_of_observation: "x" },
    access: { method: "bulk_download", endpoints: [] }, license: { name: "CC0", url: "u", redistribution: "allowed", commercial_use: "yes", attribution: "Pub, Fake." },
    key_variables: [{ name: "candidatevotes", definition: "votes", unit: "votes" }], caveats: ["a caveat that matters"], status: "healthy",
    status_reason: "ok", status_since: "2026-11-24", last_verified: "2026-11-24", adapter: "fake", adapter_version: "1.0.0", _mirrored: true,
  };
  const restricted = { ...entry, id: "locked", _mirrored: false, access: { method: "restricted", restricted_reason: "needs key", endpoints: [] } };
  clearCache();
  return { tools: new Tools([entry, restricted], store), reads };
}

test("fetch reads only matching partitions, with provenance", async () => {
  const { tools, reads } = await fixture();
  const out: any = await tools.fetch("fake-src", { state_po: "13", year: 2020 }, undefined, 10); // FIPS accepted for postal column
  assert.equal(out.row_count, 2);
  assert.deepEqual(out.rows.map((r: any) => r.candidatevotes), [2473633, 2461854]);
  assert.equal(reads.filter((r) => r.includes("pack-0.bin")).length, 1, "only the GA partition is read");
  assert.equal(out.provenance.mirrored_at, "2026-11-25T00:00:00+00:00");
  assert.ok(out.provenance.citation.includes("https://example.gov/data.csv"));
  assert.deepEqual(out.caveats, ["a caveat that matters"]);
});

test("ranges, contains, columns, limit/truncation", async () => {
  const { tools } = await fixture();
  let out: any = await tools.fetch("fake-src", { candidatevotes: { gte: 2000000 }, candidate: { contains: "trump" } }, ["state_po", "year"], 10);
  assert.deepEqual(out.rows, [{ state_po: "GA", year: 2020 }, { state_po: "GA", year: 2016 }]);
  out = await tools.fetch("fake-src", {}, undefined, 2);
  assert.equal(out.row_count, 2);
  assert.equal(out.truncated, true);
});

test("errors are helpful", async () => {
  const { tools } = await fixture();
  let out: any = await tools.fetch("fake-src", { nope: 1 });
  assert.match(out.error, /unknown filter column/);
  out = await tools.fetch("locked", {});
  assert.match(out.error, /cannot be fetched/);
  assert.ok(out.how_to_access);
  out = await tools.fetch("no-such", {});
  assert.match(out.error, /Unknown source_id/);
  const d: any = await tools.describe("fake-src");
  assert.deepEqual(d.fetch_parameters.partition_keys[0].values, ["GA", "WY"]);
  assert.equal(d.fetch_parameters.columns.find((c: any) => c.name === "candidatevotes").definition, "votes");
});

test("MCP JSON-RPC: initialize, tools/list, tools/call, notifications", async () => {
  const { tools } = await fixture();
  const init: any = await handleRpc({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18" } }, tools);
  assert.equal(init.result.protocolVersion, "2025-06-18");
  const future: any = await handleRpc({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2099-01-01" } }, tools);
  assert.equal(future.result.protocolVersion, "2025-11-25");
  assert.equal(await handleRpc({ jsonrpc: "2.0", method: "notifications/initialized" }, tools), null);
  const list: any = await handleRpc({ jsonrpc: "2.0", id: 2, method: "tools/list" }, tools);
  assert.deepEqual(list.result.tools.map((t: any) => t.name).sort(), ["catalog_status", "describe_source", "fetch", "search_catalog"]);
  const call: any = await handleRpc({ jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "fetch", arguments: { source_id: "fake-src", filters: { state_po: "WY" } } } }, tools);
  assert.equal(call.result.structuredContent.row_count, 1);
  assert.equal(call.result.isError, false);
  const bad: any = await handleRpc({ jsonrpc: "2.0", id: 4, method: "nope" }, tools);
  assert.equal(bad.error.code, -32601);
});
