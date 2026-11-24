"""Offline tests for monitor/detect_changes.py and monitor/file_issues.py."""
import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

from odc.http import SourceError

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "monitor" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


dc = load("detect_changes")
fi = load("file_issues")
rc = load("run_contracts")


def test_json_path():
    data = {"a": [{"k": "x", "v": 1}, {"k": "y", "v": 2}], "b": {"c": [5, 6]}}
    assert dc.extract_json_path(data, "a[k=y].v") == 2
    assert dc.extract_json_path(data, "b.c[1]") == 6
    assert dc.extract_json_path(data, "a[*].v") == [1, 2]
    with pytest.raises(SourceError):
        dc.extract_json_path(data, "a[k=z].v")


def test_detect_lifecycle(cat, monkeypatch):
    sid = "noaa-nclimgrid-daily"
    fps = iter([("aaa", "d1"), ("aaa", "d1"), ("bbb", "d2")])
    monkeypatch.setattr(dc, "fingerprint", lambda cd: next(fps))
    state = {}
    r1 = dc.run(cat, state, force_all=True, only={sid})
    assert r1["changed"] == [] and state[sid]["fingerprint"] == "aaa"  # baseline, no report
    r2 = dc.run(cat, state, force_all=True, only={sid})
    assert r2["changed"] == []
    r3 = dc.run(cat, state, force_all=True, only={sid})
    assert r3["changed"][0]["previous_detail"] == "d1" and r3["changed"][0]["new_detail"] == "d2"


def test_detect_errors_need_two_strikes(cat, monkeypatch):
    sid = "noaa-nclimgrid-daily"

    def boom(cd):
        raise SourceError("down", kind="network")
    monkeypatch.setattr(dc, "fingerprint", boom)
    state = {}
    r1 = dc.run(cat, state, force_all=True, only={sid})
    assert r1["unreachable"] == [] and len(r1["errors_below_threshold"]) == 1
    r2 = dc.run(cat, state, force_all=True, only={sid})
    assert r2["unreachable"][0]["consecutive_errors"] == 2


def test_not_due(cat):
    sid = "noaa-nclimgrid-daily"
    e = cat.get(sid)
    t = dc.now()
    assert not dc.is_due(e, {"last_checked": t.isoformat()}, t)
    assert dc.is_due(e, {"last_checked": (t - dt.timedelta(days=8)).isoformat()}, t)


def _contract_report(failing: list[str], passing: list[str] = ()):
    res = []
    for s in failing:
        res.append({"source_id": s, "status": "healthy", "status_since": "2026-01-01", "passed": False,
                    "cases": [{"case": "c1", "passed": False, "kind": "schema", "message": "missing columns ['x']", "seconds": 1, "rows": 0}]})
    for s in passing:
        res.append({"source_id": s, "status": "healthy", "status_since": "2026-01-01", "passed": True, "cases": []})
    return {"results": res, "quarantine_overdue": []}


def test_issue_create_then_dedup(cat):
    sid = "census-acs-summary-file"
    gh = fi.DryRun()
    fi.plan_and_file(gh, cat, {"changed": [], "unreachable": [], "checked": []}, _contract_report([sid]))
    assert len(gh.actions) == 1 and gh.actions[0]["action"] == "create"
    created = gh.actions[0]
    assert created["title"].startswith(f"[{sid}]") and created["labels"] == ["needs-repair"]
    assert "odc contract" in created["body"] and "missing columns" in created["body"]

    # Second run with the same failure and an existing open issue -> no new action.
    existing = {"needs-repair": [{"number": 7, "title": created["title"], "body": created["body"]}]}
    gh2 = fi.DryRun(existing)
    fi.plan_and_file(gh2, cat, {"changed": []}, _contract_report([sid]))
    assert gh2.actions == []

    # Different failure -> comment on the existing issue, not a new issue.
    rep = _contract_report([sid])
    rep["results"][0]["cases"][0]["message"] = "HTTP 404"
    gh3 = fi.DryRun(existing)
    fi.plan_and_file(gh3, cat, {"changed": []}, rep)
    assert [a["action"] for a in gh3.actions] == ["comment"] and gh3.actions[0]["number"] == 7


def test_source_changed_issue(cat):
    gh = fi.DryRun()
    ch = {"changed": [{"source_id": "noaa-nclimgrid-daily", "method": "http_headers", "url": "https://x", "previous_detail": "etag=1",
                       "new_detail": "etag=2", "new_fingerprint": "f2", "previous_fingerprint": "f1", "previous_checked": "t"}]}
    fi.plan_and_file(gh, cat, ch, {"results": []})
    a = gh.actions[0]
    assert a["labels"] == ["source-changed"] and "Re-check the license" in a["body"] and "etag=2" in a["body"]


def test_systemic_escalation(cat):
    failing = [f"src-{i}" for i in range(5)]
    gh = fi.DryRun()
    fi.plan_and_file(gh, cat, {"checked": failing + ["ok-1"]}, _contract_report(failing, ["ok-1"]))
    assert len(gh.actions) == 1 and gh.actions[0]["labels"] == ["needs-human"]


def test_quarantine_backoff():
    assert [d for d in range(0, 35) if rc.quarantine_retry_due(d)] == [1, 2, 4, 8, 16, 30, 31, 32, 33, 34]
