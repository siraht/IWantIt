# Library catalogs

IWantIt models “what I want” and “what I already own” as separate concerns.
Goodreads is one wishlist source. Library catalogs are reusable read-only ownership
providers used by every book workflow before search or dispatch.

The `filter_owned` workflow step asks all catalogs that support the requested
format. It matches ISBN/ASIN first, then requires strong normalized title and
author evidence. If all requested format legs are owned, the workflow ends with
`decision.status: owned`. A failed `required: true` catalog blocks acquisition to
avoid duplicates; optional catalogs fail open.
Set `require_coverage: true` when every requested format must have at least one
configured catalog; this prevents a typo or incomplete deployment from silently
skipping ownership checks.

## Configuration

```yaml
library_catalogs:
  require_coverage: true
  catalogs:
    - name: calibre
      adapter: calibre_opds
      media_types: [ebook]
      url: https://calibre.example/opds/new
      username: reader
      password: ${ENV:CALIBRE_PASSWORD}
      required: true

    - name: audiobookshelf
      adapter: audiobookshelf_api
      media_types: [audiobook]
      url: https://audiobooks.example
      api_key: ${ENV:AUDIOBOOKSHELF_API_KEY}
      required: true
```

Keep credentials in environment-backed secrets. Catalog results are not persisted
or sent to remote inference providers. `catalog owned` prints counts unless
`--full` is explicitly supplied.

## Built-in adapters

| Adapter | Use |
| --- | --- |
| `audiobookshelf_api` | Audiobookshelf HTTP API using a Bearer API key/token |
| `opds` | Any OPDS 1 Atom acquisition feed |
| `calibre_opds` | Named alias for Calibre Content Server OPDS |
| `calibre_web_opds` | Named alias for Calibre-Web OPDS |
| `calibre_web_automated_opds` | Named alias for CWA's Calibre-Web OPDS |
| `calibre_database` | Local read-only Calibre `metadata.db` |
| `calibre_ssh` | Calibre `metadata.db` queried read-only over batch-mode SSH |
| `audiobookshelf_database` | Local read-only Audiobookshelf SQLite fallback |
| `audiobookshelf_ssh` | Audiobookshelf SQLite queried read-only over SSH |
| `filesystem` | Local directory tree fallback |
| `ssh_filesystem` | Remote directory tree over batch-mode SSH |
| `smb_filesystem` | SMB tree using `smbclient` and optional credentials file |
| `external_command` | Extension command returning canonical JSON book records |

Prefer Audiobookshelf's API and an authenticated OPDS feed. Database adapters are
useful when the service is not exposed, and filesystem adapters cover unimported
files. Multiple catalogs can be combined for the same media type.

OPDS servers differ in their discovery/navigation feeds. Set `feed_urls` to one or
more feeds that contain book entries (for example a “new” or “all books” feed), and
use `max_pages` to bound pagination:

```yaml
- name: cwa
  adapter: calibre_web_automated_opds
  media_types: [ebook]
  feed_urls:
    - https://books.example/opds/new
  username: reader
  password: ${ENV:CWA_PASSWORD}
  max_pages: 100
```

Local and remote database examples:

```yaml
- name: calibre-local
  adapter: calibre_database
  media_types: [ebook]
  database: /books/Calibre/metadata.db

- name: calibre-unraid
  adapter: calibre_ssh
  media_types: [ebook]
  host: media@example.lan
  database: /mnt/books/Calibre/metadata.db

- name: loose-audiobooks
  adapter: smb_filesystem
  media_types: [audiobook]
  share: //nas/audiobooks
  credentials_file: ~/.config/iwantit/smb.conf
  required: false
```

The extension command receives `{media_type}` substitution in each argument and
must print a JSON array. Each object accepts `id`/`item_id`, `title`, `author` or
`authors`, `identifiers`, `isbn`, `asin`, `path`, `formats`, and `media_type`.
Plugins can register native adapters by calling `register_catalog_adapter(name,
factory)` during plugin discovery.

## Operations

```bash
iwantit catalog list
iwantit catalog doctor
iwantit catalog owned --media-type ebook
iwantit catalog owned --media-type audiobook --full
iwantit catalog match --media-type ebook --title Kindred --author "Octavia Butler"
iwantit doctor
```

The provider registry exposes every configured catalog as
`library_catalog.<name>` with `ownership_lookup` and `health` capabilities.

Older `goodreads.inventory.sources` configuration is read as a compatibility
bridge. New deployments should use `library_catalogs`; the bridge can be removed
after private configs have been migrated.

## Upstream interfaces

- [Audiobookshelf API](https://api.audiobookshelf.org/) and
  [API key management](https://audiobookshelf.org/docs/documentation/server-management/api-keys/)
- [Calibre Content Server](https://manual.calibre-ebook.com/server.html)
- [Calibre-Web](https://github.com/janeczku/calibre-web)
- [Calibre-Web-Automated](https://github.com/crocodilestick/Calibre-Web-Automated)
