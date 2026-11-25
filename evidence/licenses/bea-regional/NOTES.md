# License evidence: bea-regional

## Snapshots
- `2026-11-24-www-bea-gov-help-faq-145.txt` — https://www.bea.gov/help/faq/145 — retrieved 2026-11-24T23:37:30+00:00 — sha256 345c22bd8a5290e5…
- `2026-11-24-www-bea-gov-help-faq-147.txt` — https://www.bea.gov/help/faq/147 — retrieved 2026-11-24T23:37:31+00:00 — sha256 c72d2223bba2e995…
- `2026-11-24-www-bea-gov-about-policies-and-information-linking.txt` — https://www.bea.gov/about/policies-and-information/linking — retrieved 2026-11-24T23:37:31+00:00 — sha256 ef25f5d942242b3f…
- `2026-11-24-apps-bea-gov-regional-downloadzip-htm.txt` — https://apps.bea.gov/regional/downloadzip.htm — retrieved 2026-11-24T23:37:31+00:00 — sha256 ca06e3aff2bc3bfb…
- `2026-11-24-apps-bea-gov-data-json-excerpt.json` — https://apps.bea.gov/data.json (BEA Project Open Data catalog) filtered to /Regional/ — retrieved 2026-11-24

## Operative terms
- `2026-11-24-www-bea-gov-help-faq-147.txt` ("Are the information and data presented on the BEA web site copyright-protected?"): "Unless stated otherwise, the information posted on this web site is in the public domain and may be used or reproduced without specific permission. A citation such as "Source: U.S. Bureau of Economic Analysis" would be appreciated."
- `2026-11-24-www-bea-gov-help-faq-145.txt` ("Is permission needed to reproduce information from the BEA web site?"): same sentence, plus "use of the logo for any other purpose is prohibited."
- `2026-11-24-apps-bea-gov-data-json-excerpt.json`: the "Regional Accounts" dataset is `accessLevel: public` with distribution https://apps.bea.gov/regional/downloadzip.cfm; no `license` field (BEA's catalog has none for any dataset), so the FAQ statement is the operative one.
- `2026-11-24-apps-bea-gov-regional-downloadzip-htm.txt`: the regional ZIP download page; nothing on it states otherwise (no third-party or restrictive terms). It carried a "lapse in appropriations, this website is not being updated" banner on retrieval.
- `2026-11-24-www-bea-gov-about-policies-and-information-linking.txt`: linking policy; third-party copyright applies only to linked external sites, not to BEA statistics.
- Not used: the BEA API terms (API requires a key and is not used by this adapter).

## Classification
- redistribution: **allowed** — publisher states explicitly that its web-site information is public domain and may be reproduced without permission, and the regional statistics are BEA's own estimates (no third-party content indicated).
- commercial_use: **yes** — public domain.
- attribution: "Source: U.S. Bureau of Economic Analysis" (requested); we add table and vintage. Do not use the BEA logo.
