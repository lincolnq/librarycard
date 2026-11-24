# License evidence: census-pep

## Snapshots
- `2026-11-24-www-census-gov-programs-surveys-popest-data-data-sets-html.txt` — https://www.census.gov/programs-surveys/popest/data/data-sets.html — retrieved 2026-11-24T23:39:56+00:00 — sha256 c5f045db593a0e98…
- `2026-11-24-www-census-gov-about-policies-citation-html.txt` — https://www.census.gov/about/policies/citation.html — retrieved 2026-11-24T23:39:57+00:00 — sha256 ba850cd76e2c5408…
- `2026-11-24-www-census-gov-data-json-excerpt.json` — excerpt of https://www.census.gov/data.json via scripts/pod_license_excerpt.py — retrieved 2026-11-24

## Operative terms
- `2026-11-24-www-census-gov-data-json-excerpt.json` (excerpt of https://www.census.gov/data.json, the Bureau's Project Open Data catalog): every Population Estimates dataset, including "Population Estimates: Census Bureau Version: Components of Change Estimates" and "Population Estimates: Population Estimates", has `"license": "https://creativecommons.org/publicdomain/zero/1.0/"`. `_catalog_license_counts` shows all 1,800 Census datasets carry CC0.
- `2026-11-24-www-census-gov-about-policies-citation-html.txt`: "Proper citation ensures that Census Bureau statistical products and research can be discovered, reused, replicated for verification, and credited" — citation requested, not a condition on reuse.
- `2026-11-24-www-census-gov-programs-surveys-popest-data-data-sets-html.txt`: PEP datasets page (no additional restrictions).

## Classification
- redistribution: **allowed** — the publisher's dataset-level license for PEP is CC0 1.0 (clear and permissive). The bulk CSVs on www2.census.gov are the same estimates the catalogued API datasets serve.
- commercial_use: **yes** — CC0.
- attribution: "U.S. Census Bureau, Population Estimates Program, Vintage <V> ..." (citation requested by the citation policy).
