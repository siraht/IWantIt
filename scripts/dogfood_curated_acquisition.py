#!/usr/bin/env python3
"""Dogfood curated acquisition through the real CLI and loopback provider boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._curated_acquisition_fixture_support import (  # noqa: E402
    OfflineRunner,
    acquisition_intent,
    acquisition_item,
    caller,
    confirmed_intent,
    err_subject,
    service_config,
)
from iwantit.acquisition import AcquisitionService  # noqa: E402
from scripts.verify_curated_acquisition_fixtures import verify  # noqa: E402


_PRIVATE_SENTINELS = (
    "dogfood-jackett-api-sentinel",
    "dogfood-dispatch-bearer-sentinel",
    "dogfood-download-token-sentinel",
    "dogfood-provider-response-sentinel",
    "dogfood-private-handle-sentinel",
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _ProviderState:
    def __init__(self) -> None:
        self.search_requests = 0
        self.dispatch_requests: list[dict[str, Any]] = []
        self.fail_next_dispatch = False


def _handler_for(state: _ProviderState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if not self.path.startswith(
                "/api/v2.0/indexers/all/results/torznab/api"
            ):
                self.send_response(404)
                self.end_headers()
                return
            state.search_requests += 1
            body = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Artist - Track (Extended Mix) FLAC WEB</title>
      <guid>https://private.provider.invalid/item/7</guid>
      <link>https://private.provider.invalid/download/7?token=dogfood-download-token-sentinel</link>
      <comments>https://private.provider.invalid/comments/7</comments>
      <size>12345678</size>
      <torznab:attr name="indexer" value="Dogfood Jackett" />
      <torznab:attr name="seeders" value="9" />
      <torznab:attr name="peers" value="2" />
      <torznab:attr name="files" value="1" />
    </item>
  </channel>
</rss>
"""
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/dispatch":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            state.dispatch_requests.append(
                {
                    "idempotency_key": self.headers.get("Idempotency-Key"),
                    "authorization": self.headers.get("Authorization"),
                    "body": body,
                }
            )
            if state.fail_next_dispatch:
                state.fail_next_dispatch = False
                self.send_response(503)
                self.end_headers()
                return
            payload = json.dumps(
                {
                    "status": "created",
                    "private_receipt": "dogfood-provider-response-sentinel",
                }
            ).encode("utf-8")
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return Handler


def _start_server(
    state: _ProviderState,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _write_config(path: Path, *, port: int, journal_path: Path) -> None:
    trusted = caller()
    trusted.pop("origin")
    config = {
        "pre_steps": [],
        "default_workflow": "music",
        "workflows": [
            {
                "name": "music",
                "match": {"media_type": "music"},
                "steps": [
                    "jackett_search",
                    "filter_by_version",
                    "decide",
                    "private_source_dispatch",
                ],
            }
        ],
        "steps": {
            "jackett_search": {"builtin": "jackett_search"},
            "filter_by_version": {"builtin": "filter_by_version"},
            "decide": {"builtin": "decide"},
            "private_source_dispatch": {
                "builtin": "private_source_dispatch",
                "side_effect": True,
                "timeout": 2,
                "retries": 0,
            },
        },
        "acquisition": {
            "idempotency_enabled": True,
            "idempotency_path": str(journal_path),
            "lease_seconds": 60,
            "trusted_callers": [{**trusted, "active": True}],
        },
        "jackett": {
            "enabled": True,
            "url": f"http://127.0.0.1:{port}",
            "api_key": "dogfood-jackett-api-sentinel",
            "indexer": "all",
            "categories": {"music": [3000]},
            "timeout": 2,
            "retries": 0,
            "max_results": 5,
            "dispatch": {
                "url": f"http://127.0.0.1:{port}/dispatch",
                "method": "POST",
                "headers": {
                    "Authorization": "Bearer dogfood-dispatch-bearer-sentinel"
                },
                "url_field": "urls",
            },
        },
    }
    path.write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )


def _run_cli(
    payload: dict[str, Any] | None,
    *,
    config_path: Path,
    env: dict[str, str],
    extra_args: list[str] | None = None,
    allowed_codes: set[int] = frozenset({0}),
) -> tuple[dict[str, Any], int]:
    args = [
        sys.executable,
        "-m",
        "iwantit.cli",
        "acquire",
        "--config",
        str(config_path),
    ]
    if extra_args:
        args.extend(extra_args)
    elif payload is not None:
        args.append("--stdin")
    completed = subprocess.run(
        args,
        input=(
            json.dumps(payload, sort_keys=True)
            if payload is not None and "--stdin" in args
            else None
        ),
        capture_output=True,
        text=True,
        cwd=config_path.parent,
        env=env,
        check=False,
    )
    if completed.returncode not in allowed_codes:
        raise RuntimeError(
            "CLI failed unexpectedly "
            f"(exit={completed.returncode}, stderr={completed.stderr!r})"
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"CLI emitted non-JSON output: {completed.stdout!r}"
        ) from exc
    return result, completed.returncode


def _assert_private_absent(value: Any, location: str) -> None:
    serialized = json.dumps(value, sort_keys=True)
    for sentinel in _PRIVATE_SENTINELS:
        _assert(
            sentinel not in serialized,
            f"private sentinel leaked into {location}",
        )
    _assert(
        "private.provider.invalid" not in serialized,
        f"private provider URL leaked into {location}",
    )


def _error_code(result: dict[str, Any]) -> str | None:
    error = result.get("error")
    if isinstance(error, dict) and error.get("code"):
        return str(error["code"])
    items = result.get("items") or []
    if items and isinstance(items[0], dict):
        error = items[0].get("error")
        if isinstance(error, dict) and error.get("code"):
            return str(error["code"])
    return None


def _service_safe_retry(temp_dir: Path) -> dict[str, Any]:
    runner = OfflineRunner()
    service = AcquisitionService(
        service_config(temp_dir / "safe-retry.sqlite3"),
        {},
        runner=runner,
    )
    request = acquisition_intent(intent_id="dogfood-safe-retry")
    preview = service.handle(request)
    dispatch = confirmed_intent(request, preview)
    runner.safe_failures_remaining = 1
    failed = service.handle(dispatch)
    succeeded = service.handle(dispatch)
    replay = service.handle(dispatch)
    _assert(failed["status"] == "refused", "safe retry failure was not refused")
    _assert(
        _error_code(failed) == "DISPATCH_FAILED"
        and failed["items"][0]["error"]["retryable"] is True,
        "safe retry failure lacked an explicit no-side-effect retry attestation",
    )
    _assert(succeeded["status"] == "dispatched", "safe retry did not succeed")
    _assert(replay == succeeded, "safe retry completion replay drifted")
    _assert(
        len(runner.calls) == 3,
        "completed safe retry replay invoked the provider runner",
    )
    _assert_private_absent(
        {"failed": failed, "succeeded": succeeded, "replay": replay},
        "safe retry results",
    )
    return {
        "failure": "DISPATCH_FAILED",
        "retryable_only_with_no_side_effect_attestation": True,
        "retry_succeeded": True,
        "completed_replay_skipped_runner": True,
    }


def dogfood(output_dir: Path) -> tuple[dict[str, Any], str]:
    state = _ProviderState()
    server, thread = _start_server(state)
    temp_dir = Path(tempfile.mkdtemp(prefix="iwantit-curated-dogfood-"))
    config_path = temp_dir / "config.yaml"
    journal_path = temp_dir / "curated-acquisition.sqlite3"
    _write_config(
        config_path,
        port=int(server.server_address[1]),
        journal_path=journal_path,
    )
    secrets_path = temp_dir / "secrets.yaml"
    secrets_path.write_text("{}\n", encoding="utf-8")
    env = os.environ.copy()
    env["IWANTIT_SECRETS"] = str(secrets_path)
    env["XDG_STATE_HOME"] = str(temp_dir / "state")
    env["XDG_CACHE_HOME"] = str(temp_dir / "cache")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)

    outputs: dict[str, Any] = {}
    try:
        capabilities, _ = _run_cli(
            None,
            config_path=config_path,
            env=env,
            extra_args=["--capabilities"],
        )
        outputs["capabilities"] = capabilities
        _assert(
            capabilities["health"]["status"] == "ready",
            "CLI capabilities did not report ready",
        )
        _assert(
            capabilities["providers"]["configured_active"] == ["jackett"],
            "CLI capabilities did not report the actual active provider",
        )

        explicit = acquisition_intent(intent_id="dogfood-explicit")
        preview, _ = _run_cli(
            explicit,
            config_path=config_path,
            env=env,
        )
        outputs["preview"] = preview
        _assert(
            preview["status"] == "previewed"
            and preview["items"][0]["status"] == "choice_required",
            "CLI preview did not retain an explicit choice",
        )
        _assert(
            preview["items"][0]["subject"] == explicit["items"][0]["subject"],
            "CLI preview changed the exact ERR subject",
        )
        _assert(
            preview["items"][0]["candidates"][0]["source_url"] is None,
            "CLI preview exported a provider URL",
        )

        unconfirmed = deepcopy(explicit)
        unconfirmed["action"] = "dispatch"
        refused, _ = _run_cli(
            unconfirmed,
            config_path=config_path,
            env=env,
            allowed_codes={1},
        )
        outputs["unconfirmed"] = refused
        _assert(
            _error_code(refused) == "CONFIRMATION_REQUIRED",
            "CLI dispatch accepted an unconfirmed item",
        )
        _assert(
            not state.dispatch_requests,
            "unconfirmed CLI dispatch reached the provider",
        )

        dispatch_intent = confirmed_intent(explicit, preview)
        dispatched, _ = _run_cli(
            dispatch_intent,
            config_path=config_path,
            env=env,
        )
        outputs["dispatch"] = dispatched
        _assert(dispatched["status"] == "dispatched", "CLI dispatch failed")
        _assert(
            dispatched["items"][0]["subject"]
            == dispatch_intent["items"][0]["subject"],
            "CLI dispatch changed the exact ERR subject",
        )
        _assert(
            dispatched["items"][0]["verification"]
            == {
                "required": True,
                "status": "pending_err_verification",
                "ownership_update_allowed": False,
            },
            "CLI dispatch claimed ownership before ERR verification",
        )
        _assert(
            len(state.dispatch_requests) == 1,
            "confirmed CLI dispatch did not hand off exactly once",
        )

        replay, _ = _run_cli(
            dispatch_intent,
            config_path=config_path,
            env=env,
        )
        outputs["completed_replay"] = replay
        _assert(replay == dispatched, "CLI completed replay drifted")
        _assert(
            len(state.dispatch_requests) == 1,
            "CLI completed replay repeated the provider handoff",
        )

        cancel_intent = acquisition_intent(intent_id="dogfood-cancel")
        cancel_preview, _ = _run_cli(
            cancel_intent,
            config_path=config_path,
            env=env,
        )
        cancel = acquisition_intent(
            intent_id="dogfood-cancel",
            action="cancel",
        )
        cancelled, _ = _run_cli(
            cancel,
            config_path=config_path,
            env=env,
        )
        cancel_replay, _ = _run_cli(
            cancel,
            config_path=config_path,
            env=env,
        )
        cancel_dispatch = confirmed_intent(cancel_intent, cancel_preview)
        cancelled_dispatch, _ = _run_cli(
            cancel_dispatch,
            config_path=config_path,
            env=env,
            allowed_codes={1},
        )
        outputs["cancelled"] = cancelled
        outputs["cancel_replay"] = cancel_replay
        outputs["cancelled_dispatch"] = cancelled_dispatch
        _assert(
            cancelled["status"] == "cancelled"
            and cancel_replay == cancelled,
            "pre-dispatch cancellation was not stable",
        )
        _assert(
            _error_code(cancelled_dispatch) == "INTENT_CANCELLED",
            "cancelled item was dispatchable",
        )
        _assert(
            len(state.dispatch_requests) == 1,
            "cancellation caused a provider handoff",
        )

        partial = acquisition_intent(
            intent_id="dogfood-partial",
            items=[
                acquisition_item(
                    item_id="non-exact",
                    subject=err_subject(exactness="version_family"),
                ),
                acquisition_item(item_id="exact"),
            ],
        )
        partial_result, _ = _run_cli(
            partial,
            config_path=config_path,
            env=env,
            allowed_codes={1},
        )
        outputs["partial"] = partial_result
        _assert(
            partial_result["status"] == "partial"
            and partial_result["items"][0]["error"]["code"]
            == "EXACT_RECORDING_REQUIRED"
            and partial_result["items"][1]["status"] == "choice_required",
            "CLI partial batch did not preserve its valid item",
        )

        private_item = acquisition_item()
        private_item["source_handle"] = "dogfood-private-handle-sentinel"
        negative_requests = {
            "private_evidence": acquisition_intent(
                intent_id="dogfood-private-evidence",
                items=[private_item],
            ),
            "ingestion_origin": acquisition_intent(
                intent_id="dogfood-ingestion-origin",
                intent_caller=caller(origin_kind="source_ingestion"),
            ),
            "unpaired_caller": acquisition_intent(
                intent_id="dogfood-unpaired",
                intent_caller=caller(pairing_id="unpaired-instance"),
            ),
        }
        expected_errors = {
            "private_evidence": "PRIVATE_SOURCE_EVIDENCE_FORBIDDEN",
            "ingestion_origin": "INVALID_INTENT",
            "unpaired_caller": "UNPAIRED_CALLER",
        }
        for name, request in negative_requests.items():
            result, _ = _run_cli(
                request,
                config_path=config_path,
                env=env,
                allowed_codes={1},
            )
            outputs[name] = result
            _assert(
                _error_code(result) == expected_errors[name],
                f"CLI negative scenario failed closed incorrectly: {name}",
            )
        _assert(
            len(state.dispatch_requests) == 1,
            "negative CLI requests reached provider dispatch",
        )

        unknown_major = acquisition_intent(intent_id="dogfood-unknown-major")
        unknown_major["schema"] = "iwantit.acquisition-intent/99"
        unknown_result, _ = _run_cli(
            unknown_major,
            config_path=config_path,
            env=env,
            allowed_codes={1},
        )
        outputs["unknown_major"] = unknown_result
        _assert(
            _error_code(unknown_result) == "UNSUPPORTED_CONTRACT_VERSION",
            "CLI unknown major did not return a typed refusal",
        )

        confirm_switch_result, _ = _run_cli(
            acquisition_intent(intent_id="dogfood-confirm-switch"),
            config_path=config_path,
            env=env,
            extra_args=["--stdin", "--confirm"],
            allowed_codes={1},
        )
        outputs["legacy_confirm_switch"] = confirm_switch_result
        _assert(
            _error_code(confirm_switch_result) == "INVALID_INTENT",
            "legacy --confirm switch bypassed v2 item confirmation",
        )

        uncertain_intent = acquisition_intent(intent_id="dogfood-uncertain")
        uncertain_preview, _ = _run_cli(
            uncertain_intent,
            config_path=config_path,
            env=env,
        )
        uncertain_dispatch = confirmed_intent(
            uncertain_intent,
            uncertain_preview,
        )
        state.fail_next_dispatch = True
        uncertain, _ = _run_cli(
            uncertain_dispatch,
            config_path=config_path,
            env=env,
            allowed_codes={1},
        )
        uncertain_replay, _ = _run_cli(
            uncertain_dispatch,
            config_path=config_path,
            env=env,
            allowed_codes={1},
        )
        outputs["uncertain"] = uncertain
        outputs["uncertain_replay"] = uncertain_replay
        _assert(
            _error_code(uncertain) == "DISPATCH_OUTCOME_UNCERTAIN"
            and uncertain["items"][0]["error"]["retryable"] is False,
            "uncertain provider outcome was retryable",
        )
        _assert(
            uncertain_replay == uncertain,
            "uncertain provider outcome replay drifted",
        )
        _assert(
            len(state.dispatch_requests) == 2,
            "uncertain replay retried or skipped the original provider attempt",
        )

        _assert(
            state.dispatch_requests[0]["authorization"]
            == "Bearer dogfood-dispatch-bearer-sentinel",
            "loopback handoff did not exercise configured authorization",
        )
        _assert(
            "dogfood-download-token-sentinel"
            in json.dumps(state.dispatch_requests[0]["body"]),
            "loopback handoff did not exercise private dispatch coordinates",
        )
        idempotency_keys = [
            request["idempotency_key"] for request in state.dispatch_requests
        ]
        _assert(
            all(
                isinstance(value, str)
                and value.startswith("sha256:")
                and len(value) == 71
                for value in idempotency_keys
            ),
            "provider idempotency keys were not opaque hashes",
        )
        _assert(
            len(set(idempotency_keys)) == len(idempotency_keys),
            "distinct confirmed intents shared a provider idempotency key",
        )

        safe_retry = _service_safe_retry(temp_dir)
        for name, value in outputs.items():
            _assert_private_absent(value, f"CLI output {name}")

        persisted_paths = [journal_path]
        persisted_paths.extend(
            path
            for base in (temp_dir / "state", temp_dir / "cache")
            if base.exists()
            for path in base.rglob("*")
            if path.is_file()
        )
        for path in persisted_paths:
            content = path.read_bytes()
            for sentinel in _PRIVATE_SENTINELS:
                _assert(
                    sentinel.encode("utf-8") not in content,
                    f"private sentinel persisted in {path.name}",
                )
            _assert(
                b"private.provider.invalid" not in content,
                f"private provider URL persisted in {path.name}",
            )

        fixture_summary = verify(ROOT)
        evidence = {
            "schema": "iwantit.curated-acquisition-dogfood-evidence/1",
            "status": "passed",
            "boundary": {
                "contract": "local_stdio",
                "provider": "loopback_jackett_and_download_client",
                "separate_cli_processes": True,
            },
            "scenarios": {
                "capabilities": "ready",
                "preview": "choice_required",
                "unconfirmed_dispatch": "refused",
                "confirmed_dispatch": "dispatched",
                "completed_replay": "identical_without_handoff",
                "cancel_before_dispatch": "cancelled_and_replayed",
                "partial_batch": "invalid_item_refused_valid_item_preserved",
                "private_evidence": "refused_without_echo_or_persistence",
                "ingestion_origin": "refused",
                "unpaired_caller": "refused",
                "unknown_major": "typed_refusal",
                "legacy_confirm_switch": "cannot_bypass_v2_confirmation",
                "uncertain_dispatch": "reconciliation_required_without_retry",
                "safe_retry": safe_retry,
            },
            "identity": {
                "subject_schema": "err.subject/1.0",
                "entity_kind": "music.recording",
                "exactness": "exact",
                "subject_preserved": True,
            },
            "ownership_handoff": {
                "verification_status": "pending_err_verification",
                "ownership_update_allowed": False,
            },
            "effects": {
                "successful_provider_handoffs": 1,
                "uncertain_provider_attempts": 1,
                "completed_replay_provider_handoffs": 0,
                "cancel_provider_handoffs": 0,
                "opaque_unique_idempotency_keys": True,
            },
            "privacy": {
                "private_values_absent_from_results": True,
                "private_values_absent_from_journal_and_state": True,
                "provider_urls_absent_from_results_and_persistence": True,
                "provider_response_body_not_exported": True,
            },
            "fixtures": fixture_summary,
        }
        _assert_private_absent(evidence, "dogfood evidence")
        output_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = output_dir / "curated-acquisition-dogfood.json"
        evidence_bytes = (
            json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=True)
            + "\n"
        ).encode("utf-8")
        evidence_path.write_bytes(evidence_bytes)
        digest = "sha256:" + hashlib.sha256(evidence_bytes).hexdigest()
        return evidence, digest
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run offline curated acquisition dogfood."
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory for sanitized retained evidence.",
    )
    args = parser.parse_args()
    evidence, digest = dogfood(args.output_dir.resolve())
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "evidence": str(
                    (args.output_dir.resolve()
                    / "curated-acquisition-dogfood.json")
                ),
                "digest": digest,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
