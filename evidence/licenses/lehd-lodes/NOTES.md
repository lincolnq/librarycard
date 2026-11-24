# License evidence: lehd-lodes

## Snapshots
- `2026-11-24-lehd-ces-census-gov-data.txt` — https://lehd.ces.census.gov/data/ — retrieved 2026-11-24T23:38:23+00:00 — sha256 769c43050758f864…
- `2026-11-24-lehd-ces-census-gov-data-lodes-lodes8.txt` — https://lehd.ces.census.gov/data/lodes/LODES8/ — retrieved 2026-11-24T23:38:23+00:00 — sha256 0f716b8ebd412ac5…
- `2026-11-24-www-census-gov-about-policies-open-gov-open-data-html.txt` — https://www.census.gov/about/policies/open-gov/open-data.html — retrieved 2026-11-24T23:38:24+00:00 — sha256 437e793291d9bf7b…
- `2026-11-24-www-census-gov-about-policies-citation-html.txt` — https://www.census.gov/about/policies/citation.html — retrieved 2026-11-24T23:38:25+00:00 — sha256 871b206b5006502a…
- `2026-11-24-www-census-gov-data-json-excerpt.json` — https://www.census.gov/data.json filtered to /LODES|LEHD|Origin-Destination|OnTheMap|Longitudinal Employer/ — retrieved 2026-11-24

## Operative terms
- `2026-11-24-www-census-gov-data-json-excerpt.json`: the only LEHD entries in the Census Bureau's Project Open Data catalog are three "Time Series Longitudinal Employer-Household Dynamics - QWI" API datasets (CC0). **LODES is not listed**, so there is no dataset-level license statement for it.
- `2026-11-24-lehd-ces-census-gov-data.txt` (LEHD data page): describes LODES as "available online for public use" and gives a "LEHD Data Citations" format; it contains no license, terms-of-use or redistribution statement.
- `2026-11-24-lehd-ces-census-gov-data-lodes-lodes8.txt`: directory listing; no terms.
- `2026-11-24-www-census-gov-about-policies-open-gov-open-data-html.txt`: general open-data commitment ("sharing its public data as open data") without naming a license or this dataset.
- `2026-11-24-www-census-gov-about-policies-citation-html.txt`: citation guidance only.

## Classification
- redistribution: **link_only** — the data are freely downloadable public-use files from a federal agency, but no dataset-level license or explicit public-domain statement covers LODES (it is absent from data.json, and the LEHD pages are silent). POLICY.md: silent/unclear terms → link_only; do not infer CC0 from other Census datasets. LODES also incorporates state UI wage records supplied under LED partnership agreements, another reason not to assume.
- commercial_use: **unclear** — not stated.
- attribution: LEHD's requested citation format (see catalog entry).
