# License evidence: census-acs-summary-file

## Snapshots
- `2026-11-24-census-data-json-acs-excerpt.json` — excerpt of https://www.census.gov/data.json (the Census Bureau's Project Open Data catalog) — retrieved 2026-11-24 — entries for ACS detailed tables 2023/2024.
- `2026-11-24-www-census-gov-about-policies-open-gov-open-data-html.txt` — https://www.census.gov/about/policies/open-gov/open-data.html — retrieved 2026-11-24T23:24:07+00:00 — sha256 8076988ba7c23384…
- `2026-11-24-www-census-gov-about-policies-citation-html.txt` — https://www.census.gov/about/policies/citation.html — retrieved 2026-11-24T23:24:09+00:00 — sha256 180ba85889eb8c43…
- `2026-11-24-www-census-gov-programs-surveys-acs-data-summary-file-html.txt` — https://www.census.gov/programs-surveys/acs/data/summary-file.html — retrieved 2026-11-24T23:24:09+00:00 — sha256 b57c1ee411222a0e…
- `2026-11-24-www-census-gov-data-developers-about-terms-of-service-html.txt` — https://www.census.gov/data/developers/about/terms-of-service.html — retrieved 2026-11-24T23:24:27+00:00 — sha256 265346a5428d359d…

## Operative terms
- census.gov data.json (excerpt file): ACS Detailed Tables 5-Year 2024 (`ACSDT5Y2024`) → `"license": "https://creativecommons.org/publicdomain/zero/1.0/"`. 1,800 of 1,800 datasets in that catalog carry CC0.
- citation-html snapshot: Census asks users to cite the source; gives citation formats (e.g. "U.S. Census Bureau, <survey>, <table>, <year>").
- terms-of-service-html snapshot covers only the Data **API** (which now requires a key and is catalog-only here, see `census-data-api`); the summary files are plain downloads from www2.census.gov and are not subject to that API agreement.
- Title 13 confidentiality obligations (no re-identification of respondents) apply to all Census data and are compatible with redistribution of published tables.

## Classification
- redistribution: **allowed** — dataset-level license declared by the publisher is CC0 1.0 (clear and permissive).
- commercial_use: **yes** — CC0.
- attribution: Census requests citation; we use "U.S. Census Bureau, American Community Survey <period> Summary File, Table <id>.".
