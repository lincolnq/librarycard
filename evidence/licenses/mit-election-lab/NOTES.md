# License evidence: mit-election-lab

## Snapshots
- `2026-11-24-dataverse-api-excerpt.json` — https://dataverse.harvard.edu/api/datasets/:persistentId/?persistentId=<doi> for 4 DOIs + anonymous download responses — retrieved 2026-11-24
- `2026-11-24-electionlab-mit-edu-data.txt` — https://electionlab.mit.edu/data — retrieved 2026-11-24T23:30:10+00:00 — sha256 7254ceafe8e6d782…

## Operative terms
- `*-dataverse-api-excerpt.json`: Harvard Dataverse API metadata for four MIT Election Data + Science Lab datasets. All four declare `"license": {"name": "CC0 1.0", "rightsIdentifier": "CC0-1.0"}`.
- County Presidential Returns (doi:10.7910/DVN/VOQCHQ) and U.S. House (doi:10.7910/DVN/IG0UN2) have `guestbookId: 458`; anonymous download returns `{"status":"ERROR","message":"You may not download this file without the required Guestbook response for guestbookID 458."}` — the guestbook collects name/email/institution before download.
- U.S. Senate statewide (doi:10.7910/DVN/PEJ5QU) and U.S. President (doi:10.7910/DVN/42MVDX) have no guestbook; anonymous download succeeds (redirect to dvn-cloud-iqss.s3.amazonaws.com).
- electionlab-mit-edu-data snapshot: MEDSL's data page listing the datasets and asking users to cite them.

## Classification
- redistribution: **allowed** — CC0 1.0 declared at dataset level.
- commercial_use: **yes** (CC0).
- Access: datasets without a guestbook get adapters; guestbook-gated datasets are treated as registration (POLICY §Scope 2) → catalog-only `restricted` entries (`registration_required`).
- Shared by catalog entries: mit-election-president-state, mit-election-senate-state, mit-election-county-president, mit-election-house.
