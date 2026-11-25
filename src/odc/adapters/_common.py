"""Reusable building blocks for adapters. Prefer these over hand-rolled code.

* ``census_api``   - api.census.gov datasets (ACS, decennial, SAIPE, CBP, ...)
* ``socrata``      - Socrata SODA endpoints (data.cdc.gov, many state portals)
* ``scan_csv``     - stream a (possibly zipped/gzipped) CSV and filter rows
* ``ckan_like_json`` helpers can be added here when a second adapter needs them
"""

from __future__ import annotations

import csv
import io
import re
import sys
import zipfile
import zlib
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator

from .. import http
from ..http import SourceError
from .base import FilterError, rows_from_table

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10",
    "DC": "11", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19",
    "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35",
    "NY": "36", "NC": "37", "ND": "38", "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44",
    "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56", "PR": "72",
}
FIPS_STATE = {v: k for k, v in STATE_FIPS.items()}


def state_fips(value: str) -> str:
    """Accept 'TX', 'tx', '48', 48 -> '48'."""
    v = str(value).strip().upper()
    if v in STATE_FIPS:
        return STATE_FIPS[v]
    if v.isdigit() and v.zfill(2) in FIPS_STATE:
        return v.zfill(2)
    raise FilterError(f"unrecognized state {value!r}; use a 2-letter postal code (e.g. 'TX') or 2-digit FIPS (e.g. '48')")


def state_abbr(value: str) -> str:
    return FIPS_STATE[state_fips(value)]


# ------------------------------------------------------------------ Census

CENSUS_GEOS = {
    # filter value -> (for-clause geography name, needs state?)
    "us": ("us", False),
    "region": ("region", False),
    "division": ("division", False),
    "state": ("state", False),
    "county": ("county", False),
    "county_subdivision": ("county subdivision", True),
    "place": ("place", False),
    "tract": ("tract", True),
    "block_group": ("block group", True),
    "congressional_district": ("congressional district", False),
    "state_legislative_district_upper": ("state legislative district (upper chamber)", True),
    "state_legislative_district_lower": ("state legislative district (lower chamber)", True),
    "zcta": ("zip code tabulation area", False),
    "school_district_unified": ("school district (unified)", True),
    "metro_area": ("metropolitan statistical area/micropolitan statistical area", False),
}

_VAR_RE = re.compile(r"^[A-Za-z0-9_]+$")


def census_api(
    base_url: str,
    variables: list[str],
    geography: str,
    state: str | None = None,
    county: str | None = None,
    extra_params: dict | None = None,
    geo_ids: str = "*",
) -> tuple[list[dict], str]:
    """Query a Census Data API endpoint. Returns (rows, request_url).

    Census API responses are JSON arrays of arrays with a header row. Values
    are strings; we leave them as strings (adapters may coerce). Without an
    API key the Census API allows ~500 requests/day per IP, which is plenty for
    on-demand use.
    """
    if geography not in CENSUS_GEOS:
        raise FilterError(f"geography must be one of {sorted(CENSUS_GEOS)}")
    for v in variables:
        if not _VAR_RE.match(v):
            raise FilterError(f"invalid variable name {v!r}")
    if len(variables) > 49:
        raise FilterError("at most 49 variables per request (Census API limit is 50 incl. NAME)")
    geo, needs_state = CENSUS_GEOS[geography]
    if needs_state and not state:
        raise FilterError(f"geography '{geography}' requires the 'state' filter")
    params: dict[str, Any] = {"get": ",".join(["NAME", *[v for v in variables if v != "NAME"]])}
    if geography == "county" and county:
        params["for"] = f"county:{county}"
    else:
        params["for"] = f"{geo}:{geo_ids}"
    ins = []
    if state and geography not in ("us", "region", "division", "state", "zcta", "metro_area"):
        ins.append(f"state:{state_fips(state)}")
    elif geography == "state" and state:
        params["for"] = f"state:{state_fips(state)}"
    if county and geography in ("tract", "block_group", "county_subdivision"):
        ins.append(f"county:{county}")
    if geography == "block_group" and county:
        ins.append("tract:*")
    if ins:
        params["in"] = " ".join(ins)
    if extra_params:
        params.update(extra_params)
    try:
        r = http.request("GET", base_url, params=params, ok_statuses=(200, 204))
    except SourceError as e:
        if e.status == 400:
            # Census returns 400 with a useful message for unknown variables/geos.
            raise FilterError(f"Census API rejected the query: {e}") from None
        raise
    url = str(r.request.url)
    if r.status_code == 204 or not r.text.strip():
        return [], url
    try:
        table = r.json()
    except ValueError:
        raise SourceError(f"non-JSON response from {url}: {r.text[:300]}", kind="parse", url=url) from None
    return rows_from_table(table), url


def census_variable_metadata(base_url: str, variable: str) -> dict:
    return http.get_json(f"{base_url}/variables/{variable}.json")


# ------------------------------------------------------------------ Socrata

def socrata(domain: str, dataset_id: str, *, where: str | None = None, select: str | None = None,
            order: str | None = None, limit: int = 500, offset: int = 0) -> tuple[list[dict], str]:
    params: dict[str, Any] = {"$limit": limit, "$offset": offset}
    if where:
        params["$where"] = where
    if select:
        params["$select"] = select
    if order:
        params["$order"] = order
    url = f"https://{domain}/resource/{dataset_id}.json"
    r = http.request("GET", url, params=params)
    return r.json(), str(r.request.url)


def soql_quote(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


# ------------------------------------------------------------------ CSV scan

def scan_csv(
    url: str,
    *,
    cache_allowed: bool,
    predicate: Callable[[dict], bool] | None = None,
    limit: int,
    member: str | None = None,
    delimiter: str = ",",
    encoding: str = "utf-8-sig",
    columns: Iterable[str] | None = None,
    max_age_s: int = 7 * 86400,
    transform: Callable[[dict], dict] | None = None,
) -> tuple[list[dict], int]:
    """Download (license-gated cache) and stream-filter a delimited file.

    Returns (rows, matched_count). ``matched_count`` counts all matching rows
    even beyond ``limit`` so callers can report truncation honestly.
    """
    out: list[dict] = []
    matched = 0
    cols = list(columns) if columns else None
    with http.download(url, cache_allowed=cache_allowed, max_age_s=max_age_s) as path:
        with http.open_text(path, member=member, encoding=encoding) as fh:
            reader = csv.DictReader(fh, delimiter=delimiter)
            if reader.fieldnames is None:
                raise SourceError(f"{url}: empty file", kind="empty", url=url)
            reader.fieldnames = [f.strip() for f in reader.fieldnames]
            if cols:
                missing = [c for c in cols if c not in reader.fieldnames]
                if missing:
                    raise SourceError(f"{url}: expected columns {missing} not in header {reader.fieldnames[:40]}", kind="schema", url=url)
            for row in reader:
                if predicate is None or predicate(row):
                    matched += 1
                    if len(out) < limit:
                        if transform:
                            row = transform(row)
                        out.append({c: row.get(c) for c in cols} if cols else row)
    return out, matched


def select_columns(rows: list[dict], columns: list[str] | None) -> list[dict]:
    if not columns:
        return rows
    if rows:
        missing = [c for c in columns if c not in rows[0]]
        if missing:
            raise FilterError(f"unknown column(s) {missing}; available: {list(rows[0])}")
    return [{c: r.get(c) for c in columns} for r in rows]


# ------------------------------------------------------------------ Dataverse

def dataverse_files(server: str, doi: str) -> tuple[dict, str]:
    """Return ({filename: datafile dict}, dataset API url) for the latest published version."""
    url = f"https://{server}/api/datasets/:persistentId/"
    r = http.request("GET", url, params={"persistentId": doi})
    try:
        latest = r.json()["data"]["latestVersion"]
    except (ValueError, KeyError) as e:
        raise SourceError(f"unexpected Dataverse response from {r.request.url}: {e}", kind="parse", url=str(r.request.url)) from None
    files = {f["dataFile"]["filename"]: {**f["dataFile"], "_version": f"{latest.get('versionNumber')}.{latest.get('versionMinorNumber')}"}
             for f in latest.get("files", [])}
    return files, str(r.request.url)


def dataverse_file_url(server: str, file_id: int, original: bool = False) -> str:
    """Download URL for a Dataverse datafile. Tabular files are served as tab-delimited
    .tab by default; ``original=True`` returns the uploaded original format."""
    return f"https://{server}/api/access/datafile/{file_id}" + ("?format=original" if original else "")


def pick_dataverse_file(files: dict, pattern: str) -> dict:
    rx = re.compile(pattern)
    hits = sorted(n for n in files if rx.search(n))
    if not hits:
        raise SourceError(f"no Dataverse file matches /{pattern}/; files: {sorted(files)}", kind="schema")
    return files[hits[-1]]


# ------------------------------------------------------------------ OpenFEMA

OPENFEMA = "https://www.fema.gov/api/open"


def openfema(entity: str, version: int, *, filter_expr: str | None, limit: int,
             orderby: str | None = None, select: str | None = None) -> tuple[list[dict], str, int | None]:
    """Query an OpenFEMA OData-style endpoint. Returns (rows, url, total_count).

    OpenFEMA caps $top at 10000 per call; we never ask for more than MAX_LIMIT+1.
    """
    params: dict[str, Any] = {"$top": limit, "$inlinecount": "allpages", "$format": "json"}
    if filter_expr:
        params["$filter"] = filter_expr
    if orderby:
        params["$orderby"] = orderby
    if select:
        params["$select"] = select
    url = f"{OPENFEMA}/v{version}/{entity}"
    r = http.request("GET", url, params=params)
    try:
        data = r.json()
    except ValueError:
        raise SourceError(f"non-JSON from {r.request.url}", kind="parse", url=str(r.request.url)) from None
    if entity not in data:
        raise SourceError(f"OpenFEMA response lacks '{entity}' key; keys={list(data)[:10]}", kind="schema", url=str(r.request.url))
    return data[entity], str(r.request.url), (data.get("metadata") or {}).get("count")


def odata_quote(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


# ------------------------------------------------------------------ remote zip (HTTP Range)

@dataclass
class RemoteZipMember:
    name: str
    header_offset: int   # local file header position in the archive
    data_end: int        # last byte (inclusive) that can belong to this member (next header / central dir - 1)
    compress_size: int
    file_size: int
    method: int          # 0 stored, 8 deflate


class _RangeFile(io.RawIOBase):
    """Seekable read-only view of a remote file over HTTP Range requests, with a small block cache.
    Only used to let zipfile parse the central directory (a few requests at the end of the file)."""

    BLOCK = 1 << 20

    def __init__(self, url: str, size: int):
        self.url, self.size, self.pos = url, size, 0
        self.blocks: dict[int, bytes] = {}

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        return self.pos

    def readinto(self, b) -> int:
        if self.pos >= self.size:
            return 0
        bi = self.pos // self.BLOCK
        if bi not in self.blocks:
            start = bi * self.BLOCK
            self.blocks[bi] = http.read_range(self.url, start, min(self.BLOCK, self.size - start))
        blk = self.blocks[bi]
        off = self.pos - bi * self.BLOCK
        data = blk[off:off + len(b)]
        b[:len(data)] = data
        self.pos += len(data)
        return len(data)


def remote_zip_members(url: str) -> tuple[str, list[RemoteZipMember]]:
    """List the members of a (possibly multi-GB, zip64) zip over HTTP Range requests, without downloading it.
    Returns (resolved_url, members). The resolved URL is the redirect target, used for the range reads."""
    r = http.head(url)
    final = str(r.url)
    try:
        size = int(r.headers["content-length"])
    except (KeyError, ValueError):
        raise SourceError(f"{url}: no Content-Length; cannot range-read the zip", kind="schema", url=url) from None
    if (r.headers.get("accept-ranges") or "bytes").lower() != "bytes":
        raise SourceError(f"{url}: server does not accept byte ranges", kind="schema", url=url)
    try:
        zf = zipfile.ZipFile(io.BufferedReader(_RangeFile(final, size), buffer_size=1 << 16))
    except zipfile.BadZipFile as e:
        raise SourceError(f"{url}: not a zip ({e})", kind="parse", url=url) from None
    infos = sorted(zf.infolist(), key=lambda i: i.header_offset)
    ends = [i.header_offset - 1 for i in infos[1:]] + [zf.start_dir - 1]
    return final, [RemoteZipMember(i.filename, i.header_offset, e, i.compress_size, i.file_size, i.compress_type)
                   for i, e in zip(infos, ends)]


def remote_zip_lines(url: str, m: RemoteZipMember, encoding: str = "utf-8") -> Iterator[str]:
    """Stream one member of a remote zip and yield its text lines (without line endings).

    Only this member's compressed bytes are requested, as one streamed Range request; nothing is stored.
    Stop iterating to stop the download (e.g. once a small ``fetch`` has enough rows)."""
    if m.method not in (0, 8):
        raise SourceError(f"{url}!{m.name}: unsupported zip compression method {m.method}", kind="parse", url=url)
    stream = http.iter_bytes(url, m.header_offset, m.data_end)
    try:
        head = b""
        for chunk in stream:
            head += chunk
            if len(head) >= 30:
                break
        if head[:4] != b"PK\x03\x04":
            raise SourceError(f"{url}!{m.name}: no local file header at offset {m.header_offset}", kind="parse", url=url)
        skip = 30 + int.from_bytes(head[26:28], "little") + int.from_bytes(head[28:30], "little")
        d = zlib.decompressobj(-15) if m.method == 8 else None
        remaining = m.compress_size
        tail = b""
        done = False

        def compressed() -> Iterator[bytes]:
            yield head
            yield from stream

        pending = skip
        for chunk in compressed():
            if pending:
                cut = min(pending, len(chunk))
                chunk, pending = chunk[cut:], pending - cut
                if not chunk:
                    continue
            if d is not None:
                data = d.decompress(chunk)
                done = d.eof
            else:
                data, remaining = chunk[:remaining], remaining - min(remaining, len(chunk))
                done = remaining == 0
            if data:
                tail += data
                *lines, tail = tail.split(b"\n")
                for ln in lines:
                    yield ln.rstrip(b"\r").decode(encoding, errors="replace")
            if done:
                break
        if not done:
            raise SourceError(f"{url}!{m.name}: compressed stream ended early", kind="parse", url=url)
        if tail:
            yield tail.rstrip(b"\r").decode(encoding, errors="replace")
    finally:
        stream.close()
