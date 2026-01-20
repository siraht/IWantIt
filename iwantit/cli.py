"""CLI entrypoint for iwantit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import (
    ensure_config_exists,
    load_config,
    save_default_config,
    save_default_secrets,
    validate_config,
)
from .pipeline import Context, run_workflow
from .paths import ensure_dir, state_dir
from .steps.builtin import BUILTINS
from .util import (
    coerce_tags,
    is_stdin_tty,
    is_stdout_tty,
    parse_kv_pairs,
    read_json,
    read_stdin,
    write_json,
)

EXIT_NEEDS_CHOICE = 20


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


def _finalize_output(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"result": data, "decision": {"status": "complete"}}
    data.setdefault("request", {})
    data.setdefault("work", {})
    data.setdefault("decision", {"status": "complete"})
    data.setdefault("search", {})
    data.setdefault("dispatch", {})
    data.setdefault("tags", {})
    if data.get("error") and data["decision"].get("status") != "error":
        data["decision"]["status"] = "error"
    return data


def _build_request(args: argparse.Namespace) -> dict[str, Any]:
    if args.json:
        data = _load_json_file(args.json)
        return _coerce_request_payload(data)

    if args.stdin or (not is_stdin_tty() and not (args.text or args.url or args.image)):
        raw = read_stdin().strip()
        if not raw:
            return {"request": {}}
        try:
            data = read_json(raw)
            return _coerce_request_payload(data)
        except json.JSONDecodeError:
            return {"request": {"input": raw, "input_type": "text", "query": raw}}

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

    return {"request": request}


def cmd_init(args: argparse.Namespace) -> int:
    cfg_path = save_default_config(path=Path(args.config).expanduser() if args.config else None, overwrite=args.force)
    save_default_secrets(overwrite=False)
    sys.stdout.write(f"Initialized config at {cfg_path}\n")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cfg_path = ensure_config_exists(args.config)
    config = load_config(cfg_path)
    data = _build_request(args)
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
    )
    if isinstance(result, dict):
        result.pop("_meta", None)
        result.pop("_config_path", None)
    result = _finalize_output(result)
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
    context = Context(config=config, state_path=str(state_dir()), choice_index=args.choice, dry_run=args.dry_run)
    step_cfg = config.get("steps", {}).get(args.name, {"builtin": args.name})
    step_cfg = dict(step_cfg)
    step_cfg.setdefault("_step", args.name)
    try:
        result = step(data, step_cfg, context)
    except Exception as exc:
        result = {"error": {"message": str(exc), "step": args.name, "type": exc.__class__.__name__}}
    write_json(_finalize_output(result))
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
    if args.select is None:
        for idx, opt in enumerate(options):
            label = _option_label(opt)
            if not args.verbose and isinstance(opt, dict):
                score = opt.get("rank", {}).get("score")
                if score is not None:
                    label = f"{label} (score={score:.2f})"
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
        write_json(_finalize_output(data))
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="iwantit", description="Extensible media workflow runner")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="Path to config file")

    input_group = argparse.ArgumentParser(add_help=False)
    source = input_group.add_mutually_exclusive_group()
    source.add_argument("--text", help="Text input")
    source.add_argument("--url", help="URL input")
    source.add_argument("--image", help="Image path input")
    source.add_argument("--json", help="JSON file input")
    source.add_argument("--stdin", action="store_true", help="Read JSON or text from stdin")
    input_group.add_argument("--media-type", help="media type (music, movie, tv, book)")
    input_group.add_argument("--tag", action="append", help="Tag to attach", default=[])
    input_group.add_argument("--pref", action="append", help="Preference key=value", default=[])
    input_group.add_argument(
        "--book-format",
        choices=["ebook", "audiobook", "both"],
        help="Book format preference (ebook, audiobook, or both)",
    )
    input_group.add_argument("--choice", type=int, help="Choice index for selection")
    input_group.add_argument("--dry-run", action="store_true", help="Do not perform network side effects")
    input_group.add_argument("--from", dest="from_step", help="Start from this step name")
    input_group.add_argument("--until", dest="until_step", help="Stop after this step name")

    init_cmd = sub.add_parser("init", parents=[common], help="Initialize default config")
    init_cmd.add_argument("--force", action="store_true", help="Overwrite config if it exists")
    init_cmd.set_defaults(func=cmd_init)

    run_cmd = sub.add_parser("run", parents=[common, input_group], help="Run a workflow")
    run_cmd.add_argument("--workflow", help="Workflow name to run")
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

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
