"""Cross-process idempotency journal for confirmed acquisition intents."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class IdempotencyConflictError(ValueError):
    """An intent id was reused for a materially different request."""


class AcquisitionJournal:
    def __init__(self, path: Path, *, lease_seconds: int = 900) -> None:
        self.path = path.expanduser()
        self.lease_seconds = max(60, lease_seconds)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS acquisition_dispatch (
                    intent_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL,
                    result_json TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @contextmanager
    def _connection(self):  # noqa: ANN202
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def fingerprint(intent: dict[str, Any]) -> str:
        material = {
            "recording": intent.get("recording"),
            "desired": intent.get("desired"),
            "policy": intent.get("policy"),
            "selection": (intent.get("confirmation") or {}).get("selected_candidate_index"),
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode()).hexdigest()

    def begin(self, intent: dict[str, Any]) -> dict[str, Any] | None:
        intent_id = str(intent["intent_id"])
        fingerprint = self.fingerprint(intent)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT fingerprint, state, result_json, "
                "COALESCE(unixepoch('now') - unixepoch(updated_at), 0) "
                "FROM acquisition_dispatch WHERE intent_id = ?",
                (intent_id,),
            ).fetchone()
            if row:
                if row[0] != fingerprint:
                    raise IdempotencyConflictError(
                        "intent_id was already used for a different acquisition request"
                    )
                if row[1] == "completed" and row[2]:
                    return json.loads(row[2])
                if row[1] == "in_progress" and int(row[3]) < self.lease_seconds:
                    return {
                        "schema": "iwantit.acquisition-result/1",
                        "intent_id": intent_id,
                        "recording_ref": intent["recording"]["ref"],
                        "status": "already_in_progress",
                        "side_effects_allowed": False,
                        "candidates": [],
                        "selected": None,
                        "decision": {
                            "status": "already_in_progress",
                            "selected_candidate_index": None,
                            "option_count": 0,
                            "confidence": None,
                            "confidence_breakdown": {},
                        },
                        "dispatch": {},
                        "provenance": {"run_id": None, "canonical": {"fields": {}}, "search": {}},
                        "privacy": {
                            "classification": "local_private",
                            "persistence": "sanitized_local",
                            "community_publish_allowed": False,
                            "remote_inference_allowed": False,
                            "provider_payloads_exportable": False,
                            "private_providers": [],
                            "reason": "Matching confirmed dispatch is already in progress.",
                        },
                        "error": None,
                    }
                # Failed entries and abandoned leases are safe to claim again. The
                # default lease exceeds every connector's bounded request budget.
                connection.execute(
                    "UPDATE acquisition_dispatch SET state = 'in_progress', result_json = NULL, "
                    "updated_at = CURRENT_TIMESTAMP WHERE intent_id = ?",
                    (intent_id,),
                )
                return None
            connection.execute(
                "INSERT INTO acquisition_dispatch(intent_id, fingerprint, state) VALUES (?, ?, 'in_progress')",
                (intent_id, fingerprint),
            )
        return None

    def finish(self, intent_id: str, result: dict[str, Any]) -> None:
        state = "failed" if result.get("status") == "error" else "completed"
        serialized = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        with self._connection() as connection:
            connection.execute(
                "UPDATE acquisition_dispatch SET state = ?, result_json = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE intent_id = ?",
                (state, serialized, intent_id),
            )

    def fail(self, intent_id: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE acquisition_dispatch SET state = 'failed', result_json = NULL, "
                "updated_at = CURRENT_TIMESTAMP WHERE intent_id = ?",
                (intent_id,),
            )
