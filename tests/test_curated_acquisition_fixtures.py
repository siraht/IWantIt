from __future__ import annotations

import unittest

from scripts.verify_curated_acquisition_fixtures import verify


class CuratedAcquisitionFixtureTests(unittest.TestCase):
    def test_canonical_fixtures_are_deterministic_and_valid(self) -> None:
        summary = verify()

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["schemas"], 5)
        self.assertEqual(summary["fixtures"], 51)
        self.assertEqual(summary["scenarios"], 23)
        self.assertEqual(summary["replay_pairs"], 4)


if __name__ == "__main__":
    unittest.main()
