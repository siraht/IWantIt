"""Canonical metadata model with provenance tracking."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


SOURCE_PRIORITY = {
    "input": 3,
    "url": 2,
    "web_search": 2,
    "provider": 1,
    "fallback": 0,
}


SCHEMA = {
    "music": ["artist", "title", "year", "label"],
    "movie": ["title", "year"],
    "tv": ["title", "year"],
    "book": ["title", "author", "year"],
}


def _canonical(data: dict[str, Any]) -> dict[str, Any]:
    canonical = data.setdefault("canonical", {})
    canonical.setdefault("fields", {})
    canonical.setdefault("provenance", {})
    return canonical


def _priority(source: str) -> int:
    return SOURCE_PRIORITY.get(source, 0)


def set_field(
    data: dict[str, Any],
    field: str,
    value: Any,
    *,
    source: str,
    confidence: float | None = None,
) -> None:
    if value is None or value == "":
        return
    canonical = _canonical(data)
    fields = canonical["fields"]
    provenance = canonical["provenance"]
    existing = fields.get(field)
    existing_prov = provenance.get(field, {})
    existing_source = existing_prov.get("source", "fallback")
    if existing is None or _priority(source) >= _priority(existing_source):
        fields[field] = value
        provenance[field] = {
            "source": source,
            "confidence": confidence,
            "ts": datetime.now(timezone.utc).isoformat(),
            "sources": sorted(
                set((existing_prov.get("sources") or []) + [source])
            ),
        }


def merge_from_work(data: dict[str, Any], source: str) -> None:
    work = data.get("work", {}) or {}
    for key in ("artist", "title", "year", "label", "author"):
        if key in work:
            set_field(data, key, work.get(key), source=source)


def canonical_schema(media_type: str | None) -> list[str]:
    return SCHEMA.get(media_type or "", [])
