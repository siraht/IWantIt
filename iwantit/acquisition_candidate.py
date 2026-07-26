"""Stable, credential-free references for acquisition choices."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_SECRET_QUERY_KEYS = {
    "api-key",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "cookie",
    "key",
    "link",
    "password",
    "secret",
    "sig",
    "signature",
    "token",
}


def _first(*values: Any) -> Any:
    return next((item for item in values if item not in (None, "", [], {})), None)


def _integer(*values: Any) -> int | None:
    raw_value = _first(*values)
    try:
        return int(raw_value) if raw_value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        return None
    try:
        parsed = urlparse(value)
        parameters = parse_qsl(parsed.query, keep_blank_values=True)
        safe = [
            (key, item)
            for key, item in parameters
            if key.lower() not in _SECRET_QUERY_KEYS
        ]
        return urlunparse(parsed._replace(query=urlencode(safe), fragment=""))
    except ValueError:
        return None


def candidate_reference(value: Any) -> str:
    """Hash stable choice coordinates without provider credentials or private handles."""

    candidate = value if isinstance(value, dict) else {"title": str(value)}
    raw = candidate.get("_raw") if isinstance(candidate.get("_raw"), dict) else {}
    redacted = (
        candidate.get("redacted") if isinstance(candidate.get("redacted"), dict) else {}
    )
    group = redacted.get("group") if isinstance(redacted.get("group"), dict) else {}
    torrent = (
        redacted.get("torrent") if isinstance(redacted.get("torrent"), dict) else {}
    )
    music_info = group.get("musicInfo") if isinstance(group.get("musicInfo"), dict) else {}
    artist_values = music_info.get("artists") if isinstance(music_info, dict) else []
    artists = (
        [
            str(item.get("name"))
            for item in artist_values
            if isinstance(item, dict) and item.get("name")
        ]
        if isinstance(artist_values, list)
        else []
    )
    source_url = _first(
        candidate.get("info_url"),
        candidate.get("infoUrl"),
        candidate.get("guid"),
        raw.get("infoUrl"),
        raw.get("guid"),
    )
    material = {
        "title": str(
            _first(candidate.get("title"), candidate.get("name"), group.get("name"), "Candidate")
        ),
        "source": str(
            _first(
                candidate.get("indexer"),
                candidate.get("provider"),
                candidate.get("source"),
                raw.get("indexer"),
                "unknown",
            )
        ),
        "source_url": _safe_url(source_url),
        "release": {
            "title": str(
                _first(
                    group.get("name"),
                    candidate.get("title"),
                    candidate.get("name"),
                    "Candidate",
                )
            ),
            "artists": artists,
            "year": _integer(group.get("year"), candidate.get("year")),
            "label": _first(
                group.get("recordLabel"),
                torrent.get("remasterRecordLabel"),
            ),
            "catalog_number": _first(
                group.get("catalogueNumber"),
                torrent.get("remasterCatalogueNumber"),
            ),
        },
        "edition": {
            "format": _first(
                torrent.get("format"),
                candidate.get("format"),
                raw.get("format"),
            ),
            "encoding": _first(torrent.get("encoding"), candidate.get("encoding")),
            "media": _first(torrent.get("media"), candidate.get("media")),
            "remaster_year": _integer(torrent.get("remasterYear")),
            "remaster_title": _first(torrent.get("remasterTitle")),
            "file_count": _integer(
                torrent.get("fileCount"),
                candidate.get("file_count"),
            ),
            "size_bytes": _integer(
                torrent.get("size"),
                candidate.get("size"),
                raw.get("size"),
            ),
        },
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
