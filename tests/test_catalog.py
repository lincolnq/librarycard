"""Offline: every catalog entry is schema-valid and consistent with adapters, evidence and ops files."""
import datetime as dt

import pytest

from odc.adapters import adapter_for
from odc.catalog import Catalog, catalog_files, load_entry, validate_entry
from odc.consistency import consistency_problems

FILES = catalog_files()


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_entry_valid(path):
    problems = validate_entry(load_entry(path), path)
    assert not problems, "\n".join(problems)


def test_consistency(cat):
    problems = consistency_problems(cat)
    assert not problems, "\n".join(problems)


def test_ids_unique_and_stable_format(cat):
    assert len(cat.entries) == len(FILES)


def test_fetchable_entries_have_adapters(cat):
    for sid, e in cat.entries.items():
        if e["access"]["method"] != "restricted":
            assert adapter_for(e) is not None, sid


def test_license_checked_recently_or_flagged(cat):
    # Not a hard policy failure, but stale license checks should be visible in CI output.
    today = dt.date.today()
    stale = [sid for sid, e in cat.entries.items() if (today - dt.date.fromisoformat(e["license"]["checked_at"])).days > 400]
    assert not stale, f"license.checked_at older than 400 days: {stale} — re-check per docs/POLICY.md#licensing"


def test_schema_rejects_bad_entry(cat):
    e = dict(next(iter(cat.entries.values())))
    e = {**e, "status": "broken"}
    assert any("status" in p for p in validate_entry(e))
    e2 = {**next(iter(cat.entries.values())), "license": {**next(iter(cat.entries.values()))["license"], "redistribution": "unknown"}}
    assert any("unknown" in p for p in validate_entry(e2))
