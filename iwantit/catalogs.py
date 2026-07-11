"""Reusable owned-library catalogs and book ownership matching.

Catalogs are deliberately independent from request sources such as Goodreads.
Every adapter emits the same :class:`CatalogBook` contract so any book workflow
can avoid acquiring an item already present in one or more libraries.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests


class CatalogError(RuntimeError):
    """A configured owned-library catalog could not be read safely."""


@dataclass(frozen=True)
class CatalogBook:
    catalog: str
    item_id: str
    media_type: str
    title: str
    authors: tuple[str, ...] = ()
    identifiers: dict[str, str] = field(default_factory=dict)
    path: str = ""
    formats: tuple[str, ...] = ()


@dataclass(frozen=True)
class BookIdentity:
    title: str
    authors: tuple[str, ...] = ()
    identifiers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OwnershipMatch:
    owned: bool
    score: float = 0.0
    catalog: str = ""
    item_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class CatalogHealth:
    name: str
    adapter: str
    ok: bool
    message: str
    item_count: int | None = None
    required: bool = True


class CatalogAdapter(Protocol):
    name: str
    adapter_type: str
    required: bool
    media_types: tuple[str, ...]

    def books(self, media_type: str | None = None) -> list[CatalogBook]: ...

    def health(self) -> CatalogHealth: ...


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _tokens(value: str) -> list[str]:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    )
    return re.findall(r"[a-z0-9]+", ascii_value.casefold())


def _identifier(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", _clean(value).casefold())


_STOPWORDS = {
    "a",
    "an",
    "and",
    "book",
    "edition",
    "for",
    "in",
    "of",
    "on",
    "the",
    "to",
    "with",
}


def match_book(wanted: BookIdentity, owned: CatalogBook) -> OwnershipMatch:
    """Match identifiers first, then require strong title and author evidence."""

    wanted_ids = {
        (
            "isbn" if key.casefold() in {"isbn", "isbn10", "isbn13"} else key.casefold()
        ): _identifier(value)
        for key, value in wanted.identifiers.items()
        if _identifier(value)
    }
    owned_ids = {
        (
            "isbn" if key.casefold() in {"isbn", "isbn10", "isbn13"} else key.casefold()
        ): _identifier(value)
        for key, value in owned.identifiers.items()
        if _identifier(value)
    }
    for key, value in wanted_ids.items():
        if len(value) >= 8 and owned_ids.get(key) == value:
            return OwnershipMatch(
                True, 1.0, owned.catalog, owned.item_id, f"matching {key}"
            )

    haystack = " ".join((owned.title, *owned.authors, owned.path))
    haystack_tokens = set(_tokens(haystack))
    author_tokens = _tokens(" ".join(wanted.authors))
    author_markers = set()
    if author_tokens:
        author_markers.add(author_tokens[-1])
        if len(author_tokens) > 1:
            author_markers.add(author_tokens[0])
    if author_markers and not author_markers.intersection(haystack_tokens):
        return OwnershipMatch(False)

    title_head = re.split(r"[:(\[]", wanted.title, maxsplit=1)[0]
    title_tokens = [token for token in _tokens(title_head) if token not in _STOPWORDS]
    title_tokens = title_tokens or _tokens(wanted.title)
    if not title_tokens:
        return OwnershipMatch(False)
    overlap = sum(token in haystack_tokens for token in title_tokens)
    required = (
        1 if len(title_tokens) == 1 else max(2, math.ceil(len(title_tokens) * 0.7))
    )
    score = overlap / len(title_tokens)
    if overlap >= required:
        return OwnershipMatch(
            True, score, owned.catalog, owned.item_id, "title and author"
        )
    return OwnershipMatch(False, score)


class _BaseAdapter:
    adapter_type = "base"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.name = _clean(config.get("name") or self.adapter_type)
        self.required = bool(config.get("required", True))
        configured = config.get("media_types") or [config.get("media_type") or "ebook"]
        self.media_types = tuple(_clean(value).casefold() for value in configured)
        self.timeout = float(config.get("timeout", 120))

    def health(self) -> CatalogHealth:
        try:
            count = len(self.books())
            return CatalogHealth(
                self.name, self.adapter_type, True, "ok", count, self.required
            )
        except Exception as exc:
            return CatalogHealth(
                self.name, self.adapter_type, False, str(exc), None, self.required
            )

    def _book(
        self,
        *,
        item_id: Any,
        title: Any,
        authors: Iterable[Any] = (),
        identifiers: dict[str, Any] | None = None,
        path: Any = "",
        formats: Iterable[Any] = (),
        media_type: str | None = None,
    ) -> CatalogBook:
        return CatalogBook(
            catalog=self.name,
            item_id=_clean(item_id),
            media_type=media_type or self.media_types[0],
            title=_clean(title),
            authors=tuple(_clean(value) for value in authors if _clean(value)),
            identifiers={
                key.casefold(): _clean(value)
                for key, value in (identifiers or {}).items()
                if _clean(value)
            },
            path=_clean(path),
            formats=tuple(
                _clean(value).casefold() for value in formats if _clean(value)
            ),
        )


class FilesystemCatalog(_BaseAdapter):
    adapter_type = "filesystem"

    def _entries(self) -> list[str]:
        path = Path(_clean(self.config.get("path"))).expanduser()
        if not path.is_dir():
            raise CatalogError(f"catalog path is unavailable: {path}")
        return [
            str(Path(root).relative_to(path) / name)
            for root, dirs, files in os.walk(path)
            for name in (*dirs, *files)
        ]

    def books(self, media_type: str | None = None) -> list[CatalogBook]:
        kind = media_type or self.media_types[0]
        if kind not in self.media_types:
            return []
        return [
            self._book(item_id=entry, title="", path=entry, media_type=kind)
            for entry in self._entries()
        ]


class SshFilesystemCatalog(FilesystemCatalog):
    adapter_type = "ssh_filesystem"

    def _entries(self) -> list[str]:
        host, path = _clean(self.config.get("host")), _clean(self.config.get("path"))
        if not shutil.which("ssh"):
            raise CatalogError("ssh is required")
        if not re.fullmatch(r"[A-Za-z0-9_.@-]+", host) or not path.startswith("/"):
            raise CatalogError("SSH catalog requires a safe host and absolute path")
        command = f"find -- {shlex.quote(path)} -mindepth 1 -printf '%P\\n'"
        completed = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, command],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if completed.returncode:
            raise CatalogError(
                (completed.stderr.strip().splitlines() or ["SSH catalog unavailable"])[
                    -1
                ]
            )
        return [line for line in completed.stdout.splitlines() if line.strip()]


class SmbFilesystemCatalog(FilesystemCatalog):
    adapter_type = "smb_filesystem"

    def _entries(self) -> list[str]:
        share = _clean(self.config.get("share"))
        if not shutil.which("smbclient"):
            raise CatalogError("smbclient is required")
        if not share.startswith("//"):
            raise CatalogError("SMB catalog requires //server/share")
        command = ["smbclient", share, "-g"]
        credentials = _clean(self.config.get("credentials_file"))
        command.extend(
            ["-A", str(Path(credentials).expanduser())] if credentials else ["-N"]
        )
        command.extend(["-c", "recurse;ls"])
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=self.timeout, check=False
        )
        if completed.returncode:
            raise CatalogError(
                (completed.stderr.strip().splitlines() or ["SMB catalog unavailable"])[
                    -1
                ]
            )
        return [
            parts[-1]
            for line in completed.stdout.splitlines()
            if len(parts := line.split("|")) >= 2
            and parts[0] in {"D", "F"}
            and parts[-1] not in {"", ".", ".."}
        ]


class _SqliteCatalog(_BaseAdapter):
    query = ""

    def _rows(self) -> list[dict[str, Any]]:
        database = Path(_clean(self.config.get("database"))).expanduser()
        if not database.is_file():
            raise CatalogError(f"catalog database is unavailable: {database}")
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                database.resolve().as_uri() + "?mode=ro", uri=True
            )
            connection.row_factory = sqlite3.Row
            with connection:
                return [dict(row) for row in connection.execute(self.query)]
        except sqlite3.Error as exc:
            raise CatalogError(f"could not query catalog database: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def _rows_to_books(
        self, rows: list[dict[str, Any]], media_type: str
    ) -> list[CatalogBook]:
        return [
            self._book(
                item_id=row.get("id") or index,
                title=row.get("title"),
                authors=[row.get("author")],
                identifiers={"isbn": row.get("isbn"), "asin": row.get("asin")},
                path=row.get("path"),
                media_type=media_type,
            )
            for index, row in enumerate(rows)
            if _clean(row.get("title"))
        ]

    def books(self, media_type: str | None = None) -> list[CatalogBook]:
        kind = media_type or self.media_types[0]
        return (
            []
            if kind not in self.media_types
            else self._rows_to_books(self._rows(), kind)
        )


class _SshSqliteMixin:
    def _rows(self) -> list[dict[str, Any]]:
        host, database = (
            _clean(self.config.get("host")),
            _clean(self.config.get("database")),
        )
        if not shutil.which("ssh"):
            raise CatalogError("ssh is required")
        if not re.fullmatch(r"[A-Za-z0-9_.@-]+", host) or not database.startswith("/"):
            raise CatalogError(
                "SSH SQLite catalog requires a safe host and absolute database path"
            )
        remote = (
            f"sqlite3 -readonly -json {shlex.quote(database)} {shlex.quote(self.query)}"
        )
        completed = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, remote],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if completed.returncode:
            raise CatalogError(
                (
                    completed.stderr.strip().splitlines()
                    or ["remote SQLite catalog unavailable"]
                )[-1]
            )
        try:
            value = json.loads(completed.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise CatalogError("remote SQLite catalog returned invalid JSON") from exc
        if not isinstance(value, list):
            raise CatalogError("remote SQLite catalog returned an unexpected result")
        return [row for row in value if isinstance(row, dict)]


class CalibreDatabaseCatalog(_SqliteCatalog):
    adapter_type = "calibre_database"
    query = """SELECT b.id, b.title, COALESCE(GROUP_CONCAT(a.name, ' '), b.author_sort, '') author,
      COALESCE((SELECT val FROM identifiers WHERE book=b.id AND LOWER(type)='isbn' LIMIT 1), b.isbn, '') isbn,
      COALESCE((SELECT val FROM identifiers WHERE book=b.id AND LOWER(type)='asin' LIMIT 1), '') asin,
      b.path FROM books b LEFT JOIN books_authors_link l ON l.book=b.id LEFT JOIN authors a ON a.id=l.author GROUP BY b.id"""


class CalibreSshCatalog(_SshSqliteMixin, CalibreDatabaseCatalog):
    adapter_type = "calibre_ssh"


class AudiobookshelfDatabaseCatalog(_SqliteCatalog):
    adapter_type = "audiobookshelf_database"
    query = """SELECT li.id, COALESCE(li.title,b.title,'') title,
      COALESCE(li.authorNamesFirstLast,li.authorNamesLastFirst,'') author,
      COALESCE(b.isbn,'') isbn, COALESCE(b.asin,'') asin, COALESCE(li.path,'') path
      FROM libraryItems li JOIN books b ON b.id=li.mediaId WHERE li.mediaType='book'
      AND COALESCE(li.isMissing,0)=0 AND COALESCE(li.isInvalid,0)=0"""


class AudiobookshelfSshCatalog(_SshSqliteMixin, AudiobookshelfDatabaseCatalog):
    adapter_type = "audiobookshelf_ssh"


class AudiobookshelfApiCatalog(_BaseAdapter):
    adapter_type = "audiobookshelf_api"

    def _headers(self) -> dict[str, str]:
        token = _clean(self.config.get("api_key") or self.config.get("token"))
        return {"Authorization": f"Bearer {token}"} if token else {}

    def books(self, media_type: str | None = None) -> list[CatalogBook]:
        kind = media_type or "audiobook"
        if kind not in self.media_types:
            return []
        base = _clean(self.config.get("url")).rstrip("/") + "/"
        if not base.startswith(("http://", "https://")):
            raise CatalogError("Audiobookshelf catalog requires an http(s) URL")
        session = requests.Session()
        session.headers.update(self._headers())
        library_ids = [
            _clean(value)
            for value in self.config.get("library_ids", [])
            if _clean(value)
        ]
        if not library_ids:
            response = session.get(urljoin(base, "api/libraries"), timeout=self.timeout)
            response.raise_for_status()
            library_ids = [
                _clean(item.get("id"))
                for item in response.json().get("libraries", [])
                if item.get("mediaType") == "book"
            ]
        books: list[CatalogBook] = []
        for library_id in library_ids:
            response = session.get(
                urljoin(base, f"api/libraries/{library_id}/items"),
                params={"limit": 0, "minified": 0},
                timeout=self.timeout,
            )
            response.raise_for_status()
            for item in response.json().get("results", []):
                media = item.get("media") or {}
                metadata = media.get("metadata") or item.get("metadata") or {}
                authors = metadata.get("authors") or []
                names = [
                    author.get("name") if isinstance(author, dict) else author
                    for author in authors
                ]
                if not names:
                    names = [metadata.get("authorName") or item.get("authorNames")]
                books.append(
                    self._book(
                        item_id=item.get("id"),
                        title=metadata.get("title") or item.get("title"),
                        authors=names,
                        identifiers={
                            "isbn": metadata.get("isbn"),
                            "asin": metadata.get("asin"),
                        },
                        path=item.get("path"),
                        media_type=kind,
                    )
                )
        return [book for book in books if book.title]


class OpdsCatalog(_BaseAdapter):
    """OPDS 1 Atom adapter for Calibre, Calibre-Web, CWA, and compatible servers."""

    adapter_type = "opds"

    def books(self, media_type: str | None = None) -> list[CatalogBook]:
        kind = media_type or self.media_types[0]
        if kind not in self.media_types:
            return []
        urls = self.config.get("feed_urls") or [self.config.get("url")]
        pending = [_clean(url) for url in urls if _clean(url)]
        if not pending:
            raise CatalogError("OPDS catalog requires url or feed_urls")
        auth = None
        if self.config.get("username"):
            auth = (
                _clean(self.config.get("username")),
                _clean(self.config.get("password")),
            )
        headers = dict(self.config.get("headers") or {})
        token = _clean(self.config.get("token"))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        seen: set[str] = set()
        result: list[CatalogBook] = []
        max_pages = int(self.config.get("max_pages", 100))
        while pending and len(seen) < max_pages:
            url = pending.pop(0)
            if url in seen:
                continue
            seen.add(url)
            response = requests.get(
                url, auth=auth, headers=headers, timeout=self.timeout
            )
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
            for entry in root.findall("{*}entry"):
                title = _clean(entry.findtext("{*}title"))
                authors = [
                    _clean(author.findtext("{*}name"))
                    for author in entry.findall("{*}author")
                ]
                identifiers: dict[str, str] = {}
                for identifier_node in entry.findall("{*}identifier"):
                    value = _clean(identifier_node.text)
                    lower = value.casefold()
                    if "isbn" in lower:
                        identifiers["isbn"] = value.rsplit(":", 1)[-1]
                    elif "asin" in lower:
                        identifiers["asin"] = value.rsplit(":", 1)[-1]
                links = entry.findall("{*}link")
                formats = [
                    (_clean(link.get("type")).split("/")[-1])
                    for link in links
                    if "acquisition" in _clean(link.get("rel"))
                ]
                item_id = _clean(entry.findtext("{*}id")) or title
                if title and (formats or authors):
                    result.append(
                        self._book(
                            item_id=item_id,
                            title=title,
                            authors=authors,
                            identifiers=identifiers,
                            formats=formats,
                            media_type=kind,
                        )
                    )
            for link in root.findall("{*}link"):
                if _clean(link.get("rel")) == "next" and link.get("href"):
                    pending.append(urljoin(url, _clean(link.get("href"))))
        return result


class ExternalCommandCatalog(_BaseAdapter):
    """Extension point: command emits a JSON array of canonical book objects."""

    adapter_type = "external_command"

    def books(self, media_type: str | None = None) -> list[CatalogBook]:
        command = self.config.get("command")
        if not isinstance(command, list) or not command:
            raise CatalogError("external_command requires a non-empty command array")
        kind = media_type or self.media_types[0]
        completed = subprocess.run(
            [str(value).replace("{media_type}", kind) for value in command],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        if completed.returncode:
            raise CatalogError(
                (completed.stderr.strip().splitlines() or ["catalog command failed"])[
                    -1
                ]
            )
        try:
            rows = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise CatalogError("catalog command returned invalid JSON") from exc
        if not isinstance(rows, list):
            raise CatalogError("catalog command must return a JSON array")
        return [
            self._book(
                item_id=row.get("item_id") or row.get("id") or index,
                title=row.get("title"),
                authors=row.get("authors") or [row.get("author")],
                identifiers=row.get("identifiers")
                or {"isbn": row.get("isbn"), "asin": row.get("asin")},
                path=row.get("path"),
                formats=row.get("formats") or [],
                media_type=row.get("media_type") or kind,
            )
            for index, row in enumerate(rows)
            if isinstance(row, dict) and row.get("title")
        ]


AdapterFactory = Callable[[dict[str, Any]], CatalogAdapter]
CATALOG_ADAPTERS: dict[str, AdapterFactory] = {}


def register_catalog_adapter(name: str, factory: AdapterFactory) -> None:
    """Register a catalog adapter; plugins may call this during discovery."""
    CATALOG_ADAPTERS[name.casefold()] = factory


for _adapter in (
    FilesystemCatalog,
    SshFilesystemCatalog,
    SmbFilesystemCatalog,
    CalibreDatabaseCatalog,
    CalibreSshCatalog,
    AudiobookshelfDatabaseCatalog,
    AudiobookshelfSshCatalog,
    AudiobookshelfApiCatalog,
    OpdsCatalog,
    ExternalCommandCatalog,
):
    register_catalog_adapter(_adapter.adapter_type, _adapter)

# Human-friendly aliases use the same standards-based OPDS implementation.
for _alias in ("calibre_opds", "calibre_web_opds", "calibre_web_automated_opds"):
    register_catalog_adapter(_alias, OpdsCatalog)


def _legacy_catalogs(config: dict[str, Any]) -> list[dict[str, Any]]:
    inventory = (config.get("goodreads") or {}).get("inventory") or {}
    if not inventory.get("enabled", True):
        return []
    result = []
    aliases = {"local": "filesystem", "ssh": "ssh_filesystem", "smb": "smb_filesystem"}
    for media_type, sources in (inventory.get("sources") or {}).items():
        for index, source in enumerate(sources or []):
            if isinstance(source, dict):
                result.append(
                    {
                        **source,
                        "name": f"legacy-{media_type}-{index + 1}",
                        "adapter": aliases.get(source.get("type"), source.get("type")),
                        "media_types": [media_type],
                        "required": inventory.get("required", True),
                        "timeout": source.get("timeout", inventory.get("timeout", 120)),
                    }
                )
    return result


_SHARED_SNAPSHOT_CACHE: dict[tuple[str, str], tuple[float, list[CatalogBook]]] = {}


class LibraryCatalogService:
    """Aggregates configured catalogs and answers reusable ownership queries."""

    def __init__(
        self, adapters: Iterable[CatalogAdapter], *, require_coverage: bool = False
    ) -> None:
        self.adapters = list(adapters)
        self.require_coverage = require_coverage
        self._cache: dict[tuple[str, str], list[CatalogBook]] = {}

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "LibraryCatalogService":
        section = config.get("library_catalogs") or {}
        catalogs = section.get("catalogs") or _legacy_catalogs(config)
        adapters = []
        for catalog in catalogs:
            if not isinstance(catalog, dict) or not catalog.get("enabled", True):
                continue
            adapter_type = _clean(
                catalog.get("adapter") or catalog.get("type")
            ).casefold()
            factory = CATALOG_ADAPTERS.get(adapter_type)
            if not factory:
                raise CatalogError(f"unsupported catalog adapter: {adapter_type}")
            adapter = factory(catalog)
            adapter.adapter_type = adapter_type
            adapters.append(adapter)
        return cls(
            adapters, require_coverage=bool(section.get("require_coverage", False))
        )

    def books(self, media_type: str) -> list[CatalogBook]:
        books: list[CatalogBook] = []
        failures: list[str] = []
        compatible = [
            adapter for adapter in self.adapters if media_type in adapter.media_types
        ]
        if self.require_coverage and not compatible:
            raise CatalogError(f"no library catalog covers {media_type}")
        for adapter in compatible:
            key = (adapter.name, media_type)
            try:
                if key not in self._cache:
                    adapter_config = getattr(
                        adapter,
                        "config",
                        {"name": adapter.name, "adapter": adapter.adapter_type},
                    )
                    fingerprint = hashlib.sha256(
                        json.dumps(adapter_config, sort_keys=True, default=str).encode()
                    ).hexdigest()
                    shared_key = (fingerprint, media_type)
                    ttl = float(adapter_config.get("cache_ttl_seconds", 30))
                    cached = _SHARED_SNAPSHOT_CACHE.get(shared_key)
                    if cached and time.monotonic() - cached[0] <= ttl:
                        self._cache[key] = cached[1]
                    else:
                        self._cache[key] = adapter.books(media_type)
                        _SHARED_SNAPSHOT_CACHE[shared_key] = (
                            time.monotonic(),
                            self._cache[key],
                        )
                books.extend(self._cache[key])
            except Exception as exc:
                if adapter.required:
                    failures.append(f"{adapter.name}: {exc}")
        if failures:
            raise CatalogError(
                "required library catalogs failed; acquisition is blocked: "
                + "; ".join(failures)
            )
        return books

    def match(self, wanted: BookIdentity, media_type: str) -> OwnershipMatch:
        best = OwnershipMatch(False)
        for book in self.books(media_type):
            candidate = match_book(wanted, book)
            if candidate.owned:
                return candidate
            if candidate.score > best.score:
                best = candidate
        return best

    def health(self) -> list[CatalogHealth]:
        return [adapter.health() for adapter in self.adapters]
