import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("mmr", Path(__file__).parent.parent / "scripts/merge_mirror_reports.py")
mmr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mmr)


def test_missing_report_becomes_failure():
    plan = {"due": ["a", "b"], "skipped": [{"source_id": "c", "reason": "fresh"}], "failed": []}
    out = mmr.merge(plan, [{"published": [{"source_id": "a"}], "skipped": [], "failed": []}])
    assert [p["source_id"] for p in out["published"]] == ["a"]
    assert [f["source_id"] for f in out["failed"]] == ["b"] and out["failed"][0]["kind"] == "timeout"
    assert out["skipped"] == plan["skipped"]
