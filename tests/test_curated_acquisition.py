from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from jsonschema import Draft202012Validator

from iwantit.acquisition import AcquisitionService
from iwantit.acquisition_candidate import candidate_reference
from iwantit.curated_acquisition_schema import (
    ACQUISITION_CAPABILITIES_SCHEMA,
    ACQUISITION_RESULT_SCHEMA,
    MAX_RESULT_BYTES,
)
from iwantit.pipeline import Context
from iwantit.steps.builtin import decide


def subject(*, exactness: str = "exact", entity_kind: str = "music.recording") -> dict:
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


def caller() -> dict:
    return {
        "application": "metamusic",
        "instance_id": "metamusic-local-1",
        "pairing_id": "pairing-local-1",
        "pairing_revision": 1,
        "workspace_id": "workspace-1",
        "actor_id": "actor-1",
        "origin": {
            "kind": "explicit_user_acquisition",
            "interaction_id": "interaction-1",
        },
    }


def item(*, item_id: str = "item-1", item_subject: dict | None = None) -> dict:
    return {
        "item_id": item_id,
        "subject": item_subject or subject(),
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


def intent(*, action: str = "preview", items: list[dict] | None = None) -> dict:
    return {
        "schema": "iwantit.acquisition-intent/2",
        "intent_id": "intent-1",
        "idempotency_key": "idempotency-1",
        "action": action,
        "caller": caller(),
        "items": items or [item()],
    }


def target_candidate() -> dict:
    return {
        "title": "Artist - Track (Extended Mix) FLAC WEB",
        "provider": "jackett",
        "indexer": "Jackett",
        "size": 123_456,
        "info_url": "https://provider.invalid/item?id=7&token=private",
        "_private": {
            "download_url": "https://provider.invalid/get?id=7&token=private"
        },
    }


class Runner:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, bool, bool, int | None]] = []
        self.fail_preview = False
        self.fail_dispatch_once = False
        self.raise_dispatch_once = False

    def __call__(
        self,
        data: dict,
        dry_run: bool,
        confirm: bool,
        choice: int | None,
    ) -> dict:
        self.calls.append((data, dry_run, confirm, choice))
        candidate = target_candidate()
        if dry_run:
            if self.fail_preview:
                return {
                    "work": {"candidates": []},
                    "search": {
                        "jackett": {
                            "query": "Artist Track",
                            "count": 0,
                            "error_type": "HTTPError",
                        }
                    },
                    "decision": {"status": "needs_choice", "options": []},
                    "dispatch": {},
                }
            return {
                "run_id": "preview-run",
                "work": {"candidates": [candidate]},
                "decision": {"status": "needs_choice", "options": [candidate]},
                "dispatch": {},
            }
        if self.fail_dispatch_once:
            self.fail_dispatch_once = False
            return {
                "error": {
                    "code": "PROVIDER_REFUSED",
                    "retryable": True,
                    "side_effects_possible": False,
                },
                "decision": {"status": "error"},
                "dispatch": {},
            }
        if self.raise_dispatch_once:
            self.raise_dispatch_once = False
            raise RuntimeError("provider response contained bearer-value")
        expected = candidate_reference(candidate)
        if data["request"].get("selected_acquisition_candidate_ref") != expected:
            return {
                "error": {"code": "STALE_PREVIEW_CHOICE"},
                "decision": {"status": "error"},
                "dispatch": {},
            }
        return {
            "run_id": "dispatch-run",
            "work": {"candidates": [candidate], "selected": candidate},
            "decision": {"status": "selected", "selected": candidate, "index": 0},
            "dispatch": {
                "jackett": {
                    "status": "ok",
                    "count": 1,
                    "id": "opaque-dispatch-receipt",
                }
            },
        }


class CuratedAcquisitionTests(TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.runner = Runner()
        self.config = {
            "acquisition": {
                "idempotency_enabled": True,
                "idempotency_path": str(
                    Path(self.directory.name) / "acquisition.sqlite3"
                ),
                "trusted_callers": [{**caller(), "origin": None, "active": True}],
            }
        }
        self.config["acquisition"]["trusted_callers"][0].pop("origin")
        self.service = AcquisitionService(self.config, {}, runner=self.runner)

    def preview(self, payload: dict | None = None) -> dict:
        return self.service.handle(payload or intent())

    def confirmed(self, preview: dict, payload: dict | None = None) -> dict:
        value = deepcopy(payload or intent())
        value["action"] = "dispatch"
        preview_item = preview["items"][0]
        chosen = preview_item["candidates"][0]
        value["items"][0]["selection"] = {
            "preview_result_id": preview_item["preview_result_id"],
            "candidate_ref": chosen["candidate_ref"],
        }
        value["items"][0]["confirmation"] = {
            "approved": True,
            "confirmation_id": "confirmation-1",
            "confirmed_at": "2026-07-26T07:00:00Z",
            "preview_result_id": preview_item["preview_result_id"],
            "candidate_ref": chosen["candidate_ref"],
        }
        return self.service.handle(value)

    def test_preview_requires_explicit_choice_and_never_dispatches(self) -> None:
        result = self.preview()

        Draft202012Validator(ACQUISITION_RESULT_SCHEMA).validate(result)
        self.assertEqual(result["status"], "previewed")
        self.assertFalse(result["side_effects_allowed"])
        self.assertEqual(result["items"][0]["status"], "choice_required")
        self.assertIsNone(result["items"][0]["selected"])
        self.assertEqual(len(self.runner.calls), 1)
        data, dry_run, confirm, choice = self.runner.calls[0]
        self.assertTrue(dry_run)
        self.assertFalse(confirm)
        self.assertIsNone(choice)
        self.assertEqual(
            data["request"]["allowed_acquisition_providers"],
            ["jackett"],
        )
        self.assertEqual(
            data["request"]["excluded_acquisition_providers"],
            ["soulseek"],
        )
        serialized = str(result)
        self.assertIsNone(result["items"][0]["candidates"][0]["source_url"])
        self.assertNotIn("download_url", serialized)

    def test_provider_search_error_is_not_reported_as_no_candidates(self) -> None:
        self.runner.fail_preview = True

        result = self.preview()

        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["items"][0]["status"], "refused")
        self.assertEqual(result["items"][0]["error"]["code"], "PREVIEW_FAILED")
        self.assertTrue(result["items"][0]["error"]["retryable"])
        self.assertFalse(result["side_effects_allowed"])

    def test_confirmed_dispatch_occurs_once_and_replays_across_instances(self) -> None:
        preview = self.preview()
        first = self.confirmed(preview)
        second_service = AcquisitionService(self.config, {}, runner=self.runner)
        second = CuratedAcquisitionTests.confirmed(self, preview)
        second = second_service.handle(
            self._confirmed_payload(preview)
        )

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "dispatched")
        self.assertTrue(first["side_effects_allowed"])
        self.assertEqual(first["items"][0]["status"], "dispatched")
        self.assertEqual(
            first["items"][0]["verification"],
            {
                "required": True,
                "status": "pending_err_verification",
                "ownership_update_allowed": False,
            },
        )
        reference = first["items"][0]["dispatch"]["jackett"]["reference"]
        self.assertRegex(reference, r"^sha256:[0-9a-f]{64}$")
        self.assertNotIn("opaque-dispatch-receipt", json.dumps(first))
        self.assertEqual(len(self.runner.calls), 2)

    def _confirmed_payload(self, preview: dict) -> dict:
        value = intent(action="dispatch")
        preview_item = preview["items"][0]
        chosen = preview_item["candidates"][0]
        value["items"][0]["selection"] = {
            "preview_result_id": preview_item["preview_result_id"],
            "candidate_ref": chosen["candidate_ref"],
        }
        value["items"][0]["confirmation"] = {
            "approved": True,
            "confirmation_id": "confirmation-1",
            "confirmed_at": "2026-07-26T07:00:00Z",
            **value["items"][0]["selection"],
        }
        return value

    def test_dispatch_without_preview_or_confirmation_is_refused(self) -> None:
        payload = intent(action="dispatch")
        result = self.service.handle(payload)

        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["items"][0]["error"]["code"], "CONFIRMATION_REQUIRED")
        self.assertEqual(self.runner.calls, [])

    def test_ingestion_origin_and_unpaired_caller_fail_closed(self) -> None:
        ingestion = intent()
        ingestion["caller"]["origin"]["kind"] = "source_ingestion"
        unpaired = intent()
        unpaired["caller"]["pairing_id"] = "unknown-pairing"

        first = self.service.handle(ingestion)
        second = self.service.handle(unpaired)

        self.assertEqual(first["error"]["code"], "INVALID_INTENT")
        self.assertEqual(second["error"]["code"], "UNPAIRED_CALLER")
        self.assertEqual(self.runner.calls, [])

    def test_invalid_subject_is_item_scoped_and_valid_item_survives(self) -> None:
        invalid = item(
            item_id="bad",
            item_subject=subject(exactness="version_family"),
        )
        valid = item(item_id="good")
        result = self.preview(intent(items=[invalid, valid]))

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["items"][0]["error"]["code"], "EXACT_RECORDING_REQUIRED")
        self.assertEqual(result["items"][1]["status"], "choice_required")
        self.assertEqual(len(self.runner.calls), 1)

    def test_subject_boundary_returns_typed_minimized_refusals(self) -> None:
        bare = item()
        bare["subject"] = "xref:entity:01ARZ3NDEKTSV4RRFFQ69G5FAV"

        malformed_authority = item()
        malformed_authority["subject"].pop("authority_id")

        unsupported_subject_version = item()
        unsupported_subject_version["subject"]["schema_version"] = "err.subject/99.0"

        non_recording = item()
        non_recording["subject"]["entity_kind"] = "music.release"

        non_portable = item()
        non_portable["subject"]["portable_refs"] = [
            "xref:entity:01ARZ3NDEKTSV4RRFFQ69G5FAV"
        ]

        cases = (
            ("bare", bare, "INVALID_ITEM", None),
            (
                "malformed_authority",
                malformed_authority,
                "INVALID_ITEM",
                None,
            ),
            (
                "unsupported_subject_version",
                unsupported_subject_version,
                "INVALID_ITEM",
                None,
            ),
            (
                "non_recording",
                non_recording,
                "EXACT_RECORDING_REQUIRED",
                non_recording["subject"],
            ),
            (
                "non_portable",
                non_portable,
                "NON_PORTABLE_IDENTITY_EVIDENCE",
                non_portable["subject"],
            ),
        )

        for name, request_item, expected_code, expected_subject in cases:
            with self.subTest(name=name):
                result = self.service.handle(intent(items=[request_item]))
                Draft202012Validator(ACQUISITION_RESULT_SCHEMA).validate(result)
                self.assertEqual(result["status"], "refused")
                self.assertEqual(
                    result["items"][0]["error"]["code"],
                    expected_code,
                )
                self.assertEqual(
                    result["items"][0]["subject"],
                    expected_subject,
                )
        self.assertEqual(self.runner.calls, [])

    def test_private_source_evidence_is_refused_without_echoing_value(self) -> None:
        private = item()
        private["source_handle"] = "secret-curator-handle"
        result = self.preview(intent(items=[private]))

        serialized = str(result)
        self.assertEqual(
            result["items"][0]["error"]["code"],
            "PRIVATE_SOURCE_EVIDENCE_FORBIDDEN",
        )
        self.assertNotIn("secret-curator-handle", serialized)
        self.assertEqual(self.runner.calls, [])

    def test_preview_cancel_blocks_later_dispatch_and_replays_cancel(self) -> None:
        preview = self.preview()
        cancel_payload = intent(action="cancel")
        first_cancel = self.service.handle(cancel_payload)
        second_cancel = self.service.handle(cancel_payload)
        dispatch = self.service.handle(self._confirmed_payload(preview))

        self.assertEqual(first_cancel, second_cancel)
        self.assertEqual(first_cancel["status"], "cancelled")
        self.assertEqual(dispatch["items"][0]["error"]["code"], "INTENT_CANCELLED")
        self.assertEqual(len(self.runner.calls), 1)

    def test_post_dispatch_cancel_reports_unsupported(self) -> None:
        preview = self.preview()
        self.service.handle(self._confirmed_payload(preview))

        result = self.service.handle(intent(action="cancel"))

        self.assertEqual(result["status"], "refused")
        self.assertEqual(
            result["items"][0]["error"]["code"],
            "CANCELLATION_UNSUPPORTED_AFTER_DISPATCH",
        )

    def test_failed_dispatch_is_retryable_then_replay_safe(self) -> None:
        preview = self.preview()
        payload = self._confirmed_payload(preview)
        self.runner.fail_dispatch_once = True

        failed = self.service.handle(payload)
        succeeded = self.service.handle(payload)
        replay = self.service.handle(payload)

        self.assertEqual(failed["items"][0]["error"]["code"], "DISPATCH_FAILED")
        self.assertTrue(failed["items"][0]["error"]["retryable"])
        self.assertEqual(succeeded["status"], "dispatched")
        self.assertEqual(succeeded, replay)
        self.assertEqual(len(self.runner.calls), 3)

    def test_unattested_dispatch_exception_becomes_non_retryable_uncertain(self) -> None:
        preview = self.preview()
        payload = self._confirmed_payload(preview)
        self.runner.raise_dispatch_once = True

        failed = self.service.handle(payload)
        replay = self.service.handle(payload)

        self.assertEqual(
            failed["items"][0]["error"]["code"],
            "DISPATCH_OUTCOME_UNCERTAIN",
        )
        self.assertFalse(failed["items"][0]["error"]["retryable"])
        self.assertEqual(failed, replay)
        self.assertNotIn("bearer-value", json.dumps(failed))
        self.assertEqual(len(self.runner.calls), 2)

    def test_expired_dispatch_lease_requires_reconciliation_not_retry(self) -> None:
        preview = self.preview()
        payload = self._confirmed_payload(preview)
        path = Path(self.config["acquisition"]["idempotency_path"])
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                "UPDATE curated_acquisition SET state='dispatching', "
                "candidate_ref=?, confirmation_id=?, "
                "updated_at=datetime('now', '-2 hours')",
                (
                    payload["items"][0]["selection"]["candidate_ref"],
                    payload["items"][0]["confirmation"]["confirmation_id"],
                ),
            )
            connection.commit()

        result = self.service.handle(payload)
        replay = self.service.handle(payload)

        self.assertEqual(
            result["items"][0]["error"]["code"],
            "DISPATCH_OUTCOME_UNCERTAIN",
        )
        self.assertEqual(result, replay)
        self.assertEqual(len(self.runner.calls), 1)

    def test_duplicate_item_ids_are_refused_before_preview(self) -> None:
        duplicate = intent(items=[item(item_id="same"), item(item_id="same")])

        result = self.service.handle(duplicate)

        self.assertEqual(result["error"]["code"], "DUPLICATE_ITEM_ID")
        self.assertEqual(self.runner.calls, [])

    def test_unsupported_provider_is_item_scoped(self) -> None:
        unsupported = item()
        unsupported["constraints"]["sources"]["allowed_providers"] = ["redacted"]

        result = self.preview(intent(items=[unsupported]))

        self.assertEqual(
            result["items"][0]["error"]["code"],
            "UNSUPPORTED_PROVIDER",
        )
        self.assertEqual(self.runner.calls, [])

    def test_unknown_major_version_returns_typed_refusal(self) -> None:
        payload = intent()
        payload["schema"] = "iwantit.acquisition-intent/99"

        result = self.service.handle(payload)

        Draft202012Validator(ACQUISITION_RESULT_SCHEMA).validate(result)
        self.assertEqual(result["status"], "refused")
        self.assertEqual(
            result["error"]["code"],
            "UNSUPPORTED_CONTRACT_VERSION",
        )
        self.assertEqual(self.runner.calls, [])

    def test_invalid_external_id_is_not_echoed_in_refusal(self) -> None:
        payload = intent()
        payload["intent_id"] = {"private": "secret-curator-handle"}

        result = self.service.handle(payload)

        self.assertIsNone(result["intent_id"])
        self.assertNotIn("secret-curator-handle", json.dumps(result))
        self.assertEqual(self.runner.calls, [])

    def test_malformed_provider_shape_returns_typed_refusal(self) -> None:
        malformed = item()
        malformed["constraints"]["sources"]["allowed_providers"] = [
            {"bad_shape": "secret-curator-handle"}
        ]

        result = self.preview(intent(items=[malformed]))

        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["items"][0]["error"]["code"], "INVALID_ITEM")
        self.assertFalse(result["side_effects_allowed"])
        self.assertNotIn("secret-curator-handle", json.dumps(result))
        self.assertEqual(self.runner.calls, [])

    def test_private_evidence_refusal_never_enters_journal(self) -> None:
        private = item()
        private["source_handle"] = "secret-curator-handle"

        result = self.preview(intent(items=[private]))

        self.assertEqual(
            result["items"][0]["error"]["code"],
            "PRIVATE_SOURCE_EVIDENCE_FORBIDDEN",
        )
        for journal_file in Path(self.directory.name).glob("acquisition.sqlite3*"):
            self.assertNotIn(
                b"secret-curator-handle",
                journal_file.read_bytes(),
            )

    def test_result_schema_closes_nested_candidate_payloads(self) -> None:
        result = self.preview()
        mutated = deepcopy(result)
        mutated["items"][0]["candidates"][0]["release"]["provider_body"] = {
            "secret": "not allowed"
        }

        errors = list(
            Draft202012Validator(ACQUISITION_RESULT_SCHEMA).iter_errors(mutated)
        )

        self.assertTrue(errors)

    def test_preview_result_enforces_published_byte_bound(self) -> None:
        artists = [{"name": "A" * 300} for _ in range(32)]
        tags = [f"{index:02d}" + "T" * 118 for index in range(64)]
        reasons = [f"{index:02d}" + "R" * 198 for index in range(32)]
        candidates = [
            {
                "title": f"{index:03d}-" + "X" * 600,
                "provider": "jackett",
                "redacted": {
                    "group": {
                        "name": f"{index:03d}-" + "X" * 600,
                        "musicInfo": {"artists": artists},
                        "tags": tags,
                    },
                    "torrent": {},
                },
                "rank": {"reasons": reasons},
            }
            for index in range(100)
        ]

        def large_runner(*_args):  # noqa: ANN202
            return {
                "work": {"candidates": candidates},
                "decision": {"status": "needs_choice", "options": candidates},
            }

        service = AcquisitionService(self.config, {}, runner=large_runner)
        result = service.handle(intent())

        Draft202012Validator(ACQUISITION_RESULT_SCHEMA).validate(result)
        self.assertLessEqual(
            len(json.dumps(result, separators=(",", ":")).encode()),
            MAX_RESULT_BYTES,
        )
        self.assertLess(len(result["items"][0]["candidates"]), 100)

    def test_capabilities_publish_limits_pairing_and_honest_cancellation(self) -> None:
        capabilities = self.service.capabilities()

        Draft202012Validator(ACQUISITION_CAPABILITIES_SCHEMA).validate(capabilities)
        self.assertEqual(capabilities["health"]["status"], "ready")
        self.assertEqual(capabilities["limits"]["max_batch_items"], 25)
        self.assertEqual(capabilities["limits"]["max_result_bytes"], 2_097_152)
        self.assertTrue(capabilities["pairing"]["required"])
        self.assertFalse(capabilities["pairing"]["credential_in_payload"])
        self.assertFalse(capabilities["cancellation"]["after_dispatch"])
        self.assertEqual(
            capabilities["idempotency"]["abandoned_dispatch"],
            "reconciliation_required",
        )

    def test_candidate_reference_ignores_position_and_private_coordinates(self) -> None:
        first = target_candidate()
        second = target_candidate()
        second["info_url"] = "https://other-private.invalid/other?id=9&token=changed"
        second["_private"]["download_url"] = (
            "https://other-private.invalid/get?id=9&token=changed"
        )
        second["_private"]["username"] = "private-peer-handle"

        self.assertEqual(candidate_reference(first), candidate_reference(second))

    def test_decide_binds_candidate_reference_not_numeric_position(self) -> None:
        target = target_candidate()
        other = {**target_candidate(), "title": "Other Candidate", "size": 987_654}
        data = {
            "request": {
                "media_type": "music",
                "selected_acquisition_candidate_ref": candidate_reference(target),
            },
            "work": {
                "media_type": "music",
                "candidates": [other, target],
            },
        }

        selected = decide(data, {}, Context(config={}, state_path="/tmp", confirm=True))

        self.assertIs(selected["work"]["selected"], target)
        self.assertEqual(selected["decision"]["index"], 1)
        self.assertEqual(selected["decision"]["reason"], "confirmed_candidate_ref")

        stale = deepcopy(data)
        stale["request"]["selected_acquisition_candidate_ref"] = "sha256:" + "f" * 64
        stale["work"].pop("selected", None)
        refused = decide(
            stale,
            {},
            Context(config={}, state_path="/tmp", confirm=True),
        )
        self.assertEqual(refused["error"]["code"], "STALE_PREVIEW_CHOICE")
        self.assertNotIn("selected", refused["work"])
