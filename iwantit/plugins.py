"""Plugin discovery for external steps."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from .paths import config_dir


def _load_plugin_file(path: Path) -> dict[str, Any] | None:
    try:
        if path.suffix in {".yml", ".yaml"}:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        elif path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            return None
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def discover_plugins(config: dict[str, Any], cwd: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    plugin_cfg = config.get("plugins", {}) or {}
    paths: list[Path] = []
    env_paths = os.environ.get("IWANTIT_PLUGIN_PATH", "")
    if env_paths:
        for item in env_paths.split(os.pathsep):
            if item.strip():
                paths.append(Path(item).expanduser())
    for item in plugin_cfg.get("paths", []) if isinstance(plugin_cfg, dict) else []:
        if item:
            paths.append(Path(item).expanduser())
    paths.append(config_dir() / "plugins")
    paths.append(cwd / "plugins")

    steps: dict[str, Any] = {}
    metadata: list[dict[str, Any]] = []
    for base in paths:
        if not base.exists():
            continue
        candidates = list(base.glob("**/plugin.yaml")) + list(base.glob("**/plugin.yml")) + list(base.glob("**/plugin.json"))
        for plugin_file in candidates:
            data = _load_plugin_file(plugin_file)
            if not data:
                continue
            plugin_name = str(data.get("name") or plugin_file.parent.name)
            version = str(data.get("version") or "0.0.0")
            plugin_steps = data.get("steps") or {}
            if isinstance(plugin_steps, dict):
                for step_name, step_cfg in plugin_steps.items():
                    if step_name not in steps and isinstance(step_cfg, dict):
                        steps[step_name] = step_cfg
            metadata.append(
                {
                    "name": plugin_name,
                    "version": version,
                    "path": str(plugin_file),
                    "steps": sorted(list(plugin_steps.keys())) if isinstance(plugin_steps, dict) else [],
                }
            )
    return steps, metadata
