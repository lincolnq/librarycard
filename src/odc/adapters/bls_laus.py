"""BLS Local Area Unemployment Statistics (LAUS). Catalog: catalog/bls-laus.yaml

Primary path: BLS flat files at https://download.bls.gov/pub/time.series/la/ (documented in la.txt).
  la.data.<n>.<Name>  tab-delimited, CRLF, padded:  series_id  year  period  value  footnote_codes
    period M01-M12 monthly, M13 annual average; value '-' = not available (e.g. Oct 2025, shutdown)
  la.area             area_type_code  area_code  area_text  ...   (area names, 440 KB)
  Series id (20 chars) = 'LA' + seasonal (U|S) + area_code (15) + measure (2), e.g. LAUCN100010000000003.
  area_code = 2-letter prefix + state FIPS (2) + ... : ST state, CN county (ST+county FIPS), MT metro
  (state + CBSA), MC micro, DV metro division, CA combined area, CT/CS city/town, RD region/division.
  Files: 2/3 AllStates U/S, 4/5 RegionDivision U/S, 7-59 one per state (every area in that state, NSA plus SA
  statewide), 60 Metro, 61 Division, 62 Micro, 63 Combined, 64 County (~340 MB), 65 City (~330 MB),
  1 CurrentS (all seasonally adjusted series).
  download.bls.gov answers our honest UA (it 403s anonymous/curl-default clients; never spoof a browser).

Fallback: if download.bls.gov refuses us (HTTP 403 bot block), state- and county-level requests are sent to
the keyless Public Data API v1 (https://api.bls.gov/publicAPI/v1/timeseries/data/, POST JSON). v1 limits:
~25 queries/day per IP (shared by everyone behind the same egress IP), 25 series and 10 years per query, no
annual averages. When the quota is spent the API answers 200 with status REQUEST_NOT_PROCESSED.
"""

from __future__ import annotations

import csv
import datetime as dt

from .. import http
from ..http import SourceError
from ._common import FIPS_STATE, state_fips
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

BASE = "https://download.bls.gov/pub/time.series/la"
API_V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
MEASURES = {"unemployment_rate": "03", "unemployment": "04", "employment": "05", "labor_force": "06",
            "employment_population_ratio": "07", "labor_force_participation_rate": "08",
            "civilian_noninstitutional_population": "09"}
MEASURE_NAME = {v: k for k, v in MEASURES.items()}
DEFAULT_MEASURES = ["unemployment_rate", "unemployment", "employment", "labor_force"]
# area_type filter -> (la.area type codes, national file stem for U)
AREA_TYPES = {
    "state": ({"A"}, "2.AllStatesU"),
    "county": ({"F"}, "64.County"),
    "metro": ({"B"}, "60.Metro"),
    "metro_division": ({"C"}, "61.Division"),
    "micro": ({"D"}, "62.Micro"),
    "combined": ({"E"}, "63.Combined"),
    "city": ({"G", "H"}, "65.City"),
    "region_division": ({"M", "N"}, "4.RegionDivisionU"),
}
STATE_FILES = {
    "01": "7.Alabama", "02": "8.Alaska", "04": "9.Arizona", "05": "10.Arkansas", "06": "11.California",
    "08": "12.Colorado", "09": "13.Connecticut", "10": "14.Delaware", "11": "15.DC", "12": "16.Florida",
    "13": "17.Georgia", "15": "18.Hawaii", "16": "19.Idaho", "17": "20.Illinois", "18": "21.Indiana",
    "19": "22.Iowa", "20": "23.Kansas", "21": "24.Kentucky", "22": "25.Louisiana", "23": "26.Maine",
    "24": "27.Maryland", "25": "28.Massachusetts", "26": "29.Michigan", "27": "30.Minnesota",
    "28": "31.Mississippi", "29": "32.Missouri", "30": "33.Montana", "31": "34.Nebraska", "32": "35.Nevada",
    "33": "36.NewHampshire", "34": "37.NewJersey", "35": "38.NewMexico", "36": "39.NewYork",
    "37": "40.NorthCarolina", "38": "41.NorthDakota", "39": "42.Ohio", "40": "43.Oklahoma", "41": "44.Oregon",
    "42": "45.Pennsylvania", "72": "46.PuertoRico", "44": "47.RhodeIsland", "45": "48.SouthCarolina",
    "46": "49.SouthDakota", "47": "50.Tennessee", "48": "51.Texas", "49": "52.Utah", "50": "53.Vermont",
    "51": "54.Virginia", "53": "56.Washington", "54": "57.WestVirginia", "55": "58.Wisconsin", "56": "59.Wyoming",
}
FOOTNOTES = {"A": "area boundaries do not reflect official OMB definitions", "G": "2025 annual = 11-month average excluding October",
             "N": "not available", "P": "preliminary", "U": "annual average not computable (missing months)",
             "V": "survey not conducted (bad weather); interpolated, seasonally adjusted",
             "W": "household survey not conducted (bad weather); interpolated",
             "X": "unavailable due to the 2025 lapse in appropriations",
             "Y": "controlled to interpolated statewide totals (survey not conducted)"}
API_MAX_SERIES, API_MAX_YEARS = 25, 10
# la.area type code -> area_type filter value; fallback by area_code prefix when names are unavailable (API v1)
TYPE_NAME = {c: name for name, (codes, _) in AREA_TYPES.items() for c in codes}
PREFIX_TYPE = {"ST": "state", "CN": "county", "MT": "metro", "DV": "metro_division", "MC": "micro", "CA": "combined",
               "CT": "city", "CS": "city", "RD": "region_division"}
# Mirror scope: area_type -> national flat files (bulk only; the API v1 fallback never runs during ingest)
MIRROR_FILES = {
    "state": ["2.AllStatesU", "3.AllStatesS"],
    "county": ["64.County"],
    "metro": ["60.Metro"],
    "metro_division": ["61.Division"],
    "micro": ["62.Micro"],
    "combined": ["63.Combined"],
}


def _num(v: str):
    v = (v or "").strip()
    if v in ("", "-"):
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _fips(area_code: str) -> str | None:
    if area_code.startswith("ST"):
        return area_code[2:4]
    if area_code.startswith("CN"):
        return area_code[2:7]
    return None


def parse_api_v1(payload: dict, url: str) -> list[dict]:
    """Turn a v1 JSON response into raw records like the flat-file rows."""
    status = payload.get("status")
    if status != "REQUEST_SUCCEEDED":
        msg = " ".join(payload.get("message") or []) or str(status)
        raise SourceError(f"BLS API v1 did not serve the request ({status}): {msg}", kind="http", url=url, status=429)
    out = []
    for s in (payload.get("Results") or {}).get("series", []):
        sid = s.get("seriesID", "")
        for d in s.get("data", []):
            codes = ",".join(sorted({(fn or {}).get("code", "") for fn in d.get("footnotes") or []} - {"", None}))
            out.append({"series_id": sid, "year": d.get("year"), "period": d.get("period"),
                        "value": d.get("value"), "footnote_codes": codes})
    return out


def _assert_de_2020_spike(rows: list[dict]) -> None:
    apr = [r["value"] for r in rows if r["period"] == "M04" and r["measure"] == "unemployment_rate"]
    jan = [r["value"] for r in rows if r["period"] == "M01" and r["measure"] == "unemployment_rate"]
    assert apr and jan and apr[0] > jan[0] + 5, f"Delaware April 2020 rate {apr} not >5 points above January {jan}"


class BlsLaus(SourceAdapter):
    source_id = "bls-laus"
    version = "1.1.0"
    usage = ("Monthly (M01-M12) and annual-average (M13) labor force, employment, unemployment and unemployment "
             "rate by place of residence. Pick area_type (state, county, metro, city, ...) and narrow with state "
             "or county_fips; county/city without a state reads a ~340 MB national file. Default is not seasonally "
             "adjusted (seasonal='U'); 'S' exists only for states, regions/divisions and a handful of large metros/cities. "
             "One row per series x period; `value` is a percent for rates and persons for levels. Rows carry `area_type` and "
             "`state` (postal; a metro's principal state).")
    filters = [
        FilterSpec("area_type", "string", "state (default), county, metro, metro_division, micro, combined, city, region_division.",
                   enum=sorted(AREA_TYPES), default="state"),
        FilterSpec("state", "string", "Postal code or FIPS; keeps areas whose LAUS code is in this state (metros by principal state).",
                   example="DE"),
        FilterSpec("county_fips", "string", "5-digit county FIPS, e.g. '10003' (implies area_type county)."),
        FilterSpec("area_code", "string_list", "Exact 15-character LAUS area codes, e.g. ['MT1037980000000'] (from la.area)."),
        FilterSpec("measure", "string_list", f"Measures; default the first four. Choices: {sorted(MEASURES)} "
                   "(ratio/participation/population are statewide only).", enum=sorted(MEASURES)),
        FilterSpec("seasonal", "string", "U = not seasonally adjusted (default), S = seasonally adjusted.", enum=["U", "S"], default="U"),
        FilterSpec("year", "integer", "Single year."),
        FilterSpec("start_year", "integer", "First year (state series from 1976, most substate from 1990)."),
        FilterSpec("end_year", "integer", "Last year."),
        FilterSpec("periodicity", "string", "monthly, annual (M13 annual averages, NSA only) or both (default).",
                   enum=["monthly", "annual", "both"], default="both"),
    ]
    contract = [
        ContractCase(
            name="delaware_2020_covid_spike",
            filters={"area_type": "state", "state": "DE", "year": 2020, "measure": ["unemployment_rate"], "periodicity": "monthly"},
            min_rows=12, max_rows=12,
            required_columns=["series_id", "area_code", "area_name", "measure", "year", "period", "value", "fips"],
            checks=[Check("value", numeric=True, min=2, max=20), Check("series_id", regex=r"LAUST100000000000003"),
                    Check("area_name", one_of=["Delaware"])],
            custom=_assert_de_2020_spike,
        ),
        ContractCase(
            name="vermont_county_annual_2019",
            filters={"area_type": "county", "state": "VT", "year": 2019, "periodicity": "annual", "measure": ["labor_force", "unemployment_rate"]},
            min_rows=28, max_rows=28,
            required_columns=["fips", "area_name", "measure", "value"],
            checks=[Check("fips", regex=r"50\d{3}"), Check("period", one_of=["M13"])],
            limit=100,
        ),
    ]

    # ----------------------------------------------------------------- fetch
    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        atype = f.get("area_type", "state")
        st = state_fips(f["state"]) if f.get("state") else None
        cty = (f.get("county_fips") or "").strip()
        if cty:
            if len(cty) != 5 or not cty.isdigit():
                raise FilterError("county_fips must be 5 digits, e.g. '10003'")
            if st and cty[:2] != st:
                raise FilterError("county_fips is not in the given state")
            atype, st = "county", cty[:2]
        codes = set(f.get("area_code") or [])
        measures = {MEASURES[m] for m in (f.get("measure") or DEFAULT_MEASURES)}
        seasonal = f.get("seasonal", "U")
        per = f.get("periodicity", "both")
        y0 = f.get("start_year", f.get("year"))
        y1 = f.get("end_year", f.get("year"))
        if seasonal == "S" and per == "annual":
            raise FilterError("annual averages (M13) exist only for not seasonally adjusted series (seasonal='U')")
        type_codes, national = AREA_TYPES[atype]

        def keep_series(sid: str) -> bool:
            if len(sid) != 20 or sid[2] != seasonal or sid[18:20] not in measures:
                return False
            ac = sid[3:18]
            if codes:
                return ac in codes
            if cty:
                return ac == f"CN{cty}00000000"
            if st and atype != "region_division" and ac[2:4] != st:
                return False
            return True

        def keep_period(year: str, period: str) -> bool:
            y = int(year)
            if (y0 is not None and y < y0) or (y1 is not None and y > y1):
                return False
            if per == "monthly":
                return period != "M13"
            if per == "annual":
                return period == "M13"
            return True

        # pick the smallest flat file that contains the request
        if seasonal == "S":
            stem = "3.AllStatesS" if atype == "state" else "5.RegionDivisionS" if atype == "region_division" else "1.CurrentS"
        elif atype == "region_division":
            stem = national
        elif st:
            stem = STATE_FILES.get(st)
            if not stem:
                raise FilterError(f"no LAUS state file for FIPS {st}")
        elif codes and len({c[2:4] for c in codes}) == 1 and atype not in ("state",):
            stem = STATE_FILES.get(next(iter(codes))[2:4], national)
        else:
            stem = national
        url = f"{BASE}/la.data.{stem}"
        notes: list[str] = []
        try:
            names = self._area_names(cache_allowed)
            raw, matched = self._scan(url, keep_series, keep_period, names, type_codes, limit, cache_allowed)
            urls = [url, f"{BASE}/la.area"]
        except SourceError as e:
            if e.status != 403 or atype not in ("state", "county") or not (st or codes):
                raise
            raw, matched, api_url, extra = self._api_fallback(atype, st, cty, codes, measures, seasonal, y0, y1, per, limit)
            urls, notes = [api_url], extra
        notes += ["Rates are percents (one decimal); levels are persons. Data are by place of residence.",
                  "Value '-' (not available, e.g. October 2025 lost to the federal shutdown) is returned as null; "
                  "footnote_codes are explained in footnote_text."]
        if not raw:
            notes.append("No rows matched. Seasonally adjusted (S) series exist only for states, regions/divisions and a "
                         "handful of large metros/divisions/cities; metro codes carry the principal state's FIPS "
                         "(e.g. Philadelphia MT4237980000000). Look codes up in la.area.")
        if stem in ("64.County", "65.City"):
            notes.append(f"Read the national {stem} file (~340 MB); pass state to read a small per-state file instead.")
        return FetchResult(raw, urls, notes, total_available=matched,
                           metadata={"area_type": atype, "seasonal": seasonal, "file": url if urls[0] == url else None})

    def _area_names(self, cache_allowed: bool) -> dict[str, tuple[str, str]]:
        out = {}
        with http.download(f"{BASE}/la.area", cache_allowed=cache_allowed, max_age_s=7 * 86400) as p, \
                http.open_text(p, encoding="latin-1") as fh:
            reader = csv.DictReader(fh, delimiter="\t")
            require(reader.fieldnames and "area_code" in [c.strip() for c in reader.fieldnames],
                    f"{BASE}/la.area: unexpected header {reader.fieldnames}")
            for r in reader:
                r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
                out[r["area_code"]] = (r["area_type_code"], r["area_text"])
        return out

    def _row(self, sid, year, period, value, fn, names) -> dict:
        ac = sid[3:18]
        atc, name = names.get(ac, (None, None))
        fn = (fn or "").strip()
        return {"series_id": sid, "area_code": ac, "area_type_code": atc, "area_name": name, "fips": _fips(ac),
                "area_type": TYPE_NAME.get(atc) if atc else PREFIX_TYPE.get(ac[:2]),
                "state": None if ac.startswith("RD") else FIPS_STATE.get(ac[2:4]),
                "measure_code": sid[18:20], "measure": MEASURE_NAME.get(sid[18:20]), "seasonal": sid[2],
                "year": int(year), "period": period, "value": _num(value), "footnote_codes": fn or None,
                "footnote_text": "; ".join(FOOTNOTES.get(c, c) for c in fn.replace(",", "")) if fn else None}

    def _scan(self, url, keep_series, keep_period, names, type_codes, limit, cache_allowed):
        out, matched = [], 0
        with http.download(url, cache_allowed=cache_allowed, max_age_s=86400) as p, http.open_text(p, encoding="latin-1") as fh:
            reader = csv.reader(fh, delimiter="\t")
            header = [h.strip() for h in next(reader, [])]
            require(header[:4] == ["series_id", "year", "period", "value"], f"{url}: unexpected header {header}")
            for rec in reader:
                if len(rec) < 4:
                    continue
                sid = rec[0].strip()
                if not keep_series(sid):
                    continue
                if names and names.get(sid[3:18], ("?",))[0] not in type_codes:
                    continue
                year, period = rec[1].strip(), rec[2].strip()
                if not keep_period(year, period):
                    continue
                matched += 1
                if len(out) < limit:
                    out.append(self._row(sid, year, period, rec[3], rec[4] if len(rec) > 4 else "", names))
        return out, matched

    def _api_fallback(self, atype, st, cty, codes, measures, seasonal, y0, y1, per, limit):
        """download.bls.gov refused us: use the keyless API v1 (quota ~25 queries/day per IP)."""
        if per == "annual":
            raise SourceError("download.bls.gov refused the request (403) and API v1 has no annual averages", kind="http", status=403)
        if codes:
            areas = sorted(codes)
        elif atype == "county":
            if not cty:
                raise SourceError("download.bls.gov refused the request (403); the API fallback needs county_fips "
                                  "(one county) for county data", kind="http", status=403)
            areas = [f"CN{cty}00000000"]
        else:
            areas = [f"ST{st}00000000000"]
        series = [f"LA{seasonal}{a}{m}" for a in areas for m in sorted(measures)]
        if len(series) > API_MAX_SERIES:
            raise FilterError(f"API v1 fallback allows {API_MAX_SERIES} series per query; narrow area_code/measure")
        end = y1 or dt.date.today().year
        start = y0 or end - API_MAX_YEARS + 1
        if end - start + 1 > API_MAX_YEARS:
            raise FilterError(f"API v1 fallback allows {API_MAX_YEARS} years per query; narrow start_year/end_year")
        body = {"seriesid": series, "startyear": str(start), "endyear": str(end)}
        r = http.request("POST", API_V1, json_body=body, retries=1)
        try:
            payload = r.json()
        except ValueError:
            raise SourceError(f"non-JSON from {API_V1}", kind="parse", url=API_V1) from None
        out, matched = [], 0
        for rec in parse_api_v1(payload, API_V1):
            if per == "monthly" and rec["period"] == "M13":
                continue
            matched += 1
            if len(out) < limit:
                out.append(self._row(rec["series_id"], rec["year"], rec["period"], rec["value"], rec["footnote_codes"], {}))
        notes = ["download.bls.gov refused the request (HTTP 403); served from BLS Public Data API v1 instead "
                 "(no area names, no annual averages, max 10 years; ~25 queries/day shared per IP).",
                 f"API v1 POST body: series {series}, years {start}-{end}."]
        return out, matched, API_V1, notes

    # ----------------------------------------------------------------- mirror (docs/MIRROR.md)
    # One unit per area type, read from the national bulk files (all measures, U and S), split by state.
    # Reads download.bls.gov only: a 403 fails the ingest, it never falls back to the quota-limited API v1.
    mirror_partition_keys = ["area_type", "state"]
    mirror_semantics = {"state": "state_postal", "year": "year"}

    def mirror_plan(self):
        from ..mirror import MirrorUnit
        for atype in MIRROR_FILES:
            yield MirrorUnit(partition={"area_type": atype}, filters={"area_type": atype}, split_by=["state"])

    def mirror_rows(self, unit):
        atype = unit.partition["area_type"]
        type_codes = AREA_TYPES[atype][0]
        urls = [f"{BASE}/la.data.{stem}" for stem in MIRROR_FILES[atype]] + [f"{BASE}/la.area"]
        names = self._area_names(True)

        def rows():
            for url in urls[:-1]:
                with http.download(url, cache_allowed=True, max_age_s=86400) as p, http.open_text(p, encoding="latin-1") as fh:
                    reader = csv.reader(fh, delimiter="\t")
                    header = [h.strip() for h in next(reader, [])]
                    require(header[:4] == ["series_id", "year", "period", "value"], f"{url}: unexpected header {header}")
                    for rec in reader:
                        if len(rec) < 4:
                            continue
                        sid = rec[0].strip()
                        if len(sid) != 20 or names.get(sid[3:18], ("?",))[0] not in type_codes:
                            continue
                        yield self._row(sid, rec[1].strip(), rec[2].strip(), rec[3], rec[4] if len(rec) > 4 else "", names)

        notes = ["Mirror scope: states (NSA and SA), counties, metro areas, metro divisions, micro areas and combined areas, "
                 "every measure and period in the BLS bulk files. Cities/towns and census regions/divisions are not mirrored; "
                 "the local odc-server reads them from download.bls.gov.",
                 "Rates are percents (one decimal); levels are persons. Data are by place of residence.",
                 "Value '-' (not available) is null; footnote_codes are explained in footnote_text."]
        return rows(), urls, notes, {"footnotes": FOOTNOTES}


ADAPTER = BlsLaus()
