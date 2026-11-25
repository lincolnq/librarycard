# CLAUDE.md — read this first

This repository is maintained mostly by autonomous agents (Claude Code scheduled tasks) with no memory
between runs. Everything you need is in the repo. Read this file fully, then the doc for your task.

## What this is

A **find-and-fetch layer** over high-quality public datasets (domain: US domestic policy — elections,
demographics/Census, economy, health, education, housing, public finance, legislation, disasters),
exposed as an **MCP server**. Consuming agents use it to discover sources, read coverage and caveats,
and fetch data **with provenance** from the original publisher, then do their own analysis.

Non-goals (do not build these): answering questions / NL Q&A / precomputed answers; mirroring datasets;
anything requiring credentials, sign-up, or a data-use agreement (those get catalog-only
`access.method: restricted` entries with no adapter).

## Map of the repo

| Path | What |
|---|---|
| `catalog/<id>.yaml` | One entry per source. Schema: `schema/catalog-entry.schema.json`, explained in `docs/SCHEMA.md`. `_TEMPLATE.yaml` is the starting point. |
| `src/odc/adapters/<module>.py` | One adapter per fetchable source, defining `ADAPTER`. Base class + docs: `src/odc/adapters/base.py`. Shared helpers: `_common.py` (Census, Socrata, Dataverse, OpenFEMA, CSV scanning, state FIPS). Template: `_template.py`. |
| `src/odc/server.py` | MCP server: `search_catalog`, `describe_source`, `fetch`, `catalog_status`. |
| `src/odc/catalog.py` | Load/validate/search the catalog. `src/odc/consistency.py`: cross-file checks. |
| `src/odc/http.py` | ALL network access goes through here (UA, retries, license-gated cache). |
| `src/odc/contracts.py` | Contract-test runner shared by pytest and the monitor. |
| `monitor/` | No-LLM monitoring: `detect_changes.py`, `run_contracts.py`, `file_issues.py`. |
| `.github/workflows/` | `ci.yml` (validate + offline tests; live contracts for sources touched by a PR), `monitor.yml` (daily). |
| `evidence/licenses/<id>/` | Dated license/terms snapshots + `NOTES.md` with the classification reasoning. |
| `ops/network-allowlist.txt` | Every host adapters/monitor contact. |
| `ops/queue.yaml` | Sources considered but not onboarded, with reasons. |
| `docs/POLICY.md` | **Binding** rules: scope, licensing, status transitions, network, escalation. |
| `docs/ADDING_A_SOURCE.md` | Step-by-step checklist to onboard a source. |
| `docs/RUNBOOKS.md` | How to handle `source-changed` and `needs-repair` issues. |
| `docs/SCHEMA.md` | Field-by-field catalog schema + how to evolve it. |

## Setup and everyday commands

```bash
uv venv && . .venv/bin/activate && uv pip install -e ".[dev]"   # or: python -m venv .venv && pip install -e ".[dev]"
odc validate                       # schema + consistency (adapters, evidence, allowlist, queue)
pytest -m "not live" -q            # offline tests — must pass before every commit
odc contract <id> [<id> ...]       # live contract tests for specific sources
pytest -m live -q                  # live contract tests for everything (slow-ish, network)
odc search "county election results"; odc describe <id>; odc fetch <id> '{"filter": "value"}' --limit 5
odc-server                         # run the MCP server on stdio (odc-server --http for HTTP)
```

## Task routing

- **"Onboard source X" / "add sources"** → `docs/ADDING_A_SOURCE.md` (follow every step; the checklist is the definition of done).
- **Issue labeled `source-changed`** → `docs/RUNBOOKS.md#source-changed`.
- **Issue labeled `needs-repair`** → `docs/RUNBOOKS.md#needs-repair` (one repair attempt, then degrade/quarantine).
- **Issue labeled `needs-human`** → do not act; humans only.
- **Schema change needed** → `docs/SCHEMA.md#evolving-the-schema`.

## Hard rules (summary of docs/POLICY.md — read it for details)

1. **Never** add credentials/API keys anywhere. Sources needing any key → `restricted`, `adapter: null`.
2. **Licensing:** read the real terms page, snapshot it (`scripts/snapshot_license.py`), write `NOTES.md`.
   Unclear/ambiguous/missing terms → `redistribution: link_only`. Never guess permissively.
3. **No caching** unless `redistribution: allowed` (the base class enforces this — use `odc.http.download`).
   Never commit data files.
4. **Never leave a broken source `healthy`.** One repair attempt, then `degraded` or `quarantined`.
5. **Network blocked?** Don't work around it: add the host to `ops/network-allowlist.txt`, queue the source
   in `ops/queue.yaml` with `reason: network`, move on.
6. **No personal data** about identifiable private individuals (public officials' official acts are fine).
7. Catalog `id`s are permanent. Never rename or delete an entry; retire it.
8. Escalate (`needs-human` issue) only for spend/usage anomalies, systemic failures, or genuine policy gaps.

## Conventions

- Python ≥ 3.11, dependencies: `mcp`, `httpx`, `pyyaml`, `jsonschema` (+ `pytest`). Don't add dependencies
  without a strong reason; prefer stdlib (csv, zipfile, gzip, json). No pandas.
- Adapters return plain lists of dicts with JSON-serialisable values. Keep publisher column names unless
  there's a reason (document renames in `key_variables`). Convert publisher sentinel codes (e.g. -999) to
  `null` and say so in `notes` and `caveats`.
- Bump `adapter_version` (semver) **in both** the adapter (`version = ...`) and the catalog entry whenever
  adapter behaviour changes: patch = bug fix, minor = new filter/column, major = changed output shape.
- Dates in YAML are quoted strings `"YYYY-MM-DD"`. Today's date comes from the system clock (`date -I`).
- Commit messages: `<area>: <what>` e.g. `catalog: onboard bls-laus`, `adapter(census-acs-summary-file): handle 2025 layout`.
  Reference issues with `Fixes #N` in PR bodies.
- Keep contract tests cheap (narrow filters, small limits) — they run daily in CI.
- POST-only APIs: put the request body in `metadata.request_body`. Fallback endpoints count as endpoints (allowlist + offline test).
- `ops/network-allowlist.txt`: append in the sources section; sort when convenient (merges are simpler).
