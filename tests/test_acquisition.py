from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from iwantit.acquisition import (
    AcquisitionContractError,
    AcquisitionService,
    sanitize_acquisition_output,
)
from iwantit.cli import build_parser, cmd_acquire


def intent(action: str = "preview", *, approved: bool = False) -> dict:
    return {
        "schema": "iwantit.acquisition-intent/1",
        "intent_id": "intent-1",
        "action": action,
        "recording": {
            "ref": "err:entity:recording",
            "artist": "Artist",
            "title": "Track",
            "version": "Extended Mix",
            "external_refs": {"musicbrainz": "mbid"},
        },
        "desired": {
            "formats": ["FLAC"],
            "media": ["WEB"],
            "exact_version": True,
            "allow_substitution": False,
        },
        "policy": {"authorized_sources_only": True, "private": True},
        "confirmation": {"approved": approved, "selected_candidate_index": 0},
    }


class AcquisitionTests(TestCase):
    def test_preview_preserves_identity_and_never_confirms_dispatch(self) -> None:
        calls = []

        def runner(data, dry_run, confirm, choice):  # noqa: ANN001
            calls.append((data, dry_run, confirm, choice))
            return {
                "run_id": "run-1",
                "work": {"candidates": [{"title": "Track Extended Mix FLAC WEB"}]},
                "decision": {"status": "needs_choice", "options": [{"id": "candidate"}]},
                "dispatch": {},
            }

        result = AcquisitionService({}, {}, runner=runner).handle(intent())

        self.assertEqual(result["status"], "needs_choice")
        self.assertFalse(result["side_effects_allowed"])
        data, dry_run, confirm, choice = calls[0]
        self.assertTrue(dry_run)
        self.assertFalse(confirm)
        self.assertEqual(choice, 0)
        self.assertEqual(data["acquisition_intent"]["recording"]["ref"], result["recording_ref"])
        self.assertIn("Extended Mix", data["request"]["query"])
        self.assertEqual(data["request"]["release_preferences"]["formats"], ["FLAC"])
        self.assertEqual(result["privacy"]["classification"], "local_private")
        self.assertEqual(result["privacy"]["persistence"], "sanitized_local")
        self.assertFalse(result["privacy"]["community_publish_allowed"])
        self.assertFalse(result["privacy"]["remote_inference_allowed"])
        self.assertFalse(result["privacy"]["provider_payloads_exportable"])
        self.assertEqual(result["candidates"][0]["schema"], "iwantit.acquisition-candidate/1")
        self.assertEqual(result["candidates"][0]["source"], "unknown")

    def test_dispatch_requires_confirmation_without_calling_pipeline(self) -> None:
        called = False

        def runner(_data, _dry_run, _confirm, _choice):  # noqa: ANN001
            nonlocal called
            called = True
            return {}

        result = AcquisitionService({}, {}, runner=runner).handle(intent("dispatch"))

        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(result["error"]["code"], "CONFIRMATION_REQUIRED")
        self.assertFalse(called)

    def test_confirmed_dispatch_returns_machine_readable_provenance(self) -> None:
        def runner(_data, dry_run, confirm, choice):  # noqa: ANN001
            self.assertFalse(dry_run)
            self.assertTrue(confirm)
            self.assertEqual(choice, 0)
            return {
                "run_id": "run-dispatch",
                "work": {"selected": {"id": "candidate"}},
                "decision": {"status": "selected", "selected": {"id": "candidate"}},
                "dispatch": {"prowlarr": {"status": "ok", "download_id": "download"}},
                "canonical": {"fields": {"artist": "Artist", "title": "Track"}},
            }

        result = AcquisitionService({}, {}, runner=runner).handle(
            intent("dispatch", approved=True)
        )

        self.assertEqual(result["status"], "dispatched")
        self.assertTrue(result["side_effects_allowed"])
        self.assertEqual(result["provenance"]["run_id"], "run-dispatch")
        self.assertEqual(result["selected"]["schema"], "iwantit.acquisition-candidate/1")
        self.assertEqual(result["selected"]["title"], "Candidate")

    def test_invalid_intent_fails_closed(self) -> None:
        payload = intent()
        payload["desired"]["formats"] = []
        with self.assertRaisesRegex(AcquisitionContractError, "desired.formats"):
            AcquisitionService({}, {}).handle(payload)

    def test_result_projects_private_provider_payload_into_closed_summary(self) -> None:
        def runner(_data, _dry_run, _confirm, _choice):  # noqa: ANN001
            return {
                "run_id": "run-secret",
                "work": {
                    "candidates": [
                        {
                            "title": "Track",
                            "indexer": "Redacted",
                            "seeders": 12,
                            "download_url": "http://provider/download?link=secret&safe=yes",
                            "info_url": "https://redacted.sh/torrents.php?id=41&torrentid=99&token=secret",
                            "redacted": {
                                "group": {
                                    "name": "Track Release",
                                    "year": 2025,
                                    "recordLabel": "Private Label",
                                    "tags": ["deep-house"],
                                    "wikiBody": "large private provider payload",
                                },
                                "torrent": {
                                    "format": "FLAC",
                                    "encoding": "Lossless",
                                    "media": "WEB",
                                    "size": 12345,
                                    "seeders": 12,
                                    "leechers": 2,
                                    "fileCount": 4,
                                    "username": "private-user",
                                },
                            },
                            "_raw": {
                                "downloadUrl": "http://provider/raw?apikey=secret",
                                "infoUrl": "https://catalog/item?id=42&token=secret",
                                "authorization": "Bearer secret",
                            },
                        }
                    ]
                },
                "search": {
                    "provider": {
                        "results": [
                            {
                                "download_url": "https://provider/file?signature=secret",
                                "cookie": "session=secret",
                            }
                        ]
                    }
                },
                "decision": {"status": "needs_choice"},
            }

        result = AcquisitionService({}, {}, runner=runner).handle(intent())

        candidate = result["candidates"][0]
        self.assertEqual(
            set(candidate),
            {
                "schema",
                "candidate_ref",
                "position",
                "title",
                "source",
                "source_url",
                "release",
                "edition",
                "availability",
                "ranking",
            },
        )
        self.assertEqual(candidate["source"], "Redacted")
        self.assertEqual(
            candidate["source_url"],
            "https://redacted.sh/torrents.php?id=41&torrentid=99",
        )
        self.assertEqual(candidate["release"]["tags"], ["deep-house"])
        self.assertEqual(candidate["edition"]["format"], "FLAC")
        self.assertEqual(candidate["edition"]["size_bytes"], 12345)
        self.assertEqual(candidate["availability"]["seeders"], 12)
        self.assertNotIn("download_url", candidate)
        self.assertNotIn("redacted", candidate)
        self.assertNotIn("_raw", candidate)
        self.assertEqual(
            result["provenance"]["search"]["provider"],
            {"query": "", "count": 0, "error_type": None},
        )
        serialized = str(result)
        self.assertNotIn("large private provider payload", serialized)
        self.assertNotIn("private-user", serialized)
        self.assertNotIn("Bearer secret", serialized)

    def test_sanitizer_does_not_mutate_pipeline_payload(self) -> None:
        payload = {"download_url": "https://provider/file?link=secret"}
        sanitized = sanitize_acquisition_output(payload)
        self.assertEqual(payload["download_url"], "https://provider/file?link=secret")
        self.assertEqual(sanitized["download_url"], "https://provider/file")

    def test_candidate_reference_does_not_hash_access_credentials(self) -> None:
        service = AcquisitionService({}, {})
        first = service._project_candidate(
            {
                "title": "Track",
                "info_url": "https://provider/item?id=1&token=first-secret",
            },
            0,
        )
        second = service._project_candidate(
            {
                "title": "Track",
                "info_url": "https://provider/item?id=1&token=second-secret",
            },
            0,
        )

        self.assertEqual(first["candidate_ref"], second["candidate_ref"])

    def test_private_provider_registry_forces_local_only_result_handling(self) -> None:
        config = {
            "redacted": {"url": "https://redacted.sh", "api_key": "configured"}
        }

        result = AcquisitionService(config, {}, runner=lambda *_args: {}).handle(
            {**intent(), "policy": {"authorized_sources_only": True, "private": False}}
        )

        self.assertEqual(result["privacy"]["classification"], "local_private")
        self.assertEqual(result["privacy"]["private_providers"], ["redacted"])
        self.assertFalse(result["privacy"]["community_publish_allowed"])

    def test_cli_exposes_stdin_preview_and_explicit_confirmation(self) -> None:
        parser = build_parser()
        preview = parser.parse_args(["acquire", "--stdin"])
        dispatch = parser.parse_args(["acquire", "--stdin", "--confirm"])
        self.assertEqual(preview.command, "acquire")
        self.assertFalse(preview.confirm)
        self.assertTrue(dispatch.confirm)

    def test_cli_returns_failure_for_structured_v2_refusal(self) -> None:
        payload = {"schema": "iwantit.acquisition-intent/99"}
        args = SimpleNamespace(
            capabilities=False,
            schema=False,
            schema_version="2",
            confirm=False,
            config=None,
        )
        outputs = []
        with (
            patch("iwantit.cli._load_payload", return_value=payload),
            patch("iwantit.cli.ensure_config_exists", return_value=None),
            patch("iwantit.cli.load_config", return_value={}),
            patch("iwantit.cli.write_json", side_effect=outputs.append),
        ):
            status = cmd_acquire(args)

        self.assertEqual(status, 1)
        self.assertEqual(
            outputs[0]["error"]["code"],
            "UNSUPPORTED_CONTRACT_VERSION",
        )

    def test_cli_confirm_flag_cannot_bypass_v2_item_confirmation(self) -> None:
        args = SimpleNamespace(
            capabilities=False,
            schema=False,
            schema_version="2",
            confirm=True,
            config=None,
        )
        outputs = []
        with (
            patch(
                "iwantit.cli._load_payload",
                return_value={"schema": "iwantit.acquisition-intent/2"},
            ),
            patch("iwantit.cli.write_json", side_effect=outputs.append),
        ):
            status = cmd_acquire(args)

        self.assertEqual(status, 1)
        self.assertEqual(outputs[0]["error"]["code"], "INVALID_INTENT")
