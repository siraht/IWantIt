"""Versioned, policy-gated acquisition contract for external control planes."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from jsonschema import Draft202012Validator

from .pipeline import BuiltinStep, run_workflow

INTENT_SCHEMA_ID = "iwantit.acquisition-intent/1"
RESULT_SCHEMA_ID = "iwantit.acquisition-result/1"

ACQUISITION_INTENT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": INTENT_SCHEMA_ID,
    "type": "object",
    "additionalProperties": False,
    "required": ["schema", "intent_id", "action", "recording", "desired"],
    "properties": {
        "schema": {"const": INTENT_SCHEMA_ID},
        "intent_id": {"type": "string", "minLength": 1},
        "action": {"enum": ["preview", "dispatch"]},
        "recording": {
            "type": "object",
            "additionalProperties": False,
            "required": ["ref", "artist", "title"],
            "properties": {
                "ref": {"type": "string", "minLength": 1},
                "artist": {"type": "string", "minLength": 1},
                "title": {"type": "string", "minLength": 1},
                "version": {"type": "string"},
                "release": {"type": "string"},
                "year": {"type": "integer", "minimum": 1800, "maximum": 3000},
                "external_refs": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
            },
        },
        "desired": {
            "type": "object",
            "additionalProperties": False,
            "required": ["formats", "exact_version"],
            "properties": {
                "formats": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
                "media": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1},
                },
                "exact_version": {"type": "boolean"},
                "allow_substitution": {"type": "boolean", "default": False},
            },
        },
        "policy": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "authorized_sources_only": {"type": "boolean", "const": True},
                "private": {"type": "boolean"},
            },
        },
        "confirmation": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "approved": {"type": "boolean"},
                "selected_candidate_index": {"type": "integer", "minimum": 0},
            },
        },
    },
}

WorkflowRunner = Callable[[dict[str, Any], bool, bool, int | None], dict[str, Any]]


class AcquisitionContractError(ValueError):
    pass


_SECRET_KEYS = {
    "api-key",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
}
_SECRET_QUERY_KEYS = _SECRET_KEYS | {"auth", "key", "link", "sig", "signature"}
_DOWNLOAD_URL_KEYS = {"downloadurl", "download_url"}


def sanitize_acquisition_output(value: Any, *, parent_key: str = "") -> Any:
    """Return a deep-copied result with provider access material removed."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in _SECRET_KEYS:
                sanitized[key] = "***"
            else:
                sanitized[key] = sanitize_acquisition_output(child, parent_key=normalized)
        return sanitized
    if isinstance(value, list):
        return [sanitize_acquisition_output(child, parent_key=parent_key) for child in value]
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        return copy.deepcopy(value)
    try:
        parsed = urlparse(value)
        if parent_key in _DOWNLOAD_URL_KEYS:
            return urlunparse(parsed._replace(query="", fragment=""))
        parameters = parse_qsl(parsed.query, keep_blank_values=True)
        safe = [(key, item) for key, item in parameters if key.lower() not in _SECRET_QUERY_KEYS]
        return urlunparse(parsed._replace(query=urlencode(safe), fragment=""))
    except ValueError:
        return "[redacted invalid URL]"


class AcquisitionService:
    def __init__(
        self,
        config: dict[str, Any],
        builtins: dict[str, BuiltinStep],
        *,
        runner: WorkflowRunner | None = None,
    ) -> None:
        self.config = config
        self.builtins = builtins
        self.runner = runner or self._run_workflow

    def handle(self, intent: dict[str, Any]) -> dict[str, Any]:
        errors = sorted(
            Draft202012Validator(ACQUISITION_INTENT_SCHEMA).iter_errors(intent),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            error = errors[0]
            path = ".".join(str(part) for part in error.absolute_path)
            prefix = f"{path}: " if path else ""
            raise AcquisitionContractError(prefix + error.message)

        action = str(intent["action"])
        confirmation = intent.get("confirmation") or {}
        approved = confirmation.get("approved") is True
        if action == "dispatch" and not approved:
            return self._result(
                intent,
                status="confirmation_required",
                pipeline={},
                error={
                    "code": "CONFIRMATION_REQUIRED",
                    "message": "Dispatch requires confirmation.approved=true.",
                },
            )

        data = self._pipeline_input(intent)
        choice = confirmation.get("selected_candidate_index")
        pipeline = self.runner(data, action == "preview", action == "dispatch", choice)
        decision = pipeline.get("decision") or {}
        dispatch = pipeline.get("dispatch") or {}
        if pipeline.get("error") or decision.get("status") == "error":
            status = "error"
        elif action == "dispatch" and any(
            isinstance(value, dict) and value.get("status") == "ok"
            for value in dispatch.values()
        ):
            status = "dispatched"
        elif decision.get("status") == "needs_choice":
            status = "needs_choice"
        elif decision.get("status") == "selected":
            status = "selected"
        else:
            status = "previewed"
        return self._result(intent, status=status, pipeline=pipeline)

    def _pipeline_input(self, intent: dict[str, Any]) -> dict[str, Any]:
        recording = intent["recording"]
        desired = intent["desired"]
        query_parts = [recording["artist"], "-", recording["title"]]
        for value in (recording.get("version"), recording.get("release")):
            if value:
                query_parts.append(str(value))
        query_parts.extend(str(value) for value in desired["formats"])
        query_parts.extend(str(value) for value in desired.get("media", []))
        query = " ".join(query_parts)
        return {
            "request": {
                "input": query,
                "input_type": "text",
                "query": query,
                "query_original": query,
                "media_type": "music",
                "release_preferences": {
                    "formats": list(desired["formats"]),
                    "media": list(desired.get("media", [])),
                },
                "explicit_version": bool(desired["exact_version"]),
            },
            "work": {
                "media_type": "music",
                "artist": recording["artist"],
                "title": recording["title"],
                "year": recording.get("year"),
            },
            "acquisition_intent": intent,
        }

    def _run_workflow(
        self,
        data: dict[str, Any],
        dry_run: bool,
        confirm: bool,
        choice_index: int | None,
    ) -> dict[str, Any]:
        return run_workflow(
            self.config,
            data,
            self.builtins,
            workflow_name="music",
            choice_index=choice_index,
            dry_run=dry_run,
            confirm=confirm,
        )

    @staticmethod
    def _result(
        intent: dict[str, Any],
        *,
        status: str,
        pipeline: dict[str, Any],
        error: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        work = pipeline.get("work") or {}
        decision = pipeline.get("decision") or {}
        result = {
            "schema": RESULT_SCHEMA_ID,
            "intent_id": intent["intent_id"],
            "recording_ref": intent["recording"]["ref"],
            "status": status,
            "side_effects_allowed": intent["action"] == "dispatch"
            and (intent.get("confirmation") or {}).get("approved") is True,
            "candidates": work.get("candidates") or decision.get("options") or [],
            "selected": decision.get("selected") or work.get("selected"),
            "decision": decision,
            "dispatch": pipeline.get("dispatch") or {},
            "provenance": {
                "run_id": pipeline.get("run_id"),
                "canonical": pipeline.get("canonical") or {},
                "search": pipeline.get("search") or {},
            },
            "error": error or pipeline.get("error"),
        }
        return sanitize_acquisition_output(result)
