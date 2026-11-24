# License evidence: eac-eavs

## Snapshots
- `2026-11-24-www-eac-gov-main-privacy-statement.txt` — https://www.eac.gov/main/privacy-statement — retrieved 2026-11-24T23:36:32+00:00 — sha256 5d9212d299a1b866…
- `2026-11-24-www-eac-gov-data-json-excerpt.json` — https://www.eac.gov/data.json (Project Open Data catalog; written by scripts/pod_license_excerpt.py) — retrieved 2026-11-24
- `2026-11-24-www-eac-gov-research-and-data-datasets-codebooks-and-surveys.txt` — https://www.eac.gov/research-and-data/datasets-codebooks-and-surveys — retrieved 2026-11-24T23:36:32+00:00 — sha256 64679c4a573ab7c9…

## Operative terms
- `*-data-json-excerpt.json`: EAC's Project Open Data entries for the 2012-2022 EAVS datasets and the 2024 Comprehensive Report have **no `license` field**; most carry `"rights": "true"` (not a usable statement). No dataset-level license.
- `*-privacy-statement.txt` (site-wide "Privacy Statement", General Considerations, dated December 23, 2025): "Election Assistance Commission (EAC) products and materials may not be used to state or imply the endorsement by EAC or by any EAC employee of a commercial product, service or activity, or used in any other manner that might be misleading." … "we request that EAC be cited as the source of information or material used" … "You may link freely to the EAC Web site or any of its content."
- `*-datasets-codebooks-and-surveys.txt` (data page; URL redirects to /research-and-data/studies-and-reports): lists the EAVS data files; no license, copyright or public-domain statement.
- No eac.gov page found stating that EAC data or web content is in the public domain (searched the site footer, sitemap and a web search restricted to eac.gov on 2026-11-24).

## Classification
- redistribution: **link_only** — EAVS is a U.S. federal agency's survey and probably a public-domain government work, but POLICY §Licensing 3 requires the page or agency policy to say so, and nothing does. The only reuse terms are site-level and conditional (no implied endorsement, no misleading use, cite EAC). Unclear/silent terms → link_only: fetch on demand, no caching.
- commercial_use: **unclear** — not prohibited, not clearly permitted.
- attribution: "U.S. Election Assistance Commission, Election Administration and Voting Survey (EAVS) <year> public-release data." (EAC requests that it be cited as the source.)
- Re-check if EAC publishes a data license (e.g. adds `license` to data.json).
