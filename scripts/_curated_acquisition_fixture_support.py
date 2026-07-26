"""Deterministic offline data for curated acquisition conformance tooling."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from iwantit.acquisition_candidate import candidate_reference


def err_subject(
    *,
    exactness: str = "exact",
    entity_kind: str = "music.recording",
) -> dict[str, Any]:
    return {
        "schema_version": "err.subject/1.0",
        "authority_id": "xref:authority:01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "authority_revision": {
            "sequence": 42,
            "event_hash": "sha256:" + "1" * 64,
        },
        "entity_kind": entity_kind,
        "exactness": exactness,
        "local_id": "xref:entity:01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "portable_refs": [
            "musicbrainz:recording:81c386f6-ecde-480e-8f8d-7af94af61f13"
        ],
        "identity_explanation_hash": "sha256:" + "2" * 64,
    }


def caller(
    *,
    pairing_id: str = "pairing-local-1",
    origin_kind: str = "explicit_user_acquisition",
) -> dict[str, Any]:
    return {
        "application": "metamusic",
        "instance_id": "metamusic-local-1",
        "pairing_id": pairing_id,
        "pairing_revision": 1,
        "workspace_id": "workspace-1",
        "actor_id": "actor-1",
        "origin": {
            "kind": origin_kind,
            "interaction_id": "interaction-1",
        },
    }


def acquisition_item(
    *,
    item_id: str = "item-1",
    subject: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "subject": deepcopy(subject or err_subject()),
        "search_hints": {
            "artist": "Artist",
            "title": "Track",
            "version": "Extended Mix",
            "release": "Release",
            "year": 2026,
        },
        "constraints": {
            "sources": {
                "allowed_providers": ["jackett"],
                "excluded_providers": ["soulseek"],
            },
            "formats": ["FLAC"],
            "media": ["WEB"],
            "exact_version": True,
            "allow_substitution": False,
            "rights": {
                "basis": "user_authorized",
                "policy_ref": "rights-policy-1",
            },
            "policy": {
                "authorized_sources_only": True,
                "private": True,
                "policy_version": "acquisition-policy-1",
            },
            "destination": {
                "kind": "metamusic_staging",
                "ref": "staging-target-1",
            },
        },
    }


def acquisition_intent(
    *,
    intent_id: str,
    action: str = "preview",
    items: list[dict[str, Any]] | None = None,
    intent_caller: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "iwantit.acquisition-intent/2",
        "intent_id": intent_id,
        "idempotency_key": f"idempotency-{intent_id}",
        "action": action,
        "caller": deepcopy(intent_caller or caller()),
        "items": deepcopy(items or [acquisition_item()]),
    }


def confirmed_intent(
    preview_intent: dict[str, Any],
    preview_result: dict[str, Any],
    *,
    confirmation_id: str = "confirmation-1",
) -> dict[str, Any]:
    value = deepcopy(preview_intent)
    value["action"] = "dispatch"
    preview_item = preview_result["items"][0]
    chosen = preview_item["candidates"][0]
    selection = {
        "preview_result_id": preview_item["preview_result_id"],
        "candidate_ref": chosen["candidate_ref"],
    }
    value["items"][0]["selection"] = selection
    value["items"][0]["confirmation"] = {
        "approved": True,
        "confirmation_id": confirmation_id,
        "confirmed_at": "2026-07-26T18:00:00Z",
        **selection,
    }
    return value


def target_candidate() -> dict[str, Any]:
    return {
        "title": "Artist - Track (Extended Mix) FLAC WEB",
        "provider": "jackett",
        "indexer": "Jackett",
        "size": 12_345_678,
        "seeders": 9,
        "leechers": 2,
        "info_url": "https://provider.invalid/item?id=7&token=fixture-only",
        "_private": {
            "download_url": (
                "https://provider.invalid/get?id=7&token=fixture-only"
            )
        },
    }


class OfflineRunner:
    """In-memory provider boundary with deterministic, inspectable calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], bool, bool, int | None]] = []
        self.safe_failures_remaining = 0
        self.raise_dispatch_once = False

    def __call__(
        self,
        data: dict[str, Any],
        dry_run: bool,
        confirm: bool,
        choice: int | None,
    ) -> dict[str, Any]:
        self.calls.append((deepcopy(data), dry_run, confirm, choice))
        candidate = target_candidate()
        if dry_run:
            return {
                "run_id": "offline-preview",
                "work": {"candidates": [candidate]},
                "decision": {
                    "status": "needs_choice",
                    "options": [candidate],
                },
                "dispatch": {},
            }
        if self.raise_dispatch_once:
            self.raise_dispatch_once = False
            raise RuntimeError("fixture provider included bearer-value")
        if self.safe_failures_remaining:
            self.safe_failures_remaining -= 1
            return {
                "error": {
                    "code": "PROVIDER_REFUSED",
                    "retryable": True,
                    "side_effects_possible": False,
                },
                "decision": {"status": "error"},
                "dispatch": {},
            }
        expected = candidate_reference(candidate)
        if data["request"].get("selected_acquisition_candidate_ref") != expected:
            return {
                "error": {"code": "STALE_PREVIEW_CHOICE"},
                "decision": {"status": "error"},
                "dispatch": {},
            }
        return {
            "run_id": "offline-dispatch",
            "work": {"candidates": [candidate], "selected": candidate},
            "decision": {
                "status": "selected",
                "selected": candidate,
                "index": 0,
            },
            "dispatch": {
                "jackett": {
                    "status": "ok",
                    "count": 1,
                    "id": "fixture-provider-receipt",
                }
            },
        }


def service_config(journal_path: Path) -> dict[str, Any]:
    trusted = caller()
    trusted.pop("origin")
    return {
        "acquisition": {
            "idempotency_enabled": True,
            "idempotency_path": str(journal_path),
            "lease_seconds": 60,
            "trusted_callers": [{**trusted, "active": True}],
        },
        "jackett": {"enabled": True},
    }
