import json
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from iwantit.acquisition import AcquisitionService
from iwantit.private_adapters import (
    AdapterContractError,
    AdapterPolicyError,
    JackettAdapter,
    SoulseekAdapter,
    connector_enabled,
    validate_private_endpoint,
)
from iwantit.registry import iter_active_providers, validate_registry_requirements


class FakeResponse:
    def __init__(self, status: int = 200, *, body: bytes = b"", payload=None) -> None:  # noqa: ANN001
        self.status_code = status
        self.content = body
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):  # noqa: ANN201
        return self._payload


def jackett_config() -> dict:
    return {
        "jackett": {
            "enabled": True,
            "url": "http://127.0.0.1:9117",
            "api_key": "jackett-secret",
            "max_results": 5,
            "dispatch": {
                "url": "http://127.0.0.1:8080/api/torrents/add",
                "headers": {"Authorization": "Bearer client-secret"},
            },
        }
    }


def soulseek_config() -> dict:
    return {
        "soulseek": {
            "enabled": True,
            "url": "http://127.0.0.1:5030",
            "api_key": "slskd-secret",
            "search_timeout": 1,
            "max_results": 5,
        }
    }


class PrivateAdapterPolicyTests(TestCase):
    def test_connectors_are_opt_in_and_global_kill_switch_wins(self) -> None:
        config = soulseek_config()
        self.assertTrue(connector_enabled(config, "soulseek"))
        with patch.dict(os.environ, {"IWANTIT_PRIVATE_ACQUISITION_DISABLED": "1"}):
            self.assertFalse(connector_enabled(config, "soulseek"))
            with self.assertRaisesRegex(AdapterPolicyError, "disabled"):
                SoulseekAdapter(config)

    def test_clear_text_remote_endpoint_fails_closed(self) -> None:
        config = {"jackett": {"enabled": True, "url": "http://example.com", "api_key": "x"}}
        with self.assertRaisesRegex(AdapterPolicyError, "clear-text non-local"):
            validate_private_endpoint(config, "jackett")

    def test_registry_marks_enabled_connectors_private_and_checks_secret_refs(self) -> None:
        config = {
            "jackett": {"enabled": True, "url": "http://localhost:9117", "api_key": ""},
            "soulseek": {"enabled": True, "url": "http://localhost:5030", "api_key": "x"},
        }
        self.assertEqual(iter_active_providers(config), ["jackett", "soulseek"])
        errors, _warnings = validate_registry_requirements(config)
        self.assertEqual(errors, ["jackett: missing required config jackett.api_key"])


class JackettAdapterTests(TestCase):
    def test_torznab_fixture_maps_to_minimal_candidate(self) -> None:
        body = Path("tests/fixtures/jackett-music.xml").read_bytes()
        with patch(
            "iwantit.private_adapters.request_with_retry",
            return_value=FakeResponse(body=body),
        ) as request:
            candidate = JackettAdapter(jackett_config()).search("Artist Track")[0]

        self.assertEqual(candidate["provider"], "jackett")
        self.assertEqual(candidate["seeders"], 9)
        self.assertEqual(candidate["size"], 12345678)
        self.assertEqual(candidate["_private"]["download_url"], "https://jackett.local/download/42?apikey=private")
        sent = request.call_args
        self.assertEqual(sent.kwargs["params"]["apikey"], "jackett-secret")

        projected = AcquisitionService({}, {})._project_candidate(candidate, 0)
        serialized = json.dumps(projected)
        self.assertNotIn("private-peer", serialized)
        self.assertNotIn("apikey=private", serialized)
        self.assertNotIn("_private", projected)

    def test_malformed_torznab_is_contract_drift_not_an_empty_success(self) -> None:
        with patch(
            "iwantit.private_adapters.request_with_retry",
            return_value=FakeResponse(body=b"not xml"),
        ):
            with self.assertRaisesRegex(AdapterContractError, "invalid Torznab"):
                JackettAdapter(jackett_config()).search("query")

    def test_dispatch_sends_only_confirmed_selected_url_with_idempotency(self) -> None:
        response = FakeResponse(status=201, payload={"secret": "must not be returned"})
        candidate = {
            "title": "Selected",
            "_private": {"download_url": "http://jackett/file?apikey=secret"},
        }
        with patch("iwantit.private_adapters.request_with_retry", return_value=response) as request:
            result = JackettAdapter(jackett_config()).dispatch(
                candidate, idempotency_key="intent-1:candidate-1"
            )
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("secret", json.dumps(result))
        self.assertEqual(request.call_args.kwargs["headers"]["Idempotency-Key"], "intent-1:candidate-1")


class SoulseekAdapterTests(TestCase):
    def test_slskd_fixture_maps_files_without_exposing_peer_in_projection(self) -> None:
        fixture = json.loads(Path("tests/fixtures/slskd-responses.json").read_text())
        calls = [
            FakeResponse(status=201, payload={"id": "search-id"}),
            FakeResponse(payload=fixture),
        ]
        with patch("iwantit.private_adapters.request_with_retry", side_effect=calls):
            candidate = SoulseekAdapter(soulseek_config()).search("Artist Track")[0]
        self.assertEqual(candidate["title"], "Artist - Track (Extended Mix).flac")
        self.assertEqual(candidate["size"], 23456789)
        projected = AcquisitionService({}, {})._project_candidate(candidate, 0)
        self.assertNotIn("private-peer", json.dumps(projected))

    def test_slskd_contract_drift_fails_closed(self) -> None:
        calls = [FakeResponse(status=201, payload={"id": "search-id"}), FakeResponse(payload={})]
        with patch("iwantit.private_adapters.request_with_retry", side_effect=calls):
            with self.assertRaisesRegex(AdapterContractError, "must be an array"):
                SoulseekAdapter(soulseek_config()).search("Artist Track")

    def test_batch_id_is_stable_for_retries_and_cancel_tolerates_missing(self) -> None:
        candidate = {
            "_private": {
                "username": "peer/name",
                "filename": "Music\\Track.flac",
                "size": 100,
            }
        }
        responses = [FakeResponse(status=201), FakeResponse(status=200), FakeResponse(status=404)]
        with patch("iwantit.private_adapters.request_with_retry", side_effect=responses) as request:
            adapter = SoulseekAdapter(soulseek_config())
            first = adapter.dispatch(candidate, idempotency_key="intent:candidate")
            second = adapter.dispatch(candidate, idempotency_key="intent:candidate")
            adapter.cancel_transfer("peer/name", "transfer-id")
        self.assertEqual(first["id"], second["id"])
        self.assertIn("peer%2Fname", request.call_args.args[1])
