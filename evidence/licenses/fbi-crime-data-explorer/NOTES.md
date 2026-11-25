# License evidence: fbi-crime-data-explorer

## Snapshots
- `2026-11-24-api-usa-gov-crime-fbi-cde-agency-bystateabbr-de-unavailable.txt` — https://api.usa.gov/crime/fbi/cde/agency/byStateAbbr/DE — FETCH FAILED 2026-11-24T23:49:08+00:00: HTTP 403 from https://api.usa.gov/crime/fbi/cde/agency/byStateAbbr/DE: {
  "error": {
    "code": "API_KEY_MISSING",
    "message": "An API key was not provided. Please get one at https://api.data.gov
- `2026-11-24-cde-ucr-cjis-gov-latest-webapp.txt` — https://cde.ucr.cjis.gov/LATEST/webapp/ — retrieved 2026-11-24T23:49:09+00:00 — sha256 d9ba2796e35f1e03…
- `2026-11-24-www-justice-gov-data-json-excerpt.json` — excerpt of https://www.justice.gov/data.json (DOJ Project Open Data catalog): FBI entries "Uniform Crime Reporting (UCR) Program", "National Incident-Based Reporting System (NIBRS)", "NIBRS Estimates", "Crime in the United States".

## Operative terms
- `...justice-gov-data-json-excerpt.json`: all four FBI UCR/NIBRS entries carry `"license": "http://www.usa.gov/publicdomain/label/1.0/"` (U.S. Public Domain label); publisher "Federal Bureau of Investigation"; distributions point to the Crime Data Explorer downloads page (https://cde.ucr.cjis.gov/LATEST/webapp/#/pages/downloads), which is an interactive single-page app, not a stable file URL.
- `...api-usa-gov-crime-fbi-cde-...-unavailable.txt`: the official CDE API returns HTTP 403 `API_KEY_MISSING` — "An API key was not provided. Please get one at https://api.data.gov/signup/". Access needs an api.data.gov key (free, registration) — per POLICY, a restricted entry.
- `...cde-ucr-cjis-gov-latest-webapp.txt`: the CDE web app shell (client-side JS; no terms text retrievable). The app's internal endpoints and its signed bulk-download URLs are undocumented and are not used (that would work around the key requirement).

## Classification
- redistribution: **allowed** — DOJ's dataset-level POD records label the UCR/NIBRS data U.S. Public Domain (federal government work). Moot for fetching (restricted, no adapter), but recorded so a future keyless route can reuse it.
- commercial_use: **yes** — public domain.
- attribution: "Federal Bureau of Investigation, Uniform Crime Reporting Program, Crime Data Explorer."
