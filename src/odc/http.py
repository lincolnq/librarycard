"""Shared HTTP helpers for adapters and the monitor.

Rules (see CLAUDE.md):
* All network access by adapters goes through this module, so that the user
  agent, timeouts, retries and the license-gated cache are uniform.
* Never put credentials in requests. If a source needs a key it is
  ``access.method: restricted`` and has no adapter.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import shutil
import tempfile
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import httpx

USER_AGENT = os.environ.get(
    "ODC_USER_AGENT",
    "open-data-catalog/0.1 (public-data find-and-fetch service; automated, low-volume)",
)
DEFAULT_TIMEOUT = float(os.environ.get("ODC_HTTP_TIMEOUT", "60"))
CACHE_DIR = Path(os.environ.get("ODC_CACHE_DIR", Path.home() / ".cache" / "open-data-catalog"))
CACHE_ENABLED = os.environ.get("ODC_CACHE", "1") != "0"
MAX_DOWNLOAD_BYTES = int(os.environ.get("ODC_MAX_DOWNLOAD_BYTES", str(1_500_000_000)))


class SourceError(Exception):
    """The publisher could not be reached or returned something unusable.

    ``kind`` is one of: network, http, parse, empty, schema. The monitor and the
    contract runner use it to classify failures in needs-repair issues.
    """

    def __init__(self, message: str, kind: str = "network", url: str | None = None, status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.url = url
        self.status = status


def client(timeout: float | None = None) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
        timeout=httpx.Timeout(timeout or DEFAULT_TIMEOUT, connect=20),
        follow_redirects=True,
    )


def request(
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json_body: Any = None,
    headers: dict | None = None,
    retries: int = 3,
    timeout: float | None = None,
    ok_statuses: tuple[int, ...] = (200,),
) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with client(timeout) as c:
                r = c.request(method, url, params=params, json=json_body, headers=headers)
            if r.status_code in ok_statuses:
                return r
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = float(r.headers.get("Retry-After", 0) or 0) or 2 ** attempt
                time.sleep(min(wait, 30))
                continue
            raise SourceError(
                f"HTTP {r.status_code} from {r.request.url}: {r.text[:500]}", kind="http", url=str(r.request.url), status=r.status_code
            )
        except httpx.HTTPError as exc:  # network-level
            last = exc
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise SourceError(f"{type(exc).__name__} fetching {url}: {exc}", kind="network", url=url) from exc
    raise SourceError(f"giving up on {url}: {last}", kind="network", url=url)


def get_json(url: str, params: dict | None = None, **kw) -> Any:
    r = request("GET", url, params=params, **kw)
    try:
        return r.json()
    except ValueError as exc:
        raise SourceError(f"Expected JSON from {r.request.url}, got: {r.text[:300]}", kind="parse", url=str(r.request.url)) from exc


def get_text(url: str, params: dict | None = None, **kw) -> str:
    return request("GET", url, params=params, **kw).text


def head(url: str, params: dict | None = None) -> httpx.Response:
    """HEAD, falling back to a streamed GET (no body read) for servers that reject HEAD."""
    try:
        with client(30) as c:
            r = c.head(url, params=params)
            if r.status_code < 400:
                return r
            with c.stream("GET", url, params=params) as r2:
                if r2.status_code >= 400:
                    raise SourceError(f"HTTP {r2.status_code} from {url}", kind="http", url=url, status=r2.status_code)
                return r2
    except httpx.HTTPError as exc:
        raise SourceError(f"{type(exc).__name__} on {url}: {exc}", kind="network", url=url) from exc


# --------------------------------------------------------------------- files

def _cache_path(url: str) -> Path:
    h = hashlib.sha256(url.encode()).hexdigest()[:24]
    name = url.rstrip("/").rsplit("/", 1)[-1].split("?")[0][-60:] or "file"
    return CACHE_DIR / f"{h}-{name}"


def _looks_like_html(path: Path) -> bool:
    with open(path, "rb") as f:
        head = f.read(512).lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html"))


@contextmanager
def download(url: str, *, cache_allowed: bool, max_age_s: int = 7 * 86400, params: dict | None = None,
             allow_html: bool = False) -> Iterator[Path]:
    """Download ``url`` to a local file and yield its path.

    If ``cache_allowed`` (the adapter passes this from the catalog license:
    ``redistribution == 'allowed'``) and caching is enabled, the file is kept
    under ODC_CACHE_DIR for ``max_age_s``. Otherwise it is written to a temp
    file that is deleted on exit, so nothing persists for link_only sources.
    """
    full = str(httpx.URL(url, params=params)) if params else url
    if cache_allowed and CACHE_ENABLED:
        p = _cache_path(full)
        if p.exists() and time.time() - p.stat().st_mtime < max_age_s:
            yield p
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".part")
        _stream_to(full, tmp)
        if not allow_html and _looks_like_html(tmp):
            tmp.unlink(missing_ok=True)
            raise SourceError(f"{full} returned an HTML page instead of a data file (error page or moved file?)", kind="parse", url=full)
        tmp.replace(p)
        yield p
        return
    fd, name = tempfile.mkstemp(prefix="odc-")
    os.close(fd)
    tmp = Path(name)
    try:
        _stream_to(full, tmp)
        if not allow_html and _looks_like_html(tmp):
            raise SourceError(f"{full} returned an HTML page instead of a data file (error page or moved file?)", kind="parse", url=full)
        yield tmp
    finally:
        tmp.unlink(missing_ok=True)


def _stream_to(url: str, dest: Path) -> None:
    for attempt in range(3):
        try:
            with client(300) as c, c.stream("GET", url) as r:
                if r.status_code != 200:
                    raise SourceError(f"HTTP {r.status_code} downloading {url}", kind="http", url=url, status=r.status_code)
                n = 0
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        n += len(chunk)
                        if n > MAX_DOWNLOAD_BYTES:
                            raise SourceError(f"{url} exceeds ODC_MAX_DOWNLOAD_BYTES", kind="http", url=url)
                        f.write(chunk)
            return
        except httpx.HTTPError as exc:
            if attempt == 2:
                raise SourceError(f"{type(exc).__name__} downloading {url}: {exc}", kind="network", url=url) from exc
            time.sleep(2 ** attempt)


def open_text(path: Path, member: str | None = None, encoding: str = "utf-8-sig") -> io.TextIOBase:
    """Open a downloaded file as text, transparently handling .gz and .zip.

    For zips, ``member`` selects the file (exact name, or a suffix match);
    default is the first .csv/.txt member.
    """
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic[:2] == b"\x1f\x8b":
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding=encoding, errors="replace", newline="")
    if magic[:4] == b"PK\x03\x04":
        zf = zipfile.ZipFile(path)
        names = zf.namelist()
        if member:
            cands = [n for n in names if n == member or n.endswith(member)]
        else:
            cands = [n for n in names if n.lower().endswith((".csv", ".txt", ".tsv"))]
        if not cands:
            raise SourceError(f"zip {path.name} has no member matching {member!r}; members: {names[:20]}", kind="parse")
        return io.TextIOWrapper(zf.open(cands[0]), encoding=encoding, errors="replace", newline="")
    return open(path, encoding=encoding, errors="replace", newline="")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
