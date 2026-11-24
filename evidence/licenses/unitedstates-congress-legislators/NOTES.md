# License evidence: unitedstates-congress-legislators

## Snapshots
- `2026-11-24-githubusercontent-com-unitedstates-congress-legislators-main-readme-md.txt` — https://raw.githubusercontent.com/unitedstates/congress-legislators/main/README.md — retrieved 2026-11-24T23:38:57+00:00 — sha256 1363e9a08782668d…
- `2026-11-24-w-githubusercontent-com-unitedstates-congress-legislators-main-license.txt` — https://raw.githubusercontent.com/unitedstates/congress-legislators/main/LICENSE — retrieved 2026-11-24T23:38:57+00:00 — sha256 a2010f343487d3f7…
- `2026-11-24-usercontent-com-unitedstates-congress-legislators-main-contributing-md.txt` — https://raw.githubusercontent.com/unitedstates/congress-legislators/main/CONTRIBUTING.md — retrieved 2026-11-24T23:38:58+00:00 — sha256 db89259e8c55fa1d…

## Operative terms
- `*-main-readme-md.txt` (README, section "Public domain"): "This project is dedicated to the public domain (LICENSE). ... The project is in the public domain within the United States, and copyright and related rights in the work worldwide are waived through the CC0 1.0 Universal public domain dedication."
- `*-main-contributing-md.txt`: same sentence, plus "All contributions to this project will be released under the CC0 dedication."
- `*-main-license.txt`: full CC0 1.0 Universal legal code.
- The CSV/JSON files the adapter reads (gh-pages branch, served at https://unitedstates.github.io/congress-legislators/) are generated from the same repository's YAML, so the repository-level dedication covers them.

## Classification
- redistribution: **allowed** — CC0 1.0, stated explicitly at repository (= dataset) level.
- commercial_use: **yes** — CC0.
- attribution: not required; we cite "@unitedstates project, congress-legislators (CC0)" as good practice.
- Personal data: records describe members of Congress acting in official capacity (POLICY §Scope 3 allows this). The adapter
  drops the full `birthday` column and returns only `birth_year` (the year is what the official Biographical Directory headlines);
  it returns official office address/phone/contact form only, never personal contact details (none are in the source).
