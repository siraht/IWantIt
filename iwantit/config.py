"""Config loading and defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .paths import config_path, ensure_dir, secrets_path
from .util import deep_merge, resolve_env_values


def default_config() -> dict[str, Any]:
    return {
        "pre_steps": [
            "ocr",
            "fetch_url",
            "identify",
            "identify_web_search",
            "extract_release_preferences",
            "determine_media_type",
            "resolve_track_release",
        ],
        "default_workflow": "music",
        "workflows": [
            {
                "name": "music",
                "match": {"media_type": "music"},
                "steps": [
                    "prowlarr_search",
                    "filter_candidates",
                    "filter_match",
                    "redacted_enrich",
                    "filter_by_version",
                    "rank_releases",
                    "decide",
                    "prowlarr_grab",
                    "store_tags",
                ],
            },
            {
                "name": "movie",
                "match": {"media_type": "movie"},
                "steps": ["dispatch_radarr"],
            },
            {
                "name": "tv",
                "match": {"media_type": "tv"},
                "steps": ["dispatch_sonarr"],
            },
            {
                "name": "book",
                "match": {"media_type": "book"},
                "steps": [
                    "prowlarr_search",
                    "filter_candidates",
                    "filter_match",
                    "book_decide",
                    "rank_releases",
                    "decide",
                    "prowlarr_grab",
                ],
            },
        ],
        "steps": {
            "ocr": {"builtin": "ocr"},
            "fetch_url": {
                "builtin": "fetch_url",
                "timeout": 15,
                "retries": 1,
                "retry_backoff_seconds": 0.5,
                "headers": {
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            },
            "identify": {"builtin": "identify"},
            "resolve_track_release": {
                "builtin": "resolve_track_release",
                "release_priority": ["Album", "EP", "Single", "Live album"],
                "timeout": 20,
                "retries": 1,
                "retry_backoff_seconds": 0.5,
            },
            "identify_web_search": {
                "builtin": "identify_web_search",
                "provider": "kagi",
                "result_limit": 10,
                "update_query": True,
                "consensus_override": True,
                "min_match_ratio": 0.4,
                "min_token_matches": 2,
                "min_confirmations": 2,
                "single_match_ratio": 0.75,
                "cache": {"enabled": True, "ttl_seconds": 3600},
                "timeout": 15,
                "retries": 2,
                "retry_backoff_seconds": 0.5,
                "query_fields": {
                    "music": ["work.artist", "work.title", "work.year", "request.query"],
                    "movie": ["work.title", "work.year", "request.query"],
                    "tv": ["work.title", "work.year", "request.query"],
                    "book": ["work.title", "work.author", "work.year", "request.query"],
                    "default": ["request.query"],
                },
            },
            "determine_media_type": {
                "builtin": "determine_media_type",
                "provider": "kagi",
                "result_limit": 10,
                "min_score": 2,
                "fallback": True,
            },
            "identify_music": {"command": ["python3", "-m", "iwantit.steps.music_tracker_identify"]},
            "decide": {
                "builtin": "decide",
                "auto_select_formats": True,
                "auto_select_explicit": True,
            },
            "prowlarr_search": {
                "builtin": "prowlarr_search",
                "result_limit": 50,
                "normalize_query": True,
                "cache": {"enabled": True, "ttl_seconds": 1800},
                "timeout": 20,
                "retries": 2,
                "retry_backoff_seconds": 0.5,
            },
            "filter_candidates": {
                "builtin": "filter_candidates",
                "allow_missing_categories": False,
                "category_prefixes": {
                    "music": [30],
                },
            },
            "filter_match": {
                "builtin": "filter_match",
                "min_match_ratio": 0.4,
                "min_token_matches": 2,
                "keep_original_on_empty": False,
            },
            "extract_release_preferences": {
                "builtin": "extract_release_preferences",
                "edition_keywords": {
                    "deluxe": ["deluxe", "special edition"],
                    "anniversary": ["anniversary", "anniv"],
                    "studio": ["studio"],
                    "live": ["live", "concert"],
                    "bootleg": ["bootleg"],
                },
                "media_keywords": {
                    "cd": ["cd"],
                    "vinyl": ["vinyl", "lp"],
                    "web": ["web", "digital"],
                    "sacd": ["sacd"],
                    "blu-ray": ["blu-ray", "bluray"],
                },
                "format_keywords": {
                    "flac": ["flac", "lossless"],
                    "v0": ["v0"],
                    "320": ["320", "320kbps", "320k"],
                    "audiobook": ["audiobook", "audio book", "audible", "m4b", "aax"],
                    "ebook": ["ebook", "e-book", "epub", "mobi", "azw", "azw3", "pdf", "kindle"],
                },
            },
            "redacted_enrich": {
                "builtin": "redacted_enrich",
                "enabled_media": ["music"],
                "cache": {"enabled": True, "ttl_seconds": 86400},
                "timeout": 20,
                "retries": 1,
                "retry_backoff_seconds": 0.5,
            },
            "redacted_comments": {
                "builtin": "redacted_comments",
                "enabled_media": ["music"],
                "max_pages": 3,
                "cache": {"enabled": True, "ttl_seconds": 86400},
                "timeout": 20,
                "retries": 1,
                "retry_backoff_seconds": 0.5,
            },
            "apply_recommendations": {
                "builtin": "apply_recommendations",
                "weight": 500,
                "catalog_weight": 1.0,
                "label_weight": 0.7,
                "title_weight": 0.5,
                "media_weight": 0.4,
                "year_weight": 0.3,
            },
            "filter_by_version": {"builtin": "filter_by_version"},
            "book_decide": {"builtin": "book_decide"},
            "rank_releases": {"builtin": "rank_releases"},
            "prowlarr_grab": {
                "builtin": "prowlarr_grab",
                "timeout": 20,
                "retries": 1,
                "retry_backoff_seconds": 0.5,
                "side_effect": True,
            },
            "dispatch_music": {
                "builtin": "http_dispatch",
                "request": {
                    "url": "https://music.example/api/torrents",
                    "method": "POST",
                    "headers": {"Authorization": "Bearer {config.music_tracker.api_key}"},
                    "json": {
                        "release": "{work.title}",
                        "tags": "{request.tags}",
                    },
                },
            },
            "dispatch_radarr": {"builtin": "arr_dispatch", "arr": "radarr"},
            "dispatch_sonarr": {"builtin": "arr_dispatch", "arr": "sonarr"},
            "store_tags": {"builtin": "store_tags"},
        },
        "music_tracker": {
            "url": "https://tracker.example",
            "api_key": "CHANGE_ME",
            "search": {
                "method": "GET",
                "path": "/api/search",
                "headers": {"Authorization": "Bearer {config.music_tracker.api_key}"},
                "params": {"q": "{request.query}"},
            },
            "response_path": "results",
            "candidate_fields": {"id": "id", "title": "title"},
            "include_raw": True,
        },
        "prowlarr": {
            "url": "http://localhost:9696",
            "api_key": "CHANGE_ME",
            "timeout": 30,
            "download_clients": {
                "music": None,
                "book": None,
            },
            "download_client_rules": [
                {"client_id": 1, "categories": [3010, 3040, 3050, 3060]},
                {"client_id": 2, "categories": [3020], "category_prefixes": [2]},
                {"client_id": 3, "category_prefixes": [5]},
                {"client_id": 4, "categories": [3030], "category_prefixes": [7]},
            ],
            "search": {
                "indexer_ids": {
                    "music": [],
                    "book": [],
                },
                "categories": {
                    "music": [3000, 3010, 3040],
                    "book": [7000],
                },
                "request": {
                    "url": "{config.prowlarr.url}/api/v1/search",
                    "method": "GET",
                    "headers": {"X-Api-Key": "{config.prowlarr.api_key}"},
                    "params": {
                        "query": "{request.query}",
                        "type": "{request.media_type}",
                    },
                },
                "response": {
                    "results_path": None,
                    "fallback_keys": ["results", "items", "data", "releases"],
                    "fields": {
                        "title": "title",
                        "sort_title": "sortTitle",
                        "size": "size",
                        "files": "files",
                        "seeders": "seeders",
                        "leechers": "leechers",
                        "grabs": "grabs",
                        "age": "age",
                        "age_hours": "ageHours",
                        "age_minutes": "ageMinutes",
                        "indexer_id": "indexerId",
                        "indexer": "indexer",
                        "indexer_flags": "indexerFlags",
                        "guid": "guid",
                        "protocol": "protocol",
                        "download_url": "downloadUrl",
                        "info_url": "infoUrl",
                        "publish_date": "publishDate",
                        "file_name": "fileName",
                        "categories": "categories",
                    },
                    "include_raw": True,
                },
            },
            "grab": {
                "request": {
                    "url": "{config.prowlarr.url}/api/v1/search",
                    "method": "POST",
                    "headers": {"X-Api-Key": "{config.prowlarr.api_key}"},
                    "json": {
                        "guid": "{work.selected.guid}",
                        "indexerId": "{work.selected.indexer_id}",
                        "downloadClientId": "{work.download_client_id}",
                    },
                }
            },
        },
        "book": {
            "default_format": "both",
        },
        "quality_rules": {
            "music": {
                "title_fields": ["title", "name", "_raw.title", "_raw.name"],
                "release_priority": ["deluxe", "studio", "anniversary", "live", "bootleg"],
                "release_priority_weight": 60,
                "reject": [
                    r"(?i)\b24[- ]?bit\b",
                    r"(?i)\b24/\d{2,3}\b",
                    r"(?i)\bhi[- ]?res\b",
                    r"(?i)\b5\.1\b",
                    r"(?i)\bsurround\b",
                ],
                "score": [
                    {"match": r"(?i)\bflac\b", "score": 120, "label": "FLAC"},
                    {"match": r"(?i)\balac\b", "score": 110, "label": "ALAC"},
                    {"match": r"(?i)\bwav\b", "score": 100, "label": "WAV"},
                    {"match": r"(?i)\bmp3\b", "score": 15, "label": "MP3"},
                    {"match": r"(?i)\b320\s*kbps\b", "score": 30, "label": "320kbps"},
                    {"match": r"(?i)\b256\s*kbps\b", "score": 20, "label": "256kbps"},
                    {"match": r"(?i)\b192\s*kbps\b", "score": 10, "label": "192kbps"},
                    {"match": r"(?i)\bV0\b", "score": 25, "label": "V0"},
                    {"match": r"(?i)\bV2\b", "score": 10, "label": "V2"},
                    {"match": r"(?i)\bweb\b", "score": 60, "label": "WEB"},
                    {"match": r"(?i)\bcd\b", "score": 40, "label": "CD"},
                    {"match": r"(?i)\bsacd\b", "score": 5, "label": "SACD"},
                    {"match": r"(?i)\bvinyl\b", "score": -10, "label": "VINYL"},
                ],
                "numeric_fields": [
                    {"path": "seeders", "weight": 0.3, "label": "seeders"},
                    {"path": "size", "weight": 2.0, "scale": 1000000000, "label": "size_gb"},
                    {"path": "derived.bitrate_kbps", "weight": 0.05, "label": "bitrate"},
                ],
            },
            "book": {
                "title_fields": ["title", "name", "_raw.title", "_raw.name"],
                "format_rules": {
                    "audiobook": {
                        "score": [
                            {"match": r"(?i)audiobook|audio", "score": 50, "label": "audio"},
                        ],
                        "reject": [
                            r"(?i)\b(epub|mobi|azw3|pdf)\b",
                        ],
                    },
                    "ebook": {
                        "score": [
                            {"match": r"(?i)\b(epub|mobi|azw3|pdf)\b", "score": 50, "label": "ebook"},
                        ],
                        "reject": [
                            r"(?i)audiobook|audio",
                        ],
                    },
                },
            },
        },
        "web_search": {
            "provider": "kagi",
            "providers": {
                "brave": {
                    "api_key": "CHANGE_ME",
                    "api_version": "2023-01-01",
                    "request": {
                        "url": "https://api.search.brave.com/res/v1/web/search",
                        "method": "GET",
                        "headers": {
                            "Accept": "application/json",
                            "Accept-Encoding": "gzip",
                            "Api-Version": "{config.web_search.providers.brave.api_version}",
                            "X-Subscription-Token": "{config.web_search.providers.brave.api_key}",
                        },
                        "params": {
                            "q": "{request.query}",
                            "count": 5,
                        },
                    },
                    "response": {
                        "results_path": "web.results",
                        "fields": {
                            "title": "title",
                            "url": "url",
                            "snippet": "description",
                        },
                        "include_raw": False,
                    },
                },
                "kagi": {
                    "api_key": "${ENV:KAGI_SEARCH_API_KEY}",
                    "request": {
                        "url": "https://kagi.com/api/v0/search",
                        "method": "GET",
                        "headers": {
                            "Authorization": "Bot {config.web_search.providers.kagi.api_key}",
                        },
                        "params": {
                            "q": "{request.query}",
                            "limit": 5,
                        },
                    },
                    "response": {
                        "results_path": "data",
                        "fallback_keys": ["data", "results"],
                        "filter": {"field": "t", "equals": 0},
                        "fields": {
                            "title": "title",
                            "url": "url",
                            "snippet": "snippet",
                        },
                        "include_raw": False,
                    },
                },
            },
        },
        "redacted": {
            "url": "https://redacted.sh",
            "api_key": "CHANGE_ME",
            "timeout": 20,
            "release_type_map": {
                1: "Album",
                3: "Soundtrack",
                5: "EP",
                6: "Anthology",
                7: "Compilation",
                9: "Single",
                11: "Live album",
                13: "Remix",
                14: "Bootleg",
                15: "Interview",
                16: "Mixtape",
                17: "Demo",
                18: "Concert Recording",
                19: "DJ Mix",
                21: "Unknown",
            },
        },
        "media_type_detection": {
            "keywords": {
                "music": ["album", "single", "ep", "track", "song", "artist", "lyrics", "discography"],
                "movie": ["movie", "film", "trailer", "cast", "director", "runtime"],
                "tv": ["tv", "series", "season", "episode", "show", "s01", "e01"],
                "book": ["book", "novel", "author", "isbn", "paperback", "kindle", "audiobook"],
            }
        },
        "arr": {
            "radarr": {
                "url": "http://localhost:7878",
                "api_key": "CHANGE_ME",
                "root_folder": "/media/movies",
                "quality_profile_id": 1,
                "endpoint": "/api/v3/movie",
            },
            "sonarr": {
                "url": "http://localhost:8989",
                "api_key": "CHANGE_ME",
                "root_folder": "/media/tv",
                "quality_profile_id": 1,
                "endpoint": "/api/v3/series",
            },
        },
        "timeouts": {},
        "retries": {"retries": 1, "retry_backoff_seconds": 0.5, "max_backoff_seconds": 4.0},
    }


def load_config(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or config_path()
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config not found at {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    secrets = {}
    secrets_file = secrets_path()
    if secrets_file.exists():
        with secrets_file.open("r", encoding="utf-8") as handle:
            secrets = yaml.safe_load(handle) or {}
    merged = deep_merge(config, secrets)
    return resolve_env_values(merged)


def save_default_config(path: Path | None = None, overwrite: bool = False) -> Path:
    cfg_path = path or config_path()
    ensure_dir(cfg_path.parent)
    if cfg_path.exists() and not overwrite:
        return cfg_path
    with cfg_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(default_config(), handle, sort_keys=False)
    return cfg_path


def save_default_secrets(path: Path | None = None, overwrite: bool = False) -> Path:
    cfg_path = path or secrets_path()
    ensure_dir(cfg_path.parent)
    if cfg_path.exists() and not overwrite:
        return cfg_path
    with cfg_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump({}, handle, sort_keys=False)
    return cfg_path


def resolve_config_path(path_str: str | None) -> Path:
    if path_str:
        return Path(path_str).expanduser()
    return config_path()


def ensure_config_exists(path_str: str | None = None) -> Path:
    cfg_path = resolve_config_path(path_str)
    if not cfg_path.exists():
        cfg_path = save_default_config(cfg_path, overwrite=False)
    return cfg_path


def validate_config(config: dict[str, Any], builtins: list[str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    steps = config.get("steps", {}) or {}
    for name, step in steps.items():
        builtin = step.get("builtin")
        if builtin and builtin not in builtins:
            errors.append(f"unknown builtin step: {name} -> {builtin}")

    for wf in config.get("workflows", []) or []:
        for step_name in wf.get("steps", []) or []:
            if step_name not in steps:
                warnings.append(f"workflow {wf.get('name')} references undefined step {step_name}")

    for step_name in config.get("pre_steps", []) or []:
        if step_name not in steps:
            warnings.append(f"pre_steps references undefined step {step_name}")

    prowl = config.get("prowlarr", {}) or {}
    if any(step.get("builtin") == "prowlarr_search" for step in steps.values()):
        if not prowl.get("url"):
            errors.append("prowlarr.url is required")
        if not prowl.get("api_key"):
            errors.append("prowlarr.api_key is required")

    web = config.get("web_search", {}) or {}
    provider = web.get("provider")
    if provider:
        providers = web.get("providers", {}) or {}
        if provider not in providers:
            errors.append(f"web_search provider not found: {provider}")
        else:
            api_key = providers.get(provider, {}).get("api_key")
            if not api_key or api_key == "CHANGE_ME":
                warnings.append(f"web_search.providers.{provider}.api_key is not set")

    redacted = config.get("redacted", {}) or {}
    if any(step.get("builtin") in {"redacted_enrich", "redacted_comments"} for step in steps.values()):
        if not redacted.get("url"):
            errors.append("redacted.url is required")
        if not redacted.get("api_key") or redacted.get("api_key") == "CHANGE_ME":
            warnings.append("redacted.api_key is not set")

    return errors, warnings
