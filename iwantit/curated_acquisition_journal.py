"""Durable preview/choice/confirmation journal for curated acquisition v2."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class CuratedJournalConflictError(ValueError):
    """A stable intent or item ID was reused for different coordinates."""


class CuratedAcquisitionJournal:
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
                CREATE TABLE IF NOT EXISTS curated_acquisition (
                    intent_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL,
                    preview_result_id TEXT,
                    preview_json TEXT,
                    candidate_ref TEXT,
                    confirmation_id TEXT,
                    result_json TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (intent_id, item_id)
                )
                """
            )
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
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
    def _decode(value: str | None) -> dict[str, Any] | None:
        return json.loads(value) if value else None

    @staticmethod
    def _assert_fingerprint(row: sqlite3.Row, fingerprint: str) -> None:
        if row["fingerprint"] != fingerprint:
            raise CuratedJournalConflictError(
                "intent_id/item_id was already used for different acquisition coordinates"
            )

    def load_preview(
        self,
        *,
        intent_id: str,
        item_id: str,
        fingerprint: str,
    ) -> tuple[str, dict[str, Any] | None]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM curated_acquisition WHERE intent_id=? AND item_id=?",
                (intent_id, item_id),
            ).fetchone()
        if row is None:
            return "missing", None
        self._assert_fingerprint(row, fingerprint)
        if row["state"] == "cancelled":
            return "cancelled", self._decode(row["result_json"])
        return str(row["state"]), self._decode(row["preview_json"])

    def save_preview(
        self,
        *,
        intent_id: str,
        item_id: str,
        fingerprint: str,
        preview_result_id: str,
        preview: dict[str, Any],
    ) -> dict[str, Any]:
        serialized = json.dumps(
            preview,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM curated_acquisition WHERE intent_id=? AND item_id=?",
                (intent_id, item_id),
            ).fetchone()
            if row is not None:
                self._assert_fingerprint(row, fingerprint)
                existing = self._decode(row["preview_json"])
                if existing is not None:
                    return existing
                if row["state"] == "cancelled":
                    cancelled = self._decode(row["result_json"])
                    return cancelled or preview
                connection.execute(
                    "UPDATE curated_acquisition SET state='previewed', "
                    "preview_result_id=?, preview_json=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE intent_id=? AND item_id=?",
                    (preview_result_id, serialized, intent_id, item_id),
                )
            else:
                connection.execute(
                    "INSERT INTO curated_acquisition("
                    "intent_id, item_id, fingerprint, state, preview_result_id, preview_json"
                    ") VALUES (?, ?, ?, 'previewed', ?, ?)",
                    (
                        intent_id,
                        item_id,
                        fingerprint,
                        preview_result_id,
                        serialized,
                    ),
                )
        return preview

    def begin_dispatch(
        self,
        *,
        intent_id: str,
        item_id: str,
        fingerprint: str,
        preview_result_id: str,
        candidate_ref: str,
        confirmation_id: str,
    ) -> tuple[str, dict[str, Any] | None]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT *, COALESCE(unixepoch('now') - unixepoch(updated_at), 0) AS age "
                "FROM curated_acquisition WHERE intent_id=? AND item_id=?",
                (intent_id, item_id),
            ).fetchone()
            if row is None:
                return "preview_required", None
            self._assert_fingerprint(row, fingerprint)
            if row["state"] == "completed":
                return "replay", self._decode(row["result_json"])
            if row["state"] == "cancelled":
                return "cancelled", self._decode(row["result_json"])
            if row["state"] == "uncertain":
                return "uncertain", self._decode(row["result_json"])
            if row["state"] == "dispatching":
                if int(row["age"]) < self.lease_seconds:
                    return "in_progress", None
                connection.execute(
                    "UPDATE curated_acquisition SET state='uncertain', "
                    "updated_at=CURRENT_TIMESTAMP WHERE intent_id=? AND item_id=?",
                    (intent_id, item_id),
                )
                return "uncertain", None
            if row["preview_result_id"] != preview_result_id:
                return "preview_mismatch", None
            preview = self._decode(row["preview_json"]) or {}
            candidate_refs = {
                candidate.get("candidate_ref")
                for candidate in preview.get("candidates", [])
                if isinstance(candidate, dict)
            }
            if candidate_ref not in candidate_refs:
                return "candidate_mismatch", None
            if row["candidate_ref"] and row["candidate_ref"] != candidate_ref:
                raise CuratedJournalConflictError(
                    "item was already confirmed for a different candidate"
                )
            if row["confirmation_id"] and row["confirmation_id"] != confirmation_id:
                raise CuratedJournalConflictError(
                    "item was already confirmed with a different confirmation"
                )
            connection.execute(
                "UPDATE curated_acquisition SET state='dispatching', candidate_ref=?, "
                "confirmation_id=?, result_json=NULL, updated_at=CURRENT_TIMESTAMP "
                "WHERE intent_id=? AND item_id=?",
                (candidate_ref, confirmation_id, intent_id, item_id),
            )
        return "claimed", preview

    def finish_dispatch(
        self,
        *,
        intent_id: str,
        item_id: str,
        result: dict[str, Any],
    ) -> None:
        error = result.get("error") if isinstance(result.get("error"), dict) else {}
        if result.get("status") == "dispatched":
            state = "completed"
        elif error.get("code") == "DISPATCH_OUTCOME_UNCERTAIN":
            state = "uncertain"
        else:
            state = "failed"
        serialized = json.dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        with self._connection() as connection:
            connection.execute(
                "UPDATE curated_acquisition SET state=?, result_json=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE intent_id=? AND item_id=?",
                (state, serialized, intent_id, item_id),
            )

    def cancellation_state(
        self,
        *,
        intent_id: str,
        item_id: str,
        fingerprint: str,
    ) -> tuple[str, dict[str, Any] | None]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT *, COALESCE(unixepoch('now') - unixepoch(updated_at), 0) AS age "
                "FROM curated_acquisition WHERE intent_id=? AND item_id=?",
                (intent_id, item_id),
            ).fetchone()
            if row is None:
                return "preview_required", None
            self._assert_fingerprint(row, fingerprint)
            if row["state"] == "cancelled":
                return "replay", self._decode(row["result_json"])
            if row["state"] == "completed":
                return "completed", self._decode(row["result_json"])
            if row["state"] == "uncertain":
                return "uncertain", self._decode(row["result_json"])
            if row["state"] == "dispatching":
                if int(row["age"]) < self.lease_seconds:
                    return "dispatching", None
                connection.execute(
                    "UPDATE curated_acquisition SET state='uncertain', "
                    "updated_at=CURRENT_TIMESTAMP WHERE intent_id=? AND item_id=?",
                    (intent_id, item_id),
                )
                return "uncertain", None
            return "cancellable", None

    def finish_cancellation(
        self,
        *,
        intent_id: str,
        item_id: str,
        result: dict[str, Any],
    ) -> None:
        serialized = json.dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        with self._connection() as connection:
            connection.execute(
                "UPDATE curated_acquisition SET state='cancelled', result_json=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE intent_id=? AND item_id=?",
                (serialized, intent_id, item_id),
            )
