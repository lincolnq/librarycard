"""USDA ERS Rural-Urban Continuum Codes (RUCC) and Urban Influence Codes (UIC). Catalog: catalog/usda-ers-rural-urban-codes.yaml

Landing pages (the adapter scrapes the current CSV link from them, because the /media/<n>/ id and ?v= token are
assigned by the CMS and the 2013 guess /media/5768/ruralurbancontinuumcodes2023.csv was a 404):
  https://www.ers.usda.gov/data-products/rural-urban-continuum-codes  -> /media/5768/2023-rural-urban-continuum-codes.csv
  https://www.ers.usda.gov/data-products/urban-influence-codes        -> /media/6182/2024-urban-influence-codes.csv
CSV is LONG format, latin-1 encoded: FIPS (RUCC) or FIPS-UIC (UIC), State, County_Name, Attribute, Value, with
Attribute in {Population_2020, RUCC_2023 | UIC_2024, Description}. The adapter pivots to one row per county.
Two American Samoa entities (Rose Island, Swains Island) have no code and Description "Not Applicable" -> code null.
"""

from __future__ import annotations

import csv
import re

from .. import http
from ._common import state_abbr
from .base import Check, ContractCase, FetchResult, FilterError, FilterSpec, SourceAdapter, require

HOST = "https://www.ers.usda.gov"
PAGES = {
    "rucc": (f"{HOST}/data-products/rural-urban-continuum-codes", r"rural-urban-continuum-codes", "RUCC"),
    "uic": (f"{HOST}/data-products/urban-influence-codes", r"urban-influence-codes", "UIC"),
}


def csv_url(product: str) -> tuple[str, int, str]:
    """Return (csv url, code vintage year, landing page) for the newest CSV linked from the landing page."""
    page, slug, _ = PAGES[product]
    html = http.get_text(page)
    hits = re.findall(rf'href="(/media/\d+/((?:19|20)\d\d)-{slug}\.csv)(?:\?[^"]*)?"', html, re.I)
    require(bool(hits), f"{page}: no link to a <YEAR>-{slug}.csv file found; the page layout changed")
    path, year = max(hits, key=lambda h: int(h[1]))
    return HOST + path, int(year), page


class UsdaErsRuralUrbanCodes(SourceAdapter):
    source_id = "usda-ers-rural-urban-codes"
    version = "1.0.0"
    usage = ("One row per county (or county-equivalent, incl. Puerto Rico and Island Areas) with the ERS code, its "
             "text Description and the 2020 Census population. product='rucc' (default) gives Rural-Urban Continuum "
             "Codes 2023 (1-3 metro by metro size, 4-9 nonmetro by urban population and metro adjacency); "
             "product='uic' gives Urban Influence Codes 2024 (1-2 metro, 3-9 nonmetro by adjacency/urban size). "
             "Filter with `state`, `fips` or `codes`; join to other county data on FIPS.")
    filters = [
        FilterSpec("product", "string", "'rucc' = Rural-Urban Continuum Codes, 'uic' = Urban Influence Codes.",
                   enum=["rucc", "uic"], default="rucc", example="rucc"),
        FilterSpec("state", "string", "Restrict to one state (postal code or FIPS).", example="NE"),
        FilterSpec("fips", "string_list", "5-digit county FIPS codes, e.g. ['31055'].", example=["31055"]),
        FilterSpec("codes", "string_list", "Keep only these code values, e.g. ['8','9'] for the most rural RUCC classes.",
                   example=["8", "9"]),
    ]
    contract = [
        ContractCase(
            name="rucc_delaware",
            filters={"product": "rucc", "state": "DE"},
            min_rows=3, max_rows=3,
            required_columns=["FIPS", "State", "County_Name", "Population_2020", "RUCC_2023", "Description"],
            checks=[Check("RUCC_2023", numeric=True, min=1, max=9), Check("FIPS", regex=r"10\d{3}"),
                    Check("Population_2020", numeric=True, min=100_000, max=600_000)],
            limit=10,
        ),
        ContractCase(
            name="uic_all_counties",
            filters={"product": "uic"},
            min_rows=3200,
            required_columns=["FIPS", "UIC_2024", "Description"],
            checks=[Check("UIC_2024", numeric=True, min=1, max=9), Check("FIPS", regex=r"\d{5}")],
            limit=5000,
            custom=lambda rows: _check_cook(rows),
        ),
    ]

    def _fetch(self, f: dict, limit: int, cache_allowed: bool) -> FetchResult:
        product = f.get("product", "rucc")
        url, year, page = csv_url(product)
        code_col = f"{PAGES[product][2]}_{year}"
        usps = state_abbr(f["state"]) if f.get("state") else None
        fips = set(f.get("fips") or [])
        bad = [x for x in fips if not re.fullmatch(r"\d{5}", x)]
        if bad:
            raise FilterError(f"fips must be 5-digit county FIPS codes, got {bad}")
        codes = {str(c).strip() for c in (f.get("codes") or [])}
        by_fips: dict[str, dict] = {}
        with http.download(url, cache_allowed=cache_allowed, max_age_s=30 * 86400) as path:
            with http.open_text(path, encoding="latin-1") as fh:
                reader = csv.DictReader(fh)
                hdr = [h.strip() for h in (reader.fieldnames or [])]
                require(len(hdr) == 5 and hdr[1:] == ["State", "County_Name", "Attribute", "Value"] and hdr[0].startswith("FIPS"),
                        f"{url}: unexpected header {hdr}")
                reader.fieldnames = hdr
                for r in reader:
                    k = r[hdr[0]].strip().zfill(5)
                    rec = by_fips.setdefault(k, {"FIPS": k, "State": r["State"].strip(), "County_Name": r["County_Name"].strip(),
                                                 "Population_2020": None, code_col: None, "Description": None})
                    a, v = r["Attribute"].strip(), r["Value"].strip()
                    if a == "Population_2020":
                        rec[a] = int(v) if v.isdigit() else None
                    elif a == code_col:
                        rec[a] = int(v) if v.isdigit() else None
                    elif a == "Description":
                        rec[a] = v
        require(len(by_fips) > 3000 and any(r[code_col] is not None for r in by_fips.values()),
                f"{url}: parsed {len(by_fips)} counties without '{code_col}' values; attribute names changed?")
        rows = [r for r in by_fips.values()
                if (not usps or r["State"] == usps) and (not fips or r["FIPS"] in fips)
                and (not codes or str(r[code_col]) in codes)]
        notes = [f"{code_col} from {url} (linked from {page}); pivoted from the publisher's long format.",
                 "Population_2020 is the 2020 Census population used to assign the code.",
                 "Entities without a code (Description 'Not Applicable') have a null code."]
        return FetchResult(rows[:limit], [url, page], notes, total_available=len(rows),
                           metadata={"product": product, "code_column": code_col, "code_year": year})


def _check_cook(rows: list[dict]) -> None:
    cook = [r for r in rows if r["FIPS"] == "17031"]
    assert cook and cook[0]["UIC_2024"] == 1, f"Cook County, IL should be UIC 1 (large metro), got {cook}"


ADAPTER = UsdaErsRuralUrbanCodes()
