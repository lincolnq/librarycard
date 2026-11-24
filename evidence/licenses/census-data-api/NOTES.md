# License evidence: census-data-api

## Snapshots
- `2026-11-24-www-census-gov-data-developers-about-terms-of-service-html.txt` — https://www.census.gov/data/developers/about/terms-of-service.html — retrieved 2026-11-24T23:29:47+00:00 — sha256 0fb24444a8102bd3…
- `2026-11-24-www-census-gov-data-developers-guidance-api-user-guide-html.txt` — https://www.census.gov/data/developers/guidance/api-user-guide.html — retrieved 2026-11-24T23:29:47+00:00 — sha256 b760a3b8f9be1b95…

## Operative terms
- terms-of-service snapshot: "This service is offered subject to your acceptance of the terms and conditions contained herein ... Access to or use of the API or its content constitutes acceptance to this Agreement." Includes Title 13 non-identification obligations, usage limits, indemnification.
- api-user-guide snapshot: describes requesting an API key. Observed behaviour 2026-11-24: every request without `key=` returns an HTML page titled "Missing Key": "A valid key must be included with each data API request."
- The underlying datasets are CC0 per https://www.census.gov/data.json (see evidence/licenses/census-acs-summary-file/).

## Classification
- Access: **restricted** (credentials_required) — the API now requires a key on every request; per POLICY we store no credentials and build no adapter.
- redistribution: **allowed** for the data (CC0 per census.gov data.json); the API agreement governs use of the API service, which we don't use.
- commercial_use: **yes** (CC0 data).
