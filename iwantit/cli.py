"""CLI entrypoint for iwantit."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .config import (
    ensure_config_exists,
    load_config,
    save_default_config,
    save_default_secrets,
    validate_config,
)
from .registry import provider_required_keys
from .step_metadata import STEP_METADATA
from .pipeline import Context, run_workflow
from .paths import ensure_dir, state_dir
from .steps.builtin import BUILTINS
from .util import (
    cache_key,
    classify_exception,
    coerce_tags,
    is_stdin_tty,
    is_stdout_tty,
    normalize_request_input,
    parse_kv_pairs,
    redact_payload,
    read_json,
    read_stdin,
    write_json,
)

EXIT_NEEDS_CHOICE = 20
_FAILED_QUERIES_REL = Path("diagnostics") / "failed_queries.jsonl"
_COMPACT_LIST_KEYS = {"results", "candidates", "options"}
_COMPACT_ITEM_KEYS = [
    "title",
    "name",
    "release",
    "artist",
    "authors",
    "author",
    "label",
    "year",
    "date",
    "url",
    "link",
    "guid",
    "id",
    "indexer",
    "indexerId",
    "snippet",
    "description",
    "summary",
    "size",
    "seeders",
    "leechers",
    "peers",
    "category",
    "categories",
    "format",
    "bitrate",
    "quality",
    "media_type",
    "type",
    "language",
    "codec",
    "edition",
    "tags",
    "score",
    "rank",
    "imdb",
    "tmdb",
    "tvdb",
    "season",
    "episode",
    "magnet",
    "downloadUrl",
    "tracker",
    "infoHash",
    "group_id",
    "torrent_id",
]


def _load_json_file(path: str) -> dict[str, Any]:
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _coerce_request_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        if "request" in data:
            return data
        return {"request": data}
    payload: dict[str, Any] = {"input": data, "input_type": "json"}
    if isinstance(data, str):
        payload["query"] = data
    return {"request": payload}


def _normalize_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    request = payload.get("request")
    if isinstance(request, dict):
        normalize_request_input(request)
    return payload


def _finalize_output(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"result": data, "decision": {"status": "complete"}}
    data.setdefault("request", {})
    data.setdefault("work", {})
    data.setdefault("decision", {"status": "complete"})
    data.setdefault("search", {})
    data.setdefault("dispatch", {})
    data.setdefault("tags", {})
    data.setdefault("canonical", {})
    data.setdefault("warnings", [])
    if "run_id" not in data and isinstance(data.get("_meta"), dict):
        run_id = data["_meta"].get("run_id")
        if run_id:
            data["run_id"] = run_id
    if data.get("error") and data["decision"].get("status") != "error":
        data["decision"]["status"] = "error"
    return data


def _should_log_failure(result: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    decision_status = (result.get("decision") or {}).get("status")
    if decision_status == "error":
        reasons.append("error")
    work = result.get("work") or {}
    request = result.get("request") or {}
    media_type = work.get("media_type") or request.get("media_type")
    if media_type == "music":
        if not work.get("artist"):
            reasons.append("missing_artist")
        if not work.get("title"):
            reasons.append("missing_title")
    else:
        if not work.get("title"):
            reasons.append("missing_title")
    candidates = work.get("candidates") or []
    if decision_status == "needs_choice" and not candidates:
        reasons.append("no_candidates")
    query = request.get("query")
    query_original = request.get("query_original")
    if isinstance(query, str) and isinstance(query_original, str):
        if query.strip() == query_original.strip():
            reasons.append("query_unrefined")
    return (len(reasons) > 0), reasons


def _hash_value(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if not value:
        return None
    return cache_key({"value": value})


def _sanitize_input(value: Any) -> dict[str, Any]:
    info: dict[str, Any] = {"length": None, "hash": None, "domain": None}
    if value is None:
        return info
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if not value:
        return info
    info["length"] = len(value)
    info["hash"] = _hash_value(value)
    try:
        parsed = urlparse(value)
    except ValueError:
        return info
    if parsed.scheme and parsed.netloc:
        info["domain"] = parsed.netloc
    return info


def _log_failed_query(result: dict[str, Any], *, enabled: bool = True) -> None:
    if not enabled:
        return
    should_log, reasons = _should_log_failure(result)
    if not should_log:
        return
    work = result.get("work") or {}
    request = result.get("request") or {}
    search = result.get("search") or {}
    url_meta = result.get("url") or {}
    sanitized_url = None
    if isinstance(url_meta, dict):
        domain = None
        try:
            url_val = url_meta.get("url")
            if isinstance(url_val, str):
                parsed = urlparse(url_val)
                if parsed.netloc:
                    domain = parsed.netloc
        except ValueError:
            domain = None
        sanitized_url = {
            "domain": domain,
            "release_date": url_meta.get("release_date"),
            "release_year": url_meta.get("release_year"),
        }
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "reasons": reasons,
        "input": _sanitize_input(request.get("input")),
        "input_type": request.get("input_type"),
        "query": _sanitize_input(request.get("query")),
        "query_original": _sanitize_input(request.get("query_original")),
        "media_type": work.get("media_type") or request.get("media_type"),
        "work": {
            "artist": work.get("artist"),
            "title": work.get("title"),
            "year": work.get("year"),
        },
        "decision": {
            "status": (result.get("decision") or {}).get("status"),
            "reason": (result.get("decision") or {}).get("reason"),
            "index": (result.get("decision") or {}).get("index"),
        },
        "url": sanitized_url,
        "search_counts": {
            key: (val.get("count") if isinstance(val, dict) else None)
            for key, val in search.items()
        },
    }
    base = ensure_dir(state_dir())
    path = ensure_dir(base / _FAILED_QUERIES_REL.parent) / _FAILED_QUERIES_REL.name
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")


def _safe_error_message(exc: Exception) -> str:
    return str(redact_payload(str(exc)))


def _print_result_summary(result: dict[str, Any], args: argparse.Namespace) -> None:
    if getattr(args, "quiet", False):
        return
    if not sys.stderr.isatty():
        return
    request = result.get("request") or {}
    work = result.get("work") or {}
    decision = result.get("decision") or {}
    media_type = work.get("media_type") or request.get("media_type") or "unknown"
    artist = work.get("artist")
    title = work.get("title")
    year = work.get("year")
    if artist and title:
        suffix = f" ({year})" if year else ""
        sys.stderr.write(f"Parsed: {artist} — {title}{suffix}\n")
    elif title:
        suffix = f" ({year})" if year else ""
        sys.stderr.write(f"Parsed: {title}{suffix}\n")
    sys.stderr.write(f"Media: {media_type}\n")
    query = request.get("query")
    if isinstance(query, str) and query.strip():
        sys.stderr.write(f"Query: {query}\n")
    status = decision.get("status") or "unknown"
    reason = decision.get("reason")
    if reason:
        sys.stderr.write(f"Decision: {status} ({reason})\n")
    else:
        sys.stderr.write(f"Decision: {status}\n")
    warnings = result.get("warnings") or []
    if warnings:
        sys.stderr.write("Warnings:\n")
        for warning in warnings[:3]:
            if isinstance(warning, dict):
                step = warning.get("step") or "unknown"
                msg = warning.get("message") or warning.get("type") or "unknown"
                sys.stderr.write(f"- {step}: {msg}\n")
            else:
                sys.stderr.write(f"- {warning}\n")
        if len(warnings) > 3:
            sys.stderr.write(f"- (+{len(warnings) - 3} more)\n")
    if status == "needs_choice":
        sys.stderr.write("Next: pipe to chooser with `iwantit choose --stdin`\n")
        sys.stderr.write("Example: `iwantit run ... | iwantit choose --stdin --interactive`\n")
    if status == "error":
        sys.stderr.write("Next: rerun with `--media-type` or `--workflow` if detection is wrong.\n")


def _slim_categories(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    slimmed = []
    for item in value:
        if not isinstance(item, dict):
            slimmed.append(item)
            continue
        out: dict[str, Any] = {}
        if "id" in item:
            out["id"] = item.get("id")
        if "name" in item:
            out["name"] = item.get("name")
        if out:
            slimmed.append(out)
        else:
            slimmed.append(item)
    return slimmed


def _slim_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    out: dict[str, Any] = {}
    for key in _COMPACT_ITEM_KEYS:
        if key not in item:
            continue
        value = item.get(key)
        if value in (None, "", [], {}):
            continue
        if key == "rank" and isinstance(value, dict):
            rank_out: dict[str, Any] = {}
            if "score" in value:
                rank_out["score"] = value.get("score")
            reasons = value.get("reasons")
            if isinstance(reasons, list) and reasons:
                rank_out["reasons"] = reasons[:3]
            if rank_out:
                out[key] = rank_out
            continue
        if key == "categories":
            out[key] = _slim_categories(value)
            continue
        out[key] = value
    if out:
        return out
    fallback: dict[str, Any] = {}
    for key, value in item.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            fallback[key] = value
        if len(fallback) >= 6:
            break
    return fallback or item


def _compact_output(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, val in value.items():
            if isinstance(val, list) and key in _COMPACT_LIST_KEYS:
                out[key] = [_slim_item(item) for item in val]
                continue
            out[key] = _compact_output(val)
        return out
    if isinstance(value, list):
        return [_compact_output(item) for item in value]
    return value


def _build_request(args: argparse.Namespace) -> dict[str, Any]:
    if args.json:
        data = _load_json_file(args.json)
        return _normalize_request_payload(_coerce_request_payload(data))

    if args.stdin or (not is_stdin_tty() and not (args.text or args.url or args.image)):
        raw = read_stdin().strip()
        if not raw:
            return {"request": {}}
        try:
            data = read_json(raw)
            return _normalize_request_payload(_coerce_request_payload(data))
        except json.JSONDecodeError:
            payload = {"request": {"input": raw, "input_type": "text", "query": raw}}
            return _normalize_request_payload(payload)

    input_value = args.text or args.url or args.image
    input_type = "text"
    request: dict[str, Any] = {}
    if args.url:
        input_type = "url"
    elif args.image:
        input_type = "image"
        request["image_path"] = args.image
    request["input"] = input_value
    request["input_type"] = input_type
    if args.text or args.url:
        request["query"] = input_value

    if args.media_type:
        request["media_type"] = args.media_type

    request["tags"] = coerce_tags(args.tag)
    prefs = parse_kv_pairs(args.pref)
    if getattr(args, "book_format", None):
        prefs["book_format"] = args.book_format
    request["preferences"] = prefs

    return _normalize_request_payload({"request": request})


def _build_request_from_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return _normalize_request_payload(_coerce_request_payload(item))
    payload = {"request": {"input": item, "input_type": "text", "query": str(item)}}
    return _normalize_request_payload(payload)


def _load_batch_inputs(path: str) -> list[Any]:
    if path == "-":
        raw = read_stdin()
    else:
        raw = Path(path).expanduser().read_text(encoding="utf-8")
    raw = raw.strip()
    if not raw:
        return []
    try:
        data = read_json(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
    except json.JSONDecodeError:
        pass
    items = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(read_json(line))
        except json.JSONDecodeError:
            items.append(line)
    return items


def cmd_init(args: argparse.Namespace) -> int:
    cfg_path = save_default_config(path=Path(args.config).expanduser() if args.config else None, overwrite=args.force)
    save_default_secrets(overwrite=False)
    sys.stdout.write(f"Initialized config at {cfg_path}\n")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cfg_path = ensure_config_exists(args.config)
    config = load_config(cfg_path)
    if getattr(args, "batch", None):
        items = _load_batch_inputs(args.batch)
        if not items:
            write_json({"summary": {"total": 0, "selected": 0, "needs_choice": 0, "error": 0}, "results": []})
            return 0
        results = [None] * len(items)
        summary = {"total": len(items), "selected": 0, "needs_choice": 0, "error": 0}

        def run_item(idx: int, item: Any) -> None:
            data = _build_request_from_item(item)
            data["_meta"] = {"config_path": str(cfg_path)}
            result = run_workflow(
                config,
                data,
                BUILTINS,
                workflow_name=args.workflow,
                choice_index=args.choice,
                start_step=args.from_step,
                end_step=args.until_step,
                dry_run=args.dry_run,
                confirm=getattr(args, "confirm", False),
            )
            if isinstance(result, dict):
                result.pop("_meta", None)
                result.pop("_config_path", None)
            results[idx] = _finalize_output(result)

        if args.jobs is None:
            jobs = int((config.get("concurrency", {}) or {}).get("default") or 1)
        else:
            jobs = int(args.jobs or 1)
        if jobs > 1:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=jobs) as executor:
                futures = [executor.submit(run_item, idx, item) for idx, item in enumerate(items)]
                for fut in futures:
                    fut.result()
        else:
            for idx, item in enumerate(items):
                run_item(idx, item)

        for result in results:
            if not isinstance(result, dict):
                continue
            status = (result.get("decision") or {}).get("status")
            if status == "selected":
                summary["selected"] += 1
            elif status == "needs_choice":
                summary["needs_choice"] += 1
            elif status == "error" or result.get("error"):
                summary["error"] += 1
        output = {"summary": summary, "results": results}
        if not args.full:
            output = _compact_output(output)
        write_json(output)
        if summary["error"] > 0:
            return 1
        if summary["needs_choice"] > 0:
            return EXIT_NEEDS_CHOICE
        return 0

    data = _build_request(args)
    data["_meta"] = {"config_path": str(cfg_path)}
    progress = None
    if not getattr(args, "quiet", False):
        progress_messages = {
            "ocr": "OCRing image",
            "fetch_url": "Fetching URL metadata",
            "identify": "Normalizing input",
            "identify_web_search": "Verifying release via web search",
            "extract_release_preferences": "Extracting release preferences",
            "determine_media_type": "Determining media type",
            "resolve_track_release": "Resolving track to release",
            "prowlarr_search": "Searching Prowlarr",
            "filter_candidates": "Filtering candidates by category",
            "filter_match": "Filtering candidates by query match",
            "redacted_enrich": "Enriching tracker metadata",
            "filter_by_version": "Filtering by requested version",
            "book_decide": "Filtering by book format",
            "rank_releases": "Ranking candidates",
            "decide": "Selecting best release",
            "prowlarr_grab": "Sending release to Prowlarr",
            "store_tags": "Storing tags",
            "dispatch_radarr": "Sending release to Radarr",
            "dispatch_sonarr": "Sending release to Sonarr",
        }

        def _progress(step: str, phase: str, payload: dict[str, Any]) -> None:
            if phase == "start":
                message = progress_messages.get(step)
                if message:
                    sys.stderr.write(f"{message}\n")
                return
            if phase != "end":
                return
            if step == "determine_media_type":
                work = payload.get("work", {}) or {}
                request = payload.get("request", {}) or {}
                media = work.get("media_type") or request.get("media_type")
                if media:
                    sys.stderr.write(f"Media type: {media}\n")
            if step in {"prowlarr_grab", "dispatch_radarr", "dispatch_sonarr"}:
                dispatch_key = {
                    "prowlarr_grab": "prowlarr",
                    "dispatch_radarr": "radarr",
                    "dispatch_sonarr": "sonarr",
                }[step]
                target = {
                    "prowlarr_grab": "Prowlarr",
                    "dispatch_radarr": "Radarr",
                    "dispatch_sonarr": "Sonarr",
                }[step]
                entry = (payload.get("dispatch") or {}).get(dispatch_key) or {}
                status = entry.get("status")
                if status in {"ok", "dry_run"}:
                    suffix = " (dry run)" if status == "dry_run" else ""
                    sys.stderr.write(f"Release sent to {target}{suffix}\n")
                if status == "skipped" and entry.get("reason") == "needs_confirm":
                    sys.stderr.write(f"Release not sent to {target} (add --confirm)\n")

        progress = _progress
    result = run_workflow(
        config,
        data,
        BUILTINS,
        workflow_name=args.workflow,
        choice_index=args.choice,
        start_step=args.from_step,
        end_step=args.until_step,
        dry_run=args.dry_run,
        confirm=getattr(args, "confirm", False),
        progress=progress,
    )
    if isinstance(result, dict):
        result.pop("_meta", None)
        result.pop("_config_path", None)
    result = _finalize_output(result)
    diag_cfg = config.get("diagnostics", {}) or {}
    failed_cfg = diag_cfg.get("failed_queries", {}) if isinstance(diag_cfg, dict) else {}
    enabled = True
    if isinstance(failed_cfg, dict) and "enabled" in failed_cfg:
        enabled = bool(failed_cfg.get("enabled"))
    _log_failed_query(result, enabled=enabled)
    _print_result_summary(result, args)
    if not args.full:
        result = _compact_output(result)
    write_json(result)
    if result.get("error"):
        return 1
    if result.get("decision", {}).get("status") == "needs_choice":
        return EXIT_NEEDS_CHOICE
    return 0


def cmd_step(args: argparse.Namespace) -> int:
    data = _build_request(args)
    step = BUILTINS.get(args.name)
    if not step:
        sys.stderr.write(f"unknown step: {args.name}\n")
        return 1
    config = load_config(ensure_config_exists(args.config))
    ensure_dir(state_dir())
    context = Context(
        config=config,
        state_path=str(state_dir()),
        choice_index=args.choice,
        dry_run=args.dry_run,
        confirm=getattr(args, "confirm", False),
    )
    step_cfg = config.get("steps", {}).get(args.name, {"builtin": args.name})
    step_cfg = dict(step_cfg)
    step_cfg.setdefault("_step", args.name)
    try:
        result = step(data, step_cfg, context)
    except Exception as exc:
        code, hint = classify_exception(exc)
        result = {
            "error": {
                "message": _safe_error_message(exc),
                "step": args.name,
                "type": exc.__class__.__name__,
                "code": code,
                "hint": hint,
            }
        }
    output = _finalize_output(result)
    if not args.full:
        output = _compact_output(output)
    write_json(output)
    return 0 if not result.get("error") else 1


def _load_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.json:
        data = _load_json_file(args.json)
        if isinstance(data, dict):
            return data
        return {"data": data}
    if args.stdin or not is_stdin_tty():
        raw = read_stdin().strip()
        if not raw:
            return {}
        try:
            data = read_json(raw)
        except json.JSONDecodeError:
            raise ValueError("stdin did not contain valid JSON")
        if isinstance(data, dict):
            return data
        return {"data": data}
    raise ValueError("choose requires --json or --stdin")


def _option_label(option: Any, max_len: int | None = 160) -> str:
    if isinstance(option, dict):
        for key in ("title", "name", "release", "label"):
            if key in option and option[key]:
                label = str(option[key])
                if max_len is None or len(label) <= max_len:
                    return label
                return label[: max_len - 3] + "..."
        label = json.dumps(option, ensure_ascii=True)
        if max_len is None or len(label) <= max_len:
            return label
        return label[: max_len - 3] + "..."
    label = str(option)
    if max_len is None or len(label) <= max_len:
        return label
    return label[: max_len - 3] + "..."


def _select_index(options: list[Any], token: str) -> int | None:
    token = token.strip()
    if token.isdigit():
        idx = int(token)
        if 0 <= idx < len(options):
            return idx
        raise ValueError("selection index out of range")
    lowered = token.lower()
    matches = [
        idx for idx, opt in enumerate(options) if lowered in _option_label(opt, None).lower()
    ]
    if not matches:
        raise ValueError("no matching option found")
    if len(matches) > 1:
        raise ValueError("multiple options match; use a numeric index")
    return matches[0]


def cmd_choose(args: argparse.Namespace) -> int:
    try:
        data = _load_payload(args)
    except ValueError as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1
    options = []
    if isinstance(data, dict):
        options = data.get("decision", {}).get("options") or data.get("work", {}).get("candidates") or []
    if not options:
        sys.stderr.write("no options available\n")
        return 1

    def _score(option: Any) -> float | None:
        if isinstance(option, dict):
            rank = option.get("rank") or {}
            try:
                return float(rank.get("score"))
            except (TypeError, ValueError):
                return None
        return None

    def _year(option: Any) -> int | None:
        if isinstance(option, dict):
            value = option.get("year") or option.get("release_year")
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        return None

    def _matches_format(option: Any, fmt: str) -> bool:
        if not isinstance(option, dict):
            return False
        text = " ".join(
            [
                str(option.get("title") or ""),
                str(option.get("name") or ""),
                str(option.get("format") or ""),
                str(option.get("codec") or ""),
                str(option.get("bitrate") or ""),
            ]
        ).lower()
        return fmt.lower() in text

    if args.min_score is not None:
        options = [opt for opt in options if (_score(opt) is not None and _score(opt) >= args.min_score)]
    if args.year is not None:
        options = [opt for opt in options if _year(opt) == args.year]
    if args.format_hint:
        options = [opt for opt in options if _matches_format(opt, args.format_hint)]

    if args.select is None:
        for idx, opt in enumerate(options):
            label = _option_label(opt)
            if not args.verbose and isinstance(opt, dict):
                score = opt.get("rank", {}).get("score")
                if score is not None:
                    label = f"{label} (score={score:.2f})"
                if args.preview:
                    extras = []
                    for key in ("artist", "year", "format", "bitrate", "seeders", "indexer"):
                        if opt.get(key):
                            extras.append(f"{key}={opt.get(key)}")
                    if extras:
                        label = f"{label} | {', '.join(extras)}"
                if args.explain:
                    reasons = opt.get("rank", {}).get("reasons") or []
                    if reasons:
                        label = f"{label} | reasons: {', '.join(reasons[:3])}"
            if args.verbose and isinstance(opt, dict):
                label = json.dumps(opt, ensure_ascii=True)
            sys.stdout.write(f"{idx}: {label}\n")
        if args.interactive and is_stdout_tty():
            try:
                selection = input("Select index: ").strip()
            except EOFError:
                return 0
            if selection:
                args.select = selection
            else:
                return 0
        else:
            return 0
    try:
        idx = _select_index(options, args.select)
    except ValueError as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1
    if args.emit == "json":
        work = data.setdefault("work", {})
        work["selected"] = options[idx]
        data["decision"] = {"status": "selected", "selected": options[idx], "index": idx}
        output = _finalize_output(data)
        if not args.full:
            output = _compact_output(output)
        write_json(output)
        return 0
    if args.emit == "flag":
        sys.stdout.write(f"--choice {idx}\n")
        return 0
    sys.stdout.write(f"{idx}\n")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    config = load_config(ensure_config_exists(args.config))
    if args.kind == "workflows":
        for wf in config.get("workflows", []) or []:
            name = wf.get("name", "unknown")
            steps = ", ".join(wf.get("steps", []) or [])
            sys.stdout.write(f"{name}: {steps}\n")
        return 0
    if args.kind == "steps":
        for name, step in (config.get("steps", {}) or {}).items():
            if "builtin" in step:
                sys.stdout.write(f"{name}: builtin={step.get('builtin')}\n")
            elif "command" in step:
                sys.stdout.write(f"{name}: command={step.get('command')}\n")
            else:
                sys.stdout.write(f"{name}: builtin={name}\n")
        plugins = config.get("_plugins") or []
        if plugins:
            sys.stdout.write("plugins:\n")
            for plugin in plugins:
                if isinstance(plugin, dict):
                    sys.stdout.write(f"- {plugin.get('name')} {plugin.get('version')} ({plugin.get('path')})\n")
        return 0
    sys.stderr.write("unknown list kind\n")
    return 1


def cmd_validate(args: argparse.Namespace) -> int:
    config = load_config(ensure_config_exists(args.config))
    errors, warnings = validate_config(config, list(BUILTINS.keys()))
    for warning in warnings:
        sys.stderr.write(f"warning: {warning}\n")
    for error in errors:
        sys.stderr.write(f"error: {error}\n")
    return 1 if errors else 0


def _check_service(name: str, url: str, headers: dict[str, str] | None, timeout: float = 5.0) -> tuple[bool, str]:
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        if response.status_code in {401, 403}:
            return False, f"{name} auth failed ({response.status_code})"
        response.raise_for_status()
        return True, f"{name} ok"
    except requests.RequestException as exc:
        return False, f"{name} error: {_safe_error_message(exc)}"


def cmd_doctor(args: argparse.Namespace) -> int:
    config = load_config(ensure_config_exists(args.config))
    errors, warnings = validate_config(config, list(BUILTINS.keys()))
    failed = False
    for warning in warnings:
        sys.stderr.write(f"warning: {warning}\n")
    for error in errors:
        sys.stderr.write(f"error: {error}\n")
        failed = True

    prowlarr = config.get("prowlarr", {}) or {}
    if prowlarr.get("url") and prowlarr.get("api_key") and prowlarr.get("api_key") != "CHANGE_ME":
        url = prowlarr["url"].rstrip("/") + "/api/v1/system/status"
        ok, msg = _check_service("prowlarr", url, {"X-Api-Key": prowlarr["api_key"]})
        sys.stderr.write(msg + "\n")
        failed = failed or not ok

    arr = config.get("arr", {}) or {}
    for key, label in (("radarr", "radarr"), ("sonarr", "sonarr")):
        cfg = arr.get(key) or {}
        if cfg.get("url") and cfg.get("api_key") and cfg.get("api_key") != "CHANGE_ME":
            url = cfg["url"].rstrip("/") + "/api/v3/system/status"
            ok, msg = _check_service(label, url, {"X-Api-Key": cfg["api_key"]})
            sys.stderr.write(msg + "\n")
            failed = failed or not ok

    redacted = config.get("redacted", {}) or {}
    if redacted.get("url") and redacted.get("api_key") and redacted.get("api_key") != "CHANGE_ME":
        url = redacted["url"].rstrip("/") + "/ajax.php?action=index"
        ok, msg = _check_service("redacted", url, {"Authorization": redacted["api_key"]})
        sys.stderr.write(msg + "\n")
        failed = failed or not ok

    web = config.get("web_search", {}) or {}
    provider = web.get("provider")
    providers = web.get("providers", {}) or {}
    if provider and provider in providers:
        api_key = providers.get(provider, {}).get("api_key")
        if not api_key or api_key == "CHANGE_ME":
            sys.stderr.write(f"warning: web_search.providers.{provider}.api_key is not set\n")
            failed = True

    return 1 if failed else 0


def cmd_help(args: argparse.Namespace) -> int:
    topic = (args.topic or "overview").lower()
    cfg_path = None
    config = {}
    try:
        cfg_path = ensure_config_exists(None)
        config = load_config(cfg_path)
    except Exception:
        config = {}
    config_template = (
        "Minimal config template:\n"
        "  web_search:\n"
        "    provider: kagi\n"
        "    providers:\n"
        "      kagi:\n"
        "        api_key: ${ENV:KAGI_SEARCH_API_KEY}\n"
        "  prowlarr:\n"
        "    url: http://localhost:9696\n"
        "    api_key: CHANGE_ME\n"
        "  arr:\n"
        "    radarr:\n"
        "      url: http://localhost:7878\n"
        "      api_key: CHANGE_ME\n"
        "      root_folder: /media/movies\n"
        "      quality_profile_id: 1\n"
        "      endpoint: /api/v3/movie\n"
        "    sonarr:\n"
        "      url: http://localhost:8989\n"
        "      api_key: CHANGE_ME\n"
        "      root_folder: /media/tv\n"
        "      quality_profile_id: 1\n"
        "      endpoint: /api/v3/series\n"
        "  redacted:\n"
        "    url: https://redacted.sh\n"
        "    api_key: CHANGE_ME\n"
    )
    docs = {
        "overview": (
            "IWantIt quick help\n"
            "\n"
            "Install + init:\n"
            "  uv tool install .\n"
            "  iwantit init\n"
            "\n"
            "Run:\n"
            "  iwantit run --text \"Artist - Album\"\n"
            "  iwantit run --url \"https://...\"\n"
            "  iwantit run --text \"...\" --confirm   # allow dispatch/grab\n"
            "  iwantit run --batch inputs.jsonl --jobs 4\n"
            "\n"
            "When you see decision.status=needs_choice:\n"
            "  iwantit run ... | iwantit choose --stdin --interactive\n"
            "  iwantit run ... --choice N [--confirm]\n"
            "\n"
            "Doctor:\n"
            "  iwantit doctor\n"
            "\n"
            "More:\n"
            "  iwantit help config     # required config and env vars\n"
            "  iwantit help json       # input/output JSON contract\n"
            "  iwantit help safety     # dry-run vs confirm\n"
            "  iwantit help exit-codes # automation semantics\n"
            "  iwantit help errors     # error codes\n"
        ),
        "config": (
            "Config locations:\n"
            "  ~/.config/iwantit/config.yaml (override with IWANTIT_CONFIG)\n"
            "  ~/.config/iwantit/secrets.yaml (override with IWANTIT_SECRETS)\n"
            "\n"
            "Minimum config for common integrations:\n"
            "  Prowlarr: prowlarr.url, prowlarr.api_key\n"
            "  Web search: web_search.provider + provider api_key\n"
            "  Radarr: arr.radarr.url, arr.radarr.api_key (optional)\n"
            "  Sonarr: arr.sonarr.url, arr.sonarr.api_key (optional)\n"
            "  Redacted: redacted.url, redacted.api_key (optional)\n"
            "\n"
            "Use --verbose for a minimal config template.\n"
        ),
        "json": (
            "Input JSON (stdin or file):\n"
            "  { \"request\": { \"input\": \"...\", \"input_type\": \"text|url|image\", \"query\": \"...\" } }\n"
            "\n"
            "Output JSON (always):\n"
            "  run_id, request, work, decision, search, dispatch, tags, canonical, logs, report, error\n"
            "\n"
            "Notes:\n"
            "  - URL-like input is auto-detected and treated as input_type=url.\n"
            "  - Output arrays are compact by default; use --full for full items.\n"
        ),
        "safety": (
            "Safety model:\n"
            "  --dry-run: executes read-only steps but skips network side effects.\n"
            "  --confirm: allows dispatch/grab steps to run.\n"
            "\n"
            "Side-effect steps include:\n"
        ),
        "exit-codes": (
            "Exit codes:\n"
            "  0  success / selected\n"
            "  1  error\n"
            "  20 decision.status=needs_choice\n"
        ),
        "errors": (
            "Common error codes:\n"
            "  AUTH_MISSING  Missing API key or credentials\n"
            "  AUTH_FAILED   Invalid credentials or forbidden\n"
            "  NETWORK_ERROR Provider unreachable or network issue\n"
            "  TIMEOUT       Request or command timed out\n"
            "  PARSE_ERROR   Invalid JSON or parse error\n"
            "  CONFIG_ERROR  Invalid configuration\n"
            "  NOT_FOUND     Missing file or resource\n"
            "  STEP_FAILED   External step exited non-zero\n"
            "  STEP_ERROR    Generic step error\n"
            "\n"
            "Each error includes a hint field for remediation.\n"
        ),
    }
    if topic not in docs:
        sys.stderr.write(f"unknown help topic: {topic}\n")
        sys.stderr.write("available: overview, config, json, safety, exit-codes, errors\n")
        return 1
    output = docs[topic]
    if topic == "config" and config:
        req = provider_required_keys(config)
        if req:
            lines = ["\nActive providers (required keys):"]
            for name, keys in sorted(req.items()):
                if not keys:
                    continue
                lines.append(f"  - {name}: {', '.join(keys)}")
            output = output + "\n" + "\n".join(lines)
    if topic == "safety":
        side_effects = [name for name, meta in STEP_METADATA.items() if meta.get("side_effect")]
        if side_effects:
            output = output + "\n  " + ", ".join(sorted(side_effects)) + "\n"
    if topic == "config" and getattr(args, "verbose", False):
        output = output + "\n" + config_template
    sys.stdout.write(output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    epilog = (
        "Examples:\n"
        "  iwantit init\n"
        "  iwantit run --text \"Pink Floyd - Dark Side of the Moon\"\n"
        "  iwantit run --url \"https://open.spotify.com/album/...\"\n"
        "  iwantit run --text \"...\" --confirm   (allow dispatch/grab)\n"
        "  iwantit run ... | iwantit choose --stdin --interactive\n"
        "  iwantit run --batch inputs.jsonl --jobs 4\n"
        "  iwantit doctor\n"
        "\n"
        "Notes:\n"
        "  - URL-like input is auto-detected (stdin/JSON too).\n"
        "  - Output JSON is compact by default; use --full for full arrays.\n"
        "  - Exit code 20 means decision.status=needs_choice.\n"
        "\n"
        "More help:\n"
        "  iwantit help [overview|config|json|safety|exit-codes|errors]\n"
    )
    parser = argparse.ArgumentParser(
        prog="iwantit",
        description="Extensible media workflow runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="Path to config file (or set IWANTIT_CONFIG)")
    common.add_argument("--quiet", action="store_true", help="Suppress progress output")
    common.add_argument(
        "--full",
        action="store_true",
        help="Show full JSON output (disable compact result arrays)",
    )

    input_group = argparse.ArgumentParser(add_help=False)
    source = input_group.add_mutually_exclusive_group()
    source.add_argument("--text", help="Text input")
    source.add_argument("--url", help="URL input")
    source.add_argument("--image", help="Image path input")
    source.add_argument("--json", help="JSON file input")
    source.add_argument("--stdin", action="store_true", help="Read JSON or text from stdin")
    input_group.add_argument("--media-type", help="Media type override (music, movie, tv, book)")
    input_group.add_argument("--tag", action="append", help="Tag to attach", default=[])
    input_group.add_argument("--pref", action="append", help="Preference key=value", default=[])
    input_group.add_argument(
        "--book-format",
        choices=["ebook", "audiobook", "both"],
        help="Book format preference (ebook, audiobook, or both)",
    )
    input_group.add_argument("--choice", type=int, help="Choice index for selection")
    input_group.add_argument("--dry-run", action="store_true", help="Do not perform network side effects")
    input_group.add_argument(
        "--confirm",
        action="store_true",
        help="Allow side-effecting dispatch steps (downloads, arr dispatch)",
    )
    input_group.add_argument("--from", dest="from_step", help="Start from this step name")
    input_group.add_argument("--until", dest="until_step", help="Stop after this step name")

    init_cmd = sub.add_parser("init", parents=[common], help="Initialize default config")
    init_cmd.add_argument("--force", action="store_true", help="Overwrite config if it exists")
    init_cmd.set_defaults(func=cmd_init)

    run_cmd = sub.add_parser(
        "run",
        parents=[common, input_group],
        help="Run a workflow",
        description=(
            "Run the workflow for the detected or provided media type.\n"
            "\n"
            "Safety:\n"
            "  --dry-run  executes read-only steps only\n"
            "  --confirm  allows side-effect steps (grabs/dispatch)\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_cmd.add_argument("--workflow", help="Workflow name to run")
    run_cmd.add_argument("--batch", help="Process a batch of inputs (JSON list, JSONL, or plain lines)")
    run_cmd.add_argument("--jobs", type=int, help="Parallelism for --batch (default: config.concurrency.default)")
    run_cmd.set_defaults(func=cmd_run)

    step_cmd = sub.add_parser("step", parents=[common, input_group], help="Run a single built-in step")
    step_cmd.add_argument("name", help="Built-in step name")
    step_cmd.set_defaults(func=cmd_step)

    choose_group = argparse.ArgumentParser(add_help=False)
    choose_source = choose_group.add_mutually_exclusive_group()
    choose_source.add_argument("--json", help="JSON file input")
    choose_source.add_argument("--stdin", action="store_true", help="Read JSON from stdin")
    choose_cmd = sub.add_parser("choose", parents=[common, choose_group], help="Choose from decision options")
    choose_cmd.add_argument("--select", help="Index or substring match")
    choose_cmd.add_argument("--interactive", action="store_true", help="Prompt for selection if TTY")
    choose_cmd.add_argument("--verbose", action="store_true", help="Show full JSON option")
    choose_cmd.add_argument("--preview", action="store_true", help="Show extra fields for each option")
    choose_cmd.add_argument("--explain", action="store_true", help="Show rank reasons if present")
    choose_cmd.add_argument("--min-score", type=float, help="Filter options by minimum rank score")
    choose_cmd.add_argument("--year", type=int, help="Filter options by year")
    choose_cmd.add_argument("--format", dest="format_hint", help="Filter options by format substring")
    choose_cmd.add_argument(
        "--emit",
        choices=["index", "flag", "json"],
        default="index",
        help="Output format for selection",
    )
    choose_cmd.set_defaults(func=cmd_choose)

    list_cmd = sub.add_parser("list", parents=[common], help="List workflows or steps")
    list_cmd.add_argument("kind", choices=["workflows", "steps"])
    list_cmd.set_defaults(func=cmd_list)

    validate_cmd = sub.add_parser("validate", parents=[common], help="Validate config")
    validate_cmd.set_defaults(func=cmd_validate)

    doctor_cmd = sub.add_parser("doctor", parents=[common], help="Check configuration and connectivity")
    doctor_cmd.set_defaults(func=cmd_doctor)

    help_cmd = sub.add_parser("help", help="Show extended help topics")
    help_cmd.add_argument("topic", nargs="?", help="overview|config|json|safety|exit-codes")
    help_cmd.add_argument("--verbose", action="store_true", help="Include minimal config template")
    help_cmd.set_defaults(func=cmd_help)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
