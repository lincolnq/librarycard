// Cloudflare Worker entry: MCP over Streamable HTTP (stateless, JSON responses) at POST /mcp.
//
// The protocol layer is implemented directly (JSON-RPC 2.0, no SDK): initialize, ping, tools/list, tools/call,
// and notifications. No sessions are created, so any request can hit any isolate.

import catalogData from "./generated/catalog.json" with { type: "json" };
import siteFiles from "./generated/site.json" with { type: "json" };
import { INSTRUCTIONS, TOOLS, Tools } from "./tools.ts";
import { summary } from "./catalog.ts";
import type { Store } from "./mirror.ts";

export interface Env {
  DATA: Store;
}

export const SERVER_INFO = { name: "librarycard", title: "librarycard open data catalog", version: "0.2.0" };
export const PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"];

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Accept, Mcp-Protocol-Version, Mcp-Session-Id, Last-Event-ID",
  "Access-Control-Expose-Headers": "Mcp-Protocol-Version",
};

function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...CORS, ...headers } });
}

type Rpc = { jsonrpc: "2.0"; id?: string | number | null; method?: string; params?: any };

export async function handleRpc(msg: Rpc, tools: Tools): Promise<Record<string, any> | null> {
  const isNotification = msg.id === undefined;
  const reply = (result: any) => ({ jsonrpc: "2.0", id: msg.id, result });
  const fail = (code: number, message: string, data?: any) => ({ jsonrpc: "2.0", id: msg.id ?? null, error: { code, message, ...(data ? { data } : {}) } });
  if (msg.jsonrpc !== "2.0" || typeof msg.method !== "string") return isNotification ? null : fail(-32600, "Invalid Request");
  if (msg.method.startsWith("notifications/")) return null;
  switch (msg.method) {
    case "initialize": {
      const asked = msg.params?.protocolVersion;
      const version = PROTOCOL_VERSIONS.includes(asked) ? asked : PROTOCOL_VERSIONS[0];
      return reply({ protocolVersion: version, capabilities: { tools: { listChanged: false } }, serverInfo: SERVER_INFO, instructions: INSTRUCTIONS });
    }
    case "ping":
      return reply({});
    case "tools/list":
      return reply({ tools: TOOLS });
    case "tools/call": {
      const name = msg.params?.name;
      if (!TOOLS.some((t) => t.name === name)) return fail(-32602, `Unknown tool: ${name}`);
      try {
        const out = await tools.call(name, msg.params?.arguments ?? {});
        return reply({ content: [{ type: "text", text: JSON.stringify(out) }], structuredContent: out, isError: "error" in out });
      } catch (e: any) {
        console.error("tool error", name, e?.stack ?? e);
        const out = { error: `Internal error in ${name}: ${e?.message ?? e}` };
        return reply({ content: [{ type: "text", text: JSON.stringify(out) }], structuredContent: out, isError: true });
      }
    }
    case "resources/list":
      return reply({ resources: [] });
    case "prompts/list":
      return reply({ prompts: [] });
    default:
      return isNotification ? null : fail(-32601, `Method not found: ${msg.method}`);
  }
}

export async function handleMcp(request: Request, tools: Tools): Promise<Response> {
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
  if (request.method !== "POST") {
    return json({ jsonrpc: "2.0", id: null, error: { code: -32000, message: "Method not allowed: this server is stateless; use POST" } }, 405, { Allow: "POST, OPTIONS" });
  }
  let body: any;
  try {
    body = await request.json();
  } catch {
    return json({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } }, 400);
  }
  if (Array.isArray(body)) {
    const out = (await Promise.all(body.map((m) => handleRpc(m, tools)))).filter((x) => x !== null);
    return out.length ? json(out) : new Response(null, { status: 202, headers: CORS });
  }
  const out = await handleRpc(body, tools);
  return out ? json(out) : new Response(null, { status: 202, headers: CORS });
}

let toolsSingleton: Tools | null = null;
const WEB_FETCH_MAX = 1000;

/** Read-only JSON API used by the homepage (public/). Same logic as the MCP tools. */
export async function handleApi(request: Request, url: URL, tools: Tools): Promise<Response> {
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
  const path = url.pathname.replace(/\/+$/, "");
  const q = url.searchParams;
  if (path === "/api/search" && request.method === "GET") {
    return json(tools.searchCatalog({
      query: q.get("q") ?? "", domain: q.get("domain") || undefined, geography: q.get("geography") || undefined,
      time_range: q.get("time_range") || undefined, limit: Number(q.get("limit") ?? 20),
    }));
  }
  if (path === "/api/status" && request.method === "GET") return json(await tools.call("catalog_status", {}));
  if (path === "/api/sources" && request.method === "GET") {
    return json({ sources: tools.entries.map((e) => summary(e)) });
  }
  const m = path.match(/^\/api\/source\/([a-z0-9-]+)$/);
  if (m && request.method === "GET") return json(await tools.describe(m[1]));
  if (path === "/api/fetch" && request.method === "POST") {
    let body: any;
    try {
      body = await request.json();
    } catch {
      return json({ error: "body must be JSON: {source_id, filters, columns?, limit?}" }, 400);
    }
    const limit = Math.min(Number(body.limit ?? 100), WEB_FETCH_MAX);
    return json(await tools.fetch(body.source_id, body.filters ?? {}, body.columns, limit));
  }
  return json({ error: "not found", endpoints: ["GET /api/search?q=", "GET /api/sources", "GET /api/source/<id>", "POST /api/fetch", "GET /api/status"] }, 404);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.hostname === "www.librarycard.net") {
      return Response.redirect(`https://librarycard.net${url.pathname}${url.search}`, 301);
    }
    toolsSingleton ??= new Tools((catalogData as any).entries, env.DATA);
    toolsSingleton.store = env.DATA;
    if (url.pathname === "/mcp") return handleMcp(request, toolsSingleton);
    if (url.pathname.startsWith("/api/")) return handleApi(request, url, toolsSingleton);
    if (url.pathname === "/healthz") {
      const entries = (catalogData as any).entries;
      return json({ ok: true, sources: entries.length, mirrored: entries.filter((e: any) => e._mirrored).length });
    }
    // Homepage files (public/, bundled by scripts/build-site.mjs).
    const file = (siteFiles as Record<string, { type: string; body: string }>)[url.pathname];
    if (file && request.method === "GET") {
      return new Response(file.body, { headers: { "content-type": file.type, "cache-control": "public, max-age=300" } });
    }
    return json({ error: "not found" }, 404);
  },
};
