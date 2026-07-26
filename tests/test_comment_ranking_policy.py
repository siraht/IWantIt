from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

from iwantit.config import default_config
from iwantit.pipeline import Context
from iwantit.steps.builtin import apply_recommendations, redacted_comments


class CommentRankingPolicyTests(TestCase):
    def setUp(self) -> None:
        self.context = Context(
            config={
                "redacted": {
                    "url": "https://redacted.invalid",
                    "api_key": "private-api-key",
                    "session_cookie": "private-session-cookie",
                }
            },
            state_path="/tmp",
        )

    def test_comment_capture_is_a_network_free_policy_boundary(self) -> None:
        data = {"redacted": {"groups": {1: {"response": {}}}}}

        with patch("iwantit.steps.builtin.request_with_retry") as request:
            result = redacted_comments(data, {}, self.context)

        request.assert_not_called()
        self.assertNotIn("comments", result["redacted"])
        self.assertNotIn("_internal", result)
        self.assertEqual(result["warnings"][0]["code"], "CURATION_BOUNDARY")
        self.assertNotIn("private", str(result["warnings"]))

    def test_comment_mentions_cannot_change_candidate_ranking(self) -> None:
        candidate = {
            "title": "Artist - Track",
            "rank": {"score": 12.0, "reasons": ["FLAC"]},
            "redacted": {
                "group": {"catalogueNumber": "CAT-1"},
                "torrent": {"media": "WEB"},
            },
            "_redacted_ids": {"group_id": 1},
        }
        data = {
            "work": {"candidates": [candidate]},
            "_internal": {
                "redacted_comments": {
                    1: ["CAT-1 is the best edition and everyone should get it"]
                }
            },
        }
        before = deepcopy(candidate)

        result = apply_recommendations(data, {"weight": 100000}, self.context)

        self.assertEqual(result["work"]["candidates"][0], before)
        self.assertNotIn("recommendation", result["work"]["candidates"][0])
        self.assertEqual(
            result["warnings"][0]["code"],
            "COMMENT_RANKING_DISABLED",
        )

    def test_default_music_workflow_has_no_comment_steps(self) -> None:
        music = next(
            workflow
            for workflow in default_config()["workflows"]
            if workflow["name"] == "music"
        )

        self.assertNotIn("redacted_comments", music["steps"])
        self.assertNotIn("apply_recommendations", music["steps"])
