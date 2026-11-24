# License evidence: hud-fair-market-rents

## Snapshots
- `2026-11-24-www-huduser-gov-portal-datasets-fmr-html-unavailable.txt` — https://www.huduser.gov/portal/datasets/fmr.html — FETCH FAILED 2026-11-24T23:40:38+00:00: HTTP 202 from https://www.huduser.gov/portal/datasets/fmr.html: 
- `2026-11-24-www-huduser-gov-portal-dataset-fmr-api-html-unavailable.txt` — https://www.huduser.gov/portal/dataset/fmr-api.html — FETCH FAILED 2026-11-24T23:40:39+00:00: HTTP 202 from https://www.huduser.gov/portal/dataset/fmr-api.html: 
- `2026-11-24-catalog-data-gov-dataset-fair-market-rents.txt` — https://catalog.data.gov/dataset/fair-market-rents — retrieved 2026-11-24T23:40:39+00:00 — sha256 5d689cb8f9c4f7ea…
- `2026-11-24-data-hud-gov-data-json-excerpt.json` — excerpt of https://data.hud.gov/data.json via scripts/pod_license_excerpt.py — retrieved 2026-11-24

## Operative terms
- `2026-11-24-data-hud-gov-data-json-excerpt.json` (HUD's Project Open Data catalog, https://data.hud.gov/data.json): `license` is null for all 226 datasets; the "Fair Market Rents" and "Small Area Fair Market Rents" entries have only `rights`: "HUD and the dataset and metadata authors assume no responsibility for the use or misuse of the dataset. No warranty, expressed or implied ..." — a disclaimer, not a grant.
- `2026-11-24-catalog-data-gov-dataset-fair-market-rents.txt`: same metadata as shown on data.gov (accessRights Public, no license).
- `*-www-huduser-gov-portal-datasets-fmr-html-unavailable.txt`, `*-fmr-api-html-unavailable.txt`: HUD User pages return HTTP 202 with an AWS WAF JavaScript challenge to non-browser clients; terms could not be read.

## Classification
- redistribution: **link_only** — no license is stated at dataset or catalog level and the HUD User terms could not be fetched. FMRs are very likely U.S. Government works in the public domain, but POLICY says not to guess permissively.
- commercial_use: **unclear** — not stated.
- attribution: "U.S. Department of Housing and Urban Development, Office of Policy Development and Research, Fair Market Rents."
- Access is restricted anyway (API token), so the classification has no effect on caching today.
