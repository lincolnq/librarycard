# License evidence: cms-medicare-geographic-variation

## Snapshots
- `2026-11-24-data-cms-gov-terms-of-use.txt` — https://data.cms.gov/terms-of-use — retrieved 2026-11-24T23:46:12+00:00 — sha256 971a7734d4568d71…
- `2026-11-24-www-usa-gov-government-works.txt` — https://www.usa.gov/government-works — retrieved 2026-11-24T23:46:30+00:00 — sha256 b5128fd8bd0fbcb6…
- `2026-11-24-www-usa-gov-government-copyright.txt` — https://www.usa.gov/government-copyright — retrieved 2026-11-24T23:46:41+00:00 — sha256 770326f25042f225…
- `2026-11-24-data-cms-gov-data-json-excerpt.json` — excerpt of https://data.cms.gov/data.json (CMS Project Open Data catalog), entry "Medicare Geographic Variation - by National, State & County : 2024-01-01".

## Operative terms
- `...data-json-excerpt.json`: every distribution of the dataset (API "latest" 6219697b-..., API version 1e426446-..., CSV) has `"license": "https://www.usa.gov/government-works"`; publisher "Office of Enterprise Data and Analytics (OEDA)", subOrganizationOf "Centers for Medicare and Medicaid Services (CMS)"; `accessLevel: public`. (The dataset-level `license` key is absent for all 3,552 CMS entries; CMS records licences on distributions.)
- `...www-usa-gov-government-works.txt` redirects to `...www-usa-gov-government-copyright.txt`: "Government work is something created by a U.S. government officer or employee as part of their official duties." Not usable in a way that implies endorsement; agency logos need permission.
- `...data-cms-gov-terms-of-use.txt`: the data.cms.gov terms page is a client-side JavaScript application; plain retrieval returns only the app shell (0 chars of text). Its text could not be captured.
- The data are aggregate statistics computed by CMS staff from Medicare administrative claims (a government work); no third-party content is indicated.

## Classification
- redistribution: **allowed** — the agency's own dataset-level (distribution-level) licence statement in its Project Open Data catalog designates the data a U.S. Government Work (public domain, 17 U.S.C. §105). ADDING_A_SOURCE names the POD catalog as the clearest dataset-level statement for federal agencies, and dataset-level terms beat site-level terms; the uncapturable site terms page is therefore not decisive. Re-check if CMS changes the POD licence field.
- commercial_use: **yes** — public domain.
- attribution: CMS/OEDA dataset citation with release and a non-endorsement statement (catalog `license.attribution`).
