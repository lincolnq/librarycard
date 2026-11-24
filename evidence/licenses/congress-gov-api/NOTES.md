# License evidence: congress-gov-api

## Snapshots
- `2026-11-24-ithubusercontent-com-libraryofcongress-api-congress-gov-main-readme-md.txt` — https://raw.githubusercontent.com/LibraryOfCongress/api.congress.gov/main/README.md — retrieved 2026-11-24T23:39:13+00:00 — sha256 06ee3f7c0b3f62af…
- `2026-11-24-www-loc-gov-legal.txt` — https://www.loc.gov/legal/ — retrieved 2026-11-24T23:39:13+00:00 — sha256 6ecd4ab926e3f783…
- `2026-11-24-api-congress-gov-v3-bill-unavailable.txt` — https://api.congress.gov/v3/bill?format=json — FETCH FAILED 2026-11-24T23:39:13+00:00: HTTP 403 from https://api.congress.gov/v3/bill?format=json: {
  "error": {
    "code": "API_KEY_MISSING",
    "message": "No api_key was supplied. Get one at https://api.congress.gov:443"
  }
}

## Operative terms
- `*-api-congress-gov-v3-bill-unavailable.txt`: an anonymous request returns HTTP 403 `{"error": {"code": "API_KEY_MISSING", "message": "No api_key was supplied. Get one at https://api.congress.gov:443"}}`.
- `*-libraryofcongress-api-congress-gov-main-readme-md.txt` (official API docs repo): "An API key is required for access. Sign up for a key here." "The rate limit is set to 5,000 requests per hour." "Attribution: While not required, the following citation may be used for attribution". No license statement for the data.
- `*-www-loc-gov-legal.txt` (Library of Congress legal page): "As a publicly supported institution, we generally do not own the rights to materials in our collections. You should determine for yourself whether or not an item is protected by copyright or in the public domain ..."
- www.congress.gov pages (e.g. /help/using-data-offsite, /about/legal) returned HTTP 403 to non-browser clients from here.

## Classification
- redistribution: **link_only** — no dataset-level license; LOC's general statement leaves rights determination to the user. (Bill text and
  congressional records are largely federal works, but that is not stated for the API content.)
- commercial_use: **unclear**.
- Access: needs an api.data.gov key → catalog-only `restricted` entry (`credentials_required`), no adapter (POLICY §Credentials).
