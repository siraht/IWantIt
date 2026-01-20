"""Filesystem paths for config and state."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "iwantit"


def _xdg_dir(env_key: str, fallback: str) -> Path:
    base = os.environ.get(env_key)
    if base:
        return Path(base).expanduser()
    return Path(fallback).expanduser()


def config_dir() -> Path:
    return _xdg_dir("XDG_CONFIG_HOME", "~/.config") / APP_NAME


def state_dir() -> Path:
    return _xdg_dir("XDG_STATE_HOME", "~/.local/state") / APP_NAME


def cache_dir() -> Path:
    return _xdg_dir("XDG_CACHE_HOME", "~/.cache") / APP_NAME


def config_path() -> Path:
    override = os.environ.get("IWANTIT_CONFIG")
    if override:
        return Path(override).expanduser()
    return config_dir() / "config.yaml"


def secrets_path() -> Path:
    override = os.environ.get("IWANTIT_SECRETS")
    if override:
        return Path(override).expanduser()
    return config_dir() / "secrets.yaml"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
