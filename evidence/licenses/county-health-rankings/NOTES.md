# License evidence: county-health-rankings

## Snapshots
- `2026-11-24-www-countyhealthrankings-org-terms-use.txt` — https://www.countyhealthrankings.org/terms-use — retrieved 2026-11-24T23:42:12+00:00 — sha256 c31591b6d4f7c4e9…
- `2026-11-24-lthrankings-org-health-data-methodology-and-sources-data-documentation.txt` — https://www.countyhealthrankings.org/health-data/methodology-and-sources/data-documentation — retrieved 2026-11-24T23:42:12+00:00 — sha256 add3b036c2a9aa50…

## Operative terms
From `2026-11-24-www-countyhealthrankings-org-terms-use.txt` (site Terms of Use; no dataset-specific license exists — the analytic CSVs are "downloadable data files" covered by these terms):
- "All content on the CHR&R Website, including but not limited to ... information, downloadable data files ... is the property of CHR&R or its licensors with all rights reserved."
- "CHR&R grants you a non-exclusive license to access and use those portions of the CHR&R Website without a password or logon for personal or non-profit purposes including educational, research, or public health, subject to the terms of this Agreement, provided that you keep all copyright or other proprietary notices intact."
- "The CHR&R website Content may not be copied or otherwise used for commercial use (including without limitation, use to train AI models intended to be offered as commercial products) without CHR&R's express prior written consent."
- Citation: "University of Wisconsin Population Health Institute. County Health Rankings & Roadmaps."
- Terms may change without notice ("Modifications to this Agreement").
The data-documentation snapshot lists the analytic CSV files and documentation PDFs (no separate license there).

## Classification
- redistribution: **link_only** — all rights reserved; only a personal/non-profit use licence is granted. Per POLICY (non-commercial / restrictive terms) we never cache: files are streamed to a temp file per request and deleted; agents are pointed to the publisher.
- commercial_use: **no** — commercial use (including training commercial AI models) is explicitly prohibited without written consent.
- attribution: "University of Wisconsin Population Health Institute. County Health Rankings & Roadmaps <year>." (publisher's preferred citation).
- Note for maintainers: many CHR&R measures are re-published federal data (CDC, Census, BLS), but the compiled file and derived measures fall under these terms; use the federal originals (e.g. cdc-places, census-acs-summary-file) when commercial reuse matters.
