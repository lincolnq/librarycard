#!/usr/bin/env python3
"""Print space-separated source ids touched by the diff against BASE (default origin/main).

A source counts as touched if its catalog file or its adapter module changed.
Shared code (src/odc/http.py, adapters/_common.py, adapters/base.py) changing
selects every source with an adapter.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from odc.catalog import Catalog  # noqa: E402

base = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
files = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"], capture_output=True, text=True, check=True).stdout.split()
cat = Catalog.load(validate=False)
shared = {"src/odc/http.py", "src/odc/adapters/_common.py", "src/odc/adapters/base.py", "src/odc/adapters/__init__.py"}
ids = set()
for f in files:
    if f in shared:
        ids |= {sid for sid, e in cat.entries.items() if e.get("adapter") and e["status"] != "retired"}
    elif f.startswith("catalog/") and f.endswith(".yaml") and Path(f).stem in cat.entries:
        ids.add(Path(f).stem)
    elif f.startswith("src/odc/adapters/") and f.endswith(".py"):
        mod = Path(f).stem
        ids |= {sid for sid, e in cat.entries.items() if e.get("adapter") == mod}
ids = {i for i in ids if cat.entries[i].get("adapter") and cat.entries[i]["status"] != "retired"}
print(" ".join(sorted(ids)))
