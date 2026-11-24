# Open Data Catalog + MCP service

A find-and-fetch layer over high-quality public datasets for **US domestic policy research** (elections and politics,
demographics and Census, economy and labor, health, education, housing, public finance, disasters), exposed as an
[MCP](https://modelcontextprotocol.io) server.

Agents use it to **discover** which sources can answer a question, **understand** coverage and caveats, and
**fetch** data on demand from the original publisher, with provenance attached. They do the analysis themselves.

- It does not answer questions or ship precomputed "answers".
- It does not mirror datasets. Data are fetched from the publisher on demand; caching only where the license allows.
- It does not handle data needing sign-up, keys or data-use agreements. Those sources get catalog-only `restricted`
  entries so agents know they exist (e.g. the Census Data API, Google Data Commons).

The repo is maintained mostly by autonomous agents. **Start with [CLAUDE.md](CLAUDE.md).**

## Using the MCP server

```bash
uv venv && . .venv/bin/activate && uv pip install -e .
odc-server                 # stdio transport
odc-server --http          # streamable HTTP at http://127.0.0.1:8765/mcp
```

Example MCP client config (stdio):

```json
{"mcpServers": {"open-data-catalog": {"command": "/path/to/repo/.venv/bin/odc-server"}}}
```

Tools:

| Tool | Returns |
|---|---|
| `search_catalog(query, domain?, geography?, time_range?, limit?)` | Ranked source summaries, including status and whether each is fetchable |
| `describe_source(source_id)` | Full entry: coverage, key variables, **caveats**, license, status, and `fetch_parameters` |
| `fetch(source_id, filters, limit?)` | `rows` + `provenance` (publisher, request URLs, retrieval time, license, citation) + caveats + warnings. Refuses quarantined, retired and restricted sources; warns on degraded ones |
| `catalog_status()` | Counts by status, recent status changes, catalog-only entries, entries not re-verified in 90 days |

## How it stays healthy

- `monitor.yml` runs daily with no LLM. `monitor/detect_changes.py` polls each source's change signal. `monitor/run_contracts.py`
  runs live contract tests on a rotating sample. `monitor/file_issues.py` opens deduplicated GitHub issues:
  `source-changed`, `needs-repair`, and `needs-human` for systemic failures.
- Scheduled agents act on those issues following [docs/RUNBOOKS.md](docs/RUNBOOKS.md) and [docs/POLICY.md](docs/POLICY.md).

## Docs

- [CLAUDE.md](CLAUDE.md): orientation for agents
- [docs/POLICY.md](docs/POLICY.md): scope, licensing, status transitions, network, escalation (binding)
- [docs/ADDING_A_SOURCE.md](docs/ADDING_A_SOURCE.md): onboarding checklist
- [docs/RUNBOOKS.md](docs/RUNBOOKS.md): handling monitor issues
- [docs/SCHEMA.md](docs/SCHEMA.md): catalog fields, change detection, schema evolution
