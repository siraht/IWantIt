"""External identify step for a music tracker JSON API."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import requests

from ..config import ensure_config_exists, load_config
from ..pipeline import render_template
from ..util import normalize_request_input


def _read_input() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        payload = {"request": {"input": raw, "input_type": "text", "query": raw}}
        normalize_request_input(payload["request"])
        return payload
    if isinstance(data, dict):
        request = data.get("request")
        if isinstance(request, dict):
            normalize_request_input(request)
        return data
    payload = {"request": {"input": data, "input_type": "json"}}
    normalize_request_input(payload["request"])
    return payload


def _get_path(obj: Any, path: str) -> Any:
    current = obj
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _find_candidates(payload: Any, response_path: str | None) -> list[Any]:
    if response_path:
        found = _get_path(payload, response_path)
        return found if isinstance(found, list) else []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _map_candidates(candidates: list[Any], fields: dict[str, str] | None, include_raw: bool) -> list[Any]:
    if not fields:
        return candidates
    mapped = []
    for item in candidates:
        if not isinstance(item, dict):
            mapped.append(item)
            continue
        out: dict[str, Any] = {key: _get_path(item, path) for key, path in fields.items()}
        if include_raw:
            out["_raw"] = item
        mapped.append(out)
    return mapped


def _load_config(data: dict[str, Any]) -> dict[str, Any] | None:
    config_path = os.environ.get("IWANTIT_CONFIG")
    if not config_path:
        config_path = (data.get("_meta") or {}).get("config_path")
    try:
        cfg_path = ensure_config_exists(config_path)
        return load_config(cfg_path)
    except FileNotFoundError:
        return None


def main() -> int:
    data = _read_input()
    if not data:
        return 0
    config = _load_config(data)
    if not config:
        json.dump(data, sys.stdout, indent=2, ensure_ascii=True)
        sys.stdout.write("\n")
        return 0
    tracker = config.get("music_tracker", {})
    search_cfg = tracker.get("search", {})

    request = data.get("request", {})
    query = request.get("query") or (data.get("ocr", {}) or {}).get("text")
    if not query and request.get("input_type") != "image":
        query = request.get("input")
    if not query:
        json.dump(data, sys.stdout, indent=2, ensure_ascii=True)
        sys.stdout.write("\n")
        return 0

    rendered = render_template(search_cfg, data, config)
    base_url = tracker.get("url")
    url = rendered.get("url")
    if not url and base_url and rendered.get("path"):
        url = base_url.rstrip("/") + "/" + str(rendered.get("path")).lstrip("/")
    if not url:
        json.dump(data, sys.stdout, indent=2, ensure_ascii=True)
        sys.stdout.write("\n")
        return 0

    method = (rendered.get("method") or "GET").upper()
    headers = rendered.get("headers")
    params = rendered.get("params")
    json_body = rendered.get("json")
    form = rendered.get("form")

    try:
        response = requests.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json_body,
            data=form,
            timeout=tracker.get("timeout", 30),
        )
        response.raise_for_status()
    except requests.RequestException:
        json.dump(data, sys.stdout, indent=2, ensure_ascii=True)
        sys.stdout.write("\n")
        return 0

    try:
        payload = response.json()
    except json.JSONDecodeError:
        json.dump(data, sys.stdout, indent=2, ensure_ascii=True)
        sys.stdout.write("\n")
        return 0

    candidates = _find_candidates(payload, tracker.get("response_path"))
    mapped = _map_candidates(candidates, tracker.get("candidate_fields"), tracker.get("include_raw", True))

    work = data.setdefault("work", {})
    if not work.get("title"):
        work["title"] = query
    if not work.get("media_type"):
        work["media_type"] = request.get("media_type")
    if mapped:
        work["candidates"] = mapped
    data["work"] = work

    json.dump(data, sys.stdout, indent=2, ensure_ascii=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
