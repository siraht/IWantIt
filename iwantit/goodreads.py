"""Durable Goodreads shelf ingestion and book acquisition orchestration."""

from __future__ import annotations

import csv
import hashlib
import sqlite3
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from xml.etree import ElementTree

import requests

from .paths import state_dir
from .pipeline import run_workflow
from .catalogs import BookIdentity, CatalogError, LibraryCatalogService


GOODREADS_SOURCE = "goodreads"
SUPPORTED_FORMATS = ("ebook", "audiobook")
DEFAULT_GOODREADS_SETTINGS: dict[str, Any] = {
    "shelf_url": None,
    "shelf": "to-read",
    "formats": ["ebook", "audiobook"],
    "batch_limit": 10,
    "timeout": 20,
    "lease_seconds": 1800,
    "retry_base_seconds": 21600,
    "retry_max_seconds": 604800,
    "state_path": None,
}


class GoodreadsError(ValueError):
    """The supplied Goodreads source could not be consumed safely."""


@dataclass(frozen=True)
class ShelfBook:
    item_id: str
    title: str
    author: str
    isbn: str = ""
    isbn13: str = ""
    date_added: str = ""
    source_url: str = ""


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _book_fallback_id(title: str, author: str, isbn13: str, isbn: str) -> str:
    material = "|".join((isbn13, isbn, author.casefold(), title.casefold()))
    return "fallback:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _is_to_read(row: dict[str, str], shelf: str) -> bool:
    shelf = shelf.casefold()
    exclusive = _clean(row.get("Exclusive Shelf")).casefold()
    shelves = {
        token.strip().casefold()
        for token in _clean(row.get("Bookshelves")).split(",")
        if token.strip()
    }
    return exclusive == shelf or shelf in shelves


def parse_goodreads_csv(path: Path, *, shelf: str = "to-read") -> list[ShelfBook]:
    """Parse a Goodreads library export, retaining only the requested shelf."""

    path = path.expanduser()
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise GoodreadsError(f"could not read Goodreads CSV: {exc}") from exc
    with handle:
        reader = csv.DictReader(handle)
        required = {"Book Id", "Title", "Author", "Exclusive Shelf"}
        missing = sorted(required.difference(reader.fieldnames or []))
        if missing:
            raise GoodreadsError(
                "Goodreads CSV is missing required columns: " + ", ".join(missing)
            )
        books: list[ShelfBook] = []
        for row in reader:
            if not _is_to_read(row, shelf):
                continue
            title = _clean(row.get("Title"))
            author = _clean(row.get("Author"))
            isbn = _clean(row.get("ISBN")).strip('="')
            isbn13 = _clean(row.get("ISBN13")).strip('="')
            if not title or not author:
                continue
            item_id = _clean(row.get("Book Id")) or _book_fallback_id(
                title, author, isbn13, isbn
            )
            books.append(
                ShelfBook(
                    item_id=item_id,
                    title=title,
                    author=author,
                    isbn=isbn,
                    isbn13=isbn13,
                    date_added=_clean(row.get("Date Added")),
                    source_url=f"https://www.goodreads.com/book/show/{item_id}",
                )
            )
    return books


def goodreads_feed_url(shelf_url: str, *, shelf: str = "to-read") -> str:
    """Convert a Goodreads shelf HTML URL into its public RSS endpoint."""

    parsed = urlparse(shelf_url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.casefold() not in {
        "goodreads.com",
        "www.goodreads.com",
    }:
        raise GoodreadsError("Goodreads shelf URL must use https://www.goodreads.com")
    path = parsed.path.rstrip("/")
    if "/review/list_rss/" in path:
        feed_path = path
    elif "/review/list/" in path:
        feed_path = path.replace("/review/list/", "/review/list_rss/", 1)
    else:
        raise GoodreadsError("Goodreads URL must point to /review/list/<user>")
    params = parse_qs(parsed.query)
    selected_shelf = _clean(params.get("shelf", [shelf])[0]) or shelf
    query = urlencode(
        {
            "page": "1",
            "per_page": "100",
            "shelf": selected_shelf,
            "sort": "date",
        }
    )
    return urlunparse(("https", "www.goodreads.com", feed_path, "", query, ""))


def _children_by_local_name(element: ElementTree.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for child in element:
        name = child.tag.rsplit("}", 1)[-1]
        result[name] = _clean(child.text)
    return result


def parse_goodreads_rss(content: bytes | str) -> list[ShelfBook]:
    """Parse Goodreads' public shelf RSS representation."""

    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise GoodreadsError(f"Goodreads RSS returned invalid XML: {exc}") from exc
    books: list[ShelfBook] = []
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1] != "item":
            continue
        values = _children_by_local_name(item)
        title = values.get("book_title") or values.get("title") or ""
        author = values.get("author_name") or values.get("book_author") or ""
        isbn = values.get("isbn", "")
        isbn13 = values.get("isbn13", "")
        if not title or not author:
            continue
        item_id = values.get("book_id", "")
        link = values.get("link", "") or values.get("guid", "")
        if not item_id and link:
            marker = "/book/show/"
            if marker in link:
                item_id = link.split(marker, 1)[1].split("-", 1)[0].split("?", 1)[0]
        item_id = item_id or _book_fallback_id(title, author, isbn13, isbn)
        books.append(
            ShelfBook(
                item_id=item_id,
                title=title,
                author=author,
                isbn=isbn,
                isbn13=isbn13,
                date_added=values.get("user_date_added", ""),
                source_url=link or f"https://www.goodreads.com/book/show/{item_id}",
            )
        )
    if not books and root.tag.rsplit("}", 1)[-1].casefold() not in {"rss", "feed"}:
        raise GoodreadsError("Goodreads response was not an RSS feed")
    return books


def _utc_sql(value: datetime | None = None) -> str:
    value = value or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class ShelfJournal:
    """SQLite-backed state for shelf discovery and independent format legs."""

    def __init__(self, path: Path, *, lease_seconds: int = 1800) -> None:
        self.path = path.expanduser()
        self.lease_seconds = max(60, int(lease_seconds))
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            self.path.parent.chmod(0o700)
        except OSError:
            pass
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS shelf_item (
                    source TEXT NOT NULL,
                    shelf TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    author TEXT NOT NULL,
                    isbn TEXT NOT NULL DEFAULT '',
                    isbn13 TEXT NOT NULL DEFAULT '',
                    date_added TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (source, shelf, item_id)
                );
                CREATE TABLE IF NOT EXISTS shelf_leg (
                    source TEXT NOT NULL,
                    shelf TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    format TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT,
                    last_attempt_at TEXT,
                    run_id TEXT,
                    release_id TEXT,
                    last_error TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (source, shelf, item_id, format),
                    FOREIGN KEY (source, shelf, item_id)
                        REFERENCES shelf_item(source, shelf, item_id)
                );
                CREATE TABLE IF NOT EXISTS shelf_feed (
                    feed_url TEXT PRIMARY KEY,
                    etag TEXT,
                    last_modified TEXT,
                    last_sync_at TEXT,
                    last_status INTEGER
                );
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(shelf_leg)")
            }
            if "release_id" not in columns:
                connection.execute("ALTER TABLE shelf_leg ADD COLUMN release_id TEXT")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _connection(self):  # noqa: ANN202
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def feed_headers(self, feed_url: str) -> dict[str, str]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT etag, last_modified FROM shelf_feed WHERE feed_url = ?", (feed_url,)
            ).fetchone()
        headers: dict[str, str] = {}
        if row and row["etag"]:
            headers["If-None-Match"] = row["etag"]
        if row and row["last_modified"]:
            headers["If-Modified-Since"] = row["last_modified"]
        return headers

    def record_feed(
        self,
        feed_url: str,
        *,
        status: int,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO shelf_feed(feed_url, etag, last_modified, last_sync_at, last_status)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
                ON CONFLICT(feed_url) DO UPDATE SET
                    etag = COALESCE(excluded.etag, shelf_feed.etag),
                    last_modified = COALESCE(excluded.last_modified, shelf_feed.last_modified),
                    last_sync_at = CURRENT_TIMESTAMP,
                    last_status = excluded.last_status
                """,
                (feed_url, etag, last_modified, status),
            )

    def ingest(
        self,
        books: Iterable[ShelfBook],
        *,
        shelf: str,
        formats: Iterable[str],
        queue_new: bool,
        backfill: bool = False,
        full_snapshot: bool = False,
    ) -> dict[str, int]:
        formats = tuple(dict.fromkeys(formats))
        invalid = sorted(set(formats).difference(SUPPORTED_FORMATS))
        if invalid:
            raise GoodreadsError("unsupported book formats: " + ", ".join(invalid))
        books = list(books)
        stats = {"seen": len(books), "new": 0, "queued": 0, "baseline": 0}
        seen_ids = {book.item_id for book in books}
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for book in books:
                exists = connection.execute(
                    "SELECT 1 FROM shelf_item WHERE source = ? AND shelf = ? AND item_id = ?",
                    (GOODREADS_SOURCE, shelf, book.item_id),
                ).fetchone()
                if not exists:
                    stats["new"] += 1
                connection.execute(
                    """
                    INSERT INTO shelf_item(
                        source, shelf, item_id, title, author, isbn, isbn13,
                        date_added, source_url, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(source, shelf, item_id) DO UPDATE SET
                        title = excluded.title,
                        author = excluded.author,
                        isbn = excluded.isbn,
                        isbn13 = excluded.isbn13,
                        date_added = excluded.date_added,
                        source_url = excluded.source_url,
                        active = 1,
                        last_seen_at = CURRENT_TIMESTAMP
                    """,
                    (
                        GOODREADS_SOURCE,
                        shelf,
                        book.item_id,
                        book.title,
                        book.author,
                        book.isbn,
                        book.isbn13,
                        book.date_added,
                        book.source_url,
                    ),
                )
                for book_format in formats:
                    initial = "pending" if (queue_new and not exists) or backfill else "baseline"
                    inserted = connection.execute(
                        """
                        INSERT OR IGNORE INTO shelf_leg(
                            source, shelf, item_id, format, status, next_attempt_at
                        ) VALUES (?, ?, ?, ?, ?, CASE WHEN ? = 'pending' THEN CURRENT_TIMESTAMP END)
                        """,
                        (
                            GOODREADS_SOURCE,
                            shelf,
                            book.item_id,
                            book_format,
                            initial,
                            initial,
                        ),
                    ).rowcount
                    if inserted:
                        stats["queued" if initial == "pending" else "baseline"] += 1
                    elif backfill:
                        changed = connection.execute(
                            """
                            UPDATE shelf_leg SET status = 'pending', next_attempt_at = CURRENT_TIMESTAMP,
                                last_error = NULL, updated_at = CURRENT_TIMESTAMP
                            WHERE source = ? AND shelf = ? AND item_id = ? AND format = ?
                              AND status = 'baseline'
                            """,
                            (GOODREADS_SOURCE, shelf, book.item_id, book_format),
                        ).rowcount
                        stats["queued"] += changed
            if full_snapshot:
                if seen_ids:
                    placeholders = ",".join("?" for _ in seen_ids)
                    connection.execute(
                        f"""
                        UPDATE shelf_item SET active = 0
                        WHERE source = ? AND shelf = ? AND item_id NOT IN ({placeholders})
                        """,
                        (GOODREADS_SOURCE, shelf, *sorted(seen_ids)),
                    )
                else:
                    connection.execute(
                        "UPDATE shelf_item SET active = 0 WHERE source = ? AND shelf = ?",
                        (GOODREADS_SOURCE, shelf),
                    )
        return stats

    def claim_due(self, *, shelf: str, limit: int) -> list[dict[str, Any]]:
        cutoff = _utc_sql(datetime.now(timezone.utc) - timedelta(seconds=self.lease_seconds))
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # Prowlarr's grab endpoint has no idempotency key. A process may have
            # exited after the provider accepted a grab but before local commit,
            # so stale leases must never be dispatched automatically.
            connection.execute(
                """
                UPDATE shelf_leg SET status = 'uncertain', next_attempt_at = NULL,
                    last_error = 'previous process exited during acquisition; verify the download client before retrying',
                    updated_at = CURRENT_TIMESTAMP
                WHERE source = ? AND shelf = ? AND status = 'in_progress'
                  AND datetime(last_attempt_at) <= datetime(?)
                """,
                (GOODREADS_SOURCE, shelf, cutoff),
            )
            rows = connection.execute(
                """
                SELECT i.item_id, i.title, i.author, i.isbn, i.isbn13, i.source_url,
                       l.format, l.status, l.attempt_count
                FROM shelf_leg l
                JOIN shelf_item i USING(source, shelf, item_id)
                WHERE l.source = ? AND l.shelf = ? AND i.active = 1
                  AND l.status IN ('pending', 'not_found', 'error')
                  AND (l.next_attempt_at IS NULL OR datetime(l.next_attempt_at) <= CURRENT_TIMESTAMP)
                ORDER BY CASE WHEN i.date_added = '' THEN 1 ELSE 0 END,
                         i.date_added DESC, i.item_id ASC, l.format ASC
                LIMIT ?
                """,
                (GOODREADS_SOURCE, shelf, max(0, int(limit))),
            ).fetchall()
            claimed: list[dict[str, Any]] = []
            for row in rows:
                connection.execute(
                    """
                    UPDATE shelf_leg SET status = 'in_progress', attempt_count = attempt_count + 1,
                        last_attempt_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE source = ? AND shelf = ? AND item_id = ? AND format = ?
                    """,
                    (GOODREADS_SOURCE, shelf, row["item_id"], row["format"]),
                )
                claimed.append(dict(row))
        return claimed

    def claim_choice(
        self, *, shelf: str, item_id: str, book_format: str
    ) -> dict[str, Any] | None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT i.item_id, i.title, i.author, i.isbn, i.isbn13, i.source_url,
                       l.format, l.status, l.attempt_count
                FROM shelf_leg l JOIN shelf_item i USING(source, shelf, item_id)
                WHERE l.source = ? AND l.shelf = ? AND l.item_id = ? AND l.format = ?
                  AND i.active = 1 AND l.status = 'needs_choice'
                """,
                (GOODREADS_SOURCE, shelf, item_id, book_format),
            ).fetchone()
            if not row:
                return None
            connection.execute(
                """
                UPDATE shelf_leg SET status = 'in_progress', attempt_count = attempt_count + 1,
                    last_attempt_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE source = ? AND shelf = ? AND item_id = ? AND format = ?
                """,
                (GOODREADS_SOURCE, shelf, item_id, book_format),
            )
            return dict(row)

    def inventory_books(self, *, shelf: str, book_format: str) -> list[ShelfBook]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT i.item_id, i.title, i.author, i.isbn, i.isbn13,
                       i.date_added, i.source_url
                FROM shelf_item i JOIN shelf_leg l USING(source, shelf, item_id)
                WHERE i.source = ? AND i.shelf = ? AND i.active = 1 AND l.format = ?
                  AND l.status NOT IN ('owned', 'in_progress', 'uncertain')
                """,
                (GOODREADS_SOURCE, shelf, book_format),
            ).fetchall()
        return [ShelfBook(**dict(row)) for row in rows]

    def mark_owned(
        self, *, shelf: str, book_format: str, item_ids: Iterable[str]
    ) -> int:
        item_ids = tuple(dict.fromkeys(item_ids))
        if not item_ids:
            return 0
        placeholders = ",".join("?" for _ in item_ids)
        with self._connection() as connection:
            return connection.execute(
                f"""
                UPDATE shelf_leg SET status = 'owned', next_attempt_at = NULL,
                    last_error = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE source = ? AND shelf = ? AND format = ?
                  AND item_id IN ({placeholders})
                  AND status NOT IN ('in_progress', 'uncertain')
                """,
                (GOODREADS_SOURCE, shelf, book_format, *item_ids),
            ).rowcount

    def set_outcome(
        self,
        *,
        shelf: str,
        item_id: str,
        book_format: str,
        status: str,
        run_id: str | None = None,
        release_id: str | None = None,
        error: str | None = None,
        retry_at: datetime | None = None,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE shelf_leg SET status = ?, run_id = ?,
                    release_id = COALESCE(?, release_id), last_error = ?,
                    next_attempt_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE source = ? AND shelf = ? AND item_id = ? AND format = ?
                """,
                (
                    status,
                    run_id,
                    release_id,
                    _clean(error)[:500] or None,
                    _utc_sql(retry_at) if retry_at else None,
                    GOODREADS_SOURCE,
                    shelf,
                    item_id,
                    book_format,
                ),
            )

    def claimed_release_ids(self, *, shelf: str) -> set[str]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT release_id FROM shelf_leg
                WHERE source = ? AND shelf = ? AND release_id IS NOT NULL
                  AND status IN ('complete', 'dispatched', 'owned')
                """,
                (GOODREADS_SOURCE, shelf),
            ).fetchall()
        return {str(row[0]) for row in rows if row[0]}

    def reset_preview(self, *, shelf: str, item_id: str, book_format: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE shelf_leg SET status = 'pending', attempt_count = MAX(0, attempt_count - 1),
                    next_attempt_at = CURRENT_TIMESTAMP, last_attempt_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE source = ? AND shelf = ? AND item_id = ? AND format = ?
                """,
                (GOODREADS_SOURCE, shelf, item_id, book_format),
            )

    def retry(
        self,
        *,
        shelf: str,
        include_choices: bool = False,
        include_uncertain: bool = False,
        include_quarantined: bool = False,
    ) -> int:
        statuses = ["not_found", "error"]
        if include_choices:
            statuses.append("needs_choice")
        if include_uncertain:
            statuses.append("uncertain")
        if include_quarantined:
            statuses.append("quarantined")
        placeholders = ",".join("?" for _ in statuses)
        with self._connection() as connection:
            return connection.execute(
                f"""
                UPDATE shelf_leg SET status = 'pending', next_attempt_at = CURRENT_TIMESTAMP,
                    last_error = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE source = ? AND shelf = ? AND status IN ({placeholders})
                """,
                (GOODREADS_SOURCE, shelf, *statuses),
            ).rowcount

    def status(self, *, shelf: str, review_limit: int = 25) -> dict[str, Any]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT l.status, l.format, COUNT(*) AS count
                FROM shelf_leg l JOIN shelf_item i USING(source, shelf, item_id)
                WHERE l.source = ? AND l.shelf = ? AND i.active = 1
                GROUP BY l.status, l.format ORDER BY l.status, l.format
                """,
                (GOODREADS_SOURCE, shelf),
            ).fetchall()
            items = connection.execute(
                """
                SELECT COUNT(*) FROM shelf_item WHERE source = ? AND shelf = ? AND active = 1
                """,
                (GOODREADS_SOURCE, shelf),
            ).fetchone()[0]
            review = connection.execute(
                """
                SELECT i.item_id, i.title, i.author, l.format, l.status, l.last_error
                FROM shelf_leg l JOIN shelf_item i USING(source, shelf, item_id)
                WHERE l.source = ? AND l.shelf = ? AND i.active = 1
                  AND l.status IN ('needs_choice', 'error', 'uncertain', 'quarantined')
                ORDER BY l.updated_at DESC LIMIT ?
                """,
                (GOODREADS_SOURCE, shelf, max(0, int(review_limit))),
            ).fetchall()
        counts: dict[str, dict[str, int]] = {}
        for row in rows:
            counts.setdefault(row["status"], {})[row["format"]] = row["count"]
        return {
            "source": GOODREADS_SOURCE,
            "shelf": shelf,
            "items": items,
            "counts": counts,
            "review": [dict(row) for row in review],
        }


PipelineRunner = Callable[[dict[str, Any], str, bool, bool, int | None], dict[str, Any]]


class GoodreadsShelfService:
    def __init__(
        self,
        config: dict[str, Any],
        builtins: dict[str, Any],
        *,
        journal: ShelfJournal | None = None,
        runner: PipelineRunner | None = None,
    ) -> None:
        self.config = config
        self.builtins = builtins
        section = self.section
        path = section.get("state_path") or state_dir() / "goodreads-shelf.sqlite3"
        self.journal = journal or ShelfJournal(
            Path(path), lease_seconds=int(section.get("lease_seconds", 1800))
        )
        self.runner = runner or self._pipeline_runner
        self.catalogs = LibraryCatalogService.from_config(config)

    @property
    def section(self) -> dict[str, Any]:
        return {**DEFAULT_GOODREADS_SETTINGS, **(self.config.get("goodreads", {}) or {})}

    def _pipeline_runner(
        self,
        item: dict[str, Any],
        book_format: str,
        dry_run: bool,
        confirm: bool,
        choice: int | None,
    ) -> dict[str, Any]:
        query = " ".join(part for part in (item.get("author"), item.get("title")) if part)
        data = {
            "request": {
                "input": query,
                "input_type": "text",
                "query": query,
                "media_type": "book",
                "preferences": {"book_format": book_format},
                "source": {"provider": GOODREADS_SOURCE, "item_id": item.get("item_id")},
            },
            "work": {
                "media_type": "book",
                "title": item.get("title"),
                "author": item.get("author"),
                "isbn": item.get("isbn"),
                "isbn13": item.get("isbn13"),
            },
            "_internal": {
                "blocked_release_ids": sorted(
                    self.journal.claimed_release_ids(
                        shelf=self.section.get("shelf") or "to-read"
                    )
                )
            },
        }
        return run_workflow(
            self.config,
            data,
            self.builtins,
            workflow_name="book",
            start_step="filter_owned",
            choice_index=choice,
            dry_run=dry_run,
            confirm=confirm,
        )

    def _retry_at(self, attempts: int) -> datetime:
        base = max(60, int(self.section.get("retry_base_seconds", 21600)))
        maximum = max(base, int(self.section.get("retry_max_seconds", 604800)))
        delay = min(maximum, base * (2 ** max(0, attempts - 1)))
        return datetime.now(timezone.utc) + timedelta(seconds=delay)

    def reconcile_inventory(
        self, *, shelf: str, formats: Iterable[str]
    ) -> dict[str, Any]:
        if not self.catalogs.adapters:
            return {"enabled": False, "owned": {}, "errors": {}}
        owned_counts: dict[str, int] = {}
        errors: dict[str, str] = {}
        for book_format in formats:
            books = self.journal.inventory_books(shelf=shelf, book_format=book_format)
            try:
                owned = {
                    book.item_id
                    for book in books
                    if self.catalogs.match(
                        BookIdentity(
                            book.title,
                            (book.author,),
                            {"isbn": book.isbn, "isbn13": book.isbn13},
                        ),
                        book_format,
                    ).owned
                }
            except (CatalogError, OSError, subprocess.SubprocessError) as exc:
                errors[book_format] = str(exc)
                continue
            owned_counts[book_format] = self.journal.mark_owned(
                shelf=shelf, book_format=book_format, item_ids=owned
            )
        if errors:
            details = "; ".join(f"{key}: {value}" for key, value in sorted(errors.items()))
            raise CatalogError(
                "required library inventory failed; acquisition is blocked: " + details
            )
        return {"enabled": True, "owned": owned_counts, "errors": errors}

    def fetch_rss(self, shelf_url: str, *, shelf: str) -> tuple[list[ShelfBook], bool]:
        feed_url = goodreads_feed_url(shelf_url, shelf=shelf)
        headers = {
            "User-Agent": "IWantIt/0.1 Goodreads shelf sync",
            "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8",
            **self.journal.feed_headers(feed_url),
        }
        response = requests.get(
            feed_url,
            headers=headers,
            timeout=float(self.section.get("timeout", 20)),
        )
        if response.status_code == 304:
            self.journal.record_feed(feed_url, status=304)
            return [], False
        response.raise_for_status()
        books = parse_goodreads_rss(response.content)
        self.journal.record_feed(
            feed_url,
            status=response.status_code,
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
        )
        return books, True

    def process_due(
        self, *, shelf: str, limit: int, dry_run: bool, confirm: bool
    ) -> dict[str, int]:
        stats = {
            "attempted": 0,
            "downloaded": 0,
            "not_found": 0,
            "owned": 0,
            "needs_choice": 0,
            "error": 0,
            "previewed": 0,
        }
        if not dry_run and not confirm:
            return stats
        for item in self.journal.claim_due(shelf=shelf, limit=limit):
            stats["attempted"] += 1
            try:
                result = self.runner(item, item["format"], dry_run, confirm, None)
            except Exception as exc:  # The journal must survive any provider failure.
                stats["error"] += 1
                self.journal.set_outcome(
                    shelf=shelf,
                    item_id=item["item_id"],
                    book_format=item["format"],
                    status="error",
                    error=f"{exc.__class__.__name__}: {exc}",
                    retry_at=self._retry_at(int(item["attempt_count"]) + 1),
                )
                continue
            outcome = self._record_result(item, result, shelf=shelf, dry_run=dry_run)
            stats[outcome] += 1
        return stats

    def _record_result(
        self,
        item: dict[str, Any],
        result: dict[str, Any],
        *,
        shelf: str,
        dry_run: bool,
    ) -> str:
        book_format = item["format"]
        run_id = _clean(result.get("run_id")) or None
        error = result.get("error")
        decision = result.get("decision") or {}
        dispatch = (result.get("dispatch") or {}).get("prowlarr") or {}
        candidates = (result.get("work") or {}).get("candidates") or []
        selected = (result.get("work") or {}).get("selected") or {}
        raw_selected = (
            selected.get("_raw") if isinstance(selected.get("_raw"), dict) else {}
        )
        release_id = _clean(
            selected.get("guid")
            or raw_selected.get("guid")
            or selected.get("download_url")
        ) or None
        if dry_run:
            outcome = "error" if error or decision.get("status") == "error" else "previewed"
            self.journal.reset_preview(
                shelf=shelf, item_id=item["item_id"], book_format=book_format
            )
            return outcome
        if error or decision.get("status") == "error":
            message = (error or {}).get("message") if isinstance(error, dict) else str(error)
            self.journal.set_outcome(
                shelf=shelf,
                item_id=item["item_id"],
                book_format=book_format,
                status="error",
                run_id=run_id,
                error=message or "pipeline error",
                retry_at=self._retry_at(int(item["attempt_count"]) + 1),
            )
            return "error"
        if dispatch.get("status") == "ok":
            self.journal.set_outcome(
                shelf=shelf,
                item_id=item["item_id"],
                book_format=book_format,
                status="dispatched",
                run_id=run_id,
                release_id=release_id,
            )
            return "downloaded"
        if decision.get("status") == "owned":
            self.journal.set_outcome(
                shelf=shelf,
                item_id=item["item_id"],
                book_format=book_format,
                status="owned",
                run_id=run_id,
            )
            return "owned"
        if decision.get("status") == "needs_choice" and candidates:
            self.journal.set_outcome(
                shelf=shelf,
                item_id=item["item_id"],
                book_format=book_format,
                status="needs_choice",
                run_id=run_id,
                error="multiple or low-confidence candidates require review",
            )
            return "needs_choice"
        duplicate = decision.get("status") == "duplicate_release"
        self.journal.set_outcome(
            shelf=shelf,
            item_id=item["item_id"],
            book_format=book_format,
            status="not_found",
            run_id=run_id,
            error=(
                "release already dispatched for another format leg"
                if duplicate
                else "no matching release found"
            ),
            retry_at=self._retry_at(int(item["attempt_count"]) + 1),
        )
        return "not_found"

    def resolve_choice(
        self,
        *,
        shelf: str,
        item_id: str,
        book_format: str,
        choice: int,
        confirm: bool,
    ) -> dict[str, Any]:
        if not confirm:
            raise GoodreadsError("resolving a shelf choice requires --confirm")
        item = self.journal.claim_choice(
            shelf=shelf, item_id=item_id, book_format=book_format
        )
        if not item:
            raise GoodreadsError("shelf item/format is not awaiting a choice")
        try:
            result = self.runner(item, book_format, False, True, choice)
        except Exception as exc:
            self.journal.set_outcome(
                shelf=shelf,
                item_id=item_id,
                book_format=book_format,
                status="error",
                error=f"{exc.__class__.__name__}: {exc}",
                retry_at=self._retry_at(int(item["attempt_count"]) + 1),
            )
            raise
        outcome = self._record_result(item, result, shelf=shelf, dry_run=False)
        return {
            "schema": "iwantit.shelf-resolve-result/1",
            "source": GOODREADS_SOURCE,
            "shelf": shelf,
            "item_id": item_id,
            "format": book_format,
            "choice": choice,
            "outcome": outcome,
            "state": self.journal.status(shelf=shelf),
        }

    def sync(
        self,
        *,
        shelf_url: str | None = None,
        csv_path: Path | None = None,
        shelf: str = "to-read",
        formats: Iterable[str] = SUPPORTED_FORMATS,
        backfill: bool = False,
        limit: int | None = None,
        dry_run: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        formats = tuple(formats)
        ingestion: dict[str, dict[str, int]] = {}
        if csv_path:
            csv_books = parse_goodreads_csv(csv_path, shelf=shelf)
            ingestion["csv"] = self.journal.ingest(
                csv_books,
                shelf=shelf,
                formats=formats,
                queue_new=False,
                backfill=backfill,
                full_snapshot=True,
            )
        feed_changed = None
        if shelf_url:
            rss_books, feed_changed = self.fetch_rss(shelf_url, shelf=shelf)
            if feed_changed:
                ingestion["rss"] = self.journal.ingest(
                    rss_books,
                    shelf=shelf,
                    formats=formats,
                    queue_new=True,
                )
        if not csv_path and not shelf_url:
            raise GoodreadsError("configure goodreads.shelf_url or pass --url/--csv")
        inventory = self.reconcile_inventory(shelf=shelf, formats=formats)
        batch_limit = int(limit if limit is not None else self.section.get("batch_limit", 10))
        processed = self.process_due(
            shelf=shelf,
            limit=max(0, batch_limit),
            dry_run=dry_run,
            confirm=confirm,
        )
        return {
            "schema": "iwantit.shelf-sync-result/1",
            "source": GOODREADS_SOURCE,
            "shelf": shelf,
            "feed_changed": feed_changed,
            "ingestion": ingestion,
            "inventory": inventory,
            "processing": processed,
            "state": self.journal.status(shelf=shelf),
            "side_effects_allowed": bool(confirm and not dry_run),
        }


def configured_formats(value: Any) -> tuple[str, ...]:
    if value is None or value == "both":
        return SUPPORTED_FORMATS
    if isinstance(value, str):
        values = [token.strip() for token in value.split(",")]
    else:
        values = list(value)
    formats = tuple(dict.fromkeys(_clean(item).casefold() for item in values if _clean(item)))
    invalid = sorted(set(formats).difference(SUPPORTED_FORMATS))
    if invalid:
        raise GoodreadsError("unsupported book formats: " + ", ".join(invalid))
    return formats
