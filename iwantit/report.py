"""Generate human-readable run reports."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .util import redact_payload


def render_report(data: dict[str, Any]) -> str:
    request = data.get("request", {}) or {}
    work = data.get("work", {}) or {}
    decision = data.get("decision", {}) or {}
    warnings = data.get("warnings", []) or []
    run_id = data.get("run_id") or "unknown"
    lines = []
    lines.append(f"# IWantIt Run Report ({run_id})")
    lines.append("")
    lines.append(f"Generated: {datetime.utcnow().isoformat()}Z")
    lines.append("")
    lines.append("## Input")
    lines.append(f"- query: {request.get('query') or request.get('input')}")
    lines.append(f"- media_type: {work.get('media_type') or request.get('media_type')}")
    lines.append("")
    lines.append("## Parsed")
    if work.get("artist"):
        lines.append(f"- artist: {work.get('artist')}")
    if work.get("title"):
        lines.append(f"- title: {work.get('title')}")
    if work.get("year"):
        lines.append(f"- year: {work.get('year')}")
    lines.append("")
    lines.append("## Decision")
    lines.append(f"- status: {decision.get('status')}")
    if decision.get("reason"):
        lines.append(f"- reason: {decision.get('reason')}")
    if decision.get("confidence") is not None:
        lines.append(f"- confidence: {decision.get('confidence')}")
    if decision.get("selected"):
        selected = decision.get("selected")
        if isinstance(selected, dict):
            title = selected.get("title") or selected.get("name") or selected.get("release")
            if title:
                lines.append(f"- selected: {title}")
    lines.append("")
    if warnings:
        lines.append("## Warnings")
        for warn in warnings:
            if isinstance(warn, dict):
                lines.append(f"- {warn.get('step','unknown')}: {warn.get('message') or warn.get('type')}")
            else:
                lines.append(f"- {warn}")
        lines.append("")
    return "\n".join(lines)


def write_report(data: dict[str, Any], state_path: str, config: dict[str, Any]) -> str | None:
    report_cfg = config.get("report", {}) or {}
    if not report_cfg.get("enabled"):
        return None
    run_id = data.get("run_id") or "unknown"
    out_dir = Path(state_path) / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{run_id}.md"
    content = render_report(redact_payload(data))
    path.write_text(content, encoding="utf-8")
    return str(path)
