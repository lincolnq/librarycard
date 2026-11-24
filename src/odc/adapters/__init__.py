"""Adapter registry. Adapters are looked up by the catalog entry's ``adapter`` field."""

from __future__ import annotations

import importlib
from functools import lru_cache

from .base import SourceAdapter


@lru_cache(maxsize=None)
def get_adapter(module: str) -> SourceAdapter:
    mod = importlib.import_module(f"odc.adapters.{module}")
    adapter = getattr(mod, "ADAPTER", None)
    if not isinstance(adapter, SourceAdapter):
        raise TypeError(f"odc.adapters.{module} must define ADAPTER = <SourceAdapter instance>")
    return adapter


def adapter_for(entry: dict) -> SourceAdapter | None:
    if not entry.get("adapter"):
        return None
    return get_adapter(entry["adapter"])
