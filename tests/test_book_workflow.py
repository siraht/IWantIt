from unittest import TestCase

from iwantit.config import default_config
from iwantit.pipeline import Context
from iwantit.steps.builtin import book_decide, decide, prowlarr_grab, rank_releases


class BookWorkflowTests(TestCase):
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
