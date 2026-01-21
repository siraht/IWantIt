"""Config schema validation."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft7Validator


def config_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "pre_steps": {"type": "array", "items": {"type": "string"}},
            "default_workflow": {"type": "string"},
            "workflows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {
                        "name": {"type": "string"},
                        "match": {"type": "object", "additionalProperties": True},
                        "steps": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name", "steps"],
                },
            },
            "steps": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "additionalProperties": True,
                    "properties": {
                        "builtin": {"type": "string"},
                        "command": {"type": ["array", "string"]},
                        "side_effect": {"type": "boolean"},
                    },
                },
            },
            "web_search": {"type": "object", "additionalProperties": True},
            "prowlarr": {"type": "object", "additionalProperties": True},
            "redacted": {"type": "object", "additionalProperties": True},
            "arr": {"type": "object", "additionalProperties": True},
            "provider_registry": {"type": "object", "additionalProperties": True},
            "logging": {"type": "object", "additionalProperties": True},
            "report": {"type": "object", "additionalProperties": True},
            "rate_limits": {"type": "object", "additionalProperties": True},
            "concurrency": {"type": "object", "additionalProperties": True},
            "plugins": {"type": "object", "additionalProperties": True},
        },
    }


def validate_config_schema(config: dict[str, Any]) -> list[str]:
    validator = Draft7Validator(config_schema())
    errors = []
    for error in sorted(validator.iter_errors(config), key=lambda e: e.path):
        path = ".".join(str(part) for part in error.path)
        prefix = f"{path}: " if path else ""
        errors.append(prefix + error.message)
    return errors
