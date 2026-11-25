# License evidence: fec-individual-contributions

## Snapshots
- `2026-11-25-www-fec-gov-updates-sale-or-use-contributor-information.txt` — https://www.fec.gov/updates/sale-or-use-contributor-information/ — retrieved 2026-11-25T01:46:45+00:00 — sha256 0aefc6d9f4915597…
- `2026-11-25-c-gov-campaign-finance-data-contributions-individuals-file-description.txt` — https://www.fec.gov/campaign-finance-data/contributions-individuals-file-description/ — retrieved 2026-11-25T01:46:45+00:00 — sha256 7726f7545ff6b33d…
- `2026-11-25-www-fec-gov-data-browse-data.txt` — https://www.fec.gov/data/browse-data/?tab=bulk-data — retrieved 2026-11-25T01:46:46+00:00 — sha256 069612fa8dd932ea…

Also relied on (shared FEC evidence, not re-snapshotted): `evidence/licenses/fec-all-candidates/` (FEC data.json
`licence` excerpt, fecgov/FEC LICENSE.md, privacy policy).

## Operative terms
- `*-sale-or-use-contributor-information.txt`: "Under the Federal Election Campaign Act (the Act), information about
  individual contributors taken from FEC reports cannot be sold or used for soliciting contributions (including any
  political or charitable contribution) or for any commercial purpose." … "This restriction applies only to the use of
  individual contributor information. Any person may compile and sell the names of political committees. Additionally,
  Commission regulations provide that the restriction does not apply to the use of individual contributor information
  in newspapers, magazines, books or similar communications, as long as the principal purpose of the communication is
  not to solicit contributions or conduct commercial activity." … "In AO 1986-25, the Commission concluded that
  individual contributor information may be used for bona fide academic research projects that do not involve the sale
  or use of that information for a commercial purpose or for soliciting contributions." (statute 52 U.S.C. 30111(a)(4);
  regulation 11 CFR 104.15)
- Same page, "Salting": "Committees may sprinkle throughout or “salt” each report with up to ten fictitious contributor
  names. … The committee itemizes each fictitious contribution on a Schedule A, providing a real address for each
  fictitious name". These decoy rows are in the bulk file and are kept as published (they are how misuse is detected).
- `*-contributions-individuals-file-description.txt`: the file layout (21 columns) and the itemization threshold:
  "This file is a subset of all itemized contributions made by individuals disclosed to the FEC. 2015 - present:
  greater than $200 …".
- `*-browse-data.txt` (bulk data page): "Anyone can inspect and copy reports and statements filed by political
  committees. But the names and addresses of individual contributors may not be sold or used for commercial purposes
  or to solicit contributions or donations."
- No copyright or license statement restricts copying or republishing the file itself; FEC publishes it for public
  download without registration.

## Classification
- Scope: allowed by docs/POLICY.md §Scope 3 "Exception: statutory public disclosure of political contributions"
  (operator decision 2026-11-25). Guardrails implemented: rows served exactly as FEC itemizes them (no added rows, no
  joins/enrichment/geocoding; only derived helper columns cycle, month and ZIP5 computed from FEC's own fields); salted
  entries kept; no contributor-name filter in the adapter; first caveat states the 52 U.S.C. 30111(a)(4) restriction and
  every fetch repeats it in `notes`; mirror rebuilt whenever FEC regenerates the weekly zip, so removals/amendments
  propagate within one batch cycle.
- redistribution: **allowed** — POLICY §Licensing rule 9 (US federal works are public domain): FEC compiles and
  publishes this file itself from reports filed with it; no copyright terms, no third-party licensed content. The
  sale-or-use restriction is a *statute* that binds every user of the information wherever they get it, not a license
  condition FEC attaches to copies; republishing the records unchanged is what FEC itself does and is expressly not
  prohibited (the restriction targets solicitation and commercial use). The §Scope exception, which is more specific
  than rule 9(a), says how to carry it: first caveat + license notes. Recorded here because rule 9(a)/rule 7 read
  literally ("conditions on use or purpose force link_only") would point the other way; see the PR/report for this
  doc gap.
- commercial_use: **no** — commercial use (and solicitation) using individual contributor information is prohibited by
  law. (Rule 9's default "yes" would be misleading here.)
- attribution: "Federal Election Commission, Contributions by individuals file (indiv<YY>), FEC bulk data,
  https://www.fec.gov/data/browse-data/?tab=bulk-data. Use restricted by 52 U.S.C. 30111(a)(4)."
