"""Utility helpers."""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .paths import cache_dir, ensure_dir


def read_stdin() -> str:
    return sys.stdin.read()


def read_json(data: str) -> Any:
    return json.loads(data)


def write_json(obj: Any) -> None:
    json.dump(obj, sys.stdout, indent=2, ensure_ascii=True, sort_keys=False)
    sys.stdout.write("\n")


def is_stdin_tty() -> bool:
    return sys.stdin.isatty()


def is_stdout_tty() -> bool:
    return sys.stdout.isatty()


def coerce_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    return [t for t in tags if t]


def parse_kv_pairs(pairs: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if not pairs:
        return result
    for pair in pairs:
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            result[key] = value
    return result


def looks_like_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    lower = text.lower()
    if lower.startswith(("http://", "https://")):
        return True
    if lower.startswith("www.") and " " not in lower and "." in lower[4:]:
        return True
    try:
        parsed = urlparse(text)
    except ValueError:
        return False
    if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
        return True
    return False


def normalize_request_input(request: dict[str, Any]) -> None:
    if not isinstance(request, dict):
        return
    input_type = request.get("input_type")
    if input_type == "image":
        return
    candidate = None
    if isinstance(request.get("input"), str):
        candidate = request.get("input")
    elif isinstance(request.get("query"), str):
        candidate = request.get("query")
    elif isinstance(request.get("url"), str):
        candidate = request.get("url")
    if not candidate or not looks_like_url(candidate):
        return
    if input_type in (None, "", "text", "json"):
        request["input_type"] = "url"
    if "input" not in request:
        request["input"] = candidate
    if "url" not in request:
        request["url"] = candidate


def deep_merge(base: Any, overlay: Any) -> Any:
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged = dict(base)
        for key, value in overlay.items():
            if key in merged:
                merged[key] = deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
    return overlay


_ENV_PATTERN = re.compile(r"\$\{ENV:([A-Z0-9_]+)\}")


def resolve_env_values(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value.keys()) == {"_env"}:
            name = str(value.get("_env", ""))
            return os.environ.get(name, "")
        return {k: resolve_env_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_env_values(v) for v in value]
    if isinstance(value, str):
        def _replace(match: re.Match[str]) -> str:
            name = match.group(1)
            return os.environ.get(name, "")

        return _ENV_PATTERN.sub(_replace, value)
    return value


def request_with_retry(
    method: str,
    url: str,
    *,
    retries: int = 0,
    backoff_seconds: float = 0.5,
    max_backoff_seconds: float = 8.0,
    jitter: float = 0.1,
    retry_statuses: list[int] | None = None,
    **kwargs: Any,
) -> requests.Response:
    if retry_statuses is None:
        retry_statuses = [429, 502, 503, 504]
    attempt = 0
    while True:
        try:
            response = requests.request(method, url, **kwargs)
        except requests.RequestException:
            if attempt >= retries:
                raise
            delay = min(max_backoff_seconds, backoff_seconds * (2 ** attempt))
            delay = delay + (random.random() * jitter)
            time.sleep(delay)
            attempt += 1
            continue
        if response.status_code in retry_statuses and attempt < retries:
            delay = min(max_backoff_seconds, backoff_seconds * (2 ** attempt))
            delay = delay + (random.random() * jitter)
            time.sleep(delay)
            attempt += 1
            continue
        return response


def _cache_path(namespace: str, key: str) -> Path:
    base = ensure_dir(cache_dir() / namespace)
    return base / f"{key}.json"


def cache_key(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


def read_cache(namespace: str, key: str, ttl_seconds: int | None) -> Any | None:
    path = _cache_path(namespace, key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    timestamp = data.get("timestamp")
    if ttl_seconds is not None and timestamp:
        try:
            ttl = float(ttl_seconds)
        except (TypeError, ValueError):
            ttl = None
        if ttl is not None:
            age = time.time() - float(timestamp)
            if age > ttl:
                return None
    return data.get("value")


def write_cache(namespace: str, key: str, value: Any) -> None:
    path = _cache_path(namespace, key)
    payload = {"timestamp": time.time(), "value": value}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True, sort_keys=True), encoding="utf-8")
