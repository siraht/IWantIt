from unittest import TestCase

from iwantit.config import default_config
from iwantit.pipeline import Context
from iwantit.steps.builtin import (
    book_decide,
    decide,
    dedupe_book_release,
    prowlarr_grab,
    rank_releases,
)


class BookWorkflowTests(TestCase):
    def test_requested_format_is_fail_closed(self) -> None:
        config = default_config()
        context = Context(config=config, state_path="", dry_run=True)
        data = {
            "request": {"preferences": {"book_format": "ebook"}},
            "work": {
                "media_type": "book",
                "title": "Example",
                "candidates": [{"title": "Example Audiobook M4B"}],
            },
        }
        result = book_decide(data, {}, context)
        self.assertEqual(result["work"]["candidates"], [])

    def test_categories_classify_an_unlabelled_release(self) -> None:
        config = default_config()
        context = Context(config=config, state_path="", dry_run=True)
        data = {
            "request": {"preferences": {"book_format": "audiobook"}},
            "work": {
                "media_type": "book",
                "candidates": [{"title": "Example by Author", "categories": [{"id": 3030}]}],
            },
        }
        result = book_decide(data, {}, context)
        self.assertEqual(len(result["work"]["candidates"]), 1)

    def test_english_request_rejects_cyrillic_release(self) -> None:
        config = default_config()
        context = Context(config=config, state_path="", dry_run=True)
        data = {
            "request": {"query": "Shantaram", "preferences": {"book_format": "ebook"}},
            "work": {
                "media_type": "book",
                "title": "Shantaram",
                "candidates": [{"title": "Робертс Грегори Шантарам EPUB"}],
            },
        }
        result = book_decide(data, {}, context)
        self.assertEqual(result["work"]["candidates"], [])

    def test_music_only_indexer_is_blocked_for_books(self) -> None:
        config = default_config()
        data = {
            "request": {"query": "Example", "preferences": {"book_format": "audiobook"}},
            "work": {
                "media_type": "book",
                "candidates": [
                    {"title": "Example Audiobook M4B", "indexer": "Redacted"},
                    {"title": "Example Audiobook M4B", "indexer": "MyAnonamouse"},
                ],
            },
        }
        result = book_decide(data, {}, Context(config=config, state_path=""))
        self.assertEqual([item["indexer"] for item in result["work"]["candidates"]], ["MyAnonamouse"])

    def test_release_dedupe_blocks_other_format_leg(self) -> None:
        config = default_config()
        data = {
            "_internal": {"blocked_release_ids": ["same-guid"]},
            "work": {
                "media_type": "book",
                "selected": {"guid": "same-guid", "title": "Example EPUB"},
            },
        }
        result = dedupe_book_release(data, {}, Context(config=config, state_path=""))
        self.assertEqual(result["decision"]["status"], "duplicate_release")

    def test_requested_leg_controls_download_client(self) -> None:
        config = default_config()
        config["prowlarr"]["download_clients"]["book"] = {"ebook": 20, "audiobook": 21}
        data = {
            "request": {"media_type": "book", "preferences": {"book_format": "audiobook"}},
            "work": {
                "media_type": "book",
                "selected": {"title": "Unlabelled Release", "guid": "g", "indexer_id": 1},
            },
        }
        result = prowlarr_grab(
            data,
            config["steps"]["prowlarr_grab"],
            Context(config=config, state_path="", dry_run=True),
        )
        self.assertEqual(result["dispatch"]["prowlarr"]["request"]["json"]["downloadClientId"], 21)

    def test_selects_best_ebook_and_audiobook(self) -> None:
        config = default_config()
        context = Context(config=config, state_path="", dry_run=True)
        data = {
            "request": {
                "query": "Stephen Mitchell Tao Te Ching",
                "media_type": "book",
                "preferences": {"book_format": "both"},
            },
            "work": {
                "media_type": "book",
                "candidates": [
                    {
                        "title": "Stephen Mitchell - Tao Te Ching EPUB",
                        "indexer": "MyAnonaMouse",
                        "seeders": 2,
                        "grabs": 10,
                    },
                    {
                        "title": "Stephen Mitchell - Tao Te Ching EPUB",
                        "indexer": "OtherTracker",
                        "seeders": 200,
                        "grabs": 200,
                    },
                    {
                        "title": "Stephen Mitchell - Tao Te Ching Audiobook M4B",
                        "indexer": "MAM",
                        "seeders": 1,
                        "grabs": 5,
                    },
                ],
            },
        }

        data = book_decide(data, config["steps"]["book_decide"], context)
        data = rank_releases(data, config["steps"]["rank_releases"], context)
        data = decide(data, config["steps"]["decide"], context)

        decision = data.get("decision") or {}
        selected_items = decision.get("selected_items") or []
        self.assertEqual(decision.get("status"), "selected")
        self.assertEqual(decision.get("reason"), "book_formats")
        self.assertEqual(len(selected_items), 2)
        self.assertEqual(selected_items[0]["indexer"], "MyAnonaMouse")
        self.assertEqual(selected_items[1]["indexer"], "MAM")

    def test_grab_builds_requests_for_selected_book_formats(self) -> None:
        config = default_config()
        config["prowlarr"]["download_clients"]["book"] = {
            "ebook": 20,
            "audiobook": 21,
        }
        context = Context(config=config, state_path="", dry_run=True)
        data = {
            "request": {"media_type": "book"},
            "work": {
                "media_type": "book",
                "selected_items": [
                    {
                        "title": "Tao Te Ching EPUB",
                        "guid": "ebook-guid",
                        "indexer_id": 1,
                        "derived": {"book_formats": ["ebook"]},
                    },
                    {
                        "title": "Tao Te Ching Audiobook",
                        "guid": "audio-guid",
                        "indexer_id": 1,
                        "derived": {"book_formats": ["audiobook"]},
                    },
                ],
            },
        }

        result = prowlarr_grab(data, config["steps"]["prowlarr_grab"], context)

        requests = result["dispatch"]["prowlarr"]["requests"]
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["json"]["guid"], "ebook-guid")
        self.assertEqual(requests[1]["json"]["guid"], "audio-guid")
        self.assertEqual(requests[0]["json"]["downloadClientId"], 20)
        self.assertEqual(requests[1]["json"]["downloadClientId"], 21)

    def test_audiobook_ranking_prefers_newer_m4b_over_stale_mp3(self) -> None:
        config = default_config()
        context = Context(config=config, state_path="", dry_run=True)
        data = {
            "request": {
                "query": "Basic Economics Sowell",
                "media_type": "book",
                "preferences": {"book_format": "audiobook"},
            },
            "work": {
                "media_type": "book",
                "candidates": [
                    {
                        "title": "Basic Economics by Thomas Sowell [ENG / MP3]",
                        "indexer": "MyAnonamouse",
                        "seeders": 118,
                        "grabs": 946,
                        "age_hours": 83088,
                    },
                    {
                        "title": "Basic Economics by Thomas Sowell [ENG / M4B]",
                        "indexer": "MyAnonamouse",
                        "seeders": 27,
                        "grabs": 56,
                        "age_hours": 5087,
                    },
                ],
            },
        }

        data = book_decide(data, config["steps"]["book_decide"], context)
        data = rank_releases(data, config["steps"]["rank_releases"], context)

        candidates = data["work"]["candidates"]
        self.assertIn("M4B", candidates[0]["title"])
        self.assertGreater(candidates[0]["rank"]["score"], candidates[1]["rank"]["score"])

    def test_detects_kepub_and_opus_formats(self) -> None:
        config = default_config()
        context = Context(config=config, state_path="", dry_run=True)
        data = {
            "request": {
                "query": "Example Book",
                "media_type": "book",
                "preferences": {"book_format": "both"},
            },
            "work": {
                "media_type": "book",
                "candidates": [
                    {"title": "Example Book [ENG / KEPUB]", "indexer": "MyAnonamouse"},
                    {"title": "Example Book [ENG / OPUS 64k]", "indexer": "MyAnonamouse"},
                ],
            },
        }

        data = book_decide(data, config["steps"]["book_decide"], context)
        formats = [set(item["derived"]["book_formats"]) for item in data["work"]["candidates"]]
        self.assertIn({"ebook"}, formats)
        self.assertIn({"audiobook"}, formats)

    def test_newer_edition_wins_when_edition_not_requested(self) -> None:
        config = default_config()
        context = Context(config=config, state_path="", dry_run=True)
        data = {
            "request": {
                "query": "Example Economics",
                "media_type": "book",
                "preferences": {"book_format": "ebook"},
            },
            "work": {
                "media_type": "book",
                "candidates": [
                    {"title": "Example Economics 3rd Edition 2008 [EPUB]", "indexer": "MyAnonamouse", "seeders": 50},
                    {"title": "Example Economics 5th Edition 2014 [EPUB]", "indexer": "MyAnonamouse", "seeders": 10},
                ],
            },
        }

        data = book_decide(data, config["steps"]["book_decide"], context)
        data = rank_releases(data, config["steps"]["rank_releases"], context)
        self.assertIn("5th Edition", data["work"]["candidates"][0]["title"])

    def test_requested_edition_overrides_newest_edition(self) -> None:
        config = default_config()
        context = Context(config=config, state_path="", dry_run=True)
        data = {
            "request": {
                "query": "Example Economics 3rd Edition",
                "media_type": "book",
                "preferences": {"book_format": "ebook"},
            },
            "work": {
                "media_type": "book",
                "candidates": [
                    {"title": "Example Economics 3rd Edition 2008 [EPUB]", "indexer": "MyAnonamouse", "seeders": 5},
                    {"title": "Example Economics 5th Edition 2014 [EPUB]", "indexer": "MyAnonamouse", "seeders": 80},
                ],
            },
        }

        data = book_decide(data, config["steps"]["book_decide"], context)
        data = rank_releases(data, config["steps"]["rank_releases"], context)
        self.assertIn("3rd Edition", data["work"]["candidates"][0]["title"])
