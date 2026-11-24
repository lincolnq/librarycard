# License evidence: cdc-svi

## Snapshots
- `2026-11-24-arcgis-com-sharing-rest-content-items-f2af3fd35858443293b75d5f73c7d4d3.txt` — https://www.arcgis.com/sharing/rest/content/items/f2af3fd35858443293b75d5f73c7d4d3?f=json — retrieved 2026-11-24T23:39:35+00:00 — sha256 f60d9fb31a026b0a…
- `2026-11-24-www-cdc-gov-other-agencymaterials-html.txt` — https://www.cdc.gov/other/agencymaterials.html — retrieved 2026-11-24T23:39:35+00:00 — sha256 ce4947eeeef60392…
- `2026-11-24-tsdr-cdc-gov-place-health-php-svi-svi-data-documentation-download-html.txt` — https://www.atsdr.cdc.gov/place-health/php/svi/svi-data-documentation-download.html — retrieved 2026-11-24T23:39:35+00:00 — sha256 6ccb46a3657bd216…
- `2026-11-24-svi-cdc-gov-datadownloads-data-download-html.txt` — https://svi.cdc.gov/dataDownloads/data-download.html — retrieved 2026-11-24T23:39:36+00:00 — sha256 3516222c549e4bcd…

## Operative terms
- `...arcgis-com-sharing-rest-content-items-f2af3fd3...txt` — the publisher's own metadata record for the official dataset "CDC/ATSDR Social Vulnerability Index 2022 USA" on ArcGIS Online (owner `data_cdc`, CDC's official account; the SVI documentation names ArcGIS Online as an official distribution channel). `licenseInfo`: "These data are available to the public at large with no constraints or limitations. If used, please reference the Centers for Disease Control and Prevention/ Agency for Toxic Substances and Disease Registry/ Geospatial Research, Analysis, and Services Program." `accessInformation` (credits): "...; US Census Bureau, 2018-2022 American Community Survey".
- `...agencymaterials-html.txt` (CDC/ATSDR site-level): "Most of the information on the CDC and ATSDR websites is not subject to copyright, is in the public domain, and may be freely used or reproduced without obtaining copyright permission." Exceptions: contractor/grantee/third-party licensed resources. Conditions: attribution, non-endorsement disclaimer, no substantive changes, state that the material is available at no charge.
- `...svi-data-documentation-download-html.txt`: suggested citation "Centers for Disease Control and Prevention/ Agency for Toxic Substances and Disease Registry/ Geospatial Research, Analysis, and Services Program. CDC/ATSDR Social Vulnerability Index [year] Database [U.S. or State]. ... Accessed on [date]."
- The 2022 documentation PDF (svi.cdc.gov/map25/data/docs/SVI2022Documentation_ZCTA.pdf, read 2026-11-24, not snapshotted because it is 550 KB binary) states SVI was created by ATSDR's GRASP from ACS data (CC0) — i.e. a federal work built from public-domain inputs, no third-party content.

## Classification
- redistribution: **allowed** — dataset-level statement from the publisher: "available to the public at large with no constraints or limitations", consistent with CDC's public-domain policy; the inputs are Census ACS (CC0) and the index is produced by federal staff (GRASP), so the third-party exception does not apply. Site-level conditions (attribution, non-endorsement, no-charge statement) are carried in `license.attribution`; the adapter changes no substantive content (only -999 -> null, documented).
- commercial_use: **yes** — no constraints stated; federal work.
- attribution: CDC's suggested citation plus non-endorsement statement (catalog `license.attribution`).
