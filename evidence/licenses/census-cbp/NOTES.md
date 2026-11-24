# License evidence: census-cbp

## Snapshots
- `2026-11-24-nsus-gov-programs-surveys-cbp-technical-documentation-methodology-html.txt` — https://www.census.gov/programs-surveys/cbp/technical-documentation/methodology.html — retrieved 2026-11-24T23:40:04+00:00 — sha256 4991918321708156…
- `2026-11-24-www-census-gov-about-policies-citation-html.txt` — https://www.census.gov/about/policies/citation.html — retrieved 2026-11-24T23:40:05+00:00 — sha256 2a5807512a9fbc86…
- `2026-11-24-www-census-gov-data-json-excerpt.json` — https://www.census.gov/data.json filtered to /20(1[7-9]|2\d) County Business Patterns/ — retrieved 2026-11-24

## Operative terms
- `2026-11-24-www-census-gov-data-json-excerpt.json` (excerpt of https://www.census.gov/data.json, the Census Bureau's Project Open Data catalog): "2017 County Business Patterns", "2022 County Business Patterns" and "2023 County Business Patterns" each carry `"license": "https://creativecommons.org/publicdomain/zero/1.0/"`. The `_catalog_license_counts` field of the same file shows the license values used across all Census datasets in data.json. (An earlier, broader run of the excerpt script on the same date also showed CC0 on 1986-2016 CBP entries; it was overwritten by this narrower run, which keeps the years the adapter serves most.)
- `2026-11-24-www-census-gov-about-policies-citation-html.txt`: the Bureau asks users to cite the source (survey, table, year).
- `2026-11-24-...cbp-technical-documentation-methodology-html.txt`: methodology (noise infusion, EMPFLAG discontinued from reference year 2018, <3-establishment cells dropped). Not a license page; kept for caveats.

## Classification
- redistribution: **allowed** — dataset-level license in the publisher's own open-data catalog is CC0 1.0 (clear and permissive).
- commercial_use: **yes** — CC0.
- attribution: "U.S. Census Bureau, County Business Patterns <year>." (citation requested, not required).
