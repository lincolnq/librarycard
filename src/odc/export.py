"""Export the catalog as one JSON document for the TypeScript Worker (worker/).

The Worker bundles this file at deploy time, so catalog changes go live on the next deploy (CI deploys on
merge to main). Live mirror state (releases, partitions, columns) is read from R2 manifests at request time.
"""

from __future__ import annotations

import json
from pathlib import Path

from .adapters import adapter_for
from .catalog import Catalog
from .mirror import mirrorable


def export_catalog(out: Path) -> int:
    cat = Catalog.load()
    entries = []
    for sid, e in sorted(cat.entries.items()):
        a = adapter_for(e)
        entries.append({
            **e,
            "_mirrored": mirrorable(e),
            "_publisher_filters": a.describe_filters() if a else None,
        })
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"format": 1, "entries": entries}, indent=None, separators=(",", ":"), default=str))
    return len(entries)
