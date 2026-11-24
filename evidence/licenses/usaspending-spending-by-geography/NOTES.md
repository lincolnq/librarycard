# License evidence: usaspending-spending-by-geography

## Snapshots
- `2026-11-24-rency-usaspending-website-master-src-js-components-about-licensing-jsx.txt` — https://raw.githubusercontent.com/fedspendingtransparency/usaspending-website/master/src/js/components/about/Licensing.jsx — retrieved 2026-11-24T23:39:02+00:00 — sha256 17bb96438e23c94c…
- `2026-11-24-sparency-usaspending-website-master-src-js-components-about-dbinfo-jsx.txt` — https://raw.githubusercontent.com/fedspendingtransparency/usaspending-website/master/src/js/components/about/DBInfo.jsx — retrieved 2026-11-24T23:39:02+00:00 — sha256 196fb51e192323a7…
- `2026-11-24-pending-api-api-contracts-contracts-v2-search-spending-by-geography-md.txt` — https://raw.githubusercontent.com/fedspendingtransparency/usaspending-api/master/usaspending_api/api_contracts/contracts/v2/search/spending_by_geography.md — retrieved 2026-11-24T23:39:03+00:00 — sha256 49064354883d1532…
- `2026-11-24-www-treasury-gov-data-json-excerpt.json` — https://www.treasury.gov/jsonfiles/data.json (Treasury Project Open Data catalog), entries matching /USAspending/ — retrieved 2026-11-24 via scripts/pod_license_excerpt.py

## Operative terms
- USAspending.gov's About page is a JavaScript single-page app (the HTML has no text), so the page text was snapshotted from the site's own
  source on GitHub (fedspendingtransparency/usaspending-website), which is what renders https://www.usaspending.gov/about#about-licensing
  and https://www.usaspending.gov/db_info.
- `*-about-licensing-jsx.txt`: "The U.S. Department of the Treasury, Bureau of the Fiscal Service is committed to providing open data to enable
  effective tracking of federal spending. The data on this site is available to copy, adapt, redistribute, or otherwise use for
  non-commercial or for commercial purposes, subject to the Limitation on Permissible Use of Dun & Bradstreet, Inc. Data noted on the homepage."
- `*-about-dbinfo-jsx.txt`: "This website contains data supplied by third party information suppliers, one of which is D&B. ... you agree that
  you shall not use D&B Open Data without giving written attribution to the source of such data (i.e., D&B) and shall not access, use or
  disseminate D&B Open Data in bulk ... Except for data elements identified above as D&B Open Data, under no circumstances are you authorized
  to use any other D&B data for commercial, resale or marketing purposes ... Systematic access (electronic harvesting) or extraction of
  content from the website, including the use of "bots" or "spiders", is prohibited." D&B Open Data is defined as business name, street
  address, city, state, country, county code, state code/abbreviation and ZIP.
- `*-www-treasury-gov-data-json-excerpt.json`: Treasury's Project Open Data entries for USAspending have no `license` field.
- `*-spending-by-geography-md.txt`: the API contract for the endpoint used (documents fields; no terms).

## Classification
- redistribution: **link_only** — reuse is granted but explicitly *subject to* third-party (D&B) restrictions, and we can't verify which
  elements of an aggregate are D&B-derived (recipient location/county codes may be). Conditional terms → link_only (POLICY §Licensing 3, 6).
  The adapter only requests geographic aggregates (no recipient names or DUNS/UEI) through the public API the publisher documents for
  programmatic use, on demand and low-volume; nothing is cached.
- commercial_use: **unclear** — permitted for USAspending data generally, but not for non-"Open Data" D&B elements.
- attribution: the publisher's suggested general citation: "USAspending.gov, U.S. Department of Treasury, Bureau of the Fiscal Service,
  https://www.usaspending.gov. Accessed <date>."
