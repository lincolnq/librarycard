# License evidence: cdc-places

## Snapshots
- `2026-11-24-data-cdc-gov-api-views-swc5-untb-json.txt` — https://data.cdc.gov/api/views/swc5-untb.json — retrieved 2026-11-24T23:36:10+00:00 — sha256 02aecb239289eb60…
- `2026-11-24-www-cdc-gov-other-agencymaterials-html.txt` — https://www.cdc.gov/other/agencymaterials.html — retrieved 2026-11-24T23:36:10+00:00 — sha256 ce4947eeeef60392…
- `2026-11-24-www-cdc-gov-places-about-index-html.txt` — https://www.cdc.gov/places/about/index.html — retrieved 2026-11-24T23:36:10+00:00 — sha256 0985610c8c68b904…
- `2026-11-24-data-cdc-gov-data-json-excerpt.json` — excerpt of https://data.cdc.gov/data.json (CDC Project Open Data catalog), PLACES 2024/2025 release entries.

## Operative terms
- `...api-views-swc5-untb-json.txt` (dataset-level Socrata metadata for the 2025 county dataset): `"licenseId" : "PUBLIC_DOMAIN"`, `"license" : { "name" : "Public Domain" }`, `"attribution" : "Centers for Disease Control and Prevention, National Center for Chronic Disease Prevention and Health Promotion, Division of Population Health"`, `"provenance" : "official"`. The other release/geography datasets carry the same licenseId PUBLIC_DOMAIN (checked live 2026-11-24 for eav7-hnsx, cwsq-ngmh, qnzd-25i4, fu4u-a9bh, sd8v-uq83, ai6z-tcin, 4r2x-hcfq, h3ej-a9ec, dv4u-3x3q; not snapshotted).
- `...data-json-excerpt.json`: the POD `license` field is null for the PLACES entries (silent, not contradicting). Publisher: CDC; accessLevel: public.
- `...agencymaterials-html.txt`: "Most of the information on the CDC and ATSDR websites is not subject to copyright, is in the public domain, and may be freely used or reproduced without obtaining copyright permission." Exceptions are contractor/grantee/third-party licensed resources and images. Conditions for public-domain content: (1) attribution to CDC, (2) a non-endorsement disclaimer, (3) "You may not change the substantive content of the materials", (4) "state that the material is otherwise available on the agency website for no charge."
- `...places-about-index-html.txt`: PLACES is produced by CDC (with the CDC Foundation / RWJF partnership historically) from BRFSS and Census data — CDC-produced estimates, not third-party copyrighted content.

## Classification
- redistribution: **allowed** — the dataset-level license (which per POLICY beats site-level terms) is an explicit "Public Domain" declaration by the publisher, and the data are CDC model outputs (no third-party copyrighted content). The site-level conditions are ones we meet: attribution, the non-endorsement disclaimer and the "available at no charge" statement are included in `license.attribution` (carried into every provenance citation); the adapter does not alter substantive content (only type conversion and flattening of the geolocation point).
- commercial_use: **yes** — public domain.
- attribution: see catalog `license.attribution`.
