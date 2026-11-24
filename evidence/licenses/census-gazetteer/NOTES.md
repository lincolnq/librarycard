# License evidence: census-gazetteer

## Snapshots
- `2026-11-24-s-gov-geographies-reference-files-time-series-geo-gazetteer-files-html.txt` — https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html — retrieved 2026-11-24T23:39:59+00:00 — sha256 531f39980f085120…
- `2026-11-24-hic-boundary-file-shp-county-and-equivalent-for-united-states-1-500000.txt` — https://catalog.data.gov/dataset/2024-cartographic-boundary-file-shp-county-and-equivalent-for-united-states-1-500000 — retrieved 2026-11-24T23:40:01+00:00 — sha256 773d214f3f311a20…
- `2026-11-24-www-census-gov-about-policies-citation-html.txt` — https://www.census.gov/about/policies/citation.html — retrieved 2026-11-24T23:40:02+00:00 — sha256 8b8910590a539e0a…
- `2026-11-24-www-census-gov-data-json-excerpt.json` — excerpt of https://www.census.gov/data.json (0 Gazetteer entries; catalog-wide license counts) — retrieved 2026-11-24
- `2026-11-24-cb-2024-us-county-500k-iso-metadata-excerpt.txt` — use-constraint excerpt of the ISO metadata inside https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_500k.zip — retrieved 2026-11-24 (written by hand; sha256 of the xml member in the file header)

## Operative terms
- The Gazetteer files are not listed in https://www.census.gov/data.json (`2026-11-24-www-census-gov-data-json-excerpt.json`, 0 matches for gazetteer|tiger), but that catalog's `_catalog_license_counts` shows **every** one of the Bureau's 1,800 datasets is CC0 1.0 — the Bureau's open-data license policy in practice.
- `2026-11-24-hic-boundary-file-shp-county-and-equivalent-for-united-states-1-500000.txt` (catalog.data.gov record harvested from the Census Geography Division's own metadata for the 2024 cartographic boundary county file): `license https://creativecommons.org/publicdomain/zero/1.0/`; publisher "U.S. Department of Commerce, U.S. Census Bureau, Geography Division".
- `2026-11-24-cb-2024-us-county-500k-iso-metadata-excerpt.txt` (ISO metadata shipped inside that file): "Access constraints: None" and "These products are free to use in a product or publication, however acknowledgement must be given to the U.S. Census Bureau as the source."
- `2026-11-24-s-gov-geographies-reference-files-time-series-geo-gazetteer-files-html.txt`: Gazetteer landing page; states no restrictions.

## Classification
- redistribution: **allowed** — the Gazetteer is a U.S. Government work produced by the Census Geography Division from MAF/TIGER (no third-party content). The Bureau declares CC0 for all of its catalogued data, and the Geography Division's sibling products from the same database are CC0 / "free to use ... acknowledgement must be given". This is an agency-policy-level statement rather than a Gazetteer-specific one; judged clear enough because no source suggests any restriction. Re-check if the Gazetteer ever gets its own data.json/data.gov record.
- commercial_use: **yes** — CC0 / free to use.
- attribution: "U.S. Census Bureau, Geography Division, <YEAR> Gazetteer Files." (acknowledgement requested).
