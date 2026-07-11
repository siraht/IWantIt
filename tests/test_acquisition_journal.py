import json
import stat
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from iwantit.acquisition import AcquisitionService
from iwantit.acquisition_journal import AcquisitionJournal, IdempotencyConflictError


def dispatch_intent(title: str = "Track") -> dict:
    return {
        "schema": "iwantit.acquisition-intent/1",
        "intent_id": "stable-intent",
        "action": "dispatch",
        "recording": {"ref": "err:recording:1", "artist": "Artist", "title": title},
        "desired": {"formats": ["FLAC"], "exact_version": True},
        "confirmation": {"approved": True, "selected_candidate_index": 0},
    }


class AcquisitionJournalTests(TestCase):
    def test_completed_dispatch_replays_across_service_instances(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "journal.sqlite3"
            config = {
                "acquisition": {"idempotency_enabled": True, "idempotency_path": str(path)}
            }
            calls = []

            def runner(*_args):  # noqa: ANN202
                calls.append(1)
                return {
                    "work": {"selected": {"title": "Track"}},
                    "decision": {"status": "selected", "selected": {"title": "Track"}},
                    "dispatch": {"prowlarr": {"status": "ok", "id": "opaque"}},
                }

            first = AcquisitionService(config, {}, runner=runner).handle(dispatch_intent())
            second = AcquisitionService(config, {}, runner=runner).handle(dispatch_intent())

            self.assertEqual(first, second)
            self.assertEqual(len(calls), 1)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertNotIn("api_key", json.dumps(second))

    def test_intent_id_reuse_with_different_identity_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            config = {
                "acquisition": {
                    "idempotency_enabled": True,
                    "idempotency_path": str(Path(directory) / "journal.sqlite3"),
                }
            }
            runner = lambda *_args: {"decision": {"status": "selected"}}  # noqa: E731
            service = AcquisitionService(config, {}, runner=runner)
            service.handle(dispatch_intent())
            with self.assertRaisesRegex(IdempotencyConflictError, "different"):
                service.handle(dispatch_intent("Different track"))

    def test_failed_dispatch_can_be_retried(self) -> None:
        with TemporaryDirectory() as directory:
            config = {
                "acquisition": {
                    "idempotency_enabled": True,
                    "idempotency_path": str(Path(directory) / "journal.sqlite3"),
                }
            }
            calls = []

            def runner(*_args):  # noqa: ANN202
                calls.append(1)
                if len(calls) == 1:
                    return {"error": {"code": "NETWORK"}, "decision": {"status": "error"}}
                return {
                    "decision": {"status": "selected"},
                    "dispatch": {"prowlarr": {"status": "ok", "id": "opaque"}},
                }

            service = AcquisitionService(config, {}, runner=runner)
            self.assertEqual(service.handle(dispatch_intent())["status"], "error")
            self.assertEqual(service.handle(dispatch_intent())["status"], "dispatched")
            self.assertEqual(len(calls), 2)

    def test_completed_result_is_replayed_in_a_new_process(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "journal.sqlite3"
            intent = dispatch_intent()
            code = (
                "import json,sys;"
                "from pathlib import Path;"
                "from iwantit.acquisition_journal import AcquisitionJournal;"
                "j=AcquisitionJournal(Path(sys.argv[1]));"
                "i=json.loads(sys.argv[2]);"
                "r=j.begin(i);"
                "print(json.dumps(r,sort_keys=True))"
            )
            journal = AcquisitionJournal(path)
            self.assertIsNone(journal.begin(intent))
            journal.finish(intent["intent_id"], {"status": "dispatched", "opaque": "receipt"})
            completed = subprocess.run(
                [sys.executable, "-c", code, str(path), json.dumps(intent)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                json.loads(completed.stdout),
                {"status": "dispatched", "opaque": "receipt"},
            )
