import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from iwantit.cli import build_parser
from iwantit.goodreads import (
    GoodreadsShelfService,
    ShelfBook,
    ShelfJournal,
    goodreads_feed_url,
    parse_goodreads_csv,
    parse_goodreads_rss,
)


RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Want to Read</title>
  <item>
    <guid>https://www.goodreads.com/review/show/1</guid>
    <link>https://www.goodreads.com/book/show/123-example</link>
    <book_id>123</book_id><book_title>Example Book</book_title>
    <author_name>Example Author</author_name><isbn>0123456789</isbn>
    <isbn13>9780123456786</isbn13><user_date_added>Sat, 11 Jul 2026</user_date_added>
  </item>
</channel></rss>"""


class GoodreadsParsingTests(TestCase):
    def test_converts_supplied_shelf_url_to_rss(self) -> None:
        url = goodreads_feed_url(
            "https://www.goodreads.com/review/list/151049665-travis?ref=nav_mybooks&shelf=to-read"
        )
        self.assertEqual(
            url,
            "https://www.goodreads.com/review/list_rss/151049665-travis?"
            "page=1&per_page=100&shelf=to-read&sort=date",
        )

    def test_parses_rss_identity_and_metadata(self) -> None:
        books = parse_goodreads_rss(RSS)
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0].item_id, "123")
        self.assertEqual(books[0].title, "Example Book")
        self.assertEqual(books[0].author, "Example Author")
        self.assertEqual(books[0].isbn13, "9780123456786")

    def test_csv_import_filters_to_requested_shelf(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "library.csv"
            path.write_text(
                "Book Id,Title,Author,ISBN,ISBN13,Date Added,Bookshelves,Exclusive Shelf\n"
                "1,Wanted,One,,,2026/01/01,to-read,to-read\n"
                "2,Finished,Two,,,2025/01/01,read,read\n",
                encoding="utf-8",
            )
            books = parse_goodreads_csv(path)
        self.assertEqual([(book.item_id, book.title) for book in books], [("1", "Wanted")])


class ShelfJournalTests(TestCase):
    def test_csv_baseline_is_safe_and_backfill_is_explicit(self) -> None:
        with TemporaryDirectory() as directory:
            journal = ShelfJournal(Path(directory) / "shelf.sqlite3")
            book = ShelfBook("1", "Book", "Author")
            first = journal.ingest(
                [book], shelf="to-read", formats=("ebook", "audiobook"), queue_new=False
            )
            self.assertEqual(first, {"seen": 1, "new": 1, "queued": 0, "baseline": 2})
            self.assertEqual(journal.claim_due(shelf="to-read", limit=10), [])
            second = journal.ingest(
                [book],
                shelf="to-read",
                formats=("ebook", "audiobook"),
                queue_new=False,
                backfill=True,
            )
            self.assertEqual(second["queued"], 2)
            self.assertEqual(len(journal.claim_due(shelf="to-read", limit=10)), 2)

    def test_incremental_rss_only_queues_new_identity(self) -> None:
        with TemporaryDirectory() as directory:
            journal = ShelfJournal(Path(directory) / "shelf.sqlite3")
            existing = ShelfBook("1", "Existing", "Author")
            new = ShelfBook("2", "New", "Author")
            journal.ingest(
                [existing], shelf="to-read", formats=("ebook",), queue_new=False
            )
            stats = journal.ingest(
                [existing, new], shelf="to-read", formats=("ebook",), queue_new=True
            )
            due = journal.claim_due(shelf="to-read", limit=10)
        self.assertEqual(stats["new"], 1)
        self.assertEqual([item["item_id"] for item in due], ["2"])

    def test_abandoned_acquisition_requires_explicit_uncertain_retry(self) -> None:
        with TemporaryDirectory() as directory:
            journal = ShelfJournal(Path(directory) / "shelf.sqlite3", lease_seconds=60)
            journal.ingest(
                [ShelfBook("1", "Book", "Author")],
                shelf="to-read",
                formats=("ebook",),
                queue_new=True,
            )
            self.assertEqual(len(journal.claim_due(shelf="to-read", limit=1)), 1)
            with journal._connection() as connection:
                connection.execute(
                    "UPDATE shelf_leg SET last_attempt_at = '2000-01-01 00:00:00'"
                )
            self.assertEqual(journal.claim_due(shelf="to-read", limit=1), [])
            state = journal.status(shelf="to-read")
            self.assertEqual(state["counts"]["uncertain"]["ebook"], 1)
            self.assertEqual(journal.retry(shelf="to-read"), 0)
            self.assertEqual(journal.retry(shelf="to-read", include_uncertain=True), 1)


class GoodreadsShelfServiceTests(TestCase):
    def _service(self, directory: str, runner):  # noqa: ANN001, ANN202
        config = {
            "goodreads": {
                "state_path": str(Path(directory) / "shelf.sqlite3"),
                "retry_base_seconds": 60,
                "retry_max_seconds": 120,
            }
        }
        return GoodreadsShelfService(config, {}, runner=runner)

    def test_independent_format_legs_complete_once(self) -> None:
        with TemporaryDirectory() as directory:
            calls = []

            def runner(item, book_format, dry_run, confirm, choice):  # noqa: ANN001, ANN202
                calls.append((item["item_id"], book_format, dry_run, confirm, choice))
                return {
                    "run_id": f"run-{book_format}",
                    "decision": {"status": "selected"},
                    "dispatch": {"prowlarr": {"status": "ok"}},
                }

            service = self._service(directory, runner)
            service.journal.ingest(
                [ShelfBook("1", "Book", "Author")],
                shelf="to-read",
                formats=("ebook", "audiobook"),
                queue_new=True,
            )
            first = service.process_due(
                shelf="to-read", limit=10, dry_run=False, confirm=True
            )
            second = service.process_due(
                shelf="to-read", limit=10, dry_run=False, confirm=True
            )
            status = service.journal.status(shelf="to-read")
        self.assertEqual(first["downloaded"], 2)
        self.assertEqual(second["attempted"], 0)
        self.assertEqual({call[1] for call in calls}, {"ebook", "audiobook"})
        self.assertEqual(status["counts"]["complete"], {"audiobook": 1, "ebook": 1})

    def test_reconcile_inventory_marks_owned_without_running_pipeline(self) -> None:
        with TemporaryDirectory() as directory:
            ebook_root = Path(directory) / "ebooks"
            (ebook_root / "Ursula Le Guin" / "The Dispossessed").mkdir(parents=True)
            config = {
                "goodreads": {
                    "state_path": str(Path(directory) / "shelf.sqlite3"),
                    "inventory": {
                        "enabled": True,
                        "required": True,
                        "sources": {
                            "ebook": [{"type": "local", "path": str(ebook_root)}]
                        },
                    },
                }
            }
            service = GoodreadsShelfService(
                config, {}, runner=lambda *_args: self.fail("pipeline should not run")
            )
            service.journal.ingest(
                [ShelfBook("1", "The Dispossessed", "Ursula K. Le Guin")],
                shelf="to-read",
                formats=("ebook",),
                queue_new=True,
            )
            result = service.reconcile_inventory(shelf="to-read", formats=("ebook",))
            state = service.journal.status(shelf="to-read")
        self.assertEqual(result["owned"], {"ebook": 1})
        self.assertEqual(state["counts"]["owned"], {"ebook": 1})

    def test_dry_run_does_not_consume_or_increment_pending_leg(self) -> None:
        with TemporaryDirectory() as directory:
            service = self._service(
                directory,
                lambda *_args: {
                    "decision": {"status": "selected"},
                    "dispatch": {"prowlarr": {"status": "dry_run"}},
                },
            )
            service.journal.ingest(
                [ShelfBook("1", "Book", "Author")],
                shelf="to-read",
                formats=("ebook",),
                queue_new=True,
            )
            preview = service.process_due(
                shelf="to-read", limit=1, dry_run=True, confirm=False
            )
            due = service.journal.claim_due(shelf="to-read", limit=1)
        self.assertEqual(preview["previewed"], 1)
        self.assertEqual(due[0]["attempt_count"], 0)

    def test_dry_run_surfaces_pipeline_errors_without_consuming_leg(self) -> None:
        with TemporaryDirectory() as directory:
            service = self._service(
                directory,
                lambda *_args: {
                    "error": {"message": "provider unavailable"},
                    "decision": {"status": "error"},
                },
            )
            service.journal.ingest(
                [ShelfBook("1", "Book", "Author")],
                shelf="to-read",
                formats=("ebook",),
                queue_new=True,
            )
            preview = service.process_due(
                shelf="to-read", limit=1, dry_run=True, confirm=False
            )
            due = service.journal.claim_due(shelf="to-read", limit=1)
        self.assertEqual(preview["error"], 1)
        self.assertEqual(preview["previewed"], 0)
        self.assertEqual(due[0]["attempt_count"], 0)

    def test_ambiguous_candidate_requires_review_and_is_not_retried(self) -> None:
        with TemporaryDirectory() as directory:
            service = self._service(
                directory,
                lambda *_args: {
                    "run_id": "ambiguous",
                    "work": {"candidates": [{"title": "One"}, {"title": "Two"}]},
                    "decision": {"status": "needs_choice"},
                },
            )
            service.journal.ingest(
                [ShelfBook("1", "Book", "Author")],
                shelf="to-read",
                formats=("ebook",),
                queue_new=True,
            )
            result = service.process_due(
                shelf="to-read", limit=1, dry_run=False, confirm=True
            )
            due = service.journal.claim_due(shelf="to-read", limit=1)
            state = service.journal.status(shelf="to-read")
        self.assertEqual(result["needs_choice"], 1)
        self.assertEqual(due, [])
        self.assertEqual(state["review"][0]["status"], "needs_choice")
        serialized = json.dumps(state)
        self.assertNotIn('"title": "One"', serialized)
        self.assertNotIn('"title": "Two"', serialized)

    def test_explicit_choice_resolves_ambiguous_leg(self) -> None:
        with TemporaryDirectory() as directory:
            choices = []

            def runner(_item, _format, _dry_run, _confirm, choice):  # noqa: ANN001, ANN202
                choices.append(choice)
                return {
                    "run_id": "chosen",
                    "decision": {"status": "selected"},
                    "dispatch": {"prowlarr": {"status": "ok"}},
                }

            service = self._service(directory, runner)
            service.journal.ingest(
                [ShelfBook("1", "Book", "Author")],
                shelf="to-read",
                formats=("ebook",),
                queue_new=True,
            )
            service.journal.set_outcome(
                shelf="to-read",
                item_id="1",
                book_format="ebook",
                status="needs_choice",
            )
            result = service.resolve_choice(
                shelf="to-read",
                item_id="1",
                book_format="ebook",
                choice=2,
                confirm=True,
            )
        self.assertEqual(choices, [2])
        self.assertEqual(result["outcome"], "downloaded")
        self.assertEqual(result["state"]["counts"]["complete"], {"ebook": 1})

    def test_cli_exposes_sync_status_and_retry(self) -> None:
        parser = build_parser()
        sync = parser.parse_args(
            ["shelf", "sync", "goodreads", "--csv", "library.csv", "--backfill", "--confirm"]
        )
        status = parser.parse_args(["shelf", "status"])
        retry = parser.parse_args(["shelf", "retry", "--include-choices"])
        resolve = parser.parse_args(
            [
                "shelf",
                "resolve",
                "123",
                "--book-format",
                "ebook",
                "--choice",
                "0",
                "--confirm",
            ]
        )
        self.assertTrue(sync.backfill)
        self.assertTrue(sync.confirm)
        self.assertEqual(status.shelf_command, "status")
        self.assertTrue(retry.include_choices)
        self.assertFalse(retry.include_uncertain)
        self.assertEqual(resolve.item_id, "123")
        self.assertTrue(resolve.confirm)
