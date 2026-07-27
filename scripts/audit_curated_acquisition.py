#!/usr/bin/env python3
"""Fresh adversarial audit of curated acquisition through real process boundaries."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
IWANTIT = ROOT / ".venv/bin/iwantit"
METAMUSIC = Path("/data/projects/plex_music_management")
ERR = Path("/data/projects/ERR")
AUDIT_DATE = "2026-07-27"
PRIVATE_SENTINELS = (
    "audit-jackett-api-secret",
    "audit-dispatch-bearer-secret",
    "audit-download-token-secret",
    "audit-provider-private-receipt",
    "audit-private-comment-secret",
    "audit-private-excerpt-secret",
    "audit-private-handle-secret",
    "audit-private-url-secret",
    "audit-private-cookie-secret",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def git_head(path: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def subject() -> dict[str, Any]:
    return {
        "schema_version": "err.subject/1.0",
        "authority_id": "xref:authority:01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "authority_revision": {
            "sequence": 42,
            "event_hash": "sha256:" + "1" * 64,
        },
        "entity_kind": "music.recording",
        "exactness": "exact",
        "local_id": "xref:entity:01ARZ3NDEKTSV4RRFFQ69G5FAV",
        "portable_refs": [
            "musicbrainz:recording:81c386f6-ecde-480e-8f8d-7af94af61f13"
        ],
        "identity_explanation_hash": "sha256:" + "2" * 64,
    }


def caller() -> dict[str, Any]:
    return {
        "application": "metamusic",
        "instance_id": "audit-metamusic-instance",
        "pairing_id": "audit-pairing",
        "pairing_revision": 7,
        "workspace_id": "audit-workspace",
        "actor_id": "audit-actor",
        "origin": {
            "kind": "explicit_user_acquisition",
            "interaction_id": "audit-interaction",
        },
    }


def item(item_id: str = "item-1") -> dict[str, Any]:
    return {
        "item_id": item_id,
        "subject": subject(),
        "search_hints": {
            "artist": "Audit Artist",
            "title": "Audit Track",
            "version": "Extended Mix",
            "release": "Audit Release",
            "year": 2026,
        },
        "constraints": {
            "sources": {
                "allowed_providers": ["jackett"],
                "excluded_providers": [],
            },
            "formats": ["FLAC"],
            "media": ["WEB"],
            "exact_version": True,
            "allow_substitution": False,
            "rights": {
                "basis": "user_authorized",
                "policy_ref": "audit-rights-policy",
            },
            "policy": {
                "authorized_sources_only": True,
                "private": True,
                "policy_version": "audit-acquisition-policy",
            },
            "destination": {
                "kind": "metamusic_staging",
                "ref": "audit-staging",
            },
        },
    }


def intent(
    name: str,
    *,
    action: str = "preview",
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "iwantit.acquisition-intent/2",
        "intent_id": f"audit-{name}",
        "idempotency_key": f"audit-key-{name}",
        "action": action,
        "caller": caller(),
        "items": items or [item()],
    }


def confirmed(preview_request: dict[str, Any], preview: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(preview_request)
    payload["action"] = "dispatch"
    preview_item = preview["items"][0]
    candidate_ref = preview_item["candidates"][0]["candidate_ref"]
    preview_result_id = preview_item["preview_result_id"]
    payload["items"][0]["selection"] = {
        "preview_result_id": preview_result_id,
        "candidate_ref": candidate_ref,
    }
    payload["items"][0]["confirmation"] = {
        "approved": True,
        "confirmation_id": f"confirm-{payload['intent_id']}",
        "confirmed_at": "2026-07-27T00:00:00Z",
        "preview_result_id": preview_result_id,
        "candidate_ref": candidate_ref,
    }
    return payload


class ProviderState:
    def __init__(self) -> None:
        self.searches = 0
        self.dispatch_requests: list[dict[str, Any]] = []
        self.provider_effects = 0
        self.fail_search = False
        self.malformed_search = False
        self.many_candidates = False
        self.drop_after_effect = False


def handler_for(state: ProviderState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if not self.path.startswith(
                "/api/v2.0/indexers/all/results/torznab/api"
            ):
                self.send_response(404)
                self.end_headers()
                return
            state.searches += 1
            if state.fail_search:
                state.fail_search = False
                self.send_response(503)
                self.end_headers()
                return
            if state.malformed_search:
                state.malformed_search = False
                body = b"<rss><broken>"
            else:
                count = 140 if state.many_candidates else 1
                state.many_candidates = False
                entries = []
                for index in range(count):
                    suffix = f" {index}" if count > 1 else ""
                    padding = " X" * 2_000 if count > 1 else ""
                    entries.append(
                        f"""
    <item>
      <title>Audit Artist - Audit Track (Extended Mix) FLAC WEB{suffix}{padding}</title>
      <guid>https://audit-private-url-secret.invalid/item/{index}</guid>
      <link>https://audit-private-url-secret.invalid/download/{index}?token=audit-download-token-secret</link>
      <comments>https://audit-private-url-secret.invalid/comments/{index}</comments>
      <size>{12345678 + index}</size>
      <torznab:attr name="indexer" value="Audit Jackett" />
      <torznab:attr name="seeders" value="9" />
      <torznab:attr name="peers" value="2" />
      <torznab:attr name="files" value="1" />
    </item>"""
                    )
                body = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<rss version="2.0" '
                    'xmlns:torznab="http://torznab.com/schemas/2015/feed">'
                    f"<channel>{''.join(entries)}</channel></rss>"
                ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/dispatch":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            request = {
                "authorization": self.headers.get("Authorization"),
                "idempotency_key": self.headers.get("Idempotency-Key"),
                "body": json.loads(self.rfile.read(length)),
            }
            state.dispatch_requests.append(request)
            state.provider_effects += 1
            if state.drop_after_effect:
                state.drop_after_effect = False
                self.close_connection = True
                return
            response = json.dumps(
                {
                    "status": "created",
                    "receipt": "audit-provider-private-receipt",
                }
            ).encode()
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

    return Handler


def config_value(root: Path, port: int) -> dict[str, Any]:
    trusted = caller()
    trusted.pop("origin")
    return {
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
            "idempotency_path": str(root / "journal.sqlite3"),
            "lease_seconds": 60,
            "trusted_callers": [{**trusted, "active": True}],
        },
        "jackett": {
            "enabled": True,
            "url": f"http://127.0.0.1:{port}",
            "api_key": "audit-jackett-api-secret",
            "indexer": "all",
            "categories": {"music": [3000]},
            "timeout": 2,
            "retries": 0,
            "max_results": 200,
            "max_response_bytes": 5_000_000,
            "dispatch": {
                "url": f"http://127.0.0.1:{port}/dispatch",
                "method": "POST",
                "headers": {
                    "Authorization": "Bearer audit-dispatch-bearer-secret"
                },
                "url_field": "urls",
            },
        },
        "logging": {"path": str(root / "state/iwantit-audit.jsonl")},
        "report": {"enabled": True},
    }


def write_config(path: Path, value: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def run_cli(
    payload: dict[str, Any] | None,
    *,
    config_path: Path,
    env: dict[str, str],
    capabilities: bool = False,
) -> tuple[dict[str, Any], int, str]:
    command = [
        str(IWANTIT),
        "acquire",
        "--config",
        str(config_path),
        "--capabilities" if capabilities else "--stdin",
    ]
    completed = subprocess.run(
        command,
        input=json.dumps(payload, sort_keys=True) if payload is not None else None,
        cwd=config_path.parent,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    require(completed.returncode in {0, 1}, f"unexpected CLI exit {completed.returncode}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError("CLI emitted non-JSON output") from error
    require(isinstance(result, dict), "CLI result is not an object")
    return result, completed.returncode, completed.stderr


def error_code(result: dict[str, Any]) -> str | None:
    if isinstance(result.get("error"), dict):
        return str(result["error"].get("code"))
    items = result.get("items")
    if isinstance(items, list) and items and isinstance(items[0], dict):
        error = items[0].get("error")
        if isinstance(error, dict):
            return str(error.get("code"))
    return None


def assert_private_absent(value: Any, location: str) -> None:
    serialized = (
        value
        if isinstance(value, str)
        else json.dumps(value, sort_keys=True, ensure_ascii=True)
    )
    for sentinel in PRIVATE_SENTINELS:
        require(sentinel not in serialized, f"{sentinel} leaked into {location}")


def assert_refused_without_effect(
    result: dict[str, Any],
    *,
    before_effects: int,
    state: ProviderState,
) -> None:
    require(result["status"] in {"refused", "partial"}, "request did not fail closed")
    require(result["side_effects_allowed"] is False, "refusal allowed side effects")
    require(state.provider_effects == before_effects, "refusal reached provider effect")


def meta_consumer_probe(
    *,
    config_path: Path,
    env: dict[str, str],
    positive_payload_path: Path,
    refusal_payload_path: Path,
) -> dict[str, Any]:
    python = METAMUSIC / ".venv/bin/python"
    code = """
import json
import sys
from music_control_plane.acquisition import IWantItProcessGateway
from music_control_plane.curated_acquisition_contracts import AcquisitionCapabilities, AcquisitionResult

config, positive_path, refusal_path, iwantit = sys.argv[1:]
gateway = IWantItProcessGateway((iwantit, "acquire", "--config", config, "--stdin"), timeout_seconds=15)
capabilities = AcquisitionCapabilities.model_validate(gateway.capabilities())
positive = AcquisitionResult.model_validate(gateway.handle(json.load(open(positive_path))))
typed_refusal_preserved = True
try:
    AcquisitionResult.model_validate(gateway.handle(json.load(open(refusal_path))))
except RuntimeError:
    typed_refusal_preserved = False
print(json.dumps({
    "capability_contract": capabilities.contract_schema,
    "positive_contract": positive.contract_schema,
    "positive_status": positive.status,
    "typed_refusal_preserved": typed_refusal_preserved,
}, sort_keys=True))
"""
    completed = subprocess.run(
        [
            str(python),
            "-c",
            code,
            str(config_path),
            str(positive_payload_path),
            str(refusal_payload_path),
            str(IWANTIT),
        ],
        cwd=METAMUSIC,
        env={**env, "PYTHONPATH": str(METAMUSIC / "src")},
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    require(completed.returncode == 0, "MetaMusic live consumer probe failed")
    result = json.loads(completed.stdout)
    require(result["positive_contract"] == "iwantit.acquisition-result/2", "v2 drift")
    return result


def artifact_contract_probe() -> dict[str, Any]:
    python = METAMUSIC / ".venv/bin/python"
    tests = [
        (
            "tests_vnext/test_acquisition_ingest.py::"
            "test_fulfilled_audio_preview_is_write_free_then_registers_exact_bytes"
        ),
        (
            "tests_vnext/test_acquisition_ingest.py::"
            "test_fulfillment_refuses_when_err_identity_changes_after_preview"
        ),
    ]
    completed = subprocess.run(
        [str(python), "-m", "pytest", "-q", *tests],
        cwd=METAMUSIC,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    require(completed.returncode == 0, "current MetaMusic ERR artifact contract failed")
    return {"tests": tests, "passed": 2}


def run_audit(output: Path) -> dict[str, Any]:
    require(IWANTIT.is_file(), "IWantIt executable is unavailable")
    state = ProviderState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    results: list[dict[str, Any]] = []
    stderr_values: list[str] = []
    upstream_findings: list[dict[str, str]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="iwantit-adversarial-audit-") as raw:
            root = Path(raw)
            config_path = root / "iwantit.yaml"
            config = config_value(root, int(server.server_address[1]))
            write_config(config_path, config)
            secrets_path = root / "secrets.yaml"
            secrets_path.write_text("{}\n", encoding="utf-8")
            env = {
                **os.environ,
                "PYTHONPATH": str(ROOT),
                "IWANTIT_SECRETS": str(secrets_path),
                "XDG_STATE_HOME": str(root / "state"),
                "XDG_CACHE_HOME": str(root / "cache"),
            }

            capabilities, code, stderr = run_cli(
                None, config_path=config_path, env=env, capabilities=True
            )
            results.append(capabilities)
            stderr_values.append(stderr)
            require(code == 0, "capabilities failed")
            require(capabilities["health"]["status"] == "ready", "capability not ready")
            require(capabilities["limits"]["max_batch_items"] == 25, "batch limit drift")
            require(capabilities["limits"]["max_result_bytes"] == 2_097_152, "result limit drift")

            identity_cases: list[tuple[str, Any, set[str]]] = []
            bare = item()
            bare["subject"] = "xref:entity:01ARZ3NDEKTSV4RRFFQ69G5FAV"
            identity_cases.append(("bare", bare, {"INVALID_ITEM"}))
            malformed = item()
            malformed["subject"].pop("authority_id")
            identity_cases.append(("malformed", malformed, {"INVALID_ITEM"}))
            wrong_version = item()
            wrong_version["subject"]["schema_version"] = "err.subject/2.0"
            identity_cases.append(("wrong-version", wrong_version, {"INVALID_ITEM"}))
            inexact = item()
            inexact["subject"]["exactness"] = "version_family"
            identity_cases.append(("inexact", inexact, {"EXACT_RECORDING_REQUIRED"}))
            non_recording = item()
            non_recording["subject"]["entity_kind"] = "music.release"
            identity_cases.append(
                ("non-recording", non_recording, {"EXACT_RECORDING_REQUIRED"})
            )
            nonportable = item()
            nonportable["subject"]["portable_refs"] = [
                "local:recording:private",
                "https://audit-private-url-secret.invalid/recording",
            ]
            identity_cases.append(
                ("nonportable", nonportable, {"NON_PORTABLE_IDENTITY_EVIDENCE"})
            )
            for name, invalid_item, expected in identity_cases:
                before = state.provider_effects
                result, _, stderr = run_cli(
                    intent(f"identity-{name}", items=[invalid_item]),
                    config_path=config_path,
                    env=env,
                )
                results.append(result)
                stderr_values.append(stderr)
                assert_refused_without_effect(result, before_effects=before, state=state)
                require(error_code(result) in expected, f"{name} identity was not refused")

            for key, sentinel in (
                ("comment", "audit-private-comment-secret"),
                ("excerpt", "audit-private-excerpt-secret"),
                ("source_handle", "audit-private-handle-secret"),
                ("source_url", "https://audit-private-url-secret.invalid/source"),
                ("cookie", "audit-private-cookie-secret"),
                ("token", "audit-download-token-secret"),
            ):
                private_item = item()
                private_item[key] = sentinel
                before = state.provider_effects
                result, _, stderr = run_cli(
                    intent(f"private-{key}", items=[private_item]),
                    config_path=config_path,
                    env=env,
                )
                results.append(result)
                stderr_values.append(stderr)
                assert_refused_without_effect(result, before_effects=before, state=state)
                require(
                    error_code(result) == "PRIVATE_SOURCE_EVIDENCE_FORBIDDEN",
                    f"{key} was not rejected at privacy boundary",
                )
                assert_private_absent(result, f"private-{key} result")

            for origin in ("source_ingestion", "recommendation_ranking"):
                payload = intent(f"origin-{origin}", action="dispatch")
                payload["caller"]["origin"]["kind"] = origin
                before = state.provider_effects
                result, _, stderr = run_cli(
                    payload, config_path=config_path, env=env
                )
                results.append(result)
                stderr_values.append(stderr)
                assert_refused_without_effect(result, before_effects=before, state=state)

            unpaired = intent("unpaired")
            unpaired["caller"]["actor_id"] = "unpaired-actor"
            result, _, stderr = run_cli(unpaired, config_path=config_path, env=env)
            results.append(result)
            stderr_values.append(stderr)
            require(error_code(result) == "UNPAIRED_CALLER", "unpaired caller passed")

            duplicate_item = item("duplicate")
            duplicate = intent(
                "duplicate-items",
                items=[duplicate_item, copy.deepcopy(duplicate_item)],
            )
            before_searches = state.searches
            result, _, stderr = run_cli(duplicate, config_path=config_path, env=env)
            results.append(result)
            stderr_values.append(stderr)
            require(error_code(result) == "DUPLICATE_ITEM_ID", "duplicate IDs passed")
            require(state.searches == before_searches, "duplicate IDs searched provider")

            valid = item("valid-item")
            invalid = item("invalid-item")
            invalid["subject"]["exactness"] = "related"
            partial, _, stderr = run_cli(
                intent("partial", items=[valid, invalid]),
                config_path=config_path,
                env=env,
            )
            results.append(partial)
            stderr_values.append(stderr)
            require(partial["status"] == "partial", "partial batch was not retained")
            require(
                [entry["status"] for entry in partial["items"]]
                == ["choice_required", "refused"],
                "partial item statuses drifted",
            )

            main_request = intent("main")
            preview, _, stderr = run_cli(
                main_request, config_path=config_path, env=env
            )
            results.append(preview)
            stderr_values.append(stderr)
            require(preview["items"][0]["status"] == "choice_required", "preview failed")
            require(preview["side_effects_allowed"] is False, "preview allowed effects")
            require(preview["items"][0]["candidates"][0]["source_url"] is None, "URL leak")
            preview_searches = state.searches
            preview_replay, _, stderr = run_cli(
                main_request, config_path=config_path, env=env
            )
            results.append(preview_replay)
            stderr_values.append(stderr)
            require(preview_replay == preview, "preview replay changed")
            require(state.searches == preview_searches, "preview replay searched again")

            unconfirmed = copy.deepcopy(main_request)
            unconfirmed["action"] = "dispatch"
            before = state.provider_effects
            refused, _, stderr = run_cli(
                unconfirmed, config_path=config_path, env=env
            )
            results.append(refused)
            stderr_values.append(stderr)
            require(error_code(refused) == "CONFIRMATION_REQUIRED", "unconfirmed passed")
            assert_refused_without_effect(refused, before_effects=before, state=state)

            dispatch_request = confirmed(main_request, preview)
            dispatched, _, stderr = run_cli(
                dispatch_request, config_path=config_path, env=env
            )
            results.append(dispatched)
            stderr_values.append(stderr)
            effect_after_dispatch = state.provider_effects
            require(dispatched["status"] == "dispatched", "confirmed dispatch failed")
            require(effect_after_dispatch == before + 1, "dispatch effect count drifted")
            verification = dispatched["items"][0]["verification"]
            require(
                verification
                == {
                    "required": True,
                    "status": "pending_err_verification",
                    "ownership_update_allowed": False,
                },
                "ERR verification boundary drifted",
            )
            dispatch_replay, _, stderr = run_cli(
                dispatch_request, config_path=config_path, env=env
            )
            results.append(dispatch_replay)
            stderr_values.append(stderr)
            require(dispatch_replay == dispatched, "dispatch replay changed")
            require(
                state.provider_effects == effect_after_dispatch,
                "dispatch replay repeated provider effect",
            )
            require(
                len(
                    {
                        request["idempotency_key"]
                        for request in state.dispatch_requests[:effect_after_dispatch]
                    }
                )
                == effect_after_dispatch,
                "provider dispatch keys were not unique per effect",
            )

            cancel_after = copy.deepcopy(main_request)
            cancel_after["action"] = "cancel"
            cancel_result, _, stderr = run_cli(
                cancel_after, config_path=config_path, env=env
            )
            results.append(cancel_result)
            stderr_values.append(stderr)
            require(
                error_code(cancel_result) == "CANCELLATION_UNSUPPORTED_AFTER_DISPATCH",
                "post-dispatch cancellation was overstated",
            )

            cancel_request = intent("cancel")
            cancel_preview, _, stderr = run_cli(
                cancel_request, config_path=config_path, env=env
            )
            results.append(cancel_preview)
            stderr_values.append(stderr)
            cancel_payload = copy.deepcopy(cancel_request)
            cancel_payload["action"] = "cancel"
            cancelled, _, stderr = run_cli(
                cancel_payload, config_path=config_path, env=env
            )
            cancel_replay, _, stderr2 = run_cli(
                cancel_payload, config_path=config_path, env=env
            )
            results.extend([cancelled, cancel_replay])
            stderr_values.extend([stderr, stderr2])
            require(cancelled == cancel_replay, "cancel replay changed")
            require(cancelled["status"] == "cancelled", "pre-dispatch cancel failed")
            blocked_dispatch, _, stderr = run_cli(
                confirmed(cancel_request, cancel_preview),
                config_path=config_path,
                env=env,
            )
            results.append(blocked_dispatch)
            stderr_values.append(stderr)
            require(error_code(blocked_dispatch) == "INTENT_CANCELLED", "cancel bypassed")

            conflict = copy.deepcopy(main_request)
            conflict["items"][0]["search_hints"]["title"] = "Changed title"
            conflict_result, _, stderr = run_cli(
                conflict, config_path=config_path, env=env
            )
            results.append(conflict_result)
            stderr_values.append(stderr)
            require(error_code(conflict_result) == "IDEMPOTENCY_CONFLICT", "conflict passed")

            safe_request = intent("safe-retry")
            safe_preview, _, stderr = run_cli(
                safe_request, config_path=config_path, env=env
            )
            results.append(safe_preview)
            stderr_values.append(stderr)
            safe_dispatch = confirmed(safe_request, safe_preview)
            safe_config = copy.deepcopy(config)
            safe_config["jackett"]["dispatch"] = {}
            write_config(config_path, safe_config)
            before = state.provider_effects
            safe_failure, _, stderr = run_cli(
                safe_dispatch, config_path=config_path, env=env
            )
            results.append(safe_failure)
            stderr_values.append(stderr)
            require(error_code(safe_failure) == "DISPATCH_FAILED", "safe refusal uncertain")
            require(
                safe_failure["items"][0]["error"]["retryable"] is True,
                "safe refusal not retryable",
            )
            require(state.provider_effects == before, "safe refusal reached provider")
            write_config(config_path, config)
            safe_success, _, stderr = run_cli(
                safe_dispatch, config_path=config_path, env=env
            )
            safe_replay, _, stderr2 = run_cli(
                safe_dispatch, config_path=config_path, env=env
            )
            results.extend([safe_success, safe_replay])
            stderr_values.extend([stderr, stderr2])
            require(safe_success == safe_replay, "safe retry replay changed")
            require(state.provider_effects == before + 1, "safe retry effect count drifted")

            uncertain_request = intent("uncertain")
            uncertain_preview, _, stderr = run_cli(
                uncertain_request, config_path=config_path, env=env
            )
            results.append(uncertain_preview)
            stderr_values.append(stderr)
            uncertain_dispatch = confirmed(uncertain_request, uncertain_preview)
            state.drop_after_effect = True
            before = state.provider_effects
            uncertain, _, stderr = run_cli(
                uncertain_dispatch, config_path=config_path, env=env
            )
            uncertain_replay, _, stderr2 = run_cli(
                uncertain_dispatch, config_path=config_path, env=env
            )
            results.extend([uncertain, uncertain_replay])
            stderr_values.extend([stderr, stderr2])
            require(
                error_code(uncertain) == "DISPATCH_OUTCOME_UNCERTAIN",
                "lost response was not uncertain",
            )
            require(uncertain == uncertain_replay, "uncertain replay changed")
            require(
                state.provider_effects == before + 1,
                "uncertain replay repeated provider effect",
            )

            crash_request = intent("crash-window")
            crash_preview, _, stderr = run_cli(
                crash_request, config_path=config_path, env=env
            )
            results.append(crash_preview)
            stderr_values.append(stderr)
            crash_dispatch = confirmed(crash_request, crash_preview)
            with sqlite3.connect(root / "journal.sqlite3") as connection:
                connection.execute(
                    """
                    UPDATE curated_acquisition
                    SET state='dispatching',
                        candidate_ref=?,
                        confirmation_id=?,
                        updated_at=datetime('now', '-120 seconds')
                    WHERE intent_id=? AND item_id=?
                    """,
                    (
                        crash_dispatch["items"][0]["selection"]["candidate_ref"],
                        crash_dispatch["items"][0]["confirmation"]["confirmation_id"],
                        crash_dispatch["intent_id"],
                        crash_dispatch["items"][0]["item_id"],
                    ),
                )
            before = state.provider_effects
            crash_result, _, stderr = run_cli(
                crash_dispatch, config_path=config_path, env=env
            )
            results.append(crash_result)
            stderr_values.append(stderr)
            require(
                error_code(crash_result) == "DISPATCH_OUTCOME_UNCERTAIN",
                "expired lease retried unsafely",
            )
            require(state.provider_effects == before, "expired lease reached provider")

            state.fail_search = True
            provider_error, _, stderr = run_cli(
                intent("provider-error"), config_path=config_path, env=env
            )
            results.append(provider_error)
            stderr_values.append(stderr)
            require(error_code(provider_error) == "PREVIEW_FAILED", "503 became empty")
            state.malformed_search = True
            malformed_error, _, stderr = run_cli(
                intent("malformed-provider"), config_path=config_path, env=env
            )
            results.append(malformed_error)
            stderr_values.append(stderr)
            require(
                error_code(malformed_error) == "PREVIEW_FAILED",
                "malformed provider response became empty",
            )

            state.many_candidates = True
            bounded, _, stderr = run_cli(
                intent("bounded"), config_path=config_path, env=env
            )
            results.append(bounded)
            stderr_values.append(stderr)
            bounded_bytes = len(
                json.dumps(bounded, separators=(",", ":"), ensure_ascii=True).encode()
            )
            require(bounded_bytes <= 2_097_152, "result exceeded byte bound")
            require(len(bounded["items"][0]["candidates"]) <= 100, "candidate bound failed")

            oversized = intent("oversized")
            oversized["unexpected"] = "audit-private-comment-secret" * 30_000
            oversized_result, _, stderr = run_cli(
                oversized, config_path=config_path, env=env
            )
            results.append(oversized_result)
            stderr_values.append(stderr)
            require(error_code(oversized_result) == "PAYLOAD_TOO_LARGE", "oversize passed")
            assert_private_absent(oversized_result, "oversized refusal")

            require(
                (ROOT / "schemas/curated-acquisition/v2/err-subject-owner.schema.json").read_bytes()
                == (ERR / "schemas/subject-envelope.schema.json").read_bytes(),
                "ERR owner subject schema drifted",
            )

            meta_positive = intent("metamusic-live")
            meta_refusal = intent("metamusic-refusal", action="dispatch")
            meta_refusal["caller"]["origin"]["kind"] = "source_ingestion"
            positive_path = root / "meta-positive.json"
            refusal_path = root / "meta-refusal.json"
            positive_path.write_text(json.dumps(meta_positive), encoding="utf-8")
            refusal_path.write_text(json.dumps(meta_refusal), encoding="utf-8")
            meta = meta_consumer_probe(
                config_path=config_path,
                env=env,
                positive_payload_path=positive_path,
                refusal_payload_path=refusal_path,
            )
            if not meta["typed_refusal_preserved"]:
                upstream_findings.append(
                    {
                        "owner": "MetaMusic",
                        "code": "METAMUSIC_IWANTIT_EXIT_1_REJECTED",
                        "impact": (
                            "IWantIt v2 interoperation succeeds for capabilities and "
                            "positive preview, but MetaMusic's process gateway converts "
                            "IWantIt's schema-valid exit-1 refusal into GATEWAY_ERROR."
                        ),
                        "fallback": (
                            "IWantIt remains fail-closed; MetaMusic should accept exit 1 "
                            "when stdout validates as iwantit.acquisition-result/2."
                        ),
                    }
                )
            artifact = artifact_contract_probe()

            for index, result in enumerate(results):
                assert_private_absent(result, f"CLI result {index}")
            for index, stderr in enumerate(stderr_values):
                assert_private_absent(stderr, f"CLI stderr {index}")
            scan_roots = [
                root / "journal.sqlite3",
                root / "journal.sqlite3-wal",
                root / "journal.sqlite3-shm",
                root / "state",
                root / "cache",
            ]
            scanned_files = 0
            for scan_root in scan_roots:
                paths = [scan_root] if scan_root.is_file() else (
                    list(scan_root.rglob("*")) if scan_root.exists() else []
                )
                for path in paths:
                    if not path.is_file():
                        continue
                    scanned_files += 1
                    content = path.read_bytes().decode("utf-8", errors="ignore")
                    assert_private_absent(content, f"persistent file {path.name}")

            receipt = {
                "schema": "iwantit.curated-acquisition-adversarial-audit/1",
                "audit_date": AUDIT_DATE,
                "status": "passed_with_upstream_findings" if upstream_findings else "passed",
                "commits": {
                    "iwantit": git_head(ROOT),
                    "metamusic": git_head(METAMUSIC),
                    "err": git_head(ERR),
                },
                "execution": {
                    "boundary": "real iwantit CLI subprocess plus disposable loopback HTTP",
                    "cli_results_checked": len(results),
                    "provider_searches": state.searches,
                    "provider_effects": state.provider_effects,
                    "provider_dispatch_requests": len(state.dispatch_requests),
                    "persistent_files_scanned": scanned_files,
                    "max_observed_result_bytes": max(
                        len(json.dumps(value, separators=(",", ":")).encode())
                        for value in results
                    ),
                },
                "coverage": {
                    "authority_qualified_exact_identity": "passed",
                    "preview_choice_refusal_cancel_confirmation": "passed",
                    "ingestion_and_recommendation_never_dispatch": "passed",
                    "idempotent_replay_and_provider_effect_exactly_once": "passed",
                    "partial_batch_duplicate_and_malformed_inputs": "passed",
                    "provider_errors_safe_retry_and_uncertain_crash_windows": "passed",
                    "bounded_payload_candidate_and_result_output": "passed",
                    "private_evidence_payload_result_journal_log_report_scan": "passed",
                    "err_subject_and_pending_artifact_verification_contract": "passed",
                    "metamusic_current_v2_positive_process_interop": "passed",
                },
                "metamusic_consumer": meta,
                "metamusic_err_artifact_contract": artifact,
                "upstream_findings": upstream_findings,
                "limitations": [
                    "No real private provider account or non-loopback network was used.",
                    (
                        "Artifact verification exercised MetaMusic's current disposable "
                        "file/ERR workflow; IWantIt correctly returns only a pending "
                        "verification requirement and never asserts ownership."
                    ),
                ],
                "probes": [
                    ".venv/bin/python scripts/audit_curated_acquisition.py --output <path>",
                    (
                        "MetaMusic current AcquisitionCapabilities/AcquisitionResult "
                        "models over live IWantIt process output"
                    ),
                    *artifact["tests"],
                    (
                        "byte comparison: IWantIt err-subject-owner.schema.json == "
                        "ERR subject-envelope.schema.json"
                    ),
                ],
            }
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return receipt
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT
        / "docs/evidence/curated-acquisition/2026-07-27-adversarial-audit.json",
    )
    args = parser.parse_args()
    receipt = run_audit(args.output)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "output": str(args.output),
                "cli_results_checked": receipt["execution"]["cli_results_checked"],
                "upstream_findings": len(receipt["upstream_findings"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
