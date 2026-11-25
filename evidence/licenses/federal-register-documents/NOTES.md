# License evidence: federal-register-documents

## Snapshots
- `2026-11-24-www-govinfo-gov-about-policies.txt` — https://www.govinfo.gov/about/policies — retrieved 2026-11-24T23:39:00+00:00 — sha256 d9e3a2f1cb4486ab…
- `2026-11-24-www-federalregister-gov-reader-aids-developer-resources-rest-api.txt` — https://www.federalregister.gov/reader-aids/developer-resources/rest-api — retrieved 2026-11-24T23:39:01+00:00 — sha256 861af43d3a50b09a…
- `2026-11-24-www-archives-gov-data-json-excerpt.json` — https://www.archives.gov/files/data.json (NARA Project Open Data catalog), entries matching /FederalRegister.gov and API|Federal Register in XML/ — retrieved 2026-11-24 via scripts/pod_license_excerpt.py

## Operative terms
- `*-federalregister-gov-reader-aids-developer-resources-rest-api.txt`: FederalRegister.gov serves non-browser clients a "Request Access"
  page instead of its policy/terms pages: "Due to aggressive automated scraping of FederalRegister.gov and eCFR.gov, programmatic access to
  these sites is limited to access to our extensive developer APIs." So the site's own legal-status/terms pages could not be read from
  here (treated as unfetchable). It does confirm that programmatic use of the API (what our adapter does) is the sanctioned route.
- `*-www-govinfo-gov-about-policies.txt` (GPO, publisher of the official Federal Register): "Title 17, Section 105, United States Code,
  provides that: Copyright protection under this title is not available for any work of the United States Government ... By virtue of the
  foregoing, public documents can generally be reprinted without legal restriction. However, Government publications may contain
  copyrighted material which was used with permission of the copyright owner. Publication in a Government document does not authorize any
  use or appropriation of such copyright material without consent of the owner."
- `*-www-archives-gov-data-json-excerpt.json` (NARA Project Open Data catalog): entries "FederalRegister.gov and API" and "Federal Register
  in XML" are `accessLevel: public` but carry **no** `license` or `rights` field.

## Classification
- redistribution: **link_only** — Federal Register documents are federal works and generally public domain, but (a) the FederalRegister.gov
  terms could not be fetched, (b) no dataset-level license is declared in NARA's catalog, and (c) GPO states that government publications
  may contain third-party copyrighted material (POLICY §Licensing rule 6). Fetched on demand, never cached.
- commercial_use: **unclear** — public-domain status is general, not confirmed for this dataset given the third-party caveat.
- attribution: "Office of the Federal Register (NARA), Federal Register documents via the FederalRegister.gov API." FederalRegister.gov is
  not the official legal edition; the official edition is the PDF on govinfo.gov (pdf_url in each row).
