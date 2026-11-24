# Adding a source — checklist

Follow every step in order. A source is **done** only when every box in [Definition of done](#definition-of-done)
is true. Expect 30–90 minutes per source. Worked examples to copy from:

| Pattern | Example adapter | Example catalog entry |
|---|---|---|
| REST/JSON API with query filters | `src/odc/adapters/fema_disaster_declarations.py` | `catalog/fema-disaster-declarations.yaml` |
| Big bulk file(s), stream + filter | `src/odc/adapters/census_acs_summary_file.py` | `catalog/census-acs-summary-file.yaml` |
| Public cloud bucket (S3/GCS over HTTPS) | `src/odc/adapters/noaa_nclimgrid_daily.py` | `catalog/noaa-nclimgrid-daily.yaml` |
| Catalog-only (needs key / registration) | — (no adapter) | `catalog/census-data-api.yaml` |

## 0. Before you start

- [ ] `uv pip install -e ".[dev]"`, `odc validate` and `pytest -m "not live" -q` pass on a clean checkout.
- [ ] Check the source isn't already in `catalog/` (`odc search "<keywords>"`) or `ops/queue.yaml`.

## 1. Screen the candidate (stop early if it fails)

Apply `docs/POLICY.md#scope`:
- [ ] Reputable publisher? Public & free with **no** key/sign-up/guestbook/DUA? No personal data about private individuals? In domain?
- [ ] Does Google Data Commons (`data-commons`) already serve it? If yes, only proceed if we add something (finer geography, microdata, raw records, faster releases) — and say what in the description.
- [ ] Network: can you reach the data host from here? `curl -sI <url>`. If the proxy/allowlist blocks it → add host to
      `ops/network-allowlist.txt`, add to `ops/queue.yaml` with `reason: network`, **stop** (don't work around it).
- [ ] Needs a key, registration, a "guestbook" form, or a signed agreement? → write a **catalog-only** entry
      (`access.method: restricted`, `access.auth: credentials_required|registration_required|data_use_agreement`,
      `restricted_reason`, `adapter: null`, `adapter_version: null`, `change_detection.method: none`), do the
      license step, skip steps 4–6. Only do this if knowing it exists helps agents; otherwise queue it with `reason: credentials`.

Failing a screen → add an entry to `ops/queue.yaml` (`id`, `name`, `homepage`, `reason`, `detail`, `added`) and stop.

## 2. Choose the id and learn the data

- [ ] `id`: lowercase slug `<publisher>-<dataset>` (e.g. `bls-laus`, `fec-candidate-summaries`). **Permanent** — choose carefully.
- [ ] Read the publisher's documentation: methodology, update schedule, known breaks, suppression rules, geography vintages.
      Collect material for `caveats` while reading — this is the most valuable part of the entry.
- [ ] Find the **stable** machine endpoint (API base URL, bulk-file URL pattern, bucket prefix). Prefer endpoints with
      version numbers or year segments over "latest" links that silently change.
- [ ] Fetch a small sample with curl and look at the real columns, codes, sentinel values and encodings.

## 3. License (docs/POLICY.md#licensing)

- [ ] Find the dataset-level terms (license field on the dataset page, a data-policy page, terms of use).
      For US federal agencies, the agency's Project Open Data catalog is often the clearest dataset-level statement:
      `python scripts/pod_license_excerpt.py <id> https://<agency>/data.json "<title regex>"`.
- [ ] Snapshot every page you rely on: `python scripts/snapshot_license.py <id> <url> [<url> ...]`.
      This creates `evidence/licenses/<id>/<date>-*.txt` and `NOTES.md`.
- [ ] Read the snapshots. Fill in `NOTES.md` → **Operative terms** (quote the exact sentences, naming the snapshot file)
      and **Classification** (redistribution, commercial_use, attribution, and why).
- [ ] Classify: clear + permissive → `allowed`; anything unclear, conditional, NC, or unfetchable → `link_only`.

## 4. Adapter

- [ ] Copy `src/odc/adapters/_template.py` to `src/odc/adapters/<id_with_underscores>.py`.
- [ ] Reuse helpers in `_common.py` (`census_api`, `socrata`, `scan_csv`, `dataverse_*`, `openfema`, `state_fips`, ...).
      If you write a helper a second source could use, put it in `_common.py`.
- [ ] Declare `filters` (`FilterSpec`): names agents will understand (`state`, `year`, `county_fips`, ...), types,
      `required`, `enum`, `example`. Validate inputs and raise `FilterError` with a message that says how to fix it.
      Accept state as postal code or FIPS via `state_fips()` / `state_abbr()`.
- [ ] Write `usage`: 2–4 sentences an agent reads in `describe_source` (row grain, the key filter, a gotcha).
- [ ] `_fetch` returns `FetchResult(rows, request_urls, notes, total_available, metadata)`:
  - rows: list of flat dicts, JSON-serialisable values; convert publisher sentinel codes to `None` (and say so in `notes`).
  - request_urls: the actual URLs requested (these go into provenance — agents cite them).
  - Respect `limit` (stop collecting rows after `limit`; count the rest in `total_available` if cheap).
  - Bulk files: use `scan_csv(..., cache_allowed=cache_allowed)` / `http.download(...)`. **Never** cache yourself.
  - Raise `SourceError(kind=...)` (`http`, `parse`, `schema`, `empty`) when the publisher's response isn't what you expect —
    e.g. `require("expected_col" in header, "...")`. Loud failures are how the monitor finds breakage.
- [ ] `contract`: 1–3 `ContractCase`s that are **cheap** (< ~20 s, < ~50 MB download) and **stable** (historical data
      that won't change, e.g. a 2020 value), with `min_rows`, `required_columns`, and `Check`s on values
      (`numeric`, `min`/`max` plausible ranges, `one_of` for codes, `regex` for ids). Add a `custom` check for a known
      fact when useful (e.g. Phoenix July 2023 had ≥ 43 °C days). These are what detect silent breakage.
- [ ] `version = "1.0.0"`, `source_id = "<id>"`, and module-level `ADAPTER = YourAdapter()`.

## 5. Catalog entry

- [ ] Copy `catalog/_TEMPLATE.yaml` to `catalog/<id>.yaml` and fill **every** field (see `docs/SCHEMA.md`):
  - `description`: 2–4 plain sentences — what it measures, how it's produced (survey/admin records/model), by whom.
  - `coverage`: be precise about granularity and time range; `time_range.end: null` only for continuously updated data.
  - `access.endpoints`: the URLs/patterns the adapter uses (so a repair agent can find them).
  - `update.cadence` + `expected_lag` from the publisher's release schedule.
  - `change_detection` (see `docs/SCHEMA.md#change_detection`): pick a signal that moves on **releases, schema or
    methodology changes**, not on every routine refresh. Test it: `python monitor/detect_changes.py --only <id> --all --state /tmp/s.json --report /tmp/r.json` twice — the second run must report `changed=0`.
  - `license`: from step 3. `evidence: evidence/licenses/<id>/`, `checked_at` = today.
  - `key_variables`: the 4–10 most-used fields exactly as returned by `fetch`, with units and definitions.
  - `caveats`: everything that makes naive use wrong — weighting, MOEs, series breaks, definition changes,
    suppression/top-coding, geography vintages, double counting, coverage gaps. At least 3 for most sources.
  - `status: healthy`, `status_reason: Onboarded; contract tests pass.`, `status_since`/`last_verified` = today,
    `adapter`, `adapter_version` matching the adapter.
- [ ] Add every host the adapter or change detection touches to `ops/network-allowlist.txt` (with a `# <id>` comment).
- [ ] If it was in `ops/queue.yaml`, remove it from there.

## 6. Verify

- [ ] `odc validate` → 0 problems.
- [ ] `pytest -m "not live" -q` → all pass (includes offline checks of your contract filters).
- [ ] `odc contract <id>` → all PASS. Run it twice if the data is cached, to exercise both paths.
- [ ] `odc describe <id>` reads well; `odc fetch <id> '<typical filters>' --limit 5` returns sensible rows with provenance.
- [ ] `odc search "<words a user would type>"` ranks the source near the top.

## 7. Commit

- [ ] One commit per source (or small batch): `catalog: onboard <id>` including catalog entry, adapter, evidence,
      allowlist and queue changes. Never commit downloaded data.

## Definition of done

1. `catalog/<id>.yaml` valid, every field meaningful (no template placeholders), caveats substantive.
2. Adapter with filters, usage, ≥ 1 contract case; `adapter_version` matches.
3. License evidence snapshot(s) + completed `NOTES.md`; classification follows POLICY.
4. Change detection configured and tested (baseline then unchanged).
5. Hosts in `ops/network-allowlist.txt`; not in `ops/queue.yaml`.
6. `odc validate`, offline tests and `odc contract <id>` all pass.

## Lessons learned (append as you go)

- **Census Data API (api.census.gov) requires a key on every request** (since 2026). Use Census bulk files on
  www2.census.gov instead (e.g. ACS table-based summary files, PEP and SAIPE CSVs); the API is a restricted entry.
- **Harvard Dataverse "guestbook"**: some datasets (e.g. MIT Election Lab) return `"You may not download this file
  without the required Guestbook response"`. A guestbook collects name/email → treat as registration → restricted.
  Check with `curl https://dataverse.harvard.edu/api/access/datafile/<id>` before building an adapter.
- **Live/continuous APIs** (OpenFEMA etc.) change data every few minutes: point change detection at dataset
  *metadata* (definition modified date, deprecation fields), not at refresh timestamps.
- **Geographic codes**: never assume FIPS. NOAA uses NCEI state numbering; convert and keep the original code column.
- **Census GEO_IDs** contain geographic *components* (e.g. `04000A0US06` = part of California); filter to `GEO_ID[5:7] == "00"` for whole areas.
- Some agency sites (www.bls.gov, www.noaa.gov) block non-browser clients with 403 "Request blocked". That's the
  publisher's bot protection, not our allowlist: try the agency's API/bulk host instead; never spoof a browser.
