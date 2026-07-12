import json
from unittest import TestCase
from unittest.mock import patch

from iwantit.book_processing import BookProcessingError, RemoteBookProcessor


class RemoteBookProcessorTests(TestCase):
    def config(self):  # noqa: ANN201
        return {
            "book_processing": {
                "ssh_host": "media.local",
                "ebook_root": "/ebooks",
                "audiobook_root": "/audiobooks",
                "ebook_ingest_root": "/ingest",
                "state_path": "/state/processed.json",
                "min_mtime_epoch": 123,
            }
        }

    @patch("iwantit.book_processing.subprocess.run")
    def test_dry_run_is_default_and_passes_bounded_window(self, run):  # noqa: ANN001
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps({"apply": False, "results": []})
        run.return_value.stderr = ""
        result = RemoteBookProcessor(self.config()).run()
        command = run.call_args.args[0]
        self.assertEqual(command[-2:], ["0", "123"])
        self.assertFalse(result["apply"])

    def test_missing_remote_configuration_fails_closed(self) -> None:
        with self.assertRaises(BookProcessingError):
            RemoteBookProcessor({}).run(apply=True)
