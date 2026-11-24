# License evidence: noaa-nclimgrid-daily

## Snapshots
- `2026-11-24-registry-opendata-aws-noaa-nclimgrid.txt` — https://registry.opendata.aws/noaa-nclimgrid/ — retrieved 2026-11-24T23:24:12+00:00 — sha256 a52a2e16a6a45144…
- `2026-11-24-www-noaa-gov-information-technology-open-data-dissemination-unavailable.txt` — https://www.noaa.gov/information-technology/open-data-dissemination — FETCH FAILED 2026-11-24T23:24:12+00:00: HTTP 403 from https://www.noaa.gov/information-technology/open-data-dissemination: <!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<HTML><HEAD><M

## Operative terms
- registry-opendata-aws snapshot (the NOAA Open Data Dissemination listing for this bucket), section "License": "NOAA data disseminated through NODD are open to the public and can be used as desired."
- Same section: "NOAA requests attribution for the use or dissemination of unaltered NOAA data. However, it is not permissible to state or imply endorsement by or affiliation with NOAA. If you modify NOAA data, you may not state or imply that it is original, unaltered NOAA data."
- The noaa.gov open-data-dissemination page was blocked from this environment ("Request blocked", see `-unavailable.txt`); the AWS registry page is the NODD program's official listing and is sufficient.

## Classification
- redistribution: **allowed** — explicit "open to the public and can be used as desired".
- commercial_use: **yes**.
- attribution: requested; must not imply NOAA endorsement; derived values (our long-format reshaping, FIPS conversion) must not be presented as unaltered NOAA files.
