# Mirror + Worker architecture

Production traffic is served by a Cloudflare Worker at **https://mcp.librarycard.net/mcp**. It reads data from a
mirror in Cloudflare R2, not from publishers. This doc explains how the mirror is built and served and how to add a
source to it.

```
publisher files/APIs ──(GitHub Actions: odc mirror --due, Python adapters)──▶ R2 bucket librarycard-data
                                                                              │ range reads
MCP clients ──POST /mcp──▶ Worker librarycard-mcp (worker/, TypeScript) ◀────┘
                           (catalog bundled at deploy time from catalog/*.yaml)
```

## Which sources are mirrored

`odc.mirror.mirrorable(entry)` is true when **all** hold:
- `license.redistribution == "allowed"` (POLICY §Licensing). `link_only` sources are **never** mirrored. The Worker
  answers their `fetch` with `how_to_access` (publisher URLs, plus the local `odc-server` which fetches directly).
- status `healthy` or `degraded`, with an adapter
- the adapter defines `mirror_plan()`

## R2 layout (format 1)

```
mirror/<source_id>/current.json                 {"release", "manifest", "ingested_at", "row_count", "upstream_fingerprint", "adapter_version"}
mirror/<source_id>/<release>/manifest.json      partitions, columns, provenance (see below)
mirror/<source_id>/<release>/pack-<n>.bin       concatenated gzip members; each member = one partition chunk of NDJSON rows
```

Manifest fields:
- `partitions: [{k: {key: value}, c: chunk, p: pack index, o: byte offset, n: byte length, r: rows}]`
- `partition_keys`, `required_filters`, `semantics` (`state_postal|state_fips|county_fips` so the Worker accepts
  "TX", "48", "Texas"...)
- `columns: {name: {type, nulls, min, max, values?}}`, computed from the data
- `upstream: {urls, fingerprint, detail}`, `license`, `notes`, `metadata` (e.g. variable labels), `adapter_version`

Publishing uploads the packs and the manifest first, then flips `current.json`, so readers never see a half-written
release. The two most recent releases are kept.

## Ingest (Python, `src/odc/mirror.py`)

```bash
odc mirror <id>                 # ingest + publish (needs CLOUDFLARE_ACCOUNT_ID, and CLOUDFLARE_API_TOKEN unless a proxy injects it)
odc mirror <id> --dry-run --out /tmp/packs   # build locally; inspect /tmp/packs/<id>/manifest.json
odc mirror <id> --out DIR --resume          # long ingests: checkpoint after each unit; rerun the same command after
                                             # an interruption to continue (and to finish a cut-off upload)
odc mirror --due                # every mirrorable source that is missing, stale (30 days), has a new adapter_version,
                                # or whose change_detection fingerprint moved
```

`.github/workflows/mirror.yml` runs `odc mirror --due` daily and on demand.

### Adding `mirror_plan()` to an adapter

The mirror stores exactly the rows the adapter's `fetch` returns, so the parsing logic is reused. Add to the adapter class:

```python
mirror_partition_keys = ["geography", "state"]   # coarse -> fine; every row ends up in exactly one partition
mirror_required = ["geography"]                   # only for very large sources: readers must filter on these
mirror_semantics = {"state": "state_postal", "GEOID": "county_fips"}

def mirror_plan(self):
    from ..mirror import MirrorUnit
    for geo in ("state", "county"):
        # partition: values for keys known per unit; filters: adapter filters that fetch the WHOLE unit;
        # split_by: row columns whose values become further partition keys.
        yield MirrorUnit(partition={"geography": geo}, filters={"geography": geo}, split_by=["state"])
```

Rules and guidance:
- **Units must not overlap.** Each unit's rows must not land in the same partition as another unit's (enforced).
- **Every partition key must be a row column** (add it with a `mirror_rows` override if the adapter's rows lack it,
  as `unitedstates_congress_legislators.py` does) so filtering works the same for partition and row filters.
  Known exception: `cdc-places` ZCTA rows have no `stateabbr` (partition value ""); its caveat says to filter on
  `locationid`.
- **Partition size:** aim for 1–20 MB compressed per partition. Too coarse means every query reads a lot. Too fine
  (tens of thousands of partitions) makes the manifest large. Split by state for anything with sub-state rows.
- **Memory:** the default `mirror_rows` calls `_fetch` with no row limit, holding one unit's rows in memory. Keep
  units below ~1M rows, or override `mirror_rows` to return a generator.
- **Disk:** rows are spooled and packed per unit, so peak disk is one unit's raw NDJSON plus the compressed packs.
- **Multi-GB upstream files:** don't download them. `_common.remote_zip_members` / `remote_zip_lines` read a remote
  zip's central directory with HTTP Range requests and stream single members; `http.iter_bytes` resumes a dropped
  stream. Return a generator from `mirror_rows` so memory stays flat (`fec_individual_contributions.py`: 97M rows,
  ~300 MB RSS during ingest).
- **Bounded runs (agent sessions):** keep each unit to a few minutes and use `--resume` with `timeout`, e.g.
  `timeout 560 odc mirror <id> --out DIR --resume`, repeated until it exits 0. Work in an unfinished unit is lost on
  each interruption, so split heavy units (FEC splits its busiest months into two state groups). Publishing with
  `--resume` skips packs already uploaded. Upload runs at roughly 7 MB/s from cloud sessions.
  Rerunning `--resume` after a finished run republishes the same release (harmless). Timeout-killed runs leave spool
  directories under `TMPDIR`; delete them when done.
- **Paged APIs:** cache each page (the default `http` cache does) so a unit interrupted mid-way resumes without
  re-requesting, and `http.evict(url, params)` the pages once the unit finishes or if its row count doesn't match
  (`cdc_places.py`). Request sequentially with backoff.
- **Scope big sources deliberately**, e.g. ACS: the most-used tables. Write the scope into the catalog entry's
  `access.notes` and a caveat ("the mirror covers tables X..."), and say how to widen it.
- **Test:** `odc mirror <id> --dry-run --out /tmp/p`, inspect the manifest (row_count, partitions, column types),
  then publish and query through the Worker. Add a TOP1 search case if you onboarded a new source.
- **Budgets:** an ingest should finish in about 30 minutes and stay under about 5 GB compressed. Bigger sources are scoped
  (e.g. NOAA from 2024, LODES S000/JT00 for the latest year), with the scope in `access.notes` plus a caveat and a module
  constant (e.g. `MIRROR_START_YEAR`, `MIRROR_SEGMENTS`) that says how to widen it.
- **`odc mirror <id>` ingests from scratch**; it doesn't publish an earlier `--dry-run` output. For long runs, set
  `TMPDIR` to a private directory (other jobs on a shared machine may clean `/tmp`).
- **Metadata:** the Worker returns `metadata.variable_labels` trimmed to the columns in each response; keep other
  metadata small (it is sent with every fetch). Put links to codebooks there rather than large label tables.
- **Provenance:** each partition records which upstream URLs its unit read (`u` indices into `upstream.urls`), so
  fetch cites the files behind the rows returned. Return the exact file URLs from `mirror_rows`.
- Bump `adapter_version` when the row shape changes. That marks the mirror `--due` for re-ingest.

## The Worker (`worker/`)

- `src/index.ts`: MCP over Streamable HTTP, stateless JSON-RPC (initialize, ping, tools/list, tools/call).
- `src/tools.ts`: the four tools. `src/catalog.ts`: search, a port of `src/odc/catalog.py`. Keep them in sync;
  both run `tests/search_cases.json`. `src/mirror.ts`: manifest cache (5 min), filter parsing and range reads.
- The catalog is bundled from `catalog/*.yaml` at deploy time (`npm run export`), so catalog edits go live on deploy.
  Mirror data goes live as soon as `current.json` flips.
- Tests: `cd worker && npm run export && npm test` (Node 22, no dependencies beyond wrangler).
- Deploy: `.github/workflows/deploy.yml` on merge to `main` (repository secrets `CLOUDFLARE_API_TOKEN`,
  `CLOUDFLARE_ACCOUNT_ID`). Manual: `cd worker && npx wrangler deploy`.

Fetch filter language (what agents send): `{"column": value}` exact (case-insensitive); `[v1, v2]` any of;
`{"gte": a, "lte": b}` range (also `gt`/`lt`; numeric when both sides are numbers, else string order, which suits
ISO dates); `{"contains": "text"}`; `{"prefix": "06037"}` (starts with, for GEOIDs and other codes). `columns: [...]` selects output columns. The request reads at most
`MAX_SCAN_BYTES` (30 MB compressed) and then reports `scan_stopped_early`.

## Relationship to the Python server

`odc-server` (Python, stdio) still fetches **directly from publishers** using the same adapters. It is useful for
local work, for `link_only` sources, and for contract tests. Production is the Worker.
