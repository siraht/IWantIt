"""Workflow runner and step execution."""

from __future__ import annotations

import json
import os
import shlex
import string
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from .paths import ensure_dir, state_dir


class StepError(RuntimeError):
    pass


@dataclass
class Context:
    config: dict[str, Any]
    state_path: str
    choice_index: int | None = None
    dry_run: bool = False
    confirm: bool = False


BuiltinStep = Callable[[dict[str, Any], dict[str, Any], Context], dict[str, Any]]


class DotDict(dict):
    def __getattr__(self, key: str) -> Any:
        return self.get(key)

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value


class SafeMap(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


_FORMATTER = string.Formatter()


def _dotify(value: Any) -> Any:
    if isinstance(value, dict):
        return DotDict({k: _dotify(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_dotify(v) for v in value]
    return value


def _render_value(value: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {k: _render_value(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_render_value(v, ctx) for v in value]
    if isinstance(value, str):
        parsed = list(_FORMATTER.parse(value))
        if len(parsed) == 1:
            literal, field, format_spec, conv = parsed[0]
            if literal == "" and field and format_spec == "" and conv is None:
                try:
                    resolved, _ = _FORMATTER.get_field(field, (), ctx)
                    return resolved
                except Exception:
                    pass
        try:
            return value.format_map(SafeMap(ctx))
        except Exception:
            return value
    return value


def render_template(obj: Any, data: dict[str, Any], config: dict[str, Any]) -> Any:
    ctx = {
        "data": _dotify(data),
        "request": _dotify(data.get("request", {})),
        "work": _dotify(data.get("work", {})),
        "decision": _dotify(data.get("decision", {})),
        "config": _dotify(config),
    }
    return _render_value(obj, ctx)


def run_external(
    command: str | list[str],
    data: dict[str, Any],
    step: str,
    timeout: float | None = None,
) -> dict[str, Any]:
    if isinstance(command, str):
        cmd = shlex.split(command)
    else:
        cmd = command
    env = os.environ.copy()
    config_path = (data.get("_meta") or {}).get("config_path") or data.get("_config_path")
    if config_path:
        env["IWANTIT_CONFIG"] = str(config_path)
    try:
        proc = subprocess.run(
            cmd,
            input=json.dumps(data),
            text=True,
            capture_output=True,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise StepError(f"step {step} timed out after {exc.timeout}s") from exc
    if proc.returncode != 0:
        raise StepError(f"step {step} failed: {proc.stderr.strip()}")
    output = proc.stdout.strip()
    if not output:
        return data
    try:
        result = json.loads(output)
    except json.JSONDecodeError as exc:
        raise StepError(f"step {step} returned invalid JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise StepError(f"step {step} returned non-object JSON")
    for key in ("_meta", "_config_path"):
        if key in data and key not in result:
            result[key] = data[key]
    return result


def select_workflow(config: dict[str, Any], data: dict[str, Any], name: str | None) -> dict[str, Any]:
    workflows = config.get("workflows", [])
    if name:
        for wf in workflows:
            if wf.get("name") == name:
                return wf
        raise StepError(f"workflow not found: {name}")
    media_type = data.get("request", {}).get("media_type")
    if media_type:
        for wf in workflows:
            match = wf.get("match", {})
            if match.get("media_type") == media_type:
                return wf
    raise StepError("media type not determined; rerun with --media-type or --workflow")


def run_step(
    step_name: str,
    step_cfg: dict[str, Any],
    data: dict[str, Any],
    context: Context,
    builtins: dict[str, BuiltinStep],
) -> dict[str, Any]:
    if context.dry_run and step_cfg.get("skip_on_dry_run"):
        data.setdefault("dry_run", {})[step_name] = {"skipped": True, "reason": "dry_run"}
        return data
    if "command" in step_cfg:
        external_cfg = context.config.get("external_steps", {}) or {}
        timeout = step_cfg.get("timeout")
        if timeout is None:
            timeout = external_cfg.get("timeout")
        return run_external(step_cfg["command"], data, step_name, timeout=timeout)
    builtin_name = step_cfg.get("builtin", step_name)
    builtin = builtins.get(builtin_name)
    if not builtin:
        raise StepError(f"unknown builtin step: {builtin_name}")
    merged_cfg = dict(step_cfg)
    timeouts = context.config.get("timeouts", {}) or {}
    if "timeout" not in merged_cfg and step_name in timeouts:
        merged_cfg["timeout"] = timeouts[step_name]
    retries_cfg = context.config.get("retries", {}) or {}
    for key in ("retries", "retry_backoff_seconds", "max_backoff_seconds", "retry_statuses"):
        if key not in merged_cfg and key in retries_cfg:
            merged_cfg[key] = retries_cfg[key]
    merged_cfg.setdefault("_step", step_name)
    return builtin(data, merged_cfg, context)


def run_workflow(
    config: dict[str, Any],
    data: dict[str, Any],
    builtins: dict[str, BuiltinStep],
    workflow_name: str | None = None,
    choice_index: int | None = None,
    start_step: str | None = None,
    end_step: str | None = None,
    dry_run: bool = False,
    confirm: bool = False,
    progress: Callable[[str, str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    ensure_dir(state_dir())
    context = Context(
        config=config,
        state_path=str(state_dir()),
        choice_index=choice_index,
        dry_run=dry_run,
        confirm=confirm,
    )
    started = start_step is None
    saw_start = False

    for step_name in config.get("pre_steps", []) or []:
        if not started and step_name == start_step:
            started = True
            saw_start = True
        if not started:
            continue
        step_cfg = config.get("steps", {}).get(step_name, {"builtin": step_name})
        try:
            if progress:
                progress(step_name, "start", data)
            data = run_step(step_name, step_cfg, data, context, builtins)
            if progress:
                progress(step_name, "end", data)
        except Exception as exc:
            data.setdefault("error", {})["message"] = str(exc)
            data["error"]["step"] = step_name
            data["error"]["type"] = exc.__class__.__name__
            data.setdefault("decision", {})["status"] = "error"
            return data
        if end_step and step_name == end_step:
            return data

    try:
        workflow = select_workflow(config, data, workflow_name)
    except Exception as exc:
        data.setdefault("error", {})["message"] = str(exc)
        data["error"]["step"] = "select_workflow"
        data["error"]["type"] = exc.__class__.__name__
        data.setdefault("decision", {})["status"] = "error"
        return data
    for step_name in workflow.get("steps", []):
        if not started and step_name == start_step:
            started = True
            saw_start = True
        if not started:
            continue
        step_cfg = config.get("steps", {}).get(step_name, {"builtin": step_name})
        try:
            if progress:
                progress(step_name, "start", data)
            data = run_step(step_name, step_cfg, data, context, builtins)
            if progress:
                progress(step_name, "end", data)
        except Exception as exc:
            data.setdefault("error", {})["message"] = str(exc)
            data["error"]["step"] = step_name
            data["error"]["type"] = exc.__class__.__name__
            data.setdefault("decision", {})["status"] = "error"
            return data
        decision = data.get("decision", {})
        if decision.get("status") == "needs_choice":
            break
        if end_step and step_name == end_step:
            break
    if start_step and not saw_start:
        data.setdefault("error", {})["message"] = f"start step not found: {start_step}"
        data["error"]["step"] = start_step
        data["error"]["type"] = "StepNotFound"
        data.setdefault("decision", {})["status"] = "error"
    return data
