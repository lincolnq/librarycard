# License evidence: fec-all-candidates

## Snapshots
- `2026-11-24-www-fec-gov-updates-sale-or-use-contributor-information.txt` — https://www.fec.gov/updates/sale-or-use-contributor-information/ — retrieved 2026-11-24T23:34:46+00:00 — sha256 59c9f0ed5498b78b…
- `2026-11-24-www-fec-gov-data-browse-data.txt` — https://www.fec.gov/data/browse-data/?tab=bulk-data — retrieved 2026-11-24T23:34:46+00:00 — sha256 0a653b61e00a3e02…
- `2026-11-24-www-fec-gov-campaign-finance-data-all-candidates-file-description.txt` — https://www.fec.gov/campaign-finance-data/all-candidates-file-description/ — retrieved 2026-11-24T23:34:46+00:00 — sha256 0301968b8efed83a…
- `2026-11-24-raw-githubusercontent-com-fecgov-fec-master-license-md.txt` — https://raw.githubusercontent.com/fecgov/FEC/master/LICENSE.md — retrieved 2026-11-24T23:34:47+00:00 — sha256 55823790a5c97f0f…
- `2026-11-24-www-fec-gov-data-json-excerpt.json` — https://www.fec.gov/data.json (Project Open Data catalog; written by scripts/pod_license_excerpt.py) — retrieved 2026-11-24
- `2026-11-24-www-fec-gov-about-privacy-and-security-policy.txt` — https://www.fec.gov/about/privacy-and-security-policy/ — retrieved 2026-11-24T23:34:47+00:00 — sha256 a193af679cee6b67…

## Operative terms
- `*-data-json-excerpt.json`: FEC's Project Open Data catalog lists one dataset ("FEC API", the same campaign-finance data as the bulk files) with `"licence": "https://github.com/fecgov/FEC/blob/master/LICENSE.md"` (note the British spelling `licence`, which is why `pod_license_excerpt.py` printed `None`). The bulk downloads are not listed separately.
- `*-license-md.txt` (that licence): "A few restrictions limit the way you can use FEC data. For example, you can’t use contributor lists for commercial purposes or to solicit donations." … "## The rest of this project is in the worldwide public domain. As a work of the United States government, this project is in the public domain within the United States. Additionally, we waive copyright and related rights in the work worldwide through the CC0 1.0 Universal public domain dedication."
- `*-sale-or-use-contributor-information.txt`: "Under the Federal Election Campaign Act (the Act), information about individual contributors taken from FEC reports cannot be sold or used for soliciting contributions … or for any commercial purpose." … "This restriction applies only to the use of individual contributor information. Any person may compile and sell the names of political committees." (statute: 52 U.S.C. 30111(a)(4); regulation 11 CFR 104.15)
- `*-browse-data.txt` (bulk data page): "Anyone can inspect and copy reports and statements filed by political committees. But the names and addresses of individual contributors may not be sold or used for commercial purposes or to solicit contributions or donations."
- `*-all-candidates-file-description.txt`: the file layout — one record per candidate with summary totals; no individual contributor names or addresses (only the aggregate TTL_INDIV_CONTRIB).
- `*-privacy-and-security-policy.txt`: site privacy policy; says nothing about data reuse (saved to show no other terms apply).

## Classification
- redistribution: **link_only** (reviewed 2026-11-24, superseding the onboarding agent's `allowed`).
  The LICENSE.md snapshot is the licence of the fecgov/FEC *website code repository* — it enumerates fonts, the U.S. Web
  Design Standards and image assets, then says "the rest of this project is in the worldwide public domain". It is
  linked from data.json's "FEC API" entry, but it is not a dataset-level statement about the bulk data files. FEC data
  are very likely public domain as federal works (17 U.S.C. §105), but POLICY §Licensing requires a clear statement and
  forbids guessing permissively, so we fetch on demand and do not cache.
- commercial_use: **unclear** — the statutory sale-or-use restriction (52 U.S.C. 30111(a)(4)) applies to individual
  contributor information, which this file lacks, but no affirmative data license was found.
- attribution: "Federal Election Commission, All candidates file (weball<YY>), FEC bulk data."
- To upgrade to `allowed`: find an FEC page stating the bulk data (or FEC data generally) is public domain / freely
  reusable, snapshot it, and cite it here.

## Reclassification 2026-11-25 → allowed / commercial_use yes
Applied docs/POLICY.md §Licensing rule 9 (US federal works are public domain under 17 U.S.C. §105 unless conditions,
third-party content or licensed data apply; adopted 2026-11-25 under the operator's delegation). FEC is a US federal agency and produces this file itself (candidate totals compiled from filings it receives). No use conditions apply to this file: the statutory sale-or-use restriction covers individual contributor information, which this file does not contain.
The earlier `link_only` classification above was made under the superseded "silent terms → link_only" rule.
