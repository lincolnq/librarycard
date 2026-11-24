"""Offline tests for the bls-laus API v1 fallback (used only when download.bls.gov returns 403).

The live API's daily quota (~25 queries/IP) makes it unsuitable for contract tests, so the fallback's parsing
and request construction are tested here with synthetic payloads shaped like documented v1 responses.
"""
import pytest

from odc.adapters import bls_laus
from odc.http import SourceError

OK = {
    "status": "REQUEST_SUCCEEDED", "responseTime": 30, "message": [],
    "Results": {"series": [{"seriesID": "LAUCN100010000000003", "data": [
        {"year": "2020", "period": "M04", "periodName": "April", "value": "14.2", "footnotes": [{}]},
        {"year": "2025", "period": "M10", "periodName": "October", "value": "-", "footnotes": [{"code": "X", "text": "..."}]},
    ]}]},
}
QUOTA = {"status": "REQUEST_NOT_PROCESSED", "responseTime": 0,
         "message": ["Request could not be serviced, as the daily threshold for total number of requests allocated to the user with registration key  has been reached."],
         "Results": {}}


def test_parse_api_v1_rows():
    rows = bls_laus.parse_api_v1(OK, bls_laus.API_V1)
    assert rows[0] == {"series_id": "LAUCN100010000000003", "year": "2020", "period": "M04", "value": "14.2", "footnote_codes": ""}
    assert rows[1]["footnote_codes"] == "X"


def test_parse_api_v1_quota_is_loud():
    with pytest.raises(SourceError) as e:
        bls_laus.parse_api_v1(QUOTA, bls_laus.API_V1)
    assert e.value.kind == "http" and "daily threshold" in str(e.value)


def test_fallback_builds_series_and_rows(monkeypatch):
    sent = {}

    class Resp:
        def json(self):
            return OK

    def fake_request(method, url, json_body=None, **kw):
        sent.update(method=method, url=url, body=json_body)
        return Resp()

    monkeypatch.setattr(bls_laus.http, "request", fake_request)
    a = bls_laus.ADAPTER
    rows, matched, url, notes = a._api_fallback("county", "10", "10001", set(), {"03", "06"}, "U", 2019, 2020, "both", 10)
    assert sent["method"] == "POST" and url == bls_laus.API_V1
    assert sent["body"] == {"seriesid": ["LAUCN100010000000003", "LAUCN100010000000006"], "startyear": "2019", "endyear": "2020"}
    assert matched == 2 and rows[0]["fips"] == "10001" and rows[0]["measure"] == "unemployment_rate"
    assert rows[1]["value"] is None and rows[1]["footnote_codes"] == "X"


def test_fallback_rejects_more_than_ten_years():
    with pytest.raises(Exception):
        bls_laus.ADAPTER._api_fallback("state", "10", "", set(), {"03"}, "U", 2000, 2020, "both", 10)
