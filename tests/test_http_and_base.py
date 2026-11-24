"""Offline tests for file handling and filter coercion."""
import gzip
import io
import zipfile

import pytest

from odc import http
from odc.adapters.base import FilterError, FilterSpec


def test_open_text_plain_gz_zip(tmp_path):
    raw = "a,b\n1,2\n"
    p1 = tmp_path / "f.csv"
    p1.write_text(raw)
    p2 = tmp_path / "f.csv.gz"
    p2.write_bytes(gzip.compress(raw.encode()))
    p3 = tmp_path / "f.zip"
    with zipfile.ZipFile(p3, "w") as z:
        z.writestr("readme.txt", "ignore me")
        z.writestr("data/f.csv", raw)
    for p, member in ((p1, None), (p2, None), (p3, "f.csv")):
        with http.open_text(p, member=member) as fh:
            assert fh.read() == raw


def test_filter_coercion():
    assert FilterSpec("x", "integer", "an integer filter").coerce("5") == 5
    assert FilterSpec("x", "boolean", "a boolean filter").coerce("false") is False
    assert FilterSpec("x", "string_list", "a list filter").coerce("a, b") == ["a", "b"]
    with pytest.raises(FilterError):
        FilterSpec("x", "integer", "an integer filter").coerce("five")
    with pytest.raises(FilterError):
        FilterSpec("x", "string", "an enum filter", enum=["a"]).coerce("b")


def test_download_respects_license_gate(tmp_path, monkeypatch):
    calls = []

    def fake_stream(url, dest):
        calls.append(url)
        dest.write_text("x")
    monkeypatch.setattr(http, "_stream_to", fake_stream)
    monkeypatch.setattr(http, "CACHE_DIR", tmp_path / "cache")
    with http.download("https://example.gov/a.csv", cache_allowed=False) as p:
        kept = p
    assert not kept.exists(), "link_only downloads must not persist"
    assert not (tmp_path / "cache").exists()
    with http.download("https://example.gov/a.csv", cache_allowed=True) as p:
        assert p.exists()
    with http.download("https://example.gov/a.csv", cache_allowed=True):
        pass
    assert len(calls) == 2, "second allowed download should hit the cache"


def test_download_rejects_html_error_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(http, "_stream_to", lambda url, dest: dest.write_text("<!DOCTYPE html><html>Not found</html>"))
    monkeypatch.setattr(http, "CACHE_DIR", tmp_path / "cache")
    for allowed in (True, False):
        with pytest.raises(http.SourceError):
            with http.download("https://example.gov/x.csv", cache_allowed=allowed):
                pass
    assert not list((tmp_path / "cache").glob("*x.csv")), "error pages must not be cached"


def test_yaml_error_names_file(tmp_path):
    from odc.catalog import CatalogError, load_entry
    p = tmp_path / "bad.yaml"
    p.write_text("caveats:\n  - Legal: note: oops\n  x\n")
    with pytest.raises(CatalogError, match="bad.yaml"):
        load_entry(p)
