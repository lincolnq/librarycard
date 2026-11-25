// Bundle public/ (the homepage) into src/generated/site.json so the Worker serves it without the static-assets
// upload API. Run by `npm run export`.
import { readdirSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
const TYPES = { html: "text/html; charset=utf-8", css: "text/css; charset=utf-8", js: "text/javascript; charset=utf-8", svg: "image/svg+xml", txt: "text/plain; charset=utf-8" };
const site = {};
for (const f of readdirSync(new URL("../public/", import.meta.url))) {
  const ext = f.split(".").pop();
  if (!TYPES[ext]) continue;
  site[`/${f}`] = { type: TYPES[ext], body: readFileSync(new URL(`../public/${f}`, import.meta.url), "utf8") };
}
site["/"] = site["/index.html"];
mkdirSync(new URL("../src/generated/", import.meta.url), { recursive: true });
writeFileSync(new URL("../src/generated/site.json", import.meta.url), JSON.stringify(site));
console.log(`bundled ${Object.keys(site).length - 1} site files`);
