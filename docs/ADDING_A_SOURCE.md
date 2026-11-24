# Adding a source — checklist

Follow every step in order. A source is **done** only when every box in [Definition of done](#definition-of-done)
is true. Expect 30–90 minutes per source. Worked examples to copy from:

| Pattern | Example adapter | Example catalog entry |
|---|---|---|
| REST/JSON API with query filters | `src/odc/adapters/fema_disaster_declarations.py` | `catalog/fema-disaster-declarations.yaml` |
| Big bulk file(s), stream + filter | `src/odc/adapters/census_acs_summary_file.py` | `catalog/census-acs-summary-file.yaml` |
| Public cloud bucket (S3/GCS over HTTPS) | `src/odc/adapters/noaa_nclimgrid_daily.py` | `catalog/noaa-nclimgrid-daily.yaml` |
| Catalog-only (needs key / registration) | — (no adapter) | `catalog/census-data-api.yaml` |
| Dataverse dataset (research archive) | `src/odc/adapters/mit_election_president_state.py` (+ `_medsl.py`) | `catalog/mit-election-president-state.yaml` |
| POST-only JSON API | `src/odc/adapters/usaspending_spending_by_geography.py` | `catalog/usaspending-spending-by-geography.yaml` |
| Fixed-width text files | `src/odc/adapters/census_saipe.py` | `catalog/census-saipe.yaml` |
| Socrata portal, new dataset id per release | `src/odc/adapters/cdc_places.py` | `catalog/cdc-places.yaml` |
| Bulk primary + API fallback | `src/odc/adapters/bls_laus.py` (+ `tests/test_bls_laus_api_fallback.py`) | `catalog/bls-laus.yaml` |

## 0. Before you start

- [ ] `uv pip install -e ".[dev]"`, `odc validate` and `pytest -m "not live" -q` pass on a clean checkout.
- [ ] Check the source isn't already in `catalog/` (`odc search "<keywords>"`) or `ops/queue.yaml`.

## 1. Screen the candidate (stop early if it fails)

Apply `docs/POLICY.md#scope`:
- [ ] Reputable publisher? Public & free with **no** key/sign-up/guestbook/DUA? No personal data about private individuals? In domain?
- [ ] Does Google Data Commons (`data-commons`) already serve it? If yes, only proceed if we add something (finer geography, microdata, raw records, faster releases) — and say what in the description.
- [ ] Network: can you reach the data host from here? `curl -sI <url>`. If the proxy/allowlist blocks it → add host to
      `ops/network-allowlist.txt`, add to `ops/queue.yaml` with `reason: network`, **stop** (don't work around it).
- [ ] Publisher bot protection (JS challenge, WAF page) with no official keyless alternative, or download links that
      exist only inside a web app? → see `docs/POLICY.md#publisher-side-blocks-not-our-allowlist`.
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
      `python scripts/pod_license_excerpt.py <id> https://<agency>/data.json "<anchored title regex>"` (checks dataset- and
      distribution-level `license`/`licence`, keeps the newest 100 matches, appends a line to NOTES.md).
      Other acceptable places are listed in `docs/POLICY.md#licensing` rule 8 (Socrata view metadata, catalog.data.gov,
      agency ArcGIS items, the site's own source code, metadata shipped in the download).
      If the dataset isn't in the agency catalog at all, its terms are silent → `link_only` (rule 9).
- [ ] Snapshot every page you rely on: `python scripts/snapshot_license.py <id> <url> [<url> ...]`.
      This creates `evidence/licenses/<id>/<date>-*.txt` and `NOTES.md`.
- [ ] If the script warns "only N chars of text", the page is a JavaScript app or a bot challenge: it is not evidence.
      A `-unavailable.txt` file means the fetch failed; check whether it was a 404 (wrong URL: delete the file and
      fix the URL) or a block (keep it as evidence that the terms were unfetchable).
- [ ] Several datasets from one publisher with identical terms may share one evidence directory
      (e.g. `evidence/licenses/mit-election-lab/`); say in NOTES.md which entries use it.
- [ ] Read the snapshots. Fill in `NOTES.md` → **Operative terms** (quote the exact sentences, naming the snapshot file)
      and **Classification** (redistribution, commercial_use, attribution, and why).
- [ ] Classify: clear + permissive → `allowed`; anything unclear, conditional, NC, or unfetchable → `link_only`.

## 4. Adapter

- [ ] Copy `src/odc/adapters/_template.py` to `src/odc/adapters/<id_with_underscores>.py`.
- [ ] Reuse helpers in `_common.py` (`socrata`, `scan_csv`, `dataverse_*`, `openfema`, `state_fips`, ...).
      Helpers shared by several datasets of one publisher go in a private module `src/odc/adapters/_<publisher>.py`
      (e.g. `_medsl.py`); helpers any adapter could use go in `_common.py` (with a test).
      Dataverse: anchor file-name patterns (`^\d{4}-\d{4}-president\.(csv|tab)$`, not `president\.tab$`, which also
      matches `sources-president.tab`) and download with `original=True`.
- [ ] Declare `filters` (`FilterSpec`): names agents will understand (`state`, `year`, `county_fips`, ...), types,
      `required`, `enum`, `example`. Validate inputs and raise `FilterError` with a message that says how to fix it.
      Accept state as postal code or FIPS via `state_fips()` / `state_abbr()`.
- [ ] Write `usage`: 2–4 sentences an agent reads in `describe_source` (row grain, the key filter, a gotcha).
- [ ] `_fetch` returns `FetchResult(rows, request_urls, notes, total_available, metadata)`:
  - rows: list of flat dicts, JSON-serialisable values; convert publisher sentinel codes to `None` (and say so in `notes`).
  - request_urls: the actual URLs requested (these go into provenance — agents cite them). For POST APIs also put the
    exact request body in `metadata["request_body"]` so the request is reproducible.
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
  - `access.endpoints`: the URLs/patterns the adapter (or its fallback) actually contacts — every host there must be
    allowlisted. Informational links the adapter never calls (GitHub repos, docs) go in `access.notes` instead.
  - `update.cadence` + `expected_lag` from the publisher's release schedule.
  - `change_detection` (see `docs/SCHEMA.md#change_detection`): pick a signal that moves on **releases, schema or
    methodology changes**, not on every routine refresh. Test it: `python monitor/detect_changes.py --only <id> --all --state /tmp/odc-<id>-state.json --report /tmp/odc-<id>-changes.json` twice — the second run must report `changed=0`.
  - `license`: from step 3. `evidence: evidence/licenses/<id>/`, `checked_at` = today.
  - `key_variables`: the 4–10 most-used fields exactly as returned by `fetch`, with units and definitions.
  - `caveats`: everything that makes naive use wrong — weighting, MOEs, series breaks, definition changes,
    suppression/top-coding, geography vintages, double counting, coverage gaps. At least 3 for most sources.
  - `status: healthy`, `status_reason: Onboarded; contract tests pass.`, `status_since`/`last_verified` = today,
    `adapter`, `adapter_version` matching the adapter.
- [ ] YAML: quote any value containing `": "` or starting with a special character (`- Legal: x` parses as a mapping!).
- [ ] Add every host the adapter or change detection touches (including redirect targets, e.g. S3 hosts behind a
      download URL) to `ops/network-allowlist.txt` with a `# <id>` comment. Appending at the end of the sources
      section is fine; it gets sorted when branches are merged.
- [ ] If it was in `ops/queue.yaml`, remove it from there.

## 6. Verify

- [ ] `odc validate` → 0 problems.
- [ ] `pytest -m "not live" -q` → all pass (includes offline checks of your contract filters).
- [ ] `odc contract <id>` → all PASS, and `ODC_CACHE=0 odc contract <id>` → all PASS (exercises the uncached path).
      For `link_only` bulk sources every fetch re-downloads the file: keep contract downloads small.
- [ ] Fallback paths you can't exercise live (e.g. an API used only when the bulk host fails) need an offline test
      with a mocked response (`tests/test_<id>_*.py`).
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

Access
- **Census Data API (api.census.gov) requires a key on every request** (since 2026) → restricted. Use www2.census.gov
  bulk files. www2.census.gov answers **401** (not 404) for files that don't exist; treat 401/403/404 as "not published".
- **Census bulk files are mostly latin-1**; PEP file-name case varies by vintage (resolve names from the directory
  listing); Gazetteer files switched from tab to pipe delimiters (and added GEOIDFQ) in 2025.
- **Census GEO_IDs** contain geographic *components* (e.g. `04000A0US06` = part of California); keep `GEO_ID[5:7] == "00"`.
- **Never assume FIPS.** NOAA uses NCEI state numbering; convert and keep the original code column.
- **Harvard Dataverse "guestbook"**: `"You may not download this file without the required Guestbook response"` →
  registration → restricted. Check `curl https://dataverse.harvard.edu/api/access/datafile/<id>` first.
- **BLS** blocks curl's default user agent but serves our honest `ODC_USER_AGENT`. BLS API v1's daily quota is per egress
  IP and is often already exhausted in shared environments; don't make it the primary path.
- **HUD User** (www.huduser.gov) serves an AWS WAF JavaScript challenge to scripts; its API needs a token.
- **FederalRegister.gov** policy pages serve a "Request Access" page to scripts; use GovInfo/NARA pages for evidence.
- **Socrata portals that publish a new dataset id per release** (CDC PLACES): keep a release→id map in the adapter and
  watch the portal catalog search (`/api/catalog/v1?q=...`) with a `regex` change detector.
- **Take file URLs from the publisher's download page or its JavaScript**, not guessed patterns (CHR&R's 2025 file is
  `analytic_data2025_v3.csv`; SVI state files are named like `NewHampshire.csv`). ERS `/media/<n>/` links carry a `?v=`
  cache token — strip it in change-detection regexes.
- **HTML error pages with status 200** (BEA for unknown tables): `http.download` now rejects HTML responses unless
  `allow_html=True`, so they're never cached or parsed as data.

Change detection
- **Live/continuous APIs** (OpenFEMA): watch dataset *metadata* (definition modified date, deprecation fields), not
  refresh timestamps. **Nightly-regenerated files**: watch a header line, a layout/description page or a version file.

Licensing
- FEC's data.json spells the field `licence`; CMS puts licenses only on distributions; CDC PLACES has it only in Socrata
  view metadata; CDC SVI only on CDC's ArcGIS Online item. `pod_license_excerpt.py` handles the first two.
- A LICENSE file in an agency's *code* repository is not a data license (FEC).
