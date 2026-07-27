"""Hardened curated-source acquisition lifecycle."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator, FormatChecker

from .curated_acquisition_journal import (
    CuratedAcquisitionJournal,
    CuratedJournalConflictError,
)
from .curated_acquisition_schema import (
    ACQUISITION_CAPABILITIES_SCHEMA,
    ACQUISITION_INTENT_SCHEMA,
    ACQUISITION_RESULT_SCHEMA,
    CANDIDATE_SCHEMA_ID,
    CAPABILITIES_SCHEMA_ID,
    ERR_SUBJECT_SCHEMA,
    ERR_SUBJECT_SCHEMA_ID,
    INTENT_SCHEMA_ID,
    ITEM_SCHEMA,
    MAX_BATCH_ITEMS,
    MAX_CANDIDATES_PER_ITEM,
    MAX_PAYLOAD_BYTES,
    MAX_RESULT_BYTES,
    RESULT_SCHEMA_ID,
)
from .paths import state_dir
from .registry import iter_active_providers

if TYPE_CHECKING:
    from .acquisition import AcquisitionService

_FORBIDDEN_EVIDENCE_KEYS = {
    "authorization",
    "comment",
    "comments",
    "cookie",
    "excerpt",
    "excerpts",
    "handle",
    "handles",
    "password",
    "private_source",
    "raw_source",
    "source_evidence",
    "source_handle",
    "source_url",
    "token",
}
_NON_PORTABLE_REF_PREFIXES = ("xref:", "local:", "file:", "plex:", "redacted:")
_SUPPORTED_ACQUISITION_PROVIDERS = ("jackett", "prowlarr", "soulseek")
_SAFE_EXTERNAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _error(
    *,
    code: str,
    message: str,
    retryable: bool,
    category: str,
    item_id: str | None,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "retryable": retryable,
        "category": category,
        "item_id": item_id,
    }


class CuratedAcquisitionService:
    def __init__(self, legacy: AcquisitionService) -> None:
        self.legacy = legacy
        self.config = legacy.config
        acquisition_cfg = self.config.get("acquisition") or {}
        self.journal: CuratedAcquisitionJournal | None = None
        if acquisition_cfg.get("idempotency_enabled") is True:
            journal_path = acquisition_cfg.get("idempotency_path")
            self.journal = CuratedAcquisitionJournal(
                Path(journal_path).expanduser()
                if journal_path
                else state_dir() / "acquisition-dispatch.sqlite3",
                lease_seconds=int(acquisition_cfg.get("lease_seconds", 900)),
            )

    def capabilities(self) -> dict[str, Any]:
        acquisition_cfg = self.config.get("acquisition") or {}
        trusted = acquisition_cfg.get("trusted_callers") or []
        active_pairings = [
            entry
            for entry in trusted
            if isinstance(entry, dict) and entry.get("active", True) is True
        ]
        active_providers = sorted(
            set(iter_active_providers(self.config))
            & set(_SUPPORTED_ACQUISITION_PROVIDERS)
        )
        status = "ready"
        if self.journal is None:
            status = "idempotency_required"
        elif not active_pairings:
            status = "pairing_required"
        result = {
            "schema": CAPABILITIES_SCHEMA_ID,
            "contracts": {
                "intent": [INTENT_SCHEMA_ID],
                "result": [RESULT_SCHEMA_ID],
                "candidate": [CANDIDATE_SCHEMA_ID],
                "subject": [ERR_SUBJECT_SCHEMA_ID],
                "legacy_local_intent": ["iwantit.acquisition-intent/1"],
            },
            "limits": {
                "max_batch_items": MAX_BATCH_ITEMS,
                "max_payload_bytes": MAX_PAYLOAD_BYTES,
                "max_result_bytes": MAX_RESULT_BYTES,
                "max_candidates_per_item": MAX_CANDIDATES_PER_ITEM,
            },
            "actions": ["preview", "dispatch", "cancel"],
            "providers": {
                "supported": list(_SUPPORTED_ACQUISITION_PROVIDERS),
                "configured_active": active_providers,
            },
            "pairing": {
                "required": True,
                "transport": "local_stdio",
                "authentication": "host_process_plus_allowlist",
                "credential_in_payload": False,
            },
            "idempotency": {
                "required_for_v2": True,
                "durable_across_restart": True,
                "completed_dispatch_replay": True,
                "conflicting_reuse": "refused",
                "abandoned_dispatch": "reconciliation_required",
            },
            "cancellation": {
                "before_dispatch": True,
                "after_dispatch": False,
                "after_dispatch_state": "unsupported",
            },
            "health": {
                "status": status,
                "configured_pairings": len(active_pairings),
                "journal_available": self.journal is not None,
                "private_payloads_in_health": False,
            },
        }
        Draft202012Validator(ACQUISITION_CAPABILITIES_SCHEMA).validate(result)
        return result

    def refuse_unsupported_contract(self, intent: Any) -> dict[str, Any]:
        return self._top_refusal(
            intent,
            _error(
                code="UNSUPPORTED_CONTRACT_VERSION",
                message="The acquisition intent contract version is not supported.",
                retryable=False,
                category="contract",
                item_id=None,
            ),
        )

    def handle(self, intent: dict[str, Any]) -> dict[str, Any]:
        try:
            payload_bytes = len(
                json.dumps(
                    intent,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8")
            )
        except (TypeError, ValueError):
            return self._top_refusal(
                intent,
                _error(
                    code="INVALID_JSON_VALUE",
                    message="The acquisition request contains a non-JSON value.",
                    retryable=False,
                    category="contract",
                    item_id=None,
                ),
            )
        if payload_bytes > MAX_PAYLOAD_BYTES:
            return self._top_refusal(
                intent,
                _error(
                    code="PAYLOAD_TOO_LARGE",
                    message=f"The acquisition request exceeds {MAX_PAYLOAD_BYTES} bytes.",
                    retryable=False,
                    category="contract",
                    item_id=None,
                ),
            )

        envelope_schema = copy.deepcopy(ACQUISITION_INTENT_SCHEMA)
        envelope_schema["properties"]["items"]["items"] = {"type": "object"}
        errors = sorted(
            Draft202012Validator(
                envelope_schema,
                format_checker=FormatChecker(),
            ).iter_errors(intent),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            return self._top_refusal(
                intent,
                _error(
                    code="INVALID_INTENT",
                    message=self._validation_message(errors[0]),
                    retryable=False,
                    category="contract",
                    item_id=None,
                ),
            )
        item_ids = [
            raw_item.get("item_id")
            for raw_item in intent["items"]
            if isinstance(raw_item, dict)
        ]
        if len(item_ids) != len(set(item_ids)):
            return self._top_refusal(
                intent,
                _error(
                    code="DUPLICATE_ITEM_ID",
                    message="Every item_id in an acquisition batch must be unique.",
                    retryable=False,
                    category="contract",
                    item_id=None,
                ),
            )
        if self.journal is None:
            return self._top_refusal(
                intent,
                _error(
                    code="IDEMPOTENCY_REQUIRED",
                    message=(
                        "Curated acquisition v2 requires acquisition.idempotency_enabled=true."
                    ),
                    retryable=False,
                    category="contract",
                    item_id=None,
                ),
            )
        caller = intent["caller"]
        if not self._trusted_caller(caller):
            return self._top_refusal(
                intent,
                _error(
                    code="UNPAIRED_CALLER",
                    message="The caller does not match an active local pairing.",
                    retryable=False,
                    category="pairing",
                    item_id=None,
                ),
            )

        action = str(intent["action"])
        item_results: list[dict[str, Any]] = []
        for index, raw_item in enumerate(intent["items"]):
            item_id = (
                str(raw_item.get("item_id"))
                if isinstance(raw_item, dict) and raw_item.get("item_id")
                else f"index:{index}"
            )
            validation_error = self._validate_item(raw_item, action, item_id)
            if validation_error is not None:
                item_results.append(
                    self._item_error_result(
                        item_id=item_id,
                        subject=self._safe_result_subject(
                            raw_item.get("subject")
                            if isinstance(raw_item, dict)
                            else None
                        ),
                        error=validation_error,
                    )
                )
                continue
            item = raw_item
            try:
                if action == "preview":
                    item_results.append(self._preview(intent, item))
                elif action == "dispatch":
                    item_results.append(self._dispatch(intent, item))
                else:
                    item_results.append(self._cancel(intent, item))
            except CuratedJournalConflictError:
                item_results.append(
                    self._item_error_result(
                        item_id=item_id,
                        subject=item["subject"],
                        error=_error(
                            code="IDEMPOTENCY_CONFLICT",
                            message=(
                                "The stable intent/item identifiers were reused for "
                                "different acquisition coordinates."
                            ),
                            retryable=False,
                            category="conflict",
                            item_id=item_id,
                        ),
                    )
                )
            except Exception:
                item_results.append(
                    self._item_error_result(
                        item_id=item_id,
                        subject=item["subject"],
                        error=_error(
                            code="INTERNAL_ITEM_ERROR",
                            message=(
                                "The acquisition item could not be processed safely."
                            ),
                            retryable=False,
                            category="provider",
                            item_id=item_id,
                        ),
                        status="error",
                    )
                )
        return self._result(intent, item_results)

    @staticmethod
    def _validation_message(error: Any) -> str:
        path = ".".join(str(part) for part in error.absolute_path)
        location = path or "request"
        return f"Invalid acquisition contract at {location}."

    @staticmethod
    def _safe_result_subject(value: Any) -> dict[str, Any] | None:
        """Echo only a structurally valid owner subject into a closed result."""

        if not isinstance(value, dict):
            return None
        if not Draft202012Validator(ERR_SUBJECT_SCHEMA).is_valid(value):
            return None
        return value

    def _validate_item(
        self,
        item: Any,
        action: str,
        item_id: str,
    ) -> dict[str, Any] | None:
        forbidden = self._forbidden_key(item)
        if forbidden:
            return _error(
                code="PRIVATE_SOURCE_EVIDENCE_FORBIDDEN",
                message=(
                    f"Private source evidence field '{forbidden}' is not accepted "
                    "by the acquisition boundary."
                ),
                retryable=False,
                category="contract",
                item_id=item_id,
            )
        errors = sorted(
            Draft202012Validator(
                ITEM_SCHEMA,
                format_checker=FormatChecker(),
            ).iter_errors(item),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            return _error(
                code="INVALID_ITEM",
                message=self._validation_message(errors[0]),
                retryable=False,
                category="contract",
                item_id=item_id,
            )
        assert isinstance(item, dict)
        subject = item["subject"]
        subject_errors = sorted(
            Draft202012Validator(ERR_SUBJECT_SCHEMA).iter_errors(subject),
            key=lambda error: list(error.absolute_path),
        )
        if subject_errors or subject.get("schema_version") != ERR_SUBJECT_SCHEMA_ID:
            return _error(
                code="INVALID_ERR_SUBJECT",
                message="The item does not contain a supported ERR subject envelope.",
                retryable=False,
                category="identity",
                item_id=item_id,
            )
        if subject["entity_kind"] != "music.recording" or subject["exactness"] != "exact":
            return _error(
                code="EXACT_RECORDING_REQUIRED",
                message="Acquisition requires an exact music.recording ERR subject.",
                retryable=False,
                category="identity",
                item_id=item_id,
            )
        portable_refs = subject.get("portable_refs") or []
        if any(
            not isinstance(value, str)
            or value.startswith(_NON_PORTABLE_REF_PREFIXES)
            or "://" in value
            for value in portable_refs
        ):
            return _error(
                code="NON_PORTABLE_IDENTITY_EVIDENCE",
                message="The ERR subject contains non-portable identity evidence.",
                retryable=False,
                category="identity",
                item_id=item_id,
            )
        sources = item["constraints"]["sources"]
        requested_providers = set(sources["allowed_providers"]) | set(
            sources.get("excluded_providers") or []
        )
        unsupported_providers = sorted(
            requested_providers - set(_SUPPORTED_ACQUISITION_PROVIDERS)
        )
        if unsupported_providers:
            return _error(
                code="UNSUPPORTED_PROVIDER",
                message=(
                    "The item requests an acquisition provider that this contract "
                    "does not support."
                ),
                retryable=False,
                category="contract",
                item_id=item_id,
            )
        overlap = set(sources["allowed_providers"]) & set(
            sources.get("excluded_providers") or []
        )
        if overlap:
            return _error(
                code="CONFLICTING_SOURCE_CONSTRAINTS",
                message="A provider cannot be both allowed and excluded.",
                retryable=False,
                category="contract",
                item_id=item_id,
            )
        if action == "dispatch":
            selection = item.get("selection")
            confirmation = item.get("confirmation")
            if not selection or not confirmation:
                return _error(
                    code="CONFIRMATION_REQUIRED",
                    message=(
                        "Dispatch requires a retained preview choice and explicit confirmation."
                    ),
                    retryable=False,
                    category="confirmation",
                    item_id=item_id,
                )
            if (
                selection["preview_result_id"] != confirmation["preview_result_id"]
                or selection["candidate_ref"] != confirmation["candidate_ref"]
            ):
                return _error(
                    code="CONFIRMATION_MISMATCH",
                    message="Confirmation does not bind the selected preview candidate.",
                    retryable=False,
                    category="confirmation",
                    item_id=item_id,
                )
        elif item.get("selection") is not None or item.get("confirmation") is not None:
            return _error(
                code="CHOICE_NOT_ALLOWED",
                message="Preview and cancellation requests cannot carry a dispatch choice.",
                retryable=False,
                category="confirmation",
                item_id=item_id,
            )
        return None

    @classmethod
    def _forbidden_key(cls, value: Any) -> str | None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).lower()
                if normalized in _FORBIDDEN_EVIDENCE_KEYS:
                    return normalized
                found = cls._forbidden_key(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = cls._forbidden_key(child)
                if found:
                    return found
        return None

    def _trusted_caller(self, caller: dict[str, Any]) -> bool:
        configured = (self.config.get("acquisition") or {}).get("trusted_callers") or []
        keys = (
            "application",
            "instance_id",
            "pairing_id",
            "pairing_revision",
            "workspace_id",
            "actor_id",
        )
        for entry in configured:
            if not isinstance(entry, dict) or entry.get("active", True) is not True:
                continue
            if all(entry.get(key) == caller.get(key) for key in keys):
                return True
        return False

    @staticmethod
    def _fingerprint(intent: dict[str, Any], item: dict[str, Any]) -> str:
        return _canonical_hash(
            {
                "intent_id": intent["intent_id"],
                "idempotency_key": intent["idempotency_key"],
                "caller": intent["caller"],
                "item_id": item["item_id"],
                "subject": item["subject"],
                "search_hints": item["search_hints"],
                "constraints": item["constraints"],
            }
        )

    def _pipeline_input(
        self,
        intent: dict[str, Any],
        item: dict[str, Any],
        *,
        selected_candidate_ref: str | None = None,
    ) -> dict[str, Any]:
        hints = item["search_hints"]
        constraints = item["constraints"]
        query_parts = [hints["artist"], "-", hints["title"]]
        for value in (hints.get("version"), hints.get("release")):
            if value:
                query_parts.append(str(value))
        query_parts.extend(str(value) for value in constraints["formats"])
        query_parts.extend(str(value) for value in constraints.get("media", []))
        query = " ".join(query_parts)
        request = {
            "input": query,
            "input_type": "text",
            "query": query,
            "query_original": query,
            "media_type": "music",
            "release_preferences": {
                "formats": list(constraints["formats"]),
                "media": list(constraints.get("media", [])),
                "editions": [str(hints["version"])] if hints.get("version") else [],
            },
            "explicit_version": True,
            "allow_substitution": False,
            "allowed_acquisition_providers": list(
                constraints["sources"]["allowed_providers"]
            ),
            "excluded_acquisition_providers": list(
                constraints["sources"].get("excluded_providers") or []
            ),
        }
        if selected_candidate_ref:
            request["selected_acquisition_candidate_ref"] = selected_candidate_ref
        return {
            "request": request,
            "work": {
                "media_type": "music",
                "artist": hints["artist"],
                "title": hints["title"],
                "year": hints.get("year"),
            },
            "acquisition_intent": {
                "schema": INTENT_SCHEMA_ID,
                "intent_id": intent["intent_id"],
                "idempotency_key": intent["idempotency_key"],
                "item_id": item["item_id"],
                "subject": copy.deepcopy(item["subject"]),
            },
        }

    @staticmethod
    def _bounded_text(value: Any, limit: int) -> str | None:
        if value is None:
            return None
        return str(value)[:limit]

    @staticmethod
    def _bounded_integer(
        value: Any,
        *,
        maximum: int | None = None,
    ) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            result = int(value)
        except (TypeError, ValueError):
            return None
        result = max(0, result)
        return min(result, maximum) if maximum is not None else result

    def _project_candidate(
        self,
        candidate: Any,
        position: int | None,
    ) -> dict[str, Any]:
        projected = self.legacy._project_candidate(candidate, position)
        release = projected.get("release") or {}
        edition = projected.get("edition") or {}
        availability = projected.get("availability") or {}
        ranking = projected.get("ranking") or {}
        score = ranking.get("score")
        if not isinstance(score, (int, float)) or not math.isfinite(float(score)):
            score = None
        return {
            "schema": CANDIDATE_SCHEMA_ID,
            "candidate_ref": projected["candidate_ref"],
            "position": position,
            "title": self._bounded_text(projected.get("title"), 500) or "",
            "source": self._bounded_text(projected.get("source"), 120) or "unknown",
            # Provider URLs and private dispatch coordinates are not needed by
            # MetaMusic to make an explicit choice.
            "source_url": None,
            "release": {
                "title": self._bounded_text(release.get("title"), 500) or "",
                "artists": [
                    self._bounded_text(value, 300) or ""
                    for value in (release.get("artists") or [])[:32]
                ],
                "year": self._bounded_integer(
                    release.get("year"),
                    maximum=3000,
                ),
                "label": self._bounded_text(release.get("label"), 300),
                "catalog_number": self._bounded_text(
                    release.get("catalog_number"),
                    300,
                ),
                "tags": [
                    self._bounded_text(value, 120) or ""
                    for value in (release.get("tags") or [])[:64]
                ],
            },
            "edition": {
                "format": self._bounded_text(edition.get("format"), 120),
                "encoding": self._bounded_text(edition.get("encoding"), 120),
                "media": self._bounded_text(edition.get("media"), 120),
                "remaster_year": self._bounded_integer(
                    edition.get("remaster_year"),
                    maximum=3000,
                ),
                "remaster_title": self._bounded_text(
                    edition.get("remaster_title"),
                    300,
                ),
                "file_count": self._bounded_integer(edition.get("file_count")),
                "size_bytes": self._bounded_integer(edition.get("size_bytes")),
            },
            "availability": {
                "state": "observed",
                "seeders": self._bounded_integer(availability.get("seeders")),
                "leechers": self._bounded_integer(availability.get("leechers")),
                "snatches": self._bounded_integer(availability.get("snatches")),
            },
            "ranking": {
                "score": float(score) if score is not None else None,
                "rejected": bool(ranking.get("rejected", False)),
                "reasons": [
                    self._bounded_text(value, 200) or ""
                    for value in (ranking.get("reasons") or [])[:32]
                ],
            },
        }

    def _project_candidates(self, pipeline: dict[str, Any]) -> list[dict[str, Any]]:
        work = pipeline.get("work") or {}
        decision = pipeline.get("decision") or {}
        raw_candidates = work.get("candidates") or decision.get("options") or []
        return [
            self._project_candidate(candidate, index)
            for index, candidate in enumerate(
                raw_candidates[:MAX_CANDIDATES_PER_ITEM]
            )
        ]

    @staticmethod
    def _project_dispatch(dispatch: dict[str, Any]) -> dict[str, Any]:
        projected: dict[str, Any] = {}
        for provider, raw in dispatch.items():
            normalized = str(provider).lower()
            if normalized == "slskd":
                normalized = "soulseek"
            if normalized not in _SUPPORTED_ACQUISITION_PROVIDERS:
                continue
            value = raw if isinstance(raw, dict) else {}
            if value.get("status") != "ok":
                continue
            try:
                count = max(1, int(value.get("count") or 1))
            except (TypeError, ValueError):
                count = 1
            reference = value.get("download_id") or value.get("id")
            projected[normalized] = {
                "status": "ok",
                "count": count,
                "reference": (
                    _canonical_hash(
                        {
                            "provider": normalized,
                            "reference": str(reference),
                        }
                    )
                    if reference is not None
                    else None
                ),
            }
        return projected

    def _preview(self, intent: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        assert self.journal is not None
        fingerprint = self._fingerprint(intent, item)
        state, existing = self.journal.load_preview(
            intent_id=intent["intent_id"],
            item_id=item["item_id"],
            fingerprint=fingerprint,
        )
        if existing is not None:
            return existing
        if state == "cancelled":
            return self._item_error_result(
                item_id=item["item_id"],
                subject=item["subject"],
                error=_error(
                    code="INTENT_CANCELLED",
                    message="The acquisition item was cancelled before dispatch.",
                    retryable=False,
                    category="cancellation",
                    item_id=item["item_id"],
                ),
            )
        try:
            pipeline = self.legacy.runner(
                self._pipeline_input(intent, item),
                True,
                False,
                None,
            )
            candidates = self._project_candidates(pipeline)
        except Exception:
            return self._item_error_result(
                item_id=item["item_id"],
                subject=item["subject"],
                error=_error(
                    code="PREVIEW_FAILED",
                    message="The acquisition preview workflow failed safely.",
                    retryable=True,
                    category="provider",
                    item_id=item["item_id"],
                ),
                status="error",
            )
        if pipeline.get("error") or (pipeline.get("decision") or {}).get("status") == "error":
            result = self._item_error_result(
                item_id=item["item_id"],
                subject=item["subject"],
                error=_error(
                    code="PREVIEW_FAILED",
                    message="The acquisition preview workflow failed.",
                    retryable=True,
                    category="provider",
                    item_id=item["item_id"],
                ),
            )
            return result
        preview_result_id = _canonical_hash(
            {
                "fingerprint": fingerprint,
                "candidate_refs": [candidate["candidate_ref"] for candidate in candidates],
            }
        )
        result = {
            "item_id": item["item_id"],
            "subject": copy.deepcopy(item["subject"]),
            "status": "choice_required" if candidates else "no_candidates",
            "preview_result_id": preview_result_id,
            "candidates": candidates,
            "selected": None,
            "dispatch": {},
            "verification": {
                "required": False,
                "status": "not_applicable",
                "ownership_update_allowed": False,
            },
            "error": None,
        }
        result = self.legacy.sanitize_result(result)
        return self.journal.save_preview(
            intent_id=intent["intent_id"],
            item_id=item["item_id"],
            fingerprint=fingerprint,
            preview_result_id=preview_result_id,
            preview=result,
        )

    def _dispatch(self, intent: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        assert self.journal is not None
        selection = item["selection"]
        confirmation = item["confirmation"]
        fingerprint = self._fingerprint(intent, item)
        state, retained = self.journal.begin_dispatch(
            intent_id=intent["intent_id"],
            item_id=item["item_id"],
            fingerprint=fingerprint,
            preview_result_id=selection["preview_result_id"],
            candidate_ref=selection["candidate_ref"],
            confirmation_id=confirmation["confirmation_id"],
        )
        if state == "replay" and retained is not None:
            return retained
        if state == "cancelled":
            return self._item_error_result(
                item_id=item["item_id"],
                subject=item["subject"],
                error=_error(
                    code="INTENT_CANCELLED",
                    message="The acquisition item was cancelled before dispatch.",
                    retryable=False,
                    category="cancellation",
                    item_id=item["item_id"],
                ),
            )
        if state == "uncertain":
            if retained is not None:
                return retained
            result = self._item_error_result(
                item_id=item["item_id"],
                subject=item["subject"],
                error=_error(
                    code="DISPATCH_OUTCOME_UNCERTAIN",
                    message=(
                        "A prior dispatch lease expired without a durable provider "
                        "outcome; reconcile the provider before any retry."
                    ),
                    retryable=False,
                    category="provider",
                    item_id=item["item_id"],
                ),
                status="error",
                preview_result_id=selection["preview_result_id"],
            )
            self.journal.finish_dispatch(
                intent_id=intent["intent_id"],
                item_id=item["item_id"],
                result=result,
            )
            return result
        state_errors = {
            "preview_required": (
                "PREVIEW_REQUIRED",
                "Dispatch requires a retained preview.",
                False,
            ),
            "preview_mismatch": (
                "PREVIEW_MISMATCH",
                "The selected preview receipt is stale or unknown.",
                False,
            ),
            "candidate_mismatch": (
                "CANDIDATE_MISMATCH",
                "The selected candidate was not present in the retained preview.",
                False,
            ),
            "in_progress": (
                "ALREADY_IN_PROGRESS",
                "Matching confirmed dispatch is already in progress.",
                True,
            ),
        }
        if state in state_errors:
            code, message, retryable = state_errors[state]
            result = self._item_error_result(
                item_id=item["item_id"],
                subject=item["subject"],
                error=_error(
                    code=code,
                    message=message,
                    retryable=retryable,
                    category="confirmation",
                    item_id=item["item_id"],
                ),
                status="already_in_progress" if state == "in_progress" else "refused",
                preview_result_id=selection["preview_result_id"],
            )
            return result
        try:
            pipeline = self.legacy.runner(
                self._pipeline_input(
                    intent,
                    item,
                    selected_candidate_ref=selection["candidate_ref"],
                ),
                False,
                True,
                None,
            )
            decision = pipeline.get("decision") or {}
            projected_dispatch = self._project_dispatch(
                pipeline.get("dispatch") or {}
            )
        except Exception:
            result = self._item_error_result(
                item_id=item["item_id"],
                subject=item["subject"],
                error=_error(
                    code="DISPATCH_OUTCOME_UNCERTAIN",
                    message=(
                        "The dispatch workflow ended without a durable provider "
                        "outcome; reconcile the provider before any retry."
                    ),
                    retryable=False,
                    category="provider",
                    item_id=item["item_id"],
                ),
                status="error",
                preview_result_id=selection["preview_result_id"],
            )
            self.journal.finish_dispatch(
                intent_id=intent["intent_id"],
                item_id=item["item_id"],
                result=result,
            )
            return result
        pipeline_error = (
            pipeline.get("error")
            if isinstance(pipeline.get("error"), dict)
            else {}
        )
        stale_choice = (
            pipeline_error.get("code") == "STALE_PREVIEW_CHOICE"
            or (
                not projected_dispatch
                and not pipeline_error
                and decision.get("status") not in {"selected"}
            )
        )
        if not projected_dispatch:
            retry_safe = (
                pipeline_error.get("retryable") is True
                and pipeline_error.get("side_effects_possible") is False
            )
            code = (
                "STALE_PREVIEW_CHOICE"
                if stale_choice
                else "DISPATCH_FAILED"
                if retry_safe
                else "DISPATCH_OUTCOME_UNCERTAIN"
            )
            result = self._item_error_result(
                item_id=item["item_id"],
                subject=item["subject"],
                error=_error(
                    code=code,
                    message=(
                        "The retained candidate is no longer an exact current choice."
                        if stale_choice
                        else (
                            "The provider refused the dispatch before any side effect."
                            if retry_safe
                            else (
                                "The provider did not attest whether dispatch occurred; "
                                "reconcile it before any retry."
                            )
                        )
                    ),
                    retryable=retry_safe and not stale_choice,
                    category="provider",
                    item_id=item["item_id"],
                ),
                status="refused" if stale_choice else "error",
                preview_result_id=selection["preview_result_id"],
            )
            self.journal.finish_dispatch(
                intent_id=intent["intent_id"],
                item_id=item["item_id"],
                result=result,
            )
            return result
        selected_raw = decision.get("selected") or (pipeline.get("work") or {}).get(
            "selected"
        )
        selected = self._project_candidate(selected_raw, decision.get("index"))
        result = {
            "item_id": item["item_id"],
            "subject": copy.deepcopy(item["subject"]),
            "status": "dispatched",
            "preview_result_id": selection["preview_result_id"],
            "candidates": [],
            "selected": selected,
            "dispatch": projected_dispatch,
            "verification": {
                "required": True,
                "status": "pending_err_verification",
                "ownership_update_allowed": False,
            },
            "error": None,
        }
        result = self.legacy.sanitize_result(result)
        self.journal.finish_dispatch(
            intent_id=intent["intent_id"],
            item_id=item["item_id"],
            result=result,
        )
        return result

    def _cancel(self, intent: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        assert self.journal is not None
        fingerprint = self._fingerprint(intent, item)
        state, retained = self.journal.cancellation_state(
            intent_id=intent["intent_id"],
            item_id=item["item_id"],
            fingerprint=fingerprint,
        )
        if state == "replay" and retained is not None:
            return retained
        if state == "cancellable":
            result = {
                "item_id": item["item_id"],
                "subject": copy.deepcopy(item["subject"]),
                "status": "cancelled",
                "preview_result_id": None,
                "candidates": [],
                "selected": None,
                "dispatch": {},
                "verification": {
                    "required": False,
                    "status": "not_applicable",
                    "ownership_update_allowed": False,
                },
                "error": None,
            }
            result = self.legacy.sanitize_result(result)
            self.journal.finish_cancellation(
                intent_id=intent["intent_id"],
                item_id=item["item_id"],
                result=result,
            )
            return result
        if state == "completed":
            error = _error(
                code="CANCELLATION_UNSUPPORTED_AFTER_DISPATCH",
                message=(
                    "IWantIt cannot attest provider-side cancellation after dispatch."
                ),
                retryable=False,
                category="cancellation",
                item_id=item["item_id"],
            )
        elif state == "uncertain":
            error = _error(
                code="CANCELLATION_UNSUPPORTED_OUTCOME_UNCERTAIN",
                message=(
                    "IWantIt cannot cancel an unconfirmed provider outcome; "
                    "reconcile the provider first."
                ),
                retryable=False,
                category="cancellation",
                item_id=item["item_id"],
            )
        elif state == "dispatching":
            error = _error(
                code="DISPATCH_IN_PROGRESS",
                message="The dispatch lease is active; cancellation cannot be attested.",
                retryable=True,
                category="cancellation",
                item_id=item["item_id"],
            )
        else:
            error = _error(
                code="PREVIEW_REQUIRED",
                message="No retained preview exists to cancel.",
                retryable=False,
                category="cancellation",
                item_id=item["item_id"],
            )
        return self._item_error_result(
            item_id=item["item_id"],
            subject=item["subject"],
            error=error,
        )

    @staticmethod
    def _item_error_result(
        *,
        item_id: str,
        subject: dict[str, Any] | None,
        error: dict[str, Any],
        status: str = "refused",
        preview_result_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "item_id": item_id,
            "subject": copy.deepcopy(subject),
            "status": status,
            "preview_result_id": preview_result_id,
            "candidates": [],
            "selected": None,
            "dispatch": {},
            "verification": {
                "required": False,
                "status": "not_applicable",
                "ownership_update_allowed": False,
            },
            "error": error,
        }

    def _privacy(self, intent: dict[str, Any]) -> dict[str, Any]:
        raw_items = intent.get("items")
        items = raw_items if isinstance(raw_items, list) else []
        requested_private = any(
            ((item.get("constraints") or {}).get("policy") or {}).get("private")
            is True
            for item in items
            if isinstance(item, dict)
        )
        requested_sources = {
            provider
            for item in items
            if isinstance(item, dict)
            for provider in (
                ((item.get("constraints") or {}).get("sources") or {}).get(
                    "allowed_providers"
                )
                or []
            )
            if isinstance(provider, str)
        }
        local_private = requested_private or bool(
            requested_sources
            & {"prowlarr", "jackett", "soulseek", "slskd", "redacted"}
        )
        return {
            "classification": "local_private" if local_private else "restricted",
            "persistence": "sanitized_local",
            "community_publish_allowed": False,
            "remote_inference_allowed": False,
            "provider_payloads_exportable": False,
            "private_source_evidence_accepted": False,
        }

    def _result(
        self,
        intent: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        action = str(intent.get("action") or "unknown")
        bounded_items = copy.deepcopy(items)

        def build_body() -> dict[str, Any]:
            statuses = [item["status"] for item in bounded_items]
            successes = {
                "preview": {"choice_required", "no_candidates"},
                "dispatch": {"dispatched"},
                "cancel": {"cancelled"},
            }.get(action, set())
            success_count = sum(status in successes for status in statuses)
            if success_count == len(bounded_items) and bounded_items:
                status = {
                    "preview": "previewed",
                    "dispatch": "dispatched",
                    "cancel": "cancelled",
                }.get(action, "refused")
            elif success_count:
                status = "partial"
            else:
                status = "refused"
            return {
                "schema": RESULT_SCHEMA_ID,
                "intent_id": intent.get("intent_id"),
                "action": (
                    action
                    if action in {"preview", "dispatch", "cancel"}
                    else "unknown"
                ),
                "status": status,
                "side_effects_allowed": action == "dispatch"
                and any(
                    item["status"] == "dispatched" for item in bounded_items
                ),
                "items": bounded_items,
                "privacy": self._privacy(intent),
                "error": None,
            }

        body = build_body()
        while (
            len(
                json.dumps(
                    body,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8")
            )
            + 96
            > MAX_RESULT_BYTES
        ):
            candidate_items = [
                item
                for item in bounded_items
                if isinstance(item.get("candidates"), list)
                and item["candidates"]
            ]
            if not candidate_items:
                return self._top_refusal(
                    intent,
                    _error(
                        code="RESULT_TOO_LARGE",
                        message=(
                            "The bounded acquisition result could not be represented "
                            "within the published result limit."
                        ),
                        retryable=False,
                        category="contract",
                        item_id=None,
                    ),
                )
            largest = max(candidate_items, key=lambda item: len(item["candidates"]))
            largest["candidates"].pop()
            body = build_body()
        body = self.legacy.sanitize_result(body)
        result = {"result_id": _canonical_hash(body), **body}
        if len(
            json.dumps(
                result,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ) > MAX_RESULT_BYTES:
            raise AssertionError("acquisition result exceeded its published bound")
        Draft202012Validator(ACQUISITION_RESULT_SCHEMA).validate(result)
        return result

    def _top_refusal(
        self,
        intent: Any,
        error: dict[str, Any],
    ) -> dict[str, Any]:
        value = intent if isinstance(intent, dict) else {}
        raw_intent_id = value.get("intent_id")
        safe_intent_id = (
            raw_intent_id
            if isinstance(raw_intent_id, str)
            and _SAFE_EXTERNAL_ID.fullmatch(raw_intent_id)
            else None
        )
        body = {
            "schema": RESULT_SCHEMA_ID,
            "intent_id": safe_intent_id,
            "action": (
                str(value.get("action"))
                if value.get("action") in {"preview", "dispatch", "cancel"}
                else "unknown"
            ),
            "status": "refused",
            "side_effects_allowed": False,
            "items": [],
            "privacy": self._privacy(value),
            "error": error,
        }
        body = self.legacy.sanitize_result(body)
        result = {"result_id": _canonical_hash(body), **body}
        Draft202012Validator(ACQUISITION_RESULT_SCHEMA).validate(result)
        return result
