import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from iwantit.catalogs import (
    AudiobookshelfApiCatalog,
    BookIdentity,
    CalibreDatabaseCatalog,
    CatalogBook,
    CatalogError,
    LibraryCatalogService,
    OpdsCatalog,
    match_book,
)
from iwantit.config import default_config, load_config
from iwantit.pipeline import Context
from iwantit.registry import iter_active_providers, merge_provider_registry
from iwantit.steps.builtin import filter_owned


class CatalogMatchingTests(TestCase):
    def test_project_defaults_contain_no_personal_catalog_or_shelf(self) -> None:
        config = default_config()
        self.assertIsNone(config["goodreads"]["shelf_url"])
        self.assertEqual(config["library_catalogs"]["catalogs"], [])

    def test_existing_book_workflow_is_migrated_before_search(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(
                "workflows:\n- name: book\n  steps: [prowlarr_search]\nsteps:\n"
                "  prowlarr_search: {builtin: prowlarr_search}\n",
                encoding="utf-8",
            )
            config = load_config(path)
        self.assertEqual(
            config["workflows"][0]["steps"],
            ["filter_owned", "prowlarr_search", "dedupe_book_release"],
        )

    def test_identifier_match_has_priority(self) -> None:
        result = match_book(
            BookIdentity(
                "Different edition title", ("Somebody",), {"isbn": "978-0-8070-8369-7"}
            ),
            CatalogBook(
                "calibre",
                "4",
                "ebook",
                "Kindred",
                ("Octavia Butler",),
                {"isbn": "9780807083697"},
            ),
        )
        self.assertTrue(result.owned)
        self.assertEqual(result.reason, "matching isbn")

    def test_title_alone_does_not_match_wrong_author(self) -> None:
        result = match_book(
            BookIdentity("The Dispossessed", ("Ursula K. Le Guin",)),
            CatalogBook("files", "1", "ebook", "The Dispossessed", ("Iain M. Banks",)),
        )
        self.assertFalse(result.owned)


class CatalogAdapterTests(TestCase):
    @patch("iwantit.catalogs.requests.get")
    def test_opds_adapter_reads_calibre_web_acquisition_entries(
        self, get: Mock
    ) -> None:
        response = Mock()
        response.content = b"""<feed xmlns='http://www.w3.org/2005/Atom'>
          <entry><id>urn:book:1</id><title>Kindred</title>
            <author><name>Octavia E. Butler</name></author>
            <link rel='http://opds-spec.org/acquisition' type='application/epub+zip' href='/book/1.epub'/>
          </entry></feed>"""
        response.raise_for_status.return_value = None
        get.return_value = response
        books = OpdsCatalog(
            {
                "name": "cwa",
                "url": "https://books.example/opds/new",
                "username": "reader",
                "password": "secret",
                "media_types": ["ebook"],
            }
        ).books("ebook")
        self.assertEqual(books[0].formats, ("epub+zip",))
        self.assertEqual(books[0].authors, ("Octavia E. Butler",))
        self.assertEqual(get.call_args.kwargs["auth"], ("reader", "secret"))

    def test_local_calibre_database_uses_structured_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "metadata.db"
            connection = sqlite3.connect(database)
            connection.executescript(
                """
                CREATE TABLE books(id INTEGER, title TEXT, author_sort TEXT, isbn TEXT, path TEXT);
                CREATE TABLE authors(id INTEGER, name TEXT);
                CREATE TABLE books_authors_link(book INTEGER, author INTEGER);
                CREATE TABLE identifiers(book INTEGER, type TEXT, val TEXT);
                INSERT INTO books VALUES(1, 'Kindred', 'Butler, Octavia', '', 'Octavia Butler/Kindred');
                INSERT INTO authors VALUES(2, 'Octavia E. Butler');
                INSERT INTO books_authors_link VALUES(1, 2);
                INSERT INTO identifiers VALUES(1, 'isbn', '9780807083697');
                """
            )
            connection.commit()
            connection.close()
            books = CalibreDatabaseCatalog(
                {"name": "calibre", "database": str(database), "media_types": ["ebook"]}
            ).books("ebook")
        self.assertEqual(books[0].title, "Kindred")
        self.assertEqual(books[0].identifiers["isbn"], "9780807083697")

    @patch("iwantit.catalogs.requests.Session")
    def test_audiobookshelf_api_uses_supported_library_endpoints(
        self, session_class: Mock
    ) -> None:
        session = session_class.return_value
        libraries = Mock()
        libraries.json.return_value = {
            "libraries": [{"id": "lib", "mediaType": "book"}]
        }
        libraries.raise_for_status.return_value = None
        items = Mock()
        items.json.return_value = {
            "results": [
                {
                    "id": "one",
                    "path": "/books/Kindred",
                    "media": {
                        "metadata": {
                            "title": "Kindred",
                            "authors": [{"name": "Octavia Butler"}],
                            "isbn": "9780807083697",
                        }
                    },
                }
            ]
        }
        items.raise_for_status.return_value = None
        session.get.side_effect = [libraries, items]
        catalog = AudiobookshelfApiCatalog(
            {
                "name": "abs",
                "url": "http://abs:13378",
                "api_key": "secret",
                "media_types": ["audiobook"],
            }
        )
        books = catalog.books("audiobook")
        self.assertEqual(books[0].title, "Kindred")
        session.headers.update.assert_called_once_with(
            {"Authorization": "Bearer secret"}
        )
        self.assertIn("api/libraries/lib/items", session.get.call_args_list[1].args[0])

    def test_required_catalog_failure_blocks_acquisition(self) -> None:
        service = LibraryCatalogService.from_config(
            {
                "library_catalogs": {
                    "catalogs": [
                        {
                            "name": "missing",
                            "adapter": "filesystem",
                            "path": "/definitely/not/here",
                            "media_types": ["ebook"],
                            "required": True,
                        }
                    ]
                }
            }
        )
        with self.assertRaises(CatalogError):
            service.books("ebook")

    def test_required_coverage_blocks_an_unconfigured_format(self) -> None:
        service = LibraryCatalogService.from_config(
            {"library_catalogs": {"require_coverage": True, "catalogs": []}}
        )
        with self.assertRaisesRegex(
            CatalogError, "no library catalog covers audiobook"
        ):
            service.books("audiobook")

    def test_external_command_is_a_stable_extension_point(self) -> None:
        config = {
            "library_catalogs": {
                "catalogs": [
                    {
                        "name": "custom",
                        "adapter": "external_command",
                        "command": [
                            "python3",
                            "-c",
                            "import json; print(json.dumps([{'id':'1','title':'Kindred','author':'Octavia Butler'}]))",
                        ],
                        "media_types": ["ebook"],
                    }
                ]
            }
        }
        books = LibraryCatalogService.from_config(config).books("ebook")
        self.assertEqual(books[0].catalog, "custom")


class CatalogPipelineTests(TestCase):
    def test_catalogs_are_exposed_in_capability_registry(self) -> None:
        config = {
            "library_catalogs": {
                "catalogs": [
                    {
                        "name": "cwa",
                        "adapter": "calibre_web_automated_opds",
                        "media_types": ["ebook"],
                    }
                ]
            }
        }
        entry = merge_provider_registry(config)["library_catalog.cwa"]
        self.assertTrue(entry["capabilities"]["ownership_lookup"])
        self.assertIn("library_catalog.cwa", iter_active_providers(config))

    def test_owned_book_becomes_terminal_before_search(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Octavia Butler" / "Kindred").mkdir(parents=True)
            config = {
                "library_catalogs": {
                    "catalogs": [
                        {
                            "name": "ebooks",
                            "adapter": "filesystem",
                            "path": str(root),
                            "media_types": ["ebook"],
                        }
                    ]
                }
            }
            data = {
                "request": {"preferences": {"book_format": "ebook"}},
                "work": {
                    "media_type": "book",
                    "title": "Kindred",
                    "author": "Octavia E. Butler",
                },
            }
            result = filter_owned(
                data, {}, Context(config=config, state_path=directory)
            )
        self.assertEqual(result["decision"]["status"], "owned")
        self.assertEqual(result["ownership"]["ebook"]["catalog"], "ebooks")
