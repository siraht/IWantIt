"""Step metadata for built-in workflow steps."""

from __future__ import annotations

from typing import Any


STEP_METADATA: dict[str, dict[str, Any]] = {
    "ocr": {
        "side_effect": False,
        "requires": ["request.image_path"],
        "emits": ["ocr.text", "request.query"],
        "description": "Extract text from image input via OCR.",
    },
    "fetch_url": {
        "side_effect": False,
        "requires": ["request.input_type", "request.url|request.input"],
        "emits": ["url", "request.query"],
        "description": "Fetch URL metadata (title/description).",
    },
    "identify": {
        "side_effect": False,
        "requires": ["request"],
        "emits": ["work.title", "work.media_type"],
        "description": "Initialize work from request.",
    },
    "identify_web_search": {
        "side_effect": False,
        "requires": ["request.query|request.input"],
        "emits": ["search", "work.title", "work.artist", "work.year"],
        "description": "Refine query and infer artist/title/year via web search.",
    },
    "extract_release_preferences": {
        "side_effect": False,
        "requires": ["request.query|request.input"],
        "emits": ["request.release_preferences", "request.explicit_version"],
        "description": "Extract explicit format/edition preferences from query.",
    },
    "determine_media_type": {
        "side_effect": False,
        "requires": ["request.query|search"],
        "emits": ["request.media_type", "work.media_type"],
        "description": "Detect media type from query or search results.",
    },
    "resolve_track_release": {
        "side_effect": False,
        "requires": ["request.query", "work.media_type"],
        "emits": ["request.query", "work.album_title"],
        "description": "Resolve track query to likely album release.",
    },
    "prowlarr_search": {
        "side_effect": False,
        "requires": ["request.query", "work.media_type"],
        "emits": ["search.prowlarr", "work.candidates"],
        "description": "Search Prowlarr for candidates.",
    },
    "filter_candidates": {
        "side_effect": False,
        "requires": ["work.candidates"],
        "emits": ["work.candidates"],
        "description": "Filter candidates by category.",
    },
    "filter_match": {
        "side_effect": False,
        "requires": ["work.candidates", "request.query"],
        "emits": ["work.candidates"],
        "description": "Filter candidates by query match.",
    },
    "dedupe_candidates": {
        "side_effect": False,
        "requires": ["work.candidates"],
        "emits": ["work.candidates"],
        "description": "Merge duplicate candidates while preserving provenance.",
    },
    "redacted_enrich": {
        "side_effect": False,
        "requires": ["work.candidates"],
        "emits": ["work.candidates", "redacted.groups"],
        "description": "Enrich candidates with Redacted metadata.",
    },
    "redacted_comments": {
        "side_effect": False,
        "requires": ["redacted.groups"],
        "emits": ["redacted.comments|_internal.redacted_comments"],
        "description": "Fetch Redacted comments.",
    },
    "apply_recommendations": {
        "side_effect": False,
        "requires": ["work.candidates", "redacted.comments"],
        "emits": ["work.candidates"],
        "description": "Boost candidate ranks based on comments.",
    },
    "filter_by_version": {
        "side_effect": False,
        "requires": ["work.candidates", "request.release_preferences"],
        "emits": ["work.candidates"],
        "description": "Filter candidates by explicit version preference.",
    },
    "book_decide": {
        "side_effect": False,
        "requires": ["work.candidates"],
        "emits": ["work.candidates"],
        "description": "Filter book candidates by format preference.",
    },
    "rank_releases": {
        "side_effect": False,
        "requires": ["work.candidates"],
        "emits": ["work.candidates.rank"],
        "description": "Rank candidates by quality rules.",
    },
    "decide": {
        "side_effect": False,
        "requires": ["work.candidates"],
        "emits": ["decision", "work.selected"],
        "description": "Select best candidate or require user choice.",
    },
    "prowlarr_grab": {
        "side_effect": True,
        "requires": ["work.selected", "prowlarr"],
        "emits": ["dispatch.prowlarr"],
        "dispatch_key": "prowlarr",
        "description": "Send selected release to Prowlarr.",
    },
    "http_dispatch": {
        "side_effect": True,
        "requires": ["request", "work.selected|work"],
        "emits": ["dispatch.*"],
        "dispatch_key_from_cfg": "_step",
        "description": "Dispatch to arbitrary HTTP endpoint.",
    },
    "arr_dispatch": {
        "side_effect": True,
        "requires": ["work.selected|work"],
        "emits": ["dispatch.*"],
        "dispatch_key_from_cfg": "arr",
        "description": "Dispatch to Radarr/Sonarr.",
    },
    "store_tags": {
        "side_effect": False,
        "requires": ["request.tags"],
        "emits": ["tags.stored"],
        "dispatch_key": "tags",
        "description": "Store tag artifacts locally.",
    },
}


def get_step_metadata(step_name: str) -> dict[str, Any]:
    return STEP_METADATA.get(step_name, {})
