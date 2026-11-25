# Data Commons overlap audit (2026-11-25)

How librarycard relates to Google Data Commons (DC): DC is the harmonised-indicator layer; librarycard is the
source-faithful, record-level, fine-geography, caveated layer. This audit classifies each fetchable source as
`duplicate`, `partial` or `none` relative to DC, records DC variable/place ids for joining, and lists gaps.
Re-run it when onboarding sources (see docs/ADDING_A_SOURCE.md).

> Policy note: transaction-level FEC contributions name private donors and are out of scope (POLICY §Scope 3),
> even though DC lacks them. Committee-level aggregates are fine.


Audited 2026-11-25 against the live Data Commons MCP server (`search_indicators`, `get_variable_metadata`, `get_child_observations`, `get_observations`). The catalog at `/home/user/open-data-catalog/catalog/*.yaml` was only read; no repo files were changed.

**Process caveat:** the playbooks `skill://data-commons-researcher/SKILL.md` and `skill://data-commons-child-places-researcher/SKILL.md` could not be read. This session has no MCP resource-reading tool: ToolSearch for "ReadMcpResource", "read mcp resource" and "Data Commons" surfaced none. All place and variable DCIDs below were still resolved through the search tools, never guessed. The place-search tool takes place *names* and rejects raw DCIDs as `places`. Tract and block-group DCIDs were found by child enumeration of a small county.

## Scope

- The catalog has 33 entries. 7 have `access.method: restricted` and were skipped: `census-data-api`, `congress-gov-api`, `data-commons`, `fbi-crime-data-explorer`, `hud-fair-market-rents`, `mit-election-county-president` and `mit-election-house`.
  - `data-commons` is a pointer to Data Commons itself, through its hosted MCP server at `https://api.datacommons.org/mcp`.
- All 26 non-restricted sources were assessed.

## Summary table

| source id | classification | what librarycard adds | DC variables (DCIDs) | DC finest US geography | DC latest date (vs ours) |
|---|---|---|---|---|---|
| census-acs-summary-file | partial | Margins of error (`_M` columns); every detailed table, not only curated stat vars; ACS **1-year 2025** (DC's ACS 1-yr facet stops at 2019); GEO_ID-native rows | `Median_Income_Household` (B19013_E001), `Count_Person` (B01003_E001), `Count_Person_BelowPovertyLevelInThePast12Months`, `Count_Person_EnrolledInSchool` | Census block group (`CensusACS5yrSurvey`); also ZCTA, congressional district, school district | 5-yr 2024 (2020-24); next refresh due 2026-12-11. Ours: 5-yr 2024 + 1-yr 2025 |
| census-decennial-2020-pl | partial | Block level and VTD/precinct; housing occupancy (H001) and GQ (P005) detail; area/internal-point fields | `Count_Person` (P0010001; facet `USDecennialCensus_RedistrictingRelease`) | Census block group (no blocks seen) | 2020 (same) |
| census-pep | partial | Components of change (natural change, domestic/international migration, residual, GQ) and rates; vintage-specific series | `Count_Person` (POPESTIMATE; facet `USCensusPEP_Annual_Population`); `Count_BirthEvent_LiveBirth` is CDC WONDER, not PEP | County, city (`CensusPEPSurvey`) | 2025 (same) |
| census-saipe | partial | SAIPE model-based estimates (DC poverty and income come from ACS); **school-district** poverty for ages 5-17 (Title I); single-year county estimates | ACS analogues only: `Count_Person_BelowPovertyLevelInThePast12Months`, `Median_Income_Household` | ACS: block group / school district (`geoId/sch0622710` has data) | No SAIPE facet seen. ACS 2024 vs SAIPE 2024 |
| census-cbp | duplicate | Noise and employment-size flags (`emp_nf`, `empflag`), legal form of organization (`lfo`), full NAICS depth | `WagesAnnual_Establishment` (ap; facet `CensusCountyBusinessPatterns`), `Count_Worker_NAICS*` (CBP facet); `Count_Establishment_NAICS*` is mostly BLS QCEW | County, CBSA, **ZCTA** (ZBP) | 2023 (same) |
| census-gazetteer | none | Land and water area, internal-point lat/long, GEOIDFQ crosswalk; reference geography that DC does not expose as stat vars | none found (land-area search returned only land-cover fractions) | n/a | n/a (ours 2026) |
| bls-laus | duplicate | Raw BLS series ids and footnote codes; possibly 1-2 newer months | `UnemploymentRate_Person`, `Count_Person_InLaborForce`, `Count_Person_Unemployed` (facet `BLS_LAUS`, monthly SA/NSA plus annual) | City / town (`City`, `Town`, `Village`); county | **2026-07** (LA County, NSA). Ours: monthly, current |
| bea-regional | partial | Personal income / per-capita personal income (CAINC tables, not found in DC); quarterly state series (2026:Q2); state annual 2025; full LineCode tables and (D)/(NA) notes | `Amount_EconomicActivity_GrossDomesticProduction_RealValue` (CAGDP; facet `BEAGDPv2`), `Amount_..._NAICS*_RealValue`, `USStateQuarterlyIndustryGDP_NAICS_*` | County (also City in scope) | GDP 2024 (ours: county 2024, state 2025, quarterly 2026:Q2) |
| cdc-places | partial (thin) | Confidence limits (`low_/high_confidence_limit`); denominators; lat/long | `Percent_Person_Obesity`, `Percent_Person_WithDiabetes`, `Percent_Person_WithHighBloodPressure`, `Percent_Person_Smoking`, `Percent_Person_18To64Years_ReceivedNoHealthInsurance` (facet `CDC500`, crude and age-adjusted) | **Census tract** (tract `geoId/06003010000` has data), ZCTA, city | 2023 (same) |
| cdc-svi | partial | Percentile ranks `RPL_THEMES`/`RPL_THEME1-4` and flags (`F_TOTAL`) not found; tract and ZCTA files; MOEs (`M_*`/`MP_*`) | Component estimates only, via facet `CDC_Social_Vulnerability_Index` on `Count_Person`, `UnemploymentRate_Person` (2010-2022) | County (no tract in facet scope) | 2022 (same) |
| county-health-rankings | partial | Premature death / YPLL (`v001`) not found; rankings; numerators, denominators, CIs and flags; race-specific values | DC has the inputs from other upstreams: `Percent_Person_Obesity` (v011), `Percent_Person_Smoking` (v009) via CDC PLACES; `Count_Person_NoHealthInsurance` via ACS (CHR v085 uses SAHIE) | Tract (PLACES) / block group (ACS) | 2023 / 2024 (ours: 2025 release) |
| cms-medicare-geographic-variation | none | Medicare FFS and MA counts, standardized spending per capita by service, readmissions, PQIs | none (only ACS `Count_Person_WithMedicareCoverage`, a different concept) | n/a | n/a (ours 2024) |
| lehd-lodes | partial (weak) | **Census block** workplace and residence jobs; **origin-destination flows**; age, earnings and industry segments | Only county-level QCEW/CBP analogues: `Count_Worker_NAICS*` | County | QCEW 2025-12 monthly; nothing LODES-sourced |
| noaa-nclimgrid-daily | partial | **Daily** county and state area-averaged tmax/tmin/tavg/prcp (gridded nClimGrid), current to within weeks | `Mean_Rainfall` (facet `NOAA_EPA_Observed_Historical_Weather`, monthly, to 2024-03; plus 16-day GFS forecast); CMIP6 projections `MaxTemp_Daily_Hist_*` | County / ZCTA (station-based) | Observed 2024-03 monthly (ours: daily, current) |
| eac-eavs | none | Registered voters, turnout by method, mail and provisional ballots, UOCAVA, precincts and poll workers at jurisdiction level | none (voter-registration search returned only enrollment vars) | n/a | n/a (ours 2024) |
| mit-election-president-state | none | Candidate-level vote returns | none surfaced by stat-var search ("total votes", "votes cast for president") | n/a | n/a (ours 2024) |
| mit-election-senate-state | none | Candidate-level Senate returns, specials and runoffs | none surfaced | n/a | n/a (ours 2024) |
| fec-all-candidates | none | Candidate finance records | none | n/a | n/a |
| federal-register-documents | none | Document-level regulatory records | none | n/a | n/a |
| fema-disaster-declarations | none | Declaration-level records by county and program | Related but different: `FemaNaturalHazardRiskIndex_NaturalHazardImpact*`, `FemaSocialVulnerability_NaturalHazardImpact` (National Risk Index, tract-level scores) | (NRI: tract) | n/a |
| fhfa-hpi | none | Repeat-sales HPI (state, metro, **tract**), quarterly to 2026Q3 | none (only ACS home-value bins `Count_HousingUnit_HomeValue*`) | n/a | n/a |
| unitedstates-congress-legislators | none | Legislator records and crosswalk ids (bioguide, FEC, ICPSR) | none | n/a | n/a |
| voteview-congress | none | Roll-call votes, NOMINATE scores | none | n/a | n/a |
| urban-education-data-ccd | none | NCES administrative enrollment (by grade, race and sex) and district finance (revenue and expenditure) | ACS survey analogue only: `Count_Person_EnrolledInSchool` at school district (resident enrollment, a different concept) | School district (`geoId/sch<leaid>`) | ACS 2024 (ours 2024) |
| usaspending-spending-by-geography | none | Federal obligations and outlays by state, county and district | none (closest: `Count_Establishment_FederalGovernmentOwnedEstablishment_*`) | n/a | n/a |
| usda-ers-rural-urban-codes | none | RUCC 2023 / UIC 2024 classifications | none (search returned land-cover fractions) | n/a | n/a |

Totals: **duplicate 2** (cbp, laus), **partial 11**, **none 13**.

## Proposed `data_commons_variable` mappings (key_variables)

Only clear equivalents are listed.

| source | key_variable | data_commons_variable | note |
|---|---|---|---|
| census-acs-summary-file | B19013_E001 | `Median_Income_Household` | ACS5 facet `dc/base/CensusACS5YearSurvey` |
| census-acs-summary-file | B01003_E001 | `Count_Person` | Pick the ACS5 facet; other facets are PEP and decennial |
| census-decennial-2020-pl | P0010001 | `Count_Person` | Facet `USDecennialCensus_RedistrictingRelease` |
| census-pep | POPESTIMATE<YEAR> | `Count_Person` | Facet `USCensusPEP_Annual_Population` |
| census-cbp | ap | `WagesAnnual_Establishment` | Facet `CensusCountyBusinessPatterns` |
| census-cbp | emp (by NAICS) | `Count_Worker_NAICS<Sector>` | CBP facet exists alongside QCEW |
| bls-laus | measure = unemployment rate | `UnemploymentRate_Person` | |
| bls-laus | measure = labor force | `Count_Person_InLaborForce` | |
| bls-laus | measure = unemployment | `Count_Person_Unemployed` | |
| bea-regional | CAGDP real GDP line | `Amount_EconomicActivity_GrossDomesticProduction_RealValue` | Chained 2017 USD |
| cdc-places | measureid OBESITY | `Percent_Person_Obesity` | Crude vs age-adjusted = measurementMethod |
| cdc-places | measureid DIABETES | `Percent_Person_WithDiabetes` | |
| cdc-places | measureid BPHIGH | `Percent_Person_WithHighBloodPressure` | |
| cdc-places | measureid CSMOKING | `Percent_Person_Smoking` | |
| cdc-places | measureid ACCESS2 | `Percent_Person_18To64Years_ReceivedNoHealthInsurance` | |
| county-health-rankings | v011_rawvalue | `Percent_Person_Obesity` | Different upstream vintage; approximate |
| county-health-rankings | v009_rawvalue | `Percent_Person_Smoking` | Approximate |
| census-saipe | SAEPOVALL_PT | `Count_Person_BelowPovertyLevelInThePast12Months` | Concept match only (ACS, not SAIPE) |
| census-saipe | SAEMHI_PT | `Median_Income_Household` | Concept match only (ACS) |

## US place-DCID conventions (probe evidence)

| level | DCID pattern | probe evidence |
|---|---|---|
| State | `geoId/<2-digit state FIPS>` | "California" → `geoId/06`; Rhode Island `geoId/44`, Wyoming `geoId/56`, Delaware `geoId/10` |
| County | `geoId/<5-digit state+county FIPS>` | "Los Angeles County" → `geoId/06037`; "Alpine County" → `geoId/06003` |
| Census tract | `geoId/<11-digit>` | Child tract of `geoId/06003` → `geoId/06003010000` ("Census Tract 100, Alpine County") |
| Block group | `geoId/<12-digit>` | `geoId/060030100001`, `geoId/060030100002` |
| Place / city | `geoId/<7-digit state+place FIPS>` | "Los Angeles, California" → `geoId/0644000` (type City) |
| Congressional district | `geoId/<2-digit state><2-digit district>`, at-large = `00` | RI children → `geoId/4401`, `geoId/4402`; Wyoming → `geoId/5600` |
| ZCTA | `zip/<5-digit>` | "90012" → `zip/90012` (type CensusZipCodeTabulationArea) |
| School district | `geoId/sch<7-digit NCES LEA id>` | "Los Angeles Unified" → `geoId/sch0622710`, the same as the CCD `leaid` 0622710 |

Notes:
- **Congressional district DCIDs do not encode the Congress number.** `geoId/4401` is reused across redistricting.
  - The display names still read "(113th Congress)", for example "Congressional District 1 (113th Congress), Rhode Island", but the 2024 ACS values are attached to the same id.
  - So a district DCID does not tell you which boundary vintage applies. Join on `state FIPS + district` and treat the boundaries as the current ones.
- Free-text name resolution can misfire. "California's 12th congressional district" resolved to `wikidataId/Q1002264`, not a `geoId/06xx`. "Census tract 2071 Los Angeles County" failed outright.
  - Resolve districts and tracts by child enumeration (`get_child_observations` with child type `CongressionalDistrict` or `CensusTract`) from a state or county.
- The mapping from catalog GEOIDs is mechanical: Census `GEOID` → `geoId/<GEOID>`, ZCTA → `zip/<ZCTA5>`, NCES `leaid` → `geoId/sch<leaid>`.
  - Exception: a congressional-district GEOID (state+CD, 4 digits) matches directly, but check the boundary vintage.

## Where librarycard adds the most value (ranked)

1. **Election administration and returns** (`eac-eavs`, `mit-election-*`, plus the restricted county and house MIT files). No vote, registration or turnout stat vars surfaced in DC at all.
2. **Political and legislative record data** (`voteview-congress`, `unitedstates-congress-legislators`, `fec-all-candidates`, `federal-register-documents`). These are record-level data with no DC equivalent, and the core of a civic catalog.
3. **Fine-grain and flow data** (`lehd-lodes`). Block-level jobs and origin-destination flows. DC stops at county QCEW totals.
4. **Administrative spending and program data** (`usaspending-spending-by-geography`, `cms-medicare-geographic-variation`, `urban-education-data-ccd` finance and enrollment, `fema-disaster-declarations`). None has a DC equivalent.
5. **Housing prices and fresh, high-frequency series** (`fhfa-hpi`, tract HPI to 2026Q3; `noaa-nclimgrid-daily`, daily and current where DC's observed weather stops at 2024-03; `bea-regional`, quarterly 2026:Q2 and personal income).
6. **Uncertainty and full-table depth for Census products** (`census-acs-summary-file` MOEs and ACS 1-yr 2025; `census-decennial-2020-pl` blocks and VTDs; `cdc-svi` ranks; `county-health-rankings` YPLL, ranks and CIs; `census-saipe` school-district Title I estimates).
7. **Low added value**: `census-cbp` and `bls-laus` are effectively duplicated in DC. `cdc-places` differs only by its confidence intervals. For headline values, these could defer to DC.

## Onboarding priorities to complement Data Commons

- **Election results below state level**: precinct, county and district returns (for example, open versions of the restricted MIT county and house files, and state SOS certified results), plus redistricting crosswalks that tie district ids to a specific Congress. DC's district DCIDs carry no vintage.
- **Campaign finance at transaction level** (FEC individual contributions and independent expenditures) and lobbying disclosures (LDA).
- **Federal and administrative program records**: Medicaid/CHIP enrollment, SNAP by county, HUD (open alternatives to the restricted FMR entry), IRS SOI county/ZIP income and migration flows, and Education finance.
- **Fine-geography, high-frequency economic data**: QCEW county files direct (DC is about a quarter behind), and Census building permits.
- **Public safety and justice**: an open path to FBI data (the current entry is restricted), and court and incarceration data.
- **Boundary and crosswalk assets** (gazetteer-like): tract↔ZCTA↔CD↔county relationship files, so librarycard data can be joined with DC DCIDs. These would feed the proposed `data_commons_variable` / place-id mapping work.
- **De-prioritise** new sources that only re-serve ACS, PEP, LAUS, CBP or PLACES headline values. Instead, link those key_variables to their DC variable DCIDs.
