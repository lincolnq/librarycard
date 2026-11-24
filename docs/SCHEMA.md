# Catalog schema (schema_version 1)

Machine-readable definition: `schema/catalog-entry.schema.json` (JSON Schema 2020-12). This document explains
intent. `odc validate` checks both the schema and cross-file consistency (`src/odc/consistency.py`).

## Fields

YAML gotcha: quote any string containing `": "` (or starting with `-`, `:`, `{`, `[`, `*`, `&`, `!`, `%`, `@`, `` ` ``),
otherwise it is parsed as a mapping/other type and the entry fails validation.

| Field | Meaning / rules |
|---|---|
| `schema_version` | Integer, currently `1`. See [Evolving the schema](#evolving-the-schema). |
| `id` | Lowercase slug, equals the file name. **Permanent**: never renamed or reused. |
| `name` | Human-readable dataset name as the publisher calls it. |
| `publisher` | `name`, `url`, `type` (`us_federal`, `us_state`, `us_local`, `intergovernmental`, `research_institution`, `open_data_project`, `other_reputable`). |
| `homepage` | The dataset's landing page (for humans). |
| `description` | 2–4 plain sentences: what it measures and how it is produced. 80–1200 chars. |
| `domains` | Controlled vocabulary (see schema `$defs/domain`). Used by `search_catalog(domain=...)`. |
| `tags` | Free lowercase keywords that help search (synonyms, acronyms, program names). |
| `coverage.geography` | Human-readable spatial extent. |
| `coverage.countries` | ISO-3166 alpha-2 list, e.g. `[US]`. |
| `coverage.geographic_granularity` | Controlled vocabulary (`$defs/granularity`): the spatial units **and** record-level units (e.g. `person`, `legislator`, `roll_call`, `event`) at which rows are available. |
| `coverage.time_range` | `start`, `end` (`YYYY`, `YYYY-MM` or `YYYY-MM-DD`; `end: null` = ongoing), optional `notes`. |
| `coverage.temporal_granularity` | Controlled vocabulary (`$defs/period`). |
| `coverage.unit_of_observation` | What one row represents. |
| `access.method` | `api` \| `bulk_download` \| `cloud_bucket` \| `restricted`. |
| `access.endpoints` | List of `{url, description}` — the URLs/patterns the adapter (including any fallback path) contacts. Every host must be allowlisted. Put informational links in `access.notes`. |
| `access.formats`, `rate_limits`, `notes` | Free text. |
| `access.auth` | `none` for anything with an adapter. Otherwise `credentials_required` / `registration_required` / `data_use_agreement` and method must be `restricted`. |
| `access.restricted_reason` | Required when restricted: what blocks automated access. |
| `access.mcp_server` | `{url, notes}` when the publisher runs its own MCP server (e.g. Data Commons). |
| `update.cadence` | Publisher's stated cadence (`$defs/period`). |
| `update.expected_lag` | Typical delay from end of reference period to publication. |
| `change_detection` | See below. |
| `license` | `name`, `spdx` (or null), `url`, `redistribution` (`allowed`\|`link_only`; `unknown` is rejected), `commercial_use` (`yes`\|`no`\|`unclear`), `attribution`, `evidence` (dir), `checked_at`, `notes`. Rules: `docs/POLICY.md#licensing`. |
| `key_variables` | `{name, label?, unit?, definition}` — names exactly as returned by `fetch`. For restricted entries whose codebook is itself gated, list a few from public documentation and say "per publisher documentation, not verified". |
| `caveats` | ≥ 1 string, each ≥ 20 chars. Anything that makes naive use wrong. Returned with every `fetch`. |
| `related` | Other catalog ids (validated to exist). |
| `status` | `healthy` \| `degraded` \| `quarantined` \| `retired` (`docs/POLICY.md#status-transitions`). |
| `status_reason`, `status_since` | Why, and since when (date). |
| `last_verified` | Date an agent last confirmed the entry against the publisher and contract tests passed. |
| `adapter`, `adapter_version` | Module under `src/odc/adapters/` and its semver; both `null` for restricted entries. |

## change_detection

The monitor (`monitor/detect_changes.py`) polls each source every `poll_interval_days` (1–90) and compares a
fingerprint with the previous one. The first observation is a baseline (never reported). A changed fingerprint
opens/updates a `source-changed` issue. Choose a signal that moves on **new releases, schema/methodology changes,
moved files or license changes** — not on every routine data refresh (that would open an issue daily).

| method | config | fingerprint | good for |
|---|---|---|---|
| `http_headers` | `url`, optional `headers` (default `[etag, last-modified]`) | selected response headers (HEAD, falls back to GET) | a single file that is replaced on release; a changelog/readme file |
| `content_hash` | `url` | sha256 of the body | small, stable metadata files (a JSON manifest, a release-notes page **without** dynamic content) |
| `json_field` | `url`, `json_path` (string or list), optional `params` | the selected values | APIs with dataset metadata (version, modified, deprecation fields) |
| `regex` | `url`, `pattern` | sorted set of all matches (group 1 if present) | directory listings (`href="(20\d\d)/"`), version strings on a page, the header line of a nightly-regenerated CSV (`\A([^\r\n]+)`), the list of download links on a data page |
| `none` | — | never polled | **restricted entries only** |

`json_path` mini-language: `a.b`, `a[0]`, `a[*].b` (all), `a[key=value].b` (select). Test with
`python monitor/detect_changes.py --only <id> --all --state /tmp/s.json --report /tmp/r.json` (run twice; the second
must say `changed=0`). Web pages with rotating tokens/timestamps make bad `content_hash` targets — use `regex` to extract
the stable part.

## Evolving the schema

The schema will change. Rules:

1. **Additive, optional field or new enum value** (backward compatible): edit the schema JSON, document it in the
   table above, keep `schema_version: 1`. Existing entries stay valid. Add an entry to the changelog below.
2. **Breaking change** (new required field, renamed/removed field, changed meaning):
   - Bump `schema_version` (const) in the schema to `N+1`.
   - Write `scripts/migrations/v<N>_to_v<N+1>.py` that rewrites every `catalog/*.yaml` mechanically (load YAML,
     transform, dump with `sort_keys=False`), and run it in the same PR so every entry is at the new version.
   - Update `src/odc/catalog.py` (`CURRENT_SCHEMA_VERSION`), `_TEMPLATE.yaml`, this doc, and any code reading the field.
   - Fields that need human judgment for each source (e.g. a new required caveat category) should be added as
     optional first, back-filled source by source, and made required only when every entry has them.
3. Never change the meaning of `id`, and never remove `license`, `caveats`, or `status` semantics.
4. `odc validate` + offline tests must pass at every commit.

## Changelog

- v1 (2026-11-24): initial schema. `change_detection.json_path` accepts a list. Queue reason `publisher_blocked` added.
