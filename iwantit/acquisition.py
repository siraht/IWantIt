"""Versioned, policy-gated acquisition contract for external control planes."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from jsonschema import Draft202012Validator

from .pipeline import BuiltinStep, run_workflow
from .registry import iter_active_providers, merge_provider_registry

INTENT_SCHEMA_ID = "iwantit.acquisition-intent/1"
RESULT_SCHEMA_ID = "iwantit.acquisition-result/1"
CANDIDATE_SCHEMA_ID = "iwantit.acquisition-candidate/1"

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

    def _result(
        self,
        intent: dict[str, Any],
        *,
        status: str,
        pipeline: dict[str, Any],
        error: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        work = pipeline.get("work") or {}
        decision = pipeline.get("decision") or {}
        raw_candidates = work.get("candidates") or decision.get("options") or []
        candidates = [
            self._project_candidate(candidate, index)
            for index, candidate in enumerate(raw_candidates)
        ]
        selected_raw = decision.get("selected") or work.get("selected")
        selected_index = self._selected_index(raw_candidates, selected_raw)
        result = {
            "schema": RESULT_SCHEMA_ID,
            "intent_id": intent["intent_id"],
            "recording_ref": intent["recording"]["ref"],
            "status": status,
            "side_effects_allowed": intent["action"] == "dispatch"
            and (intent.get("confirmation") or {}).get("approved") is True,
            "candidates": candidates,
            "selected": (
                self._project_candidate(selected_raw, selected_index)
                if selected_raw is not None
                else None
            ),
            "decision": self._project_decision(decision, selected_index, len(candidates)),
            "dispatch": self._project_dispatch(pipeline.get("dispatch") or {}),
            "provenance": {
                "run_id": pipeline.get("run_id"),
                "canonical": self._project_canonical(pipeline.get("canonical") or {}),
                "search": self._project_search(pipeline.get("search") or {}),
            },
            "privacy": self._privacy_contract(intent),
            "error": error or pipeline.get("error"),
        }
        return sanitize_acquisition_output(result)

    @staticmethod
    def _selected_index(candidates: list[Any], selected: Any) -> int | None:
        if selected is None:
            return None
        for index, candidate in enumerate(candidates):
            if candidate is selected or candidate == selected:
                return index
        return None

    @classmethod
    def _project_candidate(cls, value: Any, position: int | None) -> dict[str, Any]:
        candidate = value if isinstance(value, dict) else {"title": str(value)}
        raw = candidate.get("_raw") if isinstance(candidate.get("_raw"), dict) else {}
        redacted = (
            candidate.get("redacted") if isinstance(candidate.get("redacted"), dict) else {}
        )
        group = redacted.get("group") if isinstance(redacted.get("group"), dict) else {}
        torrent = (
            redacted.get("torrent") if isinstance(redacted.get("torrent"), dict) else {}
        )

        def first(*values: Any) -> Any:
            return next((item for item in values if item not in (None, "", [], {})), None)

        def integer(*values: Any) -> int | None:
            raw_value = first(*values)
            try:
                return int(raw_value) if raw_value is not None else None
            except (TypeError, ValueError):
                return None

        source = str(
            first(
                candidate.get("indexer"),
                candidate.get("provider"),
                candidate.get("source"),
                raw.get("indexer"),
                "unknown",
            )
        )
        source_url = first(
            candidate.get("info_url"),
            candidate.get("infoUrl"),
            candidate.get("guid"),
            raw.get("infoUrl"),
            raw.get("guid"),
        )
        safe_source_url = (
            sanitize_acquisition_output(str(source_url), parent_key="info_url")
            if source_url
            else None
        )
        title = str(first(candidate.get("title"), candidate.get("name"), group.get("name"), "Candidate"))
        music_info = group.get("musicInfo") if isinstance(group.get("musicInfo"), dict) else {}
        artist_values = music_info.get("artists") if isinstance(music_info, dict) else []
        artists = []
        if isinstance(artist_values, list):
            artists = [
                str(item.get("name"))
                for item in artist_values
                if isinstance(item, dict) and item.get("name")
            ]
        tags = group.get("tags") if isinstance(group.get("tags"), list) else []
        release = {
            "title": str(first(group.get("name"), title)),
            "artists": artists,
            "year": integer(group.get("year"), candidate.get("year")),
            "label": first(group.get("recordLabel"), torrent.get("remasterRecordLabel")),
            "catalog_number": first(
                group.get("catalogueNumber"), torrent.get("remasterCatalogueNumber")
            ),
            "tags": sorted({str(tag) for tag in tags if isinstance(tag, str) and tag}),
        }
        edition = {
            "format": first(torrent.get("format"), candidate.get("format"), raw.get("format")),
            "encoding": first(torrent.get("encoding"), candidate.get("encoding")),
            "media": first(torrent.get("media"), candidate.get("media")),
            "remaster_year": integer(torrent.get("remasterYear")),
            "remaster_title": first(torrent.get("remasterTitle")),
            "file_count": integer(torrent.get("fileCount"), candidate.get("file_count")),
            "size_bytes": integer(torrent.get("size"), candidate.get("size"), raw.get("size")),
        }
        availability = {
            "state": "observed",
            "seeders": integer(torrent.get("seeders"), candidate.get("seeders"), raw.get("seeders")),
            "leechers": integer(
                torrent.get("leechers"), candidate.get("leechers"), raw.get("leechers")
            ),
            "snatches": integer(torrent.get("snatched"), torrent.get("snatches")),
        }
        rank = candidate.get("rank") if isinstance(candidate.get("rank"), dict) else {}
        ranking = {
            "score": float(rank["score"]) if isinstance(rank.get("score"), (int, float)) else None,
            "rejected": bool(rank.get("rejected", False)),
            "reasons": [
                str(reason)
                for reason in rank.get("reasons", [])
                if isinstance(reason, (str, int, float))
            ],
        }
        projected = {
            "schema": CANDIDATE_SCHEMA_ID,
            "position": position,
            "title": title,
            "source": source,
            "source_url": safe_source_url,
            "release": release,
            "edition": edition,
            "availability": availability,
            "ranking": ranking,
        }
        digest_payload = json.dumps(projected, sort_keys=True, separators=(",", ":"))
        return {
            **projected,
            "candidate_ref": "sha256:"
            + hashlib.sha256(digest_payload.encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def _project_decision(
        decision: dict[str, Any], selected_index: int | None, option_count: int
    ) -> dict[str, Any]:
        confidence = decision.get("confidence")
        breakdown = decision.get("confidence_breakdown")
        return {
            "status": str(decision.get("status") or ""),
            "selected_candidate_index": selected_index,
            "option_count": option_count,
            "confidence": (
                float(confidence) if isinstance(confidence, (int, float)) else None
            ),
            "confidence_breakdown": {
                str(key): float(value)
                for key, value in (breakdown.items() if isinstance(breakdown, dict) else [])
                if isinstance(value, (int, float))
            },
        }

    @staticmethod
    def _project_dispatch(dispatch: dict[str, Any]) -> dict[str, Any]:
        projected: dict[str, Any] = {}
        for provider, raw in dispatch.items():
            value = raw if isinstance(raw, dict) else {}
            reference = value.get("download_id") or value.get("id")
            projected[str(provider)] = {
                "status": str(value.get("status") or "unknown"),
                "count": int(value.get("count") or (1 if value.get("response") else 0)),
                "reference": str(reference) if reference else None,
            }
        return projected

    @staticmethod
    def _project_canonical(canonical: dict[str, Any]) -> dict[str, Any]:
        fields = canonical.get("fields") if isinstance(canonical.get("fields"), dict) else {}
        allowed = {"artist", "title", "year", "release", "version", "media_type"}
        return {
            "fields": {
                str(key): copy.deepcopy(value)
                for key, value in fields.items()
                if key in allowed and isinstance(value, (str, int, float, bool, list))
            }
        }

    @staticmethod
    def _project_search(search: dict[str, Any]) -> dict[str, Any]:
        projected: dict[str, Any] = {}
        for provider, raw in search.items():
            value = raw if isinstance(raw, dict) else {}
            projected[str(provider)] = {
                "query": str(value.get("query") or ""),
                "count": int(value.get("count") or 0),
                "error_type": (
                    str(value["error_type"]) if value.get("error_type") else None
                ),
            }
        return projected

    def _privacy_contract(self, intent: dict[str, Any]) -> dict[str, Any]:
        """Declare conservative, machine-readable handling for adapter output."""

        registry = merge_provider_registry(self.config)
        active_providers = iter_active_providers(self.config)
        private_providers = sorted(
            provider
            for provider in active_providers
            if (registry.get(provider, {}).get("data_handling") or {}).get(
                "classification"
            )
            == "local_private"
        )
        requested_private = (intent.get("policy") or {}).get("private") is True
        classification = (
            "local_private" if requested_private or private_providers else "restricted"
        )
        return {
            "classification": classification,
            "persistence": "sanitized_local",
            "community_publish_allowed": False,
            "remote_inference_allowed": False,
            "provider_payloads_exportable": False,
            "private_providers": private_providers,
            "reason": (
                "The caller requested private handling."
                if requested_private
                else "Acquisition candidates remain restricted until a provider-specific "
                "sharing policy explicitly permits another use."
            ),
        }
