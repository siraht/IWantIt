import json
from pathlib import Path
from unittest import TestCase

from iwantit.steps.builtin import _find_candidates, _map_candidates


class ProviderFixtureTests(TestCase):
    def test_kagi_fixture_mapping(self) -> None:
        payload = json.loads(Path("tests/fixtures/kagi.json").read_text(encoding="utf-8"))
        candidates = _find_candidates(payload, "data", [])
        mapped = _map_candidates(
            candidates,
            {"title": "title", "url": "url", "snippet": "snippet"},
            include_raw=False,
        )
        self.assertEqual(len(mapped), 2)
        self.assertEqual(mapped[0]["title"], "Artist - Album (2020)")

    def test_brave_fixture_mapping(self) -> None:
        payload = json.loads(Path("tests/fixtures/brave.json").read_text(encoding="utf-8"))
        candidates = _find_candidates(payload, "web.results", [])
        mapped = _map_candidates(
            candidates,
            {"title": "title", "url": "url", "snippet": "description"},
            include_raw=False,
        )
        self.assertEqual(len(mapped), 1)
        self.assertEqual(mapped[0]["url"], "https://example.com/album")
