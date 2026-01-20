"""Built-in workflow steps."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from ..pipeline import Context, render_template
from ..util import cache_key, read_cache, request_with_retry, write_cache


def identify(data: dict[str, Any], step_cfg: dict[str, Any], context: Context) -> dict[str, Any]:
    if data.get("work"):
        return data
    request = data.get("request", {})
    query = request.get("query")
    if not query and request.get("input_type") != "image":
        query = request.get("input")
    query = query or ""
    work = {
        "title": query,
        "media_type": request.get("media_type"),
        "candidates": request.get("candidates", []),
    }
    data["work"] = work
    return data


def _get_path(obj: Any, path: str) -> Any:
    current = obj
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _collect_query_fields(data: dict[str, Any], fields: list[str]) -> str:
    parts = []
    for path in fields:
        value = _get_path(data, path)
        if value is None:
            continue
        if isinstance(value, (list, dict)):
            continue
        text = str(value).strip()
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def _select_query(data: dict[str, Any], step_cfg: dict[str, Any], media_type: str | None) -> str:
    query_fields = step_cfg.get("query_fields")
    fields: list[str] | None = None
    if isinstance(query_fields, dict):
        fields = query_fields.get(media_type) or query_fields.get("default")
    elif isinstance(query_fields, list):
        fields = query_fields
    if fields:
        query = _collect_query_fields(data, fields)
        if query:
            return query
    request = data.get("request", {})
    query = request.get("query") or (data.get("ocr", {}) or {}).get("text")
    if not query and request.get("input_type") != "image":
        query = request.get("input")
    return query or ""


def _find_candidates(payload: Any, response_path: str | None, fallback_keys: list[str] | None) -> list[Any]:
    if response_path:
        found = _get_path(payload, response_path)
        return found if isinstance(found, list) else []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in fallback_keys or []:
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


def _normalize_text(text: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _normalize_search_query(query: str) -> str:
    if not query:
        return ""
    cleaned = re.sub(r"[\[\]\(\)]", " ", query)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _extract_category_ids(candidate: dict[str, Any]) -> set[int]:
    categories = candidate.get("categories")
    cat_ids: set[int] = set()
    if isinstance(categories, list):
        for cat in categories:
            if isinstance(cat, dict):
                cat_id = cat.get("id")
                try:
                    cat_ids.add(int(cat_id))
                except (TypeError, ValueError):
                    pass
                subcats = cat.get("subCategories") or cat.get("subcategories")
                if isinstance(subcats, list):
                    for sub in subcats:
                        if isinstance(sub, dict):
                            sub_id = sub.get("id")
                            try:
                                cat_ids.add(int(sub_id))
                            except (TypeError, ValueError):
                                pass
            else:
                try:
                    cat_ids.add(int(cat))
                except (TypeError, ValueError):
                    continue
    return cat_ids


def _match_category_prefix(cat_id: int, prefix: int, mode: str) -> bool:
    try:
        cat_val = int(cat_id)
        prefix_val = int(prefix)
    except (TypeError, ValueError):
        return False
    mode = (mode or "thousands").lower()
    if mode == "hundreds":
        return cat_val // 100 == prefix_val
    return cat_val // 1000 == prefix_val


def _tokenize(text: str) -> list[str]:
    cleaned = _normalize_text(text)
    if not cleaned:
        return []
    tokens = [token for token in cleaned.split(" ") if len(token) > 1]
    return tokens


def _match_score(candidate_tokens: set[str], query_tokens: set[str]) -> float:
    if not candidate_tokens or not query_tokens:
        return 0.0
    overlap = len(candidate_tokens & query_tokens)
    return overlap / max(len(candidate_tokens), 1)


def _parse_redacted_ids(url: str) -> tuple[int | None, int | None]:
    if not url:
        return None, None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None, None
    if not parsed.query:
        return None, None
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    group_id = params.get("id")
    torrent_id = params.get("torrentid")
    try:
        group_id_int = int(group_id) if group_id is not None else None
    except (TypeError, ValueError):
        group_id_int = None
    try:
        torrent_id_int = int(torrent_id) if torrent_id is not None else None
    except (TypeError, ValueError):
        torrent_id_int = None
    return group_id_int, torrent_id_int


def _normalize_release_token(text: str) -> str:
    return _normalize_text(text)


class _CommentHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._collect = False
        self._depth = 0
        self._current: list[str] = []
        self.comments: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "div":
            return
        attrs_dict = {key: value for key, value in attrs}
        div_id = attrs_dict.get("id") or ""
        if div_id.startswith("content") and div_id[len("content") :].isdigit():
            if not self._collect:
                self._collect = True
                self._depth = 1
                return
        if self._collect:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag != "div":
            return
        if self._collect:
            self._depth -= 1
            if self._depth <= 0:
                text = " ".join(self._current).strip()
                if text:
                    self.comments.append(text)
                self._current = []
                self._collect = False

    def handle_data(self, data: str) -> None:
        if self._collect:
            cleaned = data.strip()
            if cleaned:
                self._current.append(cleaned)


class _PageMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title: str | None = None
        self.description: str | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
            return
        if tag != "meta":
            return
        attrs_dict = {key.lower(): value for key, value in attrs}
        name = (attrs_dict.get("name") or attrs_dict.get("property") or "").lower()
        content = attrs_dict.get("content") or ""
        if not content:
            return
        if name in ("og:title", "twitter:title") and not self.title:
            self.title = content.strip()
        if name in ("og:description", "description", "twitter:description") and not self.description:
            self.description = content.strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            text = data.strip()
            if text:
                self.title = text


def _extract_page_meta(html: str) -> dict[str, str | None]:
    if not html:
        return {"title": None, "description": None}
    parser = _PageMetaParser()
    parser.feed(html)
    title = parser.title
    description = parser.description
    if not title:
        match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            title = re.sub(r"\s+", " ", match.group(1)).strip()
    if not description:
        match = re.search(
            r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"']([^\"']+)[\"']",
            html,
            flags=re.IGNORECASE,
        )
        if match:
            description = match.group(1).strip()
    return {"title": title, "description": description}


def _extract_comment_texts(html: str) -> list[str]:
    parser = _CommentHTMLParser()
    parser.feed(html)
    return parser.comments


def _comment_pages_from_html(html: str, group_id: int | None) -> int:
    if not html:
        return 1
    if not group_id:
        group_id = 0
    pattern = rf"torrents\\.php\\?page=(\\d+)&amp;id={group_id}#comments"
    matches = re.findall(pattern, html)
    pages: list[int] = []
    for num in matches:
        try:
            pages.append(int(num))
        except (TypeError, ValueError):
            continue
    return max(pages) if pages else 1


def _consensus_fields_from_results(
    results: list[dict[str, Any]],
    media_type: str | None,
    original_query: str,
    limit: int,
    min_match_ratio: float,
    min_token_matches: int,
    min_confirmations: int,
    single_match_ratio: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    query_tokens = set(_tokenize(original_query))
    input_year = _extract_year(original_query)
    if not query_tokens:
        return {}, {}

    scored: dict[tuple, dict[str, Any]] = {}
    for item in results[: max(limit, 1)]:
        title = item.get("title") if isinstance(item, dict) else str(item)
        if not title:
            continue
        cleaned = _strip_suffix(str(title))
        fields = _extract_fields_from_title(media_type, cleaned)
        if not fields:
            continue
        candidate_year = fields.get("year")
        if input_year and candidate_year and candidate_year != input_year:
            continue
        artist = fields.get("artist") or ""
        work_title = fields.get("title") or ""
        if media_type == "music" and not (artist and work_title):
            continue
        candidate_tokens = set(_tokenize(f"{artist} {work_title}"))
        score = _match_score(candidate_tokens, query_tokens)
        if score < min_match_ratio or len(candidate_tokens & query_tokens) < min_token_matches:
            continue
        key = (
            (artist or "").lower(),
            (work_title or "").lower(),
            candidate_year or 0,
        )
        bucket = scored.setdefault(
            key,
            {
                "fields": fields,
                "count": 0,
                "score_sum": 0.0,
            },
        )
        bucket["count"] += 1
        bucket["score_sum"] += score

    if not scored:
        return {}, {}

    best_key = max(
        scored.items(),
        key=lambda item: (item[1]["count"], item[1]["score_sum"]),
    )[0]
    best = scored[best_key]
    best_count = int(best["count"])
    avg_score = best["score_sum"] / max(best_count, 1)
    accepted = best_count >= min_confirmations or (best_count == 1 and avg_score >= single_match_ratio)
    return (best["fields"] if accepted else {}), {
        "count": best_count,
        "avg_score": avg_score,
        "accepted": accepted,
    }


def _filter_candidates_by_field(candidates: list[Any], filter_cfg: dict[str, Any]) -> list[Any]:
    field = filter_cfg.get("field")
    if not field:
        return candidates
    has_equals = "equals" in filter_cfg
    has_in = "in" in filter_cfg
    if not has_equals and not has_in:
        return candidates
    allowed_values = None
    if has_in:
        raw = filter_cfg.get("in")
        if isinstance(raw, list):
            allowed_values = set(raw)
        else:
            allowed_values = {raw}
    equals_value = filter_cfg.get("equals") if has_equals else None
    filtered = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        value = _get_path(item, field)
        if has_equals and value == equals_value:
            filtered.append(item)
        elif has_in and value in allowed_values:
            filtered.append(item)
    return filtered


def extract_release_preferences(
    data: dict[str, Any], step_cfg: dict[str, Any], context: Context
) -> dict[str, Any]:
    request = data.setdefault("request", {})
    work = data.setdefault("work", {})
    text = request.get("query_original") or request.get("query") or request.get("input") or ""
    lower = text.lower()
    prefs: dict[str, Any] = {}

    editions_cfg = step_cfg.get("edition_keywords") or {}
    editions = []
    for key, words in editions_cfg.items():
        if not isinstance(words, list):
            continue
        normalized = [str(word).lower() for word in words if word is not None]
        if any(word in lower for word in normalized if word):
            editions.append(key)
    if editions:
        prefs["editions"] = sorted(set(editions))

    media_cfg = step_cfg.get("media_keywords") or {}
    media = []
    for key, words in media_cfg.items():
        if not isinstance(words, list):
            continue
        normalized = [str(word).lower() for word in words if word is not None]
        if any(word in lower for word in normalized if word):
            media.append(key)
    if media:
        prefs["media"] = sorted(set(media))

    format_cfg = step_cfg.get("format_keywords") or {}
    formats = []
    for key, words in format_cfg.items():
        if not isinstance(words, list):
            continue
        normalized = [str(word).lower() for word in words if word is not None]
        if any(word in lower for word in normalized if word):
            formats.append(key)
    if formats:
        prefs["formats"] = sorted(set(formats))

    catalog_numbers = re.findall(r"\b[A-Z0-9]{2,}-[A-Z0-9]{2,}\b", text)
    if catalog_numbers:
        prefs["catalog_numbers"] = sorted(set(catalog_numbers))

    year = _extract_year(text)
    if year:
        prefs["year"] = [year]

    request["release_preferences"] = prefs
    explicit = bool(prefs.get("editions") or prefs.get("media") or prefs.get("formats") or prefs.get("catalog_numbers"))
    request["explicit_version"] = explicit
    data["request"] = request
    data["work"] = work
    return data


def redacted_enrich(
    data: dict[str, Any], step_cfg: dict[str, Any], context: Context
) -> dict[str, Any]:
    request = data.get("request", {})
    work = data.get("work", {})
    media_type = work.get("media_type") or request.get("media_type")
    enabled_media = step_cfg.get("enabled_media")
    if isinstance(enabled_media, list) and media_type not in enabled_media:
        return data
    candidates = work.get("candidates", []) or []
    if not candidates:
        return data
    red_cfg = context.config.get("redacted", {}) or {}
    api_key = red_cfg.get("api_key")
    if not api_key:
        return data
    base_url = (red_cfg.get("url") or "https://redacted.sh").rstrip("/")
    try:
        base_host = urlparse(base_url).hostname or ""
    except ValueError:
        base_host = ""

    group_map: dict[int, dict[str, Any]] = {}
    group_ids: set[int] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        info_url = candidate.get("info_url") or candidate.get("guid") or ""
        indexer = (candidate.get("indexer") or "").lower()
        parsed_host = ""
        if info_url:
            try:
                parsed_host = urlparse(info_url).hostname or ""
            except ValueError:
                parsed_host = ""
        is_redacted_source = (
            (base_host and parsed_host == base_host)
            or (parsed_host and base_host and parsed_host.endswith("." + base_host))
            or indexer == "redacted"
        )
        if not is_redacted_source:
            continue
        group_id, torrent_id = _parse_redacted_ids(info_url)
        if group_id:
            group_ids.add(group_id)
            candidate.setdefault("_redacted_ids", {})["group_id"] = group_id
        if torrent_id:
            candidate.setdefault("_redacted_ids", {})["torrent_id"] = torrent_id

    cache_cfg = step_cfg.get("cache") or {}
    if isinstance(cache_cfg, bool):
        cache_cfg = {"enabled": cache_cfg}
    cache_enabled = bool(cache_cfg.get("enabled"))

    for group_id in sorted(group_ids):
        payload = None
        cache_key_payload = {"action": "torrentgroup", "group_id": group_id}
        if cache_enabled:
            cached = read_cache(cache_cfg.get("namespace", "redacted"), cache_key(cache_key_payload), cache_cfg.get("ttl_seconds"))
            if cached is not None:
                payload = cached
        if payload is None:
            url = f"{base_url}/ajax.php"
            params = {"action": "torrentgroup", "id": group_id}
            response = request_with_retry(
                "GET",
                url,
                headers={"Authorization": api_key},
                params=params,
                timeout=step_cfg.get("timeout", red_cfg.get("timeout", 20)),
                retries=int(step_cfg.get("retries") or 0),
                backoff_seconds=float(step_cfg.get("retry_backoff_seconds") or 0.5),
                max_backoff_seconds=float(step_cfg.get("max_backoff_seconds") or 8.0),
                retry_statuses=step_cfg.get("retry_statuses"),
            )
            response.raise_for_status()
            payload = response.json()
            if cache_enabled:
                write_cache(cache_cfg.get("namespace", "redacted"), cache_key(cache_key_payload), payload)
        group_map[group_id] = payload

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        ids = candidate.get("_redacted_ids") or {}
        group_id = ids.get("group_id")
        torrent_id = ids.get("torrent_id")
        if not group_id:
            continue
        payload = group_map.get(group_id)
        if not isinstance(payload, dict):
            continue
        response = payload.get("response") or {}
        group_info = response.get("group") or {}
        torrent_info = None
        if torrent_id:
            for torrent in response.get("torrents", []) or []:
                if torrent.get("id") == torrent_id:
                    torrent_info = torrent
                    break
        candidate["redacted"] = {
            "group": group_info,
            "torrent": torrent_info or {},
        }
    if group_map:
        data.setdefault("redacted", {})["groups"] = group_map
    data["work"] = work
    return data


def redacted_comments(
    data: dict[str, Any], step_cfg: dict[str, Any], context: Context
) -> dict[str, Any]:
    request = data.get("request", {})
    work = data.get("work", {})
    media_type = work.get("media_type") or request.get("media_type")
    enabled_media = step_cfg.get("enabled_media")
    if isinstance(enabled_media, list) and media_type not in enabled_media:
        return data
    red_cfg = context.config.get("redacted", {}) or {}
    api_key = red_cfg.get("api_key")
    if not api_key:
        return data
    base_url = (red_cfg.get("url") or "https://redacted.sh").rstrip("/")
    groups = (data.get("redacted") or {}).get("groups", {})
    if not groups:
        return data
    session_cookie = red_cfg.get("session_cookie")

    cache_cfg = step_cfg.get("cache") or {}
    if isinstance(cache_cfg, bool):
        cache_cfg = {"enabled": cache_cfg}
    cache_enabled = bool(cache_cfg.get("enabled"))
    max_pages = int(step_cfg.get("max_pages") or 1)

    comments_map: dict[int, list[str]] = {}
    for group_id in groups.keys():
        group_comments: list[str] = []
        page = 1
        if cache_enabled:
            cached = read_cache(cache_cfg.get("namespace", "redacted_comments"), cache_key({"group_id": group_id}), cache_cfg.get("ttl_seconds"))
            if cached is not None:
                comments_map[group_id] = cached
                continue
        # Attempt to discover comment pages from group response
        payload = groups.get(group_id)
        comment_pages = None
        if isinstance(payload, dict):
            response = payload.get("response") or {}
            comment_pages = response.get("commentPages") or response.get("comment_pages")
        if comment_pages:
            try:
                comment_pages = int(comment_pages)
            except (TypeError, ValueError):
                comment_pages = None
        if comment_pages:
            start = max(1, comment_pages - max_pages + 1)
            pages = list(range(start, comment_pages + 1))
        else:
            pages = [page]

        for page in pages:
            url = f"{base_url}/ajax.php"
            params = {"action": "torrentgroup", "id": group_id, "page": page}
            response = request_with_retry(
                "GET",
                url,
                headers={"Authorization": api_key},
                params=params,
                timeout=step_cfg.get("timeout", red_cfg.get("timeout", 20)),
                retries=int(step_cfg.get("retries") or 0),
                backoff_seconds=float(step_cfg.get("retry_backoff_seconds") or 0.5),
                max_backoff_seconds=float(step_cfg.get("max_backoff_seconds") or 8.0),
                retry_statuses=step_cfg.get("retry_statuses"),
            )
            response.raise_for_status()
            payload = response.json()
            resp = payload.get("response") or {}
            comments = resp.get("comments") or []
            for entry in comments:
                if isinstance(entry, dict):
                    text = entry.get("comment")
                else:
                    text = str(entry)
                if text:
                    group_comments.append(text)

        if group_comments:
            comments_map[group_id] = group_comments
            if cache_enabled:
                write_cache(cache_cfg.get("namespace", "redacted_comments"), cache_key({"group_id": group_id}), group_comments)

    if not comments_map and session_cookie:
        for group_id in groups.keys():
            if cache_enabled:
                cached = read_cache(cache_cfg.get("namespace", "redacted_comments"), cache_key({"group_id": group_id}), cache_cfg.get("ttl_seconds"))
                if cached is not None:
                    comments_map[group_id] = cached
                    continue
            url = f"{base_url}/torrents.php"
            cookies = {"session": session_cookie}
            first = request_with_retry(
                "GET",
                url,
                params={"id": group_id},
                cookies=cookies,
                timeout=step_cfg.get("timeout", red_cfg.get("timeout", 20)),
                retries=int(step_cfg.get("retries") or 0),
                backoff_seconds=float(step_cfg.get("retry_backoff_seconds") or 0.5),
                max_backoff_seconds=float(step_cfg.get("max_backoff_seconds") or 8.0),
                retry_statuses=step_cfg.get("retry_statuses"),
            )
            first.raise_for_status()
            html = first.text
            total_pages = _comment_pages_from_html(html, group_id)
            if step_cfg.get("max_pages") in ("all", 0) or max_pages == 0:
                pages = range(1, total_pages + 1)
            else:
                start = max(1, total_pages - max_pages + 1)
                pages = range(start, total_pages + 1)
            group_comments = _extract_comment_texts(html)
            if total_pages > 1:
                for page in pages:
                    if page == 1:
                        continue
                    resp = request_with_retry(
                        "GET",
                        url,
                        params={"id": group_id, "page": page},
                        cookies=cookies,
                        timeout=step_cfg.get("timeout", red_cfg.get("timeout", 20)),
                        retries=int(step_cfg.get("retries") or 0),
                        backoff_seconds=float(step_cfg.get("retry_backoff_seconds") or 0.5),
                        max_backoff_seconds=float(step_cfg.get("max_backoff_seconds") or 8.0),
                        retry_statuses=step_cfg.get("retry_statuses"),
                    )
                    resp.raise_for_status()
                    group_comments.extend(_extract_comment_texts(resp.text))
            if group_comments:
                comments_map[group_id] = group_comments
                if cache_enabled:
                    write_cache(cache_cfg.get("namespace", "redacted_comments"), cache_key({"group_id": group_id}), group_comments)

    if comments_map:
        store_comments = bool(step_cfg.get("store_comments", False))
        if store_comments:
            data.setdefault("redacted", {})["comments"] = comments_map
        else:
            data.setdefault("redacted", {})["comment_counts"] = {
                str(group_id): len(comments)
                for group_id, comments in comments_map.items()
            }
            data.setdefault("_internal", {})["redacted_comments"] = comments_map
    return data


def apply_recommendations(
    data: dict[str, Any], step_cfg: dict[str, Any], context: Context
) -> dict[str, Any]:
    work = data.get("work", {})
    candidates = work.get("candidates", []) or []
    if not candidates:
        return data
    comments = (data.get("redacted") or {}).get("comments", {})
    if not comments:
        comments = (data.get("_internal") or {}).get("redacted_comments", {})
    if not comments:
        return data
    weight = float(step_cfg.get("weight") or 500.0)
    catalog_weight = float(step_cfg.get("catalog_weight") or 1.0)
    label_weight = float(step_cfg.get("label_weight") or 0.7)
    title_weight = float(step_cfg.get("title_weight") or 0.5)
    media_weight = float(step_cfg.get("media_weight") or 0.4)
    year_weight = float(step_cfg.get("year_weight") or 0.3)

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        red = candidate.get("redacted") or {}
        group = red.get("group") or {}
        torrent = red.get("torrent") or {}
        ids = candidate.get("_redacted_ids") or {}
        group_id = ids.get("group_id")
        if not group_id or group_id not in comments:
            continue
        comment_blob = _normalize_release_token(" ".join(comments[group_id]))
        if not comment_blob:
            continue
        score = 0.0
        matches = []

        catalog = torrent.get("remasterCatalogueNumber") or group.get("catalogueNumber")
        if catalog:
            catalog_norm = _normalize_release_token(str(catalog))
            if catalog_norm and catalog_norm in comment_blob:
                score += weight * catalog_weight
                matches.append(f"catalog:{catalog}")

        label = torrent.get("remasterRecordLabel") or group.get("recordLabel")
        if label:
            label_norm = _normalize_release_token(str(label))
            if label_norm and label_norm in comment_blob:
                score += weight * label_weight
                matches.append(f"label:{label}")

        remaster_title = torrent.get("remasterTitle")
        if remaster_title:
            title_norm = _normalize_release_token(str(remaster_title))
            if title_norm and title_norm in comment_blob:
                score += weight * title_weight
                matches.append(f"title:{remaster_title}")

        media = torrent.get("media")
        if media:
            media_norm = _normalize_release_token(str(media))
            if media_norm and media_norm in comment_blob:
                score += weight * media_weight
                matches.append(f"media:{media}")

        year = torrent.get("remasterYear") or group.get("year")
        if year:
            year_str = str(year)
            if year_str in comment_blob:
                score += weight * year_weight
                matches.append(f"year:{year}")

        if score:
            candidate["recommendation"] = {
                "score": score,
                "matches": matches,
            }
    work["candidates"] = candidates
    data["work"] = work
    return data


def filter_by_version(
    data: dict[str, Any], step_cfg: dict[str, Any], context: Context
) -> dict[str, Any]:
    request = data.get("request", {})
    work = data.get("work", {})
    candidates = work.get("candidates", []) or []
    if not candidates:
        return data
    if not request.get("explicit_version"):
        return data
    prefs = request.get("release_preferences") or {}
    if not prefs:
        return data

    def matches(candidate: dict[str, Any]) -> bool:
        text = f"{candidate.get('title','')} {candidate.get('sort_title','')}"
        text_norm = _normalize_release_token(text)
        red = candidate.get("redacted") or {}
        group = red.get("group") or {}
        torrent = red.get("torrent") or {}

        def match_any(values: list[str], haystack: str) -> bool:
            for value in values:
                token = _normalize_release_token(value)
                if token and token in haystack:
                    return True
            return False

        editions = prefs.get("editions") or []
        if editions:
            if not match_any(editions, text_norm) and not match_any(editions, _normalize_release_token(str(torrent.get("remasterTitle") or ""))):
                return False
        media = [str(item).lower() for item in (prefs.get("media") or [])]
        if media:
            media_value = str(torrent.get("media") or "").lower()
            if media_value and media_value not in media and not match_any(media, text_norm):
                return False
        formats = [str(item).lower() for item in (prefs.get("formats") or [])]
        if formats:
            format_value = str(torrent.get("format") or "").lower()
            encoding_value = str(torrent.get("encoding") or "").lower()
            if format_value and format_value not in formats and encoding_value not in formats and not match_any(formats, text_norm):
                return False
        catalogs = prefs.get("catalog_numbers") or []
        if catalogs:
            cat_value = str(torrent.get("remasterCatalogueNumber") or group.get("catalogueNumber") or "")
            if cat_value and cat_value not in catalogs and not match_any(catalogs, text_norm):
                return False
        labels = prefs.get("labels") or []
        if labels:
            label_value = str(torrent.get("remasterRecordLabel") or group.get("recordLabel") or "")
            if label_value and label_value.lower() not in [label.lower() for label in labels] and not match_any(labels, text_norm):
                return False
        years = prefs.get("year") or []
        if years:
            year_value = torrent.get("remasterYear") or group.get("year")
            if year_value and year_value not in years:
                return False
        return True

    matched = [cand for cand in candidates if isinstance(cand, dict) and matches(cand)]
    data.setdefault("filter", {})["version"] = {
        "requested": prefs,
        "matched": len(matched),
        "total": len(candidates),
    }
    if matched:
        work["candidates"] = matched
        data["work"] = work
    return data


def _redact_apikey(url: str) -> str:
    if not url:
        return url
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    if not parsed.query:
        return url
    params = parse_qsl(parsed.query, keep_blank_values=True)
    filtered = [(k, v) for k, v in params if k.lower() not in {"apikey", "api_key", "api-key"}]
    if len(filtered) == len(params):
        return url
    return urlunparse(parsed._replace(query=urlencode(filtered)))


def _scrub_candidate_urls(candidate: dict[str, Any]) -> None:
    url = candidate.get("download_url")
    if isinstance(url, str):
        candidate["download_url"] = _redact_apikey(url)
    raw = candidate.get("_raw")
    if isinstance(raw, dict):
        raw_url = raw.get("downloadUrl") or raw.get("download_url")
        if isinstance(raw_url, str):
            redacted = _redact_apikey(raw_url)
            if raw.get("downloadUrl"):
                raw["downloadUrl"] = redacted
            if raw.get("download_url"):
                raw["download_url"] = redacted


def _scrub_payload_urls(payload: Any) -> None:
    if isinstance(payload, list):
        for item in payload:
            _scrub_payload_urls(item)
        return
    if isinstance(payload, dict):
        for key in ("downloadUrl", "download_url"):
            if key in payload and isinstance(payload[key], str):
                payload[key] = _redact_apikey(payload[key])
        for value in payload.values():
            _scrub_payload_urls(value)


def _redact_headers(headers: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(headers, dict):
        return headers
    redacted = {}
    for key, value in headers.items():
        lowered = str(key).lower()
        if "authorization" in lowered or "api" in lowered or "token" in lowered:
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted


def _get_candidate_text(candidate: dict[str, Any], fields: list[str]) -> str:
    parts = []
    for path in fields:
        value = _get_path(candidate, path)
        if value is None:
            continue
        if isinstance(value, (list, dict)):
            continue
        text = str(value).strip()
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def _derive_audio_fields(text: str) -> dict[str, Any]:
    derived: dict[str, Any] = {}
    if not text:
        return derived
    match = re.search(r"\b(\d{1,2})\s*/\s*(\d{2,3}(?:\.\d)?)\b", text, flags=re.IGNORECASE)
    if match:
        try:
            derived["bit_depth"] = int(match.group(1))
        except ValueError:
            pass
        try:
            derived["sample_rate_khz"] = float(match.group(2))
        except ValueError:
            pass
    match = re.search(r"\b(\d{2})\s*[- ]?bit\b", text, flags=re.IGNORECASE)
    if match:
        try:
            derived["bit_depth"] = int(match.group(1))
        except ValueError:
            pass
    match = re.search(r"\b(\d{2,3}(?:\.\d)?)\s*k?hz\b", text, flags=re.IGNORECASE)
    if match:
        try:
            derived["sample_rate_khz"] = float(match.group(1))
        except ValueError:
            pass
    match = re.search(r"\b(\d{2,4})\s*kbps\b", text, flags=re.IGNORECASE)
    if match:
        try:
            derived["bitrate_kbps"] = int(match.group(1))
        except ValueError:
            pass
    return derived


def _release_category_for_candidate(candidate: dict[str, Any], release_type_map: dict[int, str]) -> str:
    title = str(candidate.get("title") or "").lower()
    red = candidate.get("redacted") or {}
    group = red.get("group") or {}
    torrent = red.get("torrent") or {}
    remaster_title = str(torrent.get("remasterTitle") or "").lower()
    release_type = group.get("releaseType")
    release_label = ""
    if release_type is not None:
        try:
            release_label = release_type_map.get(int(release_type), "")
        except (TypeError, ValueError):
            release_label = ""
    release_label_lower = release_label.lower()

    if "deluxe" in remaster_title or "deluxe" in title:
        return "deluxe"
    if "anniversary" in remaster_title or "anniversary" in title:
        return "anniversary"
    if "live" in remaster_title or "live" in title or "live" in release_label_lower:
        return "live"
    if "bootleg" in remaster_title or "bootleg" in title or "bootleg" in release_label_lower:
        return "bootleg"
    return "studio"


def _normalize_rules(rules: list[Any]) -> list[dict[str, Any]]:
    if not rules:
        return []
    normalized = []
    for entry in rules:
        if isinstance(entry, str):
            normalized.append({"match": entry})
        elif isinstance(entry, dict):
            normalized.append(entry)
    return normalized


def _apply_format_rules(rules: dict[str, Any], preferences: dict[str, Any]) -> dict[str, Any]:
    fmt = preferences.get("format")
    if not fmt:
        return rules
    if isinstance(fmt, list):
        formats = [str(item).lower() for item in fmt]
    else:
        formats = [str(fmt).lower()]
    if "both" in formats:
        return rules
    format_rules = rules.get("format_rules", {})
    merged = dict(rules)
    for fmt_key in formats:
        extra = format_rules.get(fmt_key)
        if not isinstance(extra, dict):
            continue
        for key in ("reject", "score", "numeric_fields", "sort_fields"):
            if key in extra:
                merged[key] = list(merged.get(key) or []) + list(extra.get(key) or [])
    return merged


def _select_media_mapping(mapping: Any, media_type: str | None) -> Any:
    if mapping is None:
        return None
    if isinstance(mapping, dict):
        if media_type and media_type in mapping:
            value = mapping.get(media_type)
        else:
            value = mapping.get("default")
        if isinstance(value, list) and not value:
            return None
        return value
    if isinstance(mapping, list) and not mapping:
        return None
    return mapping


def _strip_suffix(title: str) -> str:
    suffixes = (
        "wikipedia",
        "discogs",
        "imdb",
        "tmdb",
        "tvdb",
        "goodreads",
        "open library",
        "spotify",
        "bandcamp",
        "youtube",
        "apple music",
        "rateyourmusic",
        "rym",
        "musicbrainz",
        "allmusic",
        "last.fm",
        "soundcloud",
        "amazon",
    )
    cleaned = title.strip()
    for sep in (" - ", " | "):
        if sep in cleaned:
            parts = cleaned.split(sep)
            tail = parts[-1].strip().lower()
            if "." in tail or any(token in tail for token in suffixes):
                cleaned = sep.join(parts[:-1]).strip()
    return cleaned


def _extract_year(text: str) -> int | None:
    match = re.search(r"\b(19|20)\d{2}\b", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _infer_media_type_from_query(query: str) -> str | None:
    if not query:
        return None
    text = query.lower()
    if re.search(r"\bs\d{1,2}e\d{1,2}\b", text):
        return "tv"
    if "season" in text or "episode" in text:
        return "tv"
    if " by " in text:
        return "book"
    if " - " in query:
        parts = [part.strip() for part in query.split(" - ", 1)]
        if len(parts) == 2 and all(parts):
            return "music"
    if any(token in text for token in ("movie", "film", "trailer")):
        return "movie"
    if any(token in text for token in ("book", "novel", "audiobook")):
        return "book"
    return None


def _track_album_scores(text: str) -> tuple[int, int]:
    if not text:
        return 0, 0
    lower = text.lower()
    track_terms = [
        "single",
        "song",
        "track",
        "music video",
        "official video",
        "official visualizer",
        "lyrics",
    ]
    album_terms = [
        "album",
        "ep",
        "lp",
        "mixtape",
        "compilation",
        "deluxe edition",
        "anniversary edition",
    ]
    track_score = sum(1 for term in track_terms if term in lower)
    album_score = sum(1 for term in album_terms if term in lower)
    return track_score, album_score


def _find_album_from_results(
    results: list[dict[str, Any]] | None, artist: str, track: str
) -> dict[str, Any] | None:
    if not results:
        return None
    patterns = [
        r"from (?:the )?album\s+[\"“']?([^\"”'\n\r\-\|]{3,})",
        r"from (?:the )?ep\s+[\"“']?([^\"”'\n\r\-\|]{3,})",
        r"album\s+[\"“']?([^\"”'\n\r\-\|]{3,})",
        r"ep\s+[\"“']?([^\"”'\n\r\-\|]{3,})",
    ]
    for item in results:
        if not isinstance(item, dict):
            continue
        blob = " ".join(
            [str(item.get("title") or ""), str(item.get("snippet") or item.get("description") or "")]
        ).strip()
        if not blob:
            continue
        for pattern in patterns:
            match = re.search(pattern, blob, flags=re.IGNORECASE)
            if match:
                album = match.group(1).strip()
                if not album:
                    continue
                if track and album.lower() == track.lower():
                    continue
                return {"album": album, "source": "web"}
    return None


def _extract_fields_from_title(media_type: str | None, title: str) -> dict[str, Any]:
    if not title:
        return {}
    out: dict[str, Any] = {}
    year = _extract_year(title)
    if year:
        out["year"] = year
    if media_type == "music":
        if " - " in title:
            artist, release = title.split(" - ", 1)
            if artist.strip() and release.strip():
                out["artist"] = artist.strip()
                out["title"] = release.strip()
                return out
        out["title"] = title.strip()
        return out
    if media_type == "book":
        lower = title.lower()
        if " by " in lower:
            idx = lower.index(" by ")
            out["title"] = title[:idx].strip()
            out["author"] = title[idx + 4 :].strip()
            return out
        if " - " in title:
            book_title, author = title.split(" - ", 1)
            if book_title.strip() and author.strip():
                out["title"] = book_title.strip()
                out["author"] = author.strip()
                return out
        out["title"] = title.strip()
        return out
    out["title"] = title.strip()
    return out


def identify_web_search(
    data: dict[str, Any], step_cfg: dict[str, Any], context: Context
) -> dict[str, Any]:
    request = data.setdefault("request", {})
    work = data.setdefault("work", {})
    media_type = request.get("media_type") or work.get("media_type")
    if media_type and not work.get("media_type"):
        work["media_type"] = media_type

    seed_text = request.get("query") or request.get("input") or ""
    seed_clean = _strip_suffix(seed_text)
    seed_fields = _extract_fields_from_title(media_type, seed_clean)
    for key, value in seed_fields.items():
        if value and not work.get(key):
            work[key] = value

    query = _select_query(data, step_cfg, media_type)
    if not query:
        return data

    if "query_original" not in request:
        original_query = request.get("query") or request.get("input")
        if original_query:
            request["query_original"] = original_query
    request["query"] = query

    search_cfg = context.config.get("web_search", {})
    provider_name = step_cfg.get("provider") or search_cfg.get("provider")
    if not provider_name:
        return data
    provider_cfg = (search_cfg.get("providers") or {}).get(provider_name)
    if not provider_cfg:
        return data

    request_cfg = provider_cfg.get("request", {})
    rendered = render_template(request_cfg, data, context.config)
    url = rendered.get("url")
    if not url:
        return data
    method = (rendered.get("method") or "GET").upper()
    headers = rendered.get("headers")
    params = rendered.get("params")
    json_body = rendered.get("json")
    form = rendered.get("form")

    try:
        cache_cfg = step_cfg.get("cache") or {}
        if isinstance(cache_cfg, bool):
            cache_cfg = {"enabled": cache_cfg}
        cache_enabled = bool(cache_cfg.get("enabled"))
        cache_hit = False
        cache_value = None
        if cache_enabled:
            key_payload = {
                "provider": provider_name,
                "url": url,
                "params": params,
                "json": json_body,
                "query": query,
            }
            key = cache_key(key_payload)
            cache_value = read_cache(cache_cfg.get("namespace", "web_search"), key, cache_cfg.get("ttl_seconds"))
            if cache_value is not None:
                cache_hit = True
        if cache_hit:
            payload = cache_value
        else:
            response = request_with_retry(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                data=form,
                timeout=step_cfg.get("timeout", provider_cfg.get("timeout", 20)),
                retries=int(step_cfg.get("retries") or 0),
                backoff_seconds=float(step_cfg.get("retry_backoff_seconds") or 0.5),
                max_backoff_seconds=float(step_cfg.get("max_backoff_seconds") or 8.0),
                retry_statuses=step_cfg.get("retry_statuses"),
            )
            response.raise_for_status()
            payload = response.json()
            if cache_enabled:
                write_cache(cache_cfg.get("namespace", "web_search"), key, payload)
    except (requests.RequestException, json.JSONDecodeError):
        return data

    response_cfg = provider_cfg.get("response", {})
    results_path = response_cfg.get("results_path")
    fallback_keys = response_cfg.get("fallback_keys")
    candidates = _find_candidates(payload, results_path, fallback_keys)
    filter_cfg = response_cfg.get("filter")
    if isinstance(filter_cfg, dict):
        candidates = _filter_candidates_by_field(candidates, filter_cfg)
    mapped = _map_candidates(candidates, response_cfg.get("fields"), response_cfg.get("include_raw", False))

    limit = step_cfg.get("result_limit") or response_cfg.get("limit")
    if limit:
        mapped = mapped[: int(limit)]

    data.setdefault("search", {})[provider_name] = {
        "query": query,
        "results": mapped,
        "count": len(mapped),
    }

    if not mapped:
        return data

    original = request.get("query_original") or request.get("query") or ""
    limit = int(step_cfg.get("result_limit") or response_cfg.get("limit") or 5)
    min_match_ratio = float(step_cfg.get("min_match_ratio") or 0.4)
    min_token_matches = int(step_cfg.get("min_token_matches") or 2)
    min_confirmations = int(step_cfg.get("min_confirmations") or 2)
    single_match_ratio = float(step_cfg.get("single_match_ratio") or 0.75)
    consensus_fields, consensus_meta = _consensus_fields_from_results(
        mapped,
        media_type,
        original,
        limit,
        min_match_ratio,
        min_token_matches,
        min_confirmations,
        single_match_ratio,
    )
    if consensus_fields:
        override = bool(step_cfg.get("override", False))
        consensus_override = step_cfg.get("consensus_override")
        if consensus_override is None:
            consensus_override = True
        for key, value in consensus_fields.items():
            if value is None:
                continue
            if override or consensus_override or not work.get(key):
                work[key] = value

        update_query = step_cfg.get("update_query")
        if update_query is None:
            update_query = step_cfg.get("refine_query", True)
        if update_query:
            artist = work.get("artist")
            title = work.get("title")
            year = work.get("year")
            suffix = f" ({year})" if year else ""
            if media_type == "music" and artist and title:
                request["query"] = f"{artist} - {title}{suffix}"
            elif title:
                request["query"] = f"{title}{suffix}"
        data.setdefault("search", {})[provider_name]["analysis"] = consensus_meta

    data["work"] = work
    data["request"] = request
    return data


def determine_media_type(
    data: dict[str, Any], step_cfg: dict[str, Any], context: Context
) -> dict[str, Any]:
    request = data.setdefault("request", {})
    work = data.setdefault("work", {})
    if request.get("media_type") or work.get("media_type"):
        return data

    provider = step_cfg.get("provider") or (context.config.get("web_search", {}) or {}).get("provider")
    results = (data.get("search", {}) or {}).get(provider, {}).get("results")
    if not results:
        query = request.get("query") or request.get("input") or ""
        text = query.lower()
    else:
        limit = int(step_cfg.get("result_limit") or 5)
        chunks = []
        for item in results[:limit]:
            if isinstance(item, dict):
                title = item.get("title") or item.get("name") or ""
                snippet = item.get("snippet") or item.get("description") or ""
                chunks.append(f"{title} {snippet}".strip())
            else:
                chunks.append(str(item))
        text = " ".join(chunks).lower()
    url_meta = data.get("url") or {}
    if isinstance(url_meta, dict):
        extra = " ".join(
            [str(url_meta.get("title") or ""), str(url_meta.get("description") or "")]
        ).strip()
        if extra:
            text = f"{text} {extra}".lower()

    scores: dict[str, int] = {"music": 0, "movie": 0, "tv": 0, "book": 0}
    keywords = (context.config.get("media_type_detection", {}) or {}).get("keywords", {})
    for media_type, words in keywords.items():
        if not isinstance(words, list):
            continue
        for word in words:
            if word and word.lower() in text:
                scores[media_type] = scores.get(media_type, 0) + 1

    if re.search(r"\bs\d{1,2}e\d{1,2}\b", text):
        scores["tv"] = scores.get("tv", 0) + 2

    best = max(scores.items(), key=lambda item: item[1])
    min_score = int(step_cfg.get("min_score") or 1)
    if best[1] >= min_score:
        request["media_type"] = best[0]
        work["media_type"] = best[0]
        data["request"] = request
        data["work"] = work
        data.setdefault("decision", {})["media_type_confidence"] = best[1]
        return data

    fallback_enabled = step_cfg.get("fallback")
    if fallback_enabled is None:
        fallback_enabled = True
    if fallback_enabled:
        query = request.get("query") or request.get("input") or ""
        inferred = _infer_media_type_from_query(query)
        if inferred:
            request["media_type"] = inferred
            work["media_type"] = inferred
            data["request"] = request
            data["work"] = work
            data.setdefault("decision", {})["media_type_confidence"] = 1
    return data


def prowlarr_search(
    data: dict[str, Any], step_cfg: dict[str, Any], context: Context
) -> dict[str, Any]:
    request = data.setdefault("request", {})
    work = data.setdefault("work", {})
    media_type = request.get("media_type") or work.get("media_type")
    if media_type and not work.get("media_type"):
        work["media_type"] = media_type

    query = _select_query(data, step_cfg, media_type)
    if not query:
        return data
    normalize_query = step_cfg.get("normalize_query")
    if normalize_query is None:
        normalize_query = True
    if normalize_query:
        query = _normalize_search_query(query)
    request["query"] = query

    prow_cfg = context.config.get("prowlarr", {})
    search_cfg = prow_cfg.get("search", {})
    request_cfg = step_cfg.get("request") or search_cfg.get("request", {})
    if not request_cfg:
        return data
    rendered = render_template(request_cfg, data, context.config)
    url = rendered.get("url")
    if not url:
        base_url = prow_cfg.get("url")
        path = rendered.get("path") or search_cfg.get("path")
        if base_url and path:
            url = base_url.rstrip("/") + "/" + str(path).lstrip("/")
    if not url:
        return data

    method = (rendered.get("method") or "GET").upper()
    headers = rendered.get("headers")
    params = rendered.get("params")
    json_body = rendered.get("json")
    form = rendered.get("form")

    indexer_ids = _select_media_mapping(search_cfg.get("indexer_ids"), media_type)
    categories = _select_media_mapping(search_cfg.get("categories"), media_type)
    if method == "GET":
        if params is None:
            params = {}
        if indexer_ids is not None and "indexerIds" not in params:
            params["indexerIds"] = indexer_ids
        if categories is not None and "categories" not in params:
            params["categories"] = categories
    else:
        if json_body is None:
            json_body = {}
        if indexer_ids is not None and "indexerIds" not in json_body:
            json_body["indexerIds"] = indexer_ids
        if categories is not None and "categories" not in json_body:
            json_body["categories"] = categories

    try:
        cache_cfg = step_cfg.get("cache") or {}
        if isinstance(cache_cfg, bool):
            cache_cfg = {"enabled": cache_cfg}
        cache_enabled = bool(cache_cfg.get("enabled"))
        cache_hit = False
        cache_value = None
        if cache_enabled:
            key_payload = {
                "url": url,
                "method": method,
                "params": params,
                "json": json_body,
                "query": query,
                "indexerIds": indexer_ids,
                "categories": categories,
            }
            key = cache_key(key_payload)
            cache_value = read_cache(cache_cfg.get("namespace", "prowlarr"), key, cache_cfg.get("ttl_seconds"))
            if cache_value is not None:
                cache_hit = True
        if cache_hit:
            payload = cache_value
        else:
            response = request_with_retry(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                data=form,
                timeout=step_cfg.get("timeout", prow_cfg.get("timeout", 30)),
                retries=int(step_cfg.get("retries") or 0),
                backoff_seconds=float(step_cfg.get("retry_backoff_seconds") or 0.5),
                max_backoff_seconds=float(step_cfg.get("max_backoff_seconds") or 8.0),
                retry_statuses=step_cfg.get("retry_statuses"),
            )
            response.raise_for_status()
            payload = response.json()
            if cache_enabled:
                _scrub_payload_urls(payload)
                write_cache(cache_cfg.get("namespace", "prowlarr"), key, payload)
    except (requests.RequestException, json.JSONDecodeError):
        return data

    response_cfg = step_cfg.get("response") or search_cfg.get("response", {})
    results_path = response_cfg.get("results_path")
    fallback_keys = response_cfg.get("fallback_keys") or ["results", "items", "data", "releases"]
    candidates = _find_candidates(payload, results_path, fallback_keys)
    mapped = _map_candidates(candidates, response_cfg.get("fields"), response_cfg.get("include_raw", True))

    limit = step_cfg.get("result_limit") or response_cfg.get("limit")
    if limit:
        mapped = mapped[: int(limit)]
    for item in mapped:
        if isinstance(item, dict):
            _scrub_candidate_urls(item)
    if mapped:
        work["candidates"] = mapped

    data.setdefault("search", {})["prowlarr"] = {
        "query": query,
        "count": len(mapped),
        "results": mapped,
    }
    data["work"] = work
    data["request"] = request
    return data


def filter_candidates(
    data: dict[str, Any], step_cfg: dict[str, Any], context: Context
) -> dict[str, Any]:
    work = data.get("work", {})
    candidates = work.get("candidates", []) or []
    if not candidates:
        return data

    media_type = work.get("media_type") or data.get("request", {}).get("media_type")
    categories_cfg = step_cfg.get("categories")
    if categories_cfg is None:
        categories_cfg = (context.config.get("prowlarr", {}) or {}).get("search", {}).get("categories")
    allowed = _select_media_mapping(categories_cfg, media_type)
    if not allowed:
        return data

    allow_missing = step_cfg.get("allow_missing_categories")
    if allow_missing is None:
        allow_missing = False

    allowed_ids: set[int] = set()
    for item in allowed:
        try:
            allowed_ids.add(int(item))
        except (TypeError, ValueError):
            continue
    if not allowed_ids:
        return data

    allowed_prefixes = step_cfg.get("category_prefixes")
    if isinstance(allowed_prefixes, dict):
        allowed_prefixes = _select_media_mapping(allowed_prefixes, media_type)
    if allowed_prefixes is None and media_type == "music":
        allowed_prefixes = [30]

    filtered: list[dict[str, Any]] = []
    removed = 0
    for candidate in candidates:
        cat_ids = _extract_category_ids(candidate) if isinstance(candidate, dict) else set()
        if not cat_ids:
            if allow_missing:
                filtered.append(candidate)
            else:
                removed += 1
            continue
        matched = bool(cat_ids & allowed_ids)
        if not matched and allowed_prefixes:
            for cat_id in cat_ids:
                try:
                    if int(cat_id) // 100 in allowed_prefixes:
                        matched = True
                        break
                except (TypeError, ValueError):
                    continue
        if matched:
            filtered.append(candidate)
        else:
            removed += 1

    if removed:
        data.setdefault("filter", {})["categories"] = {
            "allowed": sorted(allowed_ids),
            "removed": removed,
            "kept": len(filtered),
            "allow_missing": bool(allow_missing),
            "prefixes": allowed_prefixes or [],
        }
    work["candidates"] = filtered
    data["work"] = work
    return data


def fetch_url(data: dict[str, Any], step_cfg: dict[str, Any], context: Context) -> dict[str, Any]:
    request = data.get("request", {})
    url = request.get("url") or request.get("input")
    if not url or request.get("input_type") != "url":
        return data
    if not url.startswith(("http://", "https://")):
        return data

    try:
        response = request_with_retry(
            "GET",
            url,
            headers=step_cfg.get(
                "headers",
                {
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            ),
            timeout=step_cfg.get("timeout", 15),
            retries=int(step_cfg.get("retries") or 0),
            backoff_seconds=float(step_cfg.get("retry_backoff_seconds") or 0.5),
            max_backoff_seconds=float(step_cfg.get("max_backoff_seconds") or 8.0),
            retry_statuses=step_cfg.get("retry_statuses"),
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        data.setdefault("url", {})["error"] = str(exc)
        return data

    content_type = (response.headers.get("content-type") or "").lower()
    if "text/html" not in content_type:
        data.setdefault("url", {})["content_type"] = content_type
        return data

    meta = _extract_page_meta(response.text)
    if (not meta.get("title") or meta.get("title") in ("- YouTube", "YouTube")) and "youtube.com" in url:
        try:
            oembed_url = "https://www.youtube.com/oembed"
            oembed_params = {"url": url, "format": "json"}
            oembed = request_with_retry(
                "GET",
                oembed_url,
                params=oembed_params,
                timeout=step_cfg.get("timeout", 15),
                retries=int(step_cfg.get("retries") or 0),
                backoff_seconds=float(step_cfg.get("retry_backoff_seconds") or 0.5),
                max_backoff_seconds=float(step_cfg.get("max_backoff_seconds") or 8.0),
                retry_statuses=step_cfg.get("retry_statuses"),
            )
            oembed.raise_for_status()
            payload = oembed.json()
            if isinstance(payload, dict) and payload.get("title"):
                meta["title"] = str(payload["title"]).strip()
        except (requests.RequestException, json.JSONDecodeError):
            pass
    data["url"] = {
        "url": url,
        "title": meta.get("title"),
        "description": meta.get("description"),
        "content_type": content_type,
    }

    if not request.get("query_original"):
        request["query_original"] = request.get("query") or url

    if meta.get("title") and (not request.get("query") or request.get("query") == url):
        request["query"] = meta["title"]
        data["request"] = request
    return data


def resolve_track_release(
    data: dict[str, Any], step_cfg: dict[str, Any], context: Context
) -> dict[str, Any]:
    request = data.get("request", {}) or {}
    work = data.get("work", {}) or {}
    media_type = work.get("media_type") or request.get("media_type")
    if media_type != "music":
        return data

    query = request.get("query") or request.get("input") or ""
    query_lower = query.lower()
    if any(token in query_lower for token in ("album", "ep", "lp", "mixtape", "compilation")):
        return data

    provider = (context.config.get("web_search", {}) or {}).get("provider")
    results = (data.get("search", {}) or {}).get(provider, {}).get("results") or []
    track_score, album_score = _track_album_scores(query)
    input_url = request.get("input") if request.get("input_type") == "url" else ""
    if isinstance(input_url, str) and "youtube.com" in input_url:
        track_score += 2
    for item in results:
        if not isinstance(item, dict):
            continue
        blob = " ".join(
            [str(item.get("title") or ""), str(item.get("snippet") or item.get("description") or "")]
        ).strip()
        t_score, a_score = _track_album_scores(blob)
        track_score += t_score
        album_score += a_score

    if track_score <= album_score:
        return data

    artist = work.get("artist") or ""
    title = work.get("title") or ""
    seed = {}
    if not (artist and title):
        seed = _extract_fields_from_title("music", _strip_suffix(query))
        artist = artist or seed.get("artist") or ""
        title = title or seed.get("title") or ""
    elif " - " in title:
        seed = _extract_fields_from_title("music", _strip_suffix(title))
    if seed and seed.get("artist") and seed.get("title"):
        if not artist or " - " in title:
            artist = seed["artist"]
            title = seed["title"]
    if not (artist and title):
        return data

    work["track_title"] = title
    work["track_artist"] = artist

    album_from_web = _find_album_from_results(results, artist, title)
    if album_from_web:
        work["album_title"] = album_from_web["album"]
        work["track_release_source"] = album_from_web.get("source")
        year = work.get("year") or _extract_year(query)
        suffix = f" {year}" if year else ""
        request["query"] = f"{artist} - {work['album_title']}{suffix}"
        data["request"] = request
        data["work"] = work
        return data

    red_cfg = context.config.get("redacted", {}) or {}
    api_key = red_cfg.get("api_key")
    if not api_key:
        return data
    base_url = (red_cfg.get("url") or "https://redacted.sh").rstrip("/")
    params = {
        "action": "browse",
        "artistname": artist,
        "filelist": title,
        "searchstr": title,
        "filter_cat[]": [0],
    }
    try:
        response = request_with_retry(
            "GET",
            f"{base_url}/ajax.php",
            headers={"Authorization": api_key},
            params=params,
            timeout=step_cfg.get("timeout", red_cfg.get("timeout", 20)),
            retries=int(step_cfg.get("retries") or 0),
            backoff_seconds=float(step_cfg.get("retry_backoff_seconds") or 0.5),
            max_backoff_seconds=float(step_cfg.get("max_backoff_seconds") or 8.0),
            retry_statuses=step_cfg.get("retry_statuses"),
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, json.JSONDecodeError):
        return data

    results = (payload.get("response") or {}).get("results") or []
    work["track_search_results"] = results
    if not results:
        data["work"] = work
        return data

    priority = step_cfg.get("release_priority") or ["Album", "EP", "Single", "Live album"]
    priority_map = {name.lower(): idx for idx, name in enumerate(priority)}
    best = None
    for item in results:
        if not isinstance(item, dict):
            continue
        release_type = str(item.get("releaseType") or "").strip()
        release_key = release_type.lower()
        rank = priority_map.get(release_key, len(priority_map) + 1)
        group_name = item.get("groupName") or item.get("name")
        if not group_name:
            continue
        candidate = {
            "group_name": group_name,
            "release_type": release_type,
            "year": item.get("groupYear") or item.get("year"),
            "rank": rank,
        }
        if best is None or candidate["rank"] < best["rank"]:
            best = candidate

    if best:
        work["album_title"] = best["group_name"]
        work["track_release_type"] = best["release_type"]
        work["track_release_source"] = "redacted_browse"
        year = best.get("year") or work.get("year") or _extract_year(query)
        suffix = f" {year}" if year else ""
        request["query"] = f"{artist} - {best['group_name']}{suffix}"
        data["request"] = request
        data["work"] = work
        return data

    data["work"] = work
    return data


def _resolve_download_client_id(
    candidate: dict[str, Any], rules: list[dict[str, Any]] | None
) -> int | None:
    if not rules or not isinstance(candidate, dict):
        return None
    cat_ids = _extract_category_ids(candidate)
    if not cat_ids:
        return None
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        client_id = rule.get("client_id") or rule.get("id")
        if client_id is None:
            continue
        categories = rule.get("categories") or []
        prefixes = rule.get("category_prefixes") or []
        prefix_mode = rule.get("prefix_mode") or "thousands"
        for cat in categories:
            try:
                if int(cat) in cat_ids:
                    return int(client_id)
            except (TypeError, ValueError):
                continue
        for prefix in prefixes:
            for cat_id in cat_ids:
                if _match_category_prefix(cat_id, prefix, prefix_mode):
                    return int(client_id)
    return None


def filter_match(
    data: dict[str, Any], step_cfg: dict[str, Any], context: Context
) -> dict[str, Any]:
    work = data.get("work", {})
    candidates = work.get("candidates", []) or []
    if not candidates:
        return data

    media_type = work.get("media_type") or data.get("request", {}).get("media_type")
    match_fields_cfg = step_cfg.get("match_fields") or {
        "music": ["work.artist", "work.title", "work.year", "request.query"],
        "movie": ["work.title", "work.year", "request.query"],
        "tv": ["work.title", "work.year", "request.query"],
        "book": ["work.title", "work.author", "work.year", "request.query"],
        "default": ["request.query"],
    }
    fields = _select_media_mapping(match_fields_cfg, media_type) or ["request.query"]
    query_bits = []
    for field in fields:
        value = _get_path(data, field)
        if value:
            query_bits.append(str(value))
    query = " ".join(query_bits).strip()
    if not query:
        return data

    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return data

    min_match_ratio = float(step_cfg.get("min_match_ratio") or 0.4)
    min_token_matches = int(step_cfg.get("min_token_matches") or 2)
    title_fields = step_cfg.get("title_fields") or [
        "title",
        "name",
        "_raw.title",
        "_raw.name",
        "releaseTitle",
        "release_title",
    ]

    filtered: list[dict[str, Any]] = []
    removed = 0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            removed += 1
            continue
        text = _get_candidate_text(candidate, title_fields)
        candidate_tokens = set(_tokenize(text))
        score = _match_score(candidate_tokens, query_tokens)
        if score < min_match_ratio or len(candidate_tokens & query_tokens) < min_token_matches:
            removed += 1
            continue
        filtered.append(candidate)

    if removed:
        data.setdefault("filter", {})["match"] = {
            "removed": removed,
            "kept": len(filtered),
            "min_match_ratio": min_match_ratio,
            "min_token_matches": min_token_matches,
        }

    if not filtered and step_cfg.get("keep_original_on_empty"):
        return data

    work["candidates"] = filtered
    data["work"] = work
    return data


def rank_releases(
    data: dict[str, Any], step_cfg: dict[str, Any], context: Context
) -> dict[str, Any]:
    work = data.get("work", {})
    candidates = work.get("candidates", []) or []
    if not candidates:
        return data

    media_type = work.get("media_type") or data.get("request", {}).get("media_type")
    rules_cfg = context.config.get("quality_rules", {}) or {}
    rules = rules_cfg.get(media_type) or rules_cfg.get("default") or {}
    preferences = data.get("request", {}).get("preferences", {}) or {}
    rules = _apply_format_rules(rules, preferences)

    title_fields = step_cfg.get("title_fields") or rules.get(
        "title_fields",
        ["title", "name", "_raw.title", "_raw.name", "releaseTitle", "release_title"],
    )
    reject_rules = _normalize_rules(rules.get("reject") or [])
    score_rules = _normalize_rules(rules.get("score") or [])
    numeric_fields = rules.get("numeric_fields") or []
    sort_fields = rules.get("sort_fields")

    ranked: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in candidates:
        if isinstance(item, dict):
            candidate = dict(item)
        else:
            candidate = {"title": str(item)}
        text = _get_candidate_text(candidate, title_fields)
        derived = _derive_audio_fields(text)
        if derived:
            existing = candidate.get("derived")
            if isinstance(existing, dict):
                merged = dict(existing)
                for key, value in derived.items():
                    if key not in merged:
                        merged[key] = value
                candidate["derived"] = merged
            else:
                candidate["derived"] = derived
        score = float(rules.get("base_score") or 0.0)
        reasons = []
        rejected_match = False
        for rule in reject_rules:
            pattern = rule.get("match") or rule.get("regex")
            if not pattern:
                continue
            try:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    rejected_match = True
                    reasons.append(rule.get("label") or f"reject:{pattern}")
            except re.error:
                continue
        for rule in score_rules:
            pattern = rule.get("match") or rule.get("regex")
            if not pattern:
                continue
            try:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    add = float(rule.get("score", 0.0))
                    score += add
                    reasons.append(rule.get("label") or f"{pattern}:{add:+g}")
            except re.error:
                continue
        for entry in numeric_fields:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            if not path:
                continue
            value = _get_path(candidate, path)
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            scale = entry.get("scale")
            if scale:
                try:
                    numeric = numeric / float(scale)
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
            cap = entry.get("max")
            if cap is not None:
                try:
                    cap_value = float(cap)
                    if numeric > cap_value:
                        numeric = cap_value
                except (TypeError, ValueError):
                    pass
            weight = float(entry.get("weight", 1.0))
            score += numeric * weight
            reasons.append(entry.get("label") or f"{path}:{numeric}*{weight}")

        release_priority = rules.get("release_priority") or []
        if isinstance(release_priority, list) and release_priority:
            release_type_map = (context.config.get("redacted", {}) or {}).get("release_type_map", {})
            category = _release_category_for_candidate(candidate, release_type_map)
            if category in release_priority:
                weight = float(rules.get("release_priority_weight") or 50.0)
                bump = weight * (len(release_priority) - release_priority.index(category))
                score += bump
                reasons.append(f"release:{category}")

        rec = candidate.get("recommendation") or {}
        try:
            rec_score = float(rec.get("score") or 0.0)
        except (TypeError, ValueError):
            rec_score = 0.0
        if rec_score:
            score += rec_score
            reasons.append("recommendation")

        candidate["rank"] = {
            "score": score,
            "rejected": rejected_match,
            "reasons": reasons,
        }
        if rejected_match:
            rejected.append(candidate)
        else:
            ranked.append(candidate)

    if sort_fields:
        def sort_key(item: dict[str, Any]) -> tuple:
            values = []
            for entry in sort_fields:
                if not isinstance(entry, dict):
                    continue
                path = entry.get("path")
                if not path:
                    continue
                value = _get_path(item, path)
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    numeric = 0.0
                if entry.get("desc", True):
                    numeric *= -1
                values.append(numeric)
            return tuple(values)

        ranked.sort(key=sort_key)
    else:
        ranked.sort(
            key=lambda item: (
                -float(item.get("rank", {}).get("score", 0.0)),
                -float(_get_path(item, "seeders") or 0.0),
                -float(_get_path(item, "size") or 0.0),
            )
        )

    if rejected:
        work["rejected_candidates"] = rejected
    work["candidates"] = ranked
    data["work"] = work
    return data


def prowlarr_grab(
    data: dict[str, Any], step_cfg: dict[str, Any], context: Context
) -> dict[str, Any]:
    work = data.get("work", {})
    selected = work.get("selected")
    if not selected:
        return data
    if not isinstance(selected, dict):
        selected = {"title": str(selected)}
        work["selected"] = selected
    raw = selected.get("_raw")
    if isinstance(raw, dict):
        if not selected.get("guid") and raw.get("guid"):
            selected["guid"] = raw.get("guid")
        if not selected.get("indexer_id"):
            idx = raw.get("indexerId") or raw.get("indexer_id")
            if idx is not None:
                selected["indexer_id"] = idx

    media_type = work.get("media_type") or data.get("request", {}).get("media_type")
    prow_cfg = context.config.get("prowlarr", {})
    download_clients = prow_cfg.get("download_clients", {})
    if media_type and not work.get("download_client_id"):
        work["download_client_id"] = download_clients.get(media_type)
    if not work.get("download_client_id"):
        rules_cfg = prow_cfg.get("download_client_rules")
        if isinstance(rules_cfg, dict):
            rules = _select_media_mapping(rules_cfg, media_type)
        else:
            rules = rules_cfg
        resolved = _resolve_download_client_id(selected, rules if isinstance(rules, list) else None)
        if resolved is not None:
            work["download_client_id"] = resolved

    grab_cfg = prow_cfg.get("grab", {})
    request_cfg = step_cfg.get("request") or grab_cfg.get("request", {})
    if not request_cfg:
        return data
    rendered = render_template(request_cfg, data, context.config)
    url = rendered.get("url")
    if not url:
        base_url = prow_cfg.get("url")
        path = rendered.get("path") or grab_cfg.get("path")
        if base_url and path:
            url = base_url.rstrip("/") + "/" + str(path).lstrip("/")
    if not url:
        return data

    method = (rendered.get("method") or "POST").upper()
    headers = rendered.get("headers")
    params = rendered.get("params")
    json_body = rendered.get("json")
    form = rendered.get("form")
    if isinstance(json_body, dict):
        cleaned: dict[str, Any] = {}
        unresolved: list[str] = []
        for key, value in json_body.items():
            if value is None or value == "":
                continue
            if isinstance(value, str) and value.strip().startswith("{") and value.strip().endswith("}"):
                unresolved.append(key)
                continue
            cleaned[key] = value
        if unresolved:
            raise RuntimeError(f"prowlarr grab missing template values for: {', '.join(unresolved)}")
        json_body = cleaned

    if context.dry_run:
        data.setdefault("dispatch", {})["prowlarr"] = {
            "status": "dry_run",
            "request": {
                "method": method,
                "url": _redact_apikey(url),
                "headers": _redact_headers(headers),
                "params": params,
                "json": json_body,
                "form": form,
            },
        }
        data["work"] = work
        return data

    response = request_with_retry(
        method,
        url,
        headers=headers,
        params=params,
        json=json_body,
        data=form,
        timeout=step_cfg.get("timeout", prow_cfg.get("timeout", 30)),
        retries=int(step_cfg.get("retries") or 0),
        backoff_seconds=float(step_cfg.get("retry_backoff_seconds") or 0.5),
        max_backoff_seconds=float(step_cfg.get("max_backoff_seconds") or 8.0),
        retry_statuses=step_cfg.get("retry_statuses"),
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = {"text": response.text}

    data.setdefault("dispatch", {})["prowlarr"] = {
        "status": "ok",
        "response": payload,
        "url": _redact_apikey(url),
    }
    data["work"] = work
    return data


def decide(data: dict[str, Any], step_cfg: dict[str, Any], context: Context) -> dict[str, Any]:
    request = data.get("request", {}) or {}
    work = data.get("work", {})
    preselected = work.get("selected")
    if preselected is not None:
        index = None
        candidates = work.get("candidates", []) or []
        if candidates and preselected in candidates:
            index = candidates.index(preselected)
        data["decision"] = {"status": "selected", "selected": preselected, "index": index}
        data["work"] = work
        return data
    candidates = work.get("candidates", []) or []
    decision = {
        "status": "needs_choice",
        "reason": "no_candidates",
        "options": candidates,
    }

    if context.choice_index is not None and candidates:
        idx = context.choice_index
        if 0 <= idx < len(candidates):
            selected = candidates[idx]
            decision = {
                "status": "selected",
                "selected": selected,
                "index": idx,
            }
            work["selected"] = selected
            data["work"] = work
            data["decision"] = decision
            return data

    if request.get("explicit_version") and step_cfg.get("auto_select_explicit", True) and candidates:
        selected = candidates[0]
        decision = {
            "status": "selected",
            "selected": selected,
            "index": 0,
            "reason": "explicit_version",
        }
        work["selected"] = selected
        data["work"] = work
        data["decision"] = decision
        return data

    media_type = work.get("media_type") or data.get("request", {}).get("media_type")
    auto_formats = step_cfg.get("auto_select_formats")
    if auto_formats is None:
        auto_formats = True
    if auto_formats and media_type == "music" and len(candidates) > 1:
        def detect_format(candidate: dict[str, Any]) -> str | None:
            text = " ".join(
                [
                    str(candidate.get("title") or ""),
                    str(candidate.get("sort_title") or ""),
                ]
            ).lower()
            if re.search(r"\bflac\b", text):
                return "flac"
            if re.search(r"\bv0\b", text):
                return "v0"
            if re.search(r"\b320\b", text) and re.search(r"\bkbps\b|\b320k\b|\bmp3\b", text):
                return "320"
            return None

        preference = {"flac": 0, "v0": 1, "320": 2}
        detected: list[str | None] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                detected.append(None)
                continue
            detected.append(detect_format(candidate))
        available = {fmt for fmt in detected if fmt in preference}
        if available:
            best_pref = min(preference[fmt] for fmt in available)
            allowed_candidates = [
                cand
                for cand, fmt in zip(candidates, detected)
                if fmt in preference and preference[fmt] == best_pref
            ]
            if allowed_candidates:
                def score(candidate: dict[str, Any]) -> float:
                    rank = candidate.get("rank") or {}
                    try:
                        return float(rank.get("score") or 0.0)
                    except (TypeError, ValueError):
                        return 0.0
                selected = max(allowed_candidates, key=score)
                idx = candidates.index(selected)
                decision = {
                    "status": "selected",
                    "selected": selected,
                    "index": idx,
                    "reason": "auto_format",
                }
                work["selected"] = selected
                data["work"] = work
                data["decision"] = decision
                return data

    if len(candidates) == 1:
        selected = candidates[0]
        decision = {"status": "selected", "selected": selected, "index": 0}
        work["selected"] = selected
    elif len(candidates) > 1:
        decision = {
            "status": "needs_choice",
            "reason": "multiple_candidates",
            "options": candidates,
        }
    data["work"] = work
    data["decision"] = decision
    return data


def book_decide(data: dict[str, Any], step_cfg: dict[str, Any], context: Context) -> dict[str, Any]:
    """Placeholder for future book format decision logic."""
    return data


def ocr(data: dict[str, Any], step_cfg: dict[str, Any], context: Context) -> dict[str, Any]:
    request = data.get("request", {})
    image_path = request.get("image_path")
    if not image_path:
        return data
    cmd = step_cfg.get("command", "tesseract")
    lang = step_cfg.get("lang", "eng")
    try:
        proc = subprocess.run(
            [cmd, image_path, "stdout", "-l", lang],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("tesseract not found; install or configure ocr.command") from exc
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip())
    text = proc.stdout.strip()
    data.setdefault("ocr", {})["text"] = text
    if not request.get("query") and text:
        request["query"] = text
        data["request"] = request
    return data


def dispatch_http(data: dict[str, Any], step_cfg: dict[str, Any], context: Context) -> dict[str, Any]:
    request_cfg = step_cfg.get("request", {})
    rendered = render_template(request_cfg, data, context.config)
    url = rendered.get("url")
    if not url:
        raise RuntimeError("http dispatch missing request.url")
    method = (rendered.get("method") or "POST").upper()
    headers = rendered.get("headers")
    params = rendered.get("params")
    json_body = rendered.get("json")
    form = rendered.get("form")
    files = None
    file_path = rendered.get("file")
    step_key = step_cfg.get("_step", step_cfg.get("name", "http"))
    if context.dry_run:
        data.setdefault("dispatch", {})[step_key] = {
            "status": "dry_run",
            "request": {
                "method": method,
                "url": _redact_apikey(url),
                "headers": _redact_headers(headers),
                "params": params,
                "json": json_body,
                "form": form,
                "file": file_path,
            },
        }
        return data
    if file_path:
        path = Path(file_path)
        if not path.exists():
            raise RuntimeError(f"http dispatch file not found: {path}")
        files = {"file": path.open("rb")}
    try:
        response = request_with_retry(
            method,
            url,
            headers=headers,
            params=params,
            json=json_body,
            data=form,
            files=files,
            timeout=step_cfg.get("timeout", 30),
            retries=int(step_cfg.get("retries") or 0),
            backoff_seconds=float(step_cfg.get("retry_backoff_seconds") or 0.5),
            max_backoff_seconds=float(step_cfg.get("max_backoff_seconds") or 8.0),
            retry_statuses=step_cfg.get("retry_statuses"),
        )
    finally:
        if files:
            for handle in files.values():
                handle.close()
    response.raise_for_status()
    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = {"text": response.text}
    data.setdefault("dispatch", {})[step_key] = {
        "status": "ok",
        "response": payload,
        "url": _redact_apikey(url),
    }
    return data


def _arr_payload(media_type: str | None, work: dict[str, Any], arr_cfg: dict[str, Any]) -> dict[str, Any]:
    title = work.get("title")
    ids = work.get("ids", {}) or {}
    if media_type == "movie":
        payload = {
            "title": title,
            "tmdbId": ids.get("tmdb"),
            "qualityProfileId": arr_cfg.get("quality_profile_id"),
            "rootFolderPath": arr_cfg.get("root_folder"),
            "monitored": True,
            "minimumAvailability": arr_cfg.get("minimum_availability", "released"),
            "addOptions": {"searchForMovie": True},
        }
        return payload
    if media_type == "tv":
        payload = {
            "title": title,
            "tvdbId": ids.get("tvdb"),
            "qualityProfileId": arr_cfg.get("quality_profile_id"),
            "rootFolderPath": arr_cfg.get("root_folder"),
            "monitored": True,
            "seasonFolder": True,
            "seriesType": arr_cfg.get("series_type", "standard"),
            "addOptions": {"searchForMissingEpisodes": True},
        }
        return payload
    if media_type == "book":
        payload = {
            "title": title,
            "author": work.get("author"),
            "qualityProfileId": arr_cfg.get("quality_profile_id"),
            "rootFolderPath": arr_cfg.get("root_folder"),
            "monitored": True,
        }
        return payload
    return {"title": title}


def dispatch_arr(data: dict[str, Any], step_cfg: dict[str, Any], context: Context) -> dict[str, Any]:
    arr_name = step_cfg.get("arr")
    if not arr_name:
        raise RuntimeError("arr dispatcher missing 'arr' setting")
    arr_cfg = (context.config.get("arr") or {}).get(arr_name)
    if not arr_cfg:
        raise RuntimeError(f"arr config not found for {arr_name}")
    base_url = arr_cfg.get("url")
    endpoint = arr_cfg.get("endpoint")
    if not base_url or not endpoint:
        raise RuntimeError(f"arr config missing url/endpoint for {arr_name}")
    work = data.get("work", {})
    selected = work.get("selected", {})
    media_type = work.get("media_type")
    payload = arr_cfg.get("payload")
    if payload:
        payload = render_template(payload, data, context.config)
    else:
        payload = _arr_payload(media_type, selected or work, arr_cfg)
    headers = {
        "X-Api-Key": arr_cfg.get("api_key", ""),
    }
    url = base_url.rstrip("/") + endpoint
    if context.dry_run:
        data.setdefault("dispatch", {})[arr_name] = {
            "status": "dry_run",
            "request": {
                "method": "POST",
                "url": url,
                "headers": _redact_headers(headers),
                "json": payload,
            },
        }
        return data
    response = request_with_retry(
        "POST",
        url,
        json=payload,
        headers=headers,
        timeout=step_cfg.get("timeout", arr_cfg.get("timeout", 30)),
        retries=int(step_cfg.get("retries") or 0),
        backoff_seconds=float(step_cfg.get("retry_backoff_seconds") or 0.5),
        max_backoff_seconds=float(step_cfg.get("max_backoff_seconds") or 8.0),
        retry_statuses=step_cfg.get("retry_statuses"),
    )
    response.raise_for_status()
    try:
        payload_out = response.json()
    except json.JSONDecodeError:
        payload_out = {"text": response.text}
    data.setdefault("dispatch", {})[arr_name] = {
        "status": "ok",
        "response": payload_out,
        "url": url,
    }
    return data


def store_tags(data: dict[str, Any], step_cfg: dict[str, Any], context: Context) -> dict[str, Any]:
    request = data.get("request", {})
    tags = request.get("tags", [])
    if not tags:
        return data
    work = data.get("work", {})
    title = work.get("title") or request.get("query") or "unknown"
    media_type = work.get("media_type") or request.get("media_type") or "unknown"
    slug = "".join(ch if ch.isalnum() else "-" for ch in title.lower()).strip("-")
    filename = f"{slug}.json" if slug else "unknown.json"
    base = Path(context.state_path) / "tags" / media_type
    base.mkdir(parents=True, exist_ok=True)
    payload = {
        "title": title,
        "media_type": media_type,
        "tags": tags,
        "stored_at": datetime.now(timezone.utc).isoformat(),
    }
    with (base / filename).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)
    data.setdefault("tags", {})["stored"] = str(base / filename)
    return data


BUILTINS = {
    "identify": identify,
    "identify_web_search": identify_web_search,
    "determine_media_type": determine_media_type,
    "decide": decide,
    "ocr": ocr,
    "http_dispatch": dispatch_http,
    "arr_dispatch": dispatch_arr,
    "extract_release_preferences": extract_release_preferences,
    "prowlarr_search": prowlarr_search,
    "filter_candidates": filter_candidates,
    "filter_match": filter_match,
    "fetch_url": fetch_url,
    "resolve_track_release": resolve_track_release,
    "redacted_enrich": redacted_enrich,
    "redacted_comments": redacted_comments,
    "apply_recommendations": apply_recommendations,
    "filter_by_version": filter_by_version,
    "rank_releases": rank_releases,
    "prowlarr_grab": prowlarr_grab,
    "store_tags": store_tags,
    "book_decide": book_decide,
}
