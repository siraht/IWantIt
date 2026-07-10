from unittest import TestCase

from iwantit.acquisition import AcquisitionContractError, AcquisitionService
from iwantit.cli import build_parser


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
        self.assertEqual(result["selected"]["id"], "candidate")

    def test_invalid_intent_fails_closed(self) -> None:
        payload = intent()
        payload["desired"]["formats"] = []
        with self.assertRaisesRegex(AcquisitionContractError, "too short"):
            AcquisitionService({}, {}).handle(payload)

    def test_cli_exposes_stdin_preview_and_explicit_confirmation(self) -> None:
        parser = build_parser()
        preview = parser.parse_args(["acquire", "--stdin"])
        dispatch = parser.parse_args(["acquire", "--stdin", "--confirm"])
        self.assertEqual(preview.command, "acquire")
        self.assertFalse(preview.confirm)
        self.assertTrue(dispatch.confirm)
