"""Provider registry and validation helpers."""

from __future__ import annotations

from typing import Any


def builtin_provider_registry() -> dict[str, dict[str, Any]]:
    return {
        "web_search.kagi": {
            "type": "web_search",
            "name": "kagi",
            "media_types": ["music", "movie", "tv", "book"],
            "auth": {"scheme": "api_key", "key_path": "web_search.providers.kagi.api_key"},
            "required_keys": ["web_search.providers.kagi.api_key"],
            "optional_keys": ["web_search.providers.kagi.request"],
            "rate_limit": {"requests_per_minute": 60},
            "capabilities": {"web_search": True, "metadata": True},
        },
        "web_search.brave": {
            "type": "web_search",
            "name": "brave",
            "media_types": ["music", "movie", "tv", "book"],
            "auth": {"scheme": "api_key", "key_path": "web_search.providers.brave.api_key"},
            "required_keys": ["web_search.providers.brave.api_key"],
            "optional_keys": ["web_search.providers.brave.request"],
            "rate_limit": {"requests_per_minute": 60},
            "capabilities": {"web_search": True, "metadata": True},
        },
        "prowlarr": {
            "type": "indexer",
            "name": "prowlarr",
            "media_types": ["music", "book"],
            "auth": {"scheme": "api_key", "key_path": "prowlarr.api_key"},
            "required_keys": ["prowlarr.url", "prowlarr.api_key"],
            "optional_keys": ["prowlarr.search", "prowlarr.grab"],
            "rate_limit": {"requests_per_minute": 120},
            "capabilities": {"search": True, "grab": True},
        },
        "redacted": {
            "type": "tracker",
            "name": "redacted",
            "media_types": ["music"],
            "auth": {"scheme": "api_key", "key_path": "redacted.api_key"},
            "required_keys": ["redacted.url", "redacted.api_key"],
            "optional_keys": ["redacted.session_cookie"],
            "rate_limit": {"requests_per_minute": 60},
            "capabilities": {"metadata": True, "comments": True},
        },
        "radarr": {
            "type": "arr",
            "name": "radarr",
            "media_types": ["movie"],
            "auth": {"scheme": "api_key", "key_path": "arr.radarr.api_key"},
            "required_keys": ["arr.radarr.url", "arr.radarr.api_key", "arr.radarr.endpoint"],
            "optional_keys": ["arr.radarr.root_folder", "arr.radarr.quality_profile_id"],
            "capabilities": {"dispatch": True},
        },
        "sonarr": {
            "type": "arr",
            "name": "sonarr",
            "media_types": ["tv"],
            "auth": {"scheme": "api_key", "key_path": "arr.sonarr.api_key"},
            "required_keys": ["arr.sonarr.url", "arr.sonarr.api_key", "arr.sonarr.endpoint"],
            "optional_keys": ["arr.sonarr.root_folder", "arr.sonarr.quality_profile_id"],
            "capabilities": {"dispatch": True},
        },
    }


def merge_provider_registry(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    registry = dict(builtin_provider_registry())
    custom = config.get("provider_registry")
    if isinstance(custom, dict):
        for key, value in custom.items():
            if not isinstance(value, dict):
                continue
            merged = dict(registry.get(key, {}))
            merged.update(value)
            registry[key] = merged
    return registry


def iter_active_providers(config: dict[str, Any]) -> list[str]:
    active: list[str] = []
    web_cfg = config.get("web_search", {}) or {}
    provider = web_cfg.get("provider")
    if provider:
        active.append(f"web_search.{provider}")
    providers = web_cfg.get("providers")
    if isinstance(providers, dict):
        for name in providers.keys():
            key = f"web_search.{name}"
            if key not in active:
                active.append(key)
    if config.get("prowlarr"):
        active.append("prowlarr")
    red = config.get("redacted", {}) or {}
    if red:
        active.append("redacted")
    arr = config.get("arr", {}) or {}
    if isinstance(arr, dict):
        if arr.get("radarr"):
            active.append("radarr")
        if arr.get("sonarr"):
            active.append("sonarr")
    return active


def _get_path(obj: dict[str, Any], path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        if value.strip() == "" or value.strip().upper() == "CHANGE_ME":
            return True
    return False


def validate_registry_requirements(config: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    registry = merge_provider_registry(config)
    for provider_key in iter_active_providers(config):
        entry = registry.get(provider_key)
        if not entry:
            warnings.append(f"provider registry missing definition: {provider_key}")
            continue
        required = entry.get("required_keys") or []
        for key_path in required:
            value = _get_path(config, key_path)
            if is_missing_value(value):
                errors.append(f"{provider_key}: missing required config {key_path}")
    return errors, warnings


def provider_required_keys(config: dict[str, Any]) -> dict[str, list[str]]:
    registry = merge_provider_registry(config)
    out: dict[str, list[str]] = {}
    for provider_key in iter_active_providers(config):
        entry = registry.get(provider_key) or {}
        required = entry.get("required_keys") or []
        out[provider_key] = list(required)
    return out


def provider_rate_limit(config: dict[str, Any], provider_key: str) -> int | None:
    overrides = config.get("rate_limits", {}) or {}
    if isinstance(overrides, dict) and provider_key in overrides:
        raw = overrides.get(provider_key)
        if isinstance(raw, dict):
            raw = raw.get("requests_per_minute")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    entry = merge_provider_registry(config).get(provider_key) or {}
    rate = entry.get("rate_limit") or {}
    try:
        return int(rate.get("requests_per_minute"))
    except (TypeError, ValueError):
        return None


def provider_concurrency(config: dict[str, Any], provider_key: str) -> int | None:
    overrides = config.get("concurrency", {}) or {}
    providers = overrides.get("providers") if isinstance(overrides, dict) else None
    if isinstance(providers, dict) and provider_key in providers:
        try:
            return int(providers.get(provider_key))
        except (TypeError, ValueError):
            return None
    return None
