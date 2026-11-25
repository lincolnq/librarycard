import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { search, statusReport } from "../src/catalog.ts";

const entries = JSON.parse(readFileSync(new URL("../src/generated/catalog.json", import.meta.url), "utf8")).entries;
const cases: Record<string, string> = JSON.parse(readFileSync(new URL("../../tests/search_cases.json", import.meta.url), "utf8"));

for (const [q, expected] of Object.entries(cases)) {
  test(`top-1 for "${q}" is ${expected} (same as Python)`, () => {
    assert.equal(search(entries, q, { limit: 3 })[0]?.id, expected);
  });
}

test("filters", () => {
  assert.ok(search(entries, "", { geography: "tract", limit: 100 }).some((r) => r.id === "census-acs-summary-file"));
  assert.ok(search(entries, "", { geography: "Texas", limit: 100 }).some((r) => r.id === "noaa-nclimgrid-daily"));
  assert.ok(!search(entries, "", { time_range: "1900-1940", limit: 100 }).some((r) => r.id === "noaa-nclimgrid-daily"));
  assert.throws(() => search(entries, "x", { time_range: "recent" }));
});

test("status", () => {
  const s = statusReport(entries);
  assert.equal(s.total_sources, entries.length);
});
