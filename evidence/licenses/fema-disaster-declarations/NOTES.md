# License evidence: fema-disaster-declarations

## Snapshots
- `2026-11-24-www-fema-gov-about-openfema-terms-conditions.txt` — https://www.fema.gov/about/openfema/terms-conditions — retrieved 2026-11-24T23:24:11+00:00 — sha256 a5880aa329143ea6…

## Operative terms
- terms-conditions snapshot: "By accessing OpenFEMA datasets, you agree that the data will be used solely for statistical research or as a reporting record."
- "Unauthorized use may cause FEMA to deny your future access to this data. FEMA may rescind your use of the data if FEMA believes that it does not serve the public interest. You agree you will cease using the data and destroy any copy you may have if requested by FEMA."
- Required statement: "This product uses the Federal Emergency Management Agency's OpenFEMA API, but is not endorsed by FEMA. The Federal Government or FEMA cannot vouch for the data or analyses derived from these data after the data have been retrieved from the Agency's website(s)."
- "Data accessed through FEMA's API does not include controls over its end use." (permissive in tone, but the conditions above remain)

## Classification
- redistribution: **link_only** — the data are federal and openly published, but the terms impose use conditions (statistical research / reporting record only; FEMA may require destruction of copies). Those are conditions we can't guarantee downstream users meet, so per docs/POLICY.md#licensing we do not cache or redistribute; we fetch on demand and link.
- commercial_use: **unclear** — not prohibited, not clearly permitted given the purpose limitation.
- attribution: FEMA's required non-endorsement statement + dataset/endpoint + retrieval time (see catalog `license.attribution`).
