# Policy

This document is binding on every agent run in this repository. When it and another doc
disagree, this one wins. If a situation is genuinely not covered here, see
[Escalation](#escalation) — do not improvise a new policy silently.

## Contents
- [Scope](#scope)
- [Licensing](#licensing)
- [Caching and redistribution](#caching-and-redistribution)
- [Status transitions](#status-transitions)
- [Network access](#network-access)
- [Credentials](#credentials)
- [Escalation](#escalation)
- [What agents may change without asking](#what-agents-may-change-without-asking)

## Scope

A source may be onboarded only if **all** of these hold:

1. **Reputable publisher**: a government (federal, state, local), an intergovernmental body, a
   research institution (university lab, established research center), or an established
   open-data project with a documented methodology and a track record (e.g. `@unitedstates`,
   Open States, MIT Election Data + Science Lab). No anonymous scrapes, no commercial data
   brokers, no personal blogs.
2. **Public and free**: retrievable without sign-up, API key, payment, or a signed data-use
   agreement. Sources failing this get a catalog-only entry with `access.method: restricted`
   and `adapter: null` (so agents know they exist) — never an adapter.
3. **No personal data about identifiable private individuals**, with one exception below. Not allowed: voter files,
   addresses, case records naming private people, anything scraped or enriched about individuals. Allowed: aggregate statistics; anonymised
   public-use microdata released by statistical agencies (e.g. ACS PUMS, CPS); records about
   **public officials acting in their official capacity** (roll-call votes, sponsored bills,
   committee assignments, campaign-committee totals); records about organisations.
   For public officials, return official identifiers and official contact details only: reduce birth dates to the
   year, and drop personal email/phone/home address, biography text and photos unless they are the official ones.

   **Exception: statutory public disclosure of political contributions** (operator decision, 2026-11-25). Records that
   a government publishes *by law* about individuals' political contributions, chiefly FEC itemized individual
   contributions, may be served, under these guardrails:
   - Threshold: only what the agency itself itemizes (FEC: contributors aggregating more than $200 to a committee in
     an election cycle). Never add contributions the agency did not itemize.
   - Fields: only fields the agency publishes (FEC: name, city, state, ZIP, employer, occupation, date, amount,
     recipient committee). Never join, enrich or geocode them with other personal data.
   - The first caveat must state the legal use restriction (FEC: 52 U.S.C. 30111(a)(4), no use for soliciting
     contributions or any commercial purpose). Keep the agency's "salted" decoy entries as published.
   - No tools or filters whose purpose is profiling one private person beyond what the agency's own search offers.
   - Remove a record within one batch cycle if the agency removes or amends it (the mirror is rebuilt per release).
4. **In domain** for this catalog (currently: US domestic policy research — elections & politics,
   demographics/Census, economy & labor, income/poverty, housing, health, education, public
   finance & spending, legislation/regulation, crime/justice, environment/disasters as they
   bear on policy). Out-of-domain candidates go to `ops/queue.yaml` with reason `scope`.
5. **Complements Google Data Commons** where possible. Data Commons (catalog id `data-commons`)
   already serves many headline indicators through its own MCP server. Prefer microdata,
   sub-national detail, administrative records, election returns, and scientific/observational
   data over re-serving national indicator time series that Data Commons already exposes.
   Duplication is allowed when we add something Data Commons lacks (finer geography, raw
   records, faster release), and the entry's description should say what that is.

## Licensing

You judge licensing yourself, applying these rules mechanically. Never guess in the permissive
direction.

1. **Read the actual terms.** Find the publisher's license / terms-of-use / copyright /
   "data policy" page for this specific dataset (dataset-level terms beat site-level terms).
2. **Save a snapshot** under `evidence/licenses/<id>/`:
   - `YYYY-MM-DD-<slug>.html` (or `.txt`/`.md`/`.json`) — the raw page as retrieved on that date.
     Use `python scripts/snapshot_license.py <id> <url> [<url> ...]`, which records the
     retrieval date, URL and sha256 in `NOTES.md`.
   - `NOTES.md` — the URL(s), retrieval date, and a short quote of the operative sentence(s)
     plus your reasoning for the classification below.
   If the page can't be fetched (blocked, 403), save what you can (e.g. a search-result
   excerpt, or a `*-unavailable.txt` noting the failure) and classify as if terms were unclear.
3. **Classify `license.redistribution`:**
   - `allowed` — the terms are clear **and** permit redistribution. Examples: public domain
     (US federal government works under 17 U.S.C. §105, *when the page says so or the agency's
     policy states it*), CC0, CC BY, CC BY-SA, ODbL, Open Government License, explicit "may be
     freely reused/redistributed".
   - `link_only` — the terms are unclear, ambiguous, silent, restrictive, or you couldn't find
     them. Also use `link_only` for non-commercial licences (CC BY-NC), "for research use only",
     or any terms with conditions you can't verify we meet.
   - `unknown` is not allowed in a committed entry; resolve it to one of the above.
4. **Classify `license.commercial_use`:** `yes` only if clearly permitted (public domain, CC0,
   CC BY, etc.); `no` if prohibited (NC); otherwise `unclear`.
5. **`license.attribution`**: the citation text the publisher asks for, or if none, a standard
   form: "<Publisher>, <Dataset name>." Always present — attribution is good practice even for
   public-domain data.
6. **Third-party content**: if a federal site states that some datasets contain third-party
   copyrighted material, and you can't confirm this dataset is free of it, use `link_only`.
7. **Conditions we can satisfy in `license.attribution`** — credit the agency, state non-endorsement, don't present
   modified data as original — do **not** by themselves force `link_only`. Put the required wording in `attribution`
   (it is returned in every fetch's provenance). Conditions on *purpose* ("research only"), on downstream users, or
   letting the publisher demand deletion **do** force `link_only`.
8. **Where to look for a dataset-level statement** (any of these counts as evidence if it comes from the publisher's
   own account/domain): the agency's Project Open Data catalog (`/data.json`; check dataset-level **and**
   distribution-level `license`/`licence` fields — `scripts/pod_license_excerpt.py` does both); the dataset's
   catalog.data.gov page; Socrata view metadata (`https://<portal>/api/views/<id>.json` → `license`); the agency's
   ArcGIS Online item; the publisher's own source code for the site (e.g. a licensing component on GitHub) when the
   site itself is JavaScript-only; metadata files shipped inside the download (save an excerpt with the archive's
   sha256). Save each as evidence.
9. **US federal works are public domain** (17 U.S.C. §105; decided 2026-11-25 by the maintainer under the operator's delegation, superseding the earlier
   "silent terms → link_only" rule for this case). Data produced and published by a US federal agency is
   `redistribution: allowed`, `commercial_use: yes`, **even without an explicit license statement**, unless:
   (a) its terms add conditions on use, purpose or deletion (e.g. OpenFEMA), (b) the agency warns it may contain
   third-party copyrighted or licensed content and we can't rule that out for this dataset (e.g. FHFA, Federal
   Register), (c) it includes licensed third-party data (e.g. USAspending's Dun & Bradstreet fields), or (d) it
   isn't actually produced by the federal government (contractor-owned, university-hosted, state data relayed).
   In those cases use `link_only`. Record which rule applied in NOTES.md. Do not use a code repository's LICENSE
   file as a data license.
10. **Non-commercial-only terms** (e.g. "licensed for personal or non-profit purposes"): onboard as `link_only`,
   `commercial_use: no`, and make the **first** caveat state the restriction in plain words so consuming agents see
   it. Whether a given deployment of this service qualifies as non-commercial is the operator's decision, not an
   agent's (see Escalation 3); the human operator has been asked about `county-health-rankings` (2026-11-24).
11. **Re-check** the license whenever the source is flagged `source-changed`, and at least once a
   year (`license.checked_at` older than 365 days is a reason to re-check during any visit).
   Each re-check adds a new dated snapshot; never delete old snapshots.

## Mirroring, caching and redistribution

- **Default for redistributable data: mirror it.** Sources with `license.redistribution: allowed` are downloaded
  once per upstream release, partitioned, and stored in our R2 bucket. The production MCP server serves them from
  there (docs/MIRROR.md). This is cheaper and faster than per-request passthrough and puts far less load on publishers.
  (This supersedes the original bootstrap brief's "no mirroring" rule; decided by the operator on 2026-11-25.)
- **`link_only` sources are never mirrored or cached.** The production server returns `how_to_access` for them, and
  the local `odc-server` fetches them from the publisher on demand, streaming to a temp file that is deleted
  afterwards. Upgrading a source to `allowed` (with evidence, per §Licensing) is what makes it mirrorable.
- Every served row keeps its provenance: publisher, original URLs, upstream release fingerprint, mirror time, license
  and attribution. Never strip or alter attribution.
- Adapters must use `odc.http.download(..., cache_allowed=...)` for local fetches; the base class passes
  `cache_allowed = (license.redistribution == "allowed")`.
- Never commit data files to git. Test fixtures must be tiny (< 20 KB) and only from `allowed` sources.
- Mirror storage and Worker usage cost money (R2 storage, Workers Paid). Scope very large sources deliberately (see
  docs/MIRROR.md). An unexpected jump in storage or request volume is an Escalation §1 spend anomaly.

## Status transitions

| From | To | When |
|---|---|---|
| (new) | `healthy` | Onboarded; contract tests pass. |
| `healthy` | `degraded` | A repair attempt failed but the source is **partially usable** (e.g. one of several endpoints broken, latest year missing, a filter unsupported). `status_reason` says exactly what doesn't work. |
| `healthy`/`degraded` | `quarantined` | A repair attempt failed and the source is **not usable** (all contract cases fail, endpoint gone, response garbage), or the license changed to something incompatible and fetching must stop. |
| `degraded`/`quarantined` | `healthy` | Fixed; contract tests pass. |
| `quarantined` | `retired` | **30 days** in quarantine with no fix, or the publisher discontinued the dataset. |
| anything | `retired` | Publisher discontinued it, or it is no longer in scope. |

Rules:
- **One repair attempt.** An agent handling a `needs-repair` issue gets one attempt (one PR) to
  fix. If that doesn't get contract tests green, the same PR must move the status to `degraded`
  or `quarantined`. **Never leave a broken source marked `healthy`.**
- Every status change updates `status`, `status_reason` (specific, not "broken"), and
  `status_since` (today), in the same commit.
- Quarantined sources are retried by the monitor with backoff (days 1, 2, 4, 8, 16 after
  `status_since`, then daily from day 30). If one starts passing, the monitor opens a
  `needs-repair` issue asking an agent to restore it. At day 30 it opens an issue to fix or retire.
- `retired` entries stay in `catalog/` forever (ids are never reused); the server hides them from
  search by default and refuses to fetch them.
- `fetch` refuses `quarantined`, `retired` and `restricted` entries and warns on `degraded`.

## Network access

This repo's agents may run in a cloud environment with a domain allowlist.

- `ops/network-allowlist.txt` lists every host that adapters and the monitor contact (one host
  per line, `*.example.gov` wildcards allowed). `odc validate` fails if a fetchable source uses a
  host that isn't listed.
- If a source's domain is **blocked** in your environment (proxy 403, DNS failure for a host that
  resolves elsewhere): **do not work around it** (no mirrors, no alternative proxies, no copying
  data from elsewhere). Instead: add the host to `ops/network-allowlist.txt`, add/keep the source
  in `ops/queue.yaml` with `reason: network` and the exact error in `detail`, and move on.
- A `network`-kind failure in a `needs-repair` issue should first be checked against this list.

### Publisher-side blocks (not our allowlist)

- A publisher's own bot protection (HTTP 202/403 JavaScript challenges, "Request blocked", WAF pages) is not a
  network-allowlist problem. Never spoof a browser or solve challenges. Use an official API or bulk host if one exists;
  otherwise queue the source with `reason: publisher_blocked` and quote the response in `detail`.
- Download links that exist only inside a web app (signed URLs from undocumented internal endpoints) are not a
  keyless public route. Treat the source as `restricted` (or queue it) rather than building on undocumented endpoints.

## Credentials

- No credentials, API keys, tokens or cookies anywhere in this repository, its issues, or its
  CI configuration (other than the built-in `GITHUB_TOKEN`).
- A source that needs any key (even a free one, even a `DEMO_KEY`) is `access.method: restricted`,
  `access.auth: credentials_required`, `adapter: null`.

## Escalation

Escalate to a human (open an issue labeled `needs-human`, and do nothing else about it) **only** for:

1. **Spending or usage anomalies** (thresholds in docs/MAINTAINER.md), and any decision that adds a paid service or
   raises expected monthly cost by more than $10. These need approval *before* acting. Examples: a publisher reports we exceeded a quota, CI minutes or
   scheduled-task runs far above normal, any bill.
2. **Systemic failure** — a large fraction of sources failing at once (the monitor does this
   automatically when ≥ 4 sources and ≥ 40% of those checked fail in one run). Likely a bug in
   shared code or the environment, not N publisher changes.
3. **A policy question this document genuinely doesn't answer** (e.g. a publisher sends a
   takedown request; a source's legal status is contested).

Everything else — repairs, status changes, license reclassification, adding/removing sources,
schema migrations — is resolved in-repo by agents via pull requests.

## What agents may change without asking

- Add, repair, degrade, quarantine or retire sources (following this document).
- Refine docs, tests, adapters, shared helpers (with tests).
- Evolve the schema following `docs/SCHEMA.md#evolving-the-schema`.

Agents must not: weaken this policy, delete license evidence, delete catalog entries, add
credentials, add network workarounds, or disable the monitor.
