# Goodreads Want to Read automation

IWantIt can ingest a complete Goodreads library export and then poll the public
`to-read` RSS feed for incremental additions. Each book has independent `ebook`
and `audiobook` state, so completing one format never causes it to be downloaded
again while the other format retries.

The personal CSV is intentionally ignored by Git because Goodreads exports can
contain reviews and private notes.

## Configuration

Configure a shelf in your private config:

```yaml
goodreads:
  shelf_url: https://www.goodreads.com/review/list/YOUR_ID?shelf=to-read
  shelf: to-read
  formats: [ebook, audiobook]
  batch_limit: 10
  timeout: 20
  lease_seconds: 1800
  retry_base_seconds: 21600
  retry_max_seconds: 604800
  state_path: null
```

With `state_path: null`, state is stored in
`~/.local/state/iwantit/goodreads-shelf.sqlite3`. The database and its parent
directory are created with private permissions.

Before any search or grab, the normal book workflow checks the reusable
`library_catalogs` subsystem. Goodreads does not know about Calibre,
Calibre-Web-Automated, Audiobookshelf, filesystem layouts, or transports. See
[Library catalogs](library_catalogs.md) for supported adapters and configuration.

## Initial import

First import the full CSV as a safe baseline. This records all current books but
does not queue downloads:

```bash
iwantit shelf sync goodreads \
  --csv docs/goodreads_library_export.csv \
  --limit 0
```

Review the state:

```bash
iwantit shelf status
```

To intentionally queue the complete existing `to-read` shelf, use `--backfill`.
This is a durable state change even with `--dry-run`:

```bash
iwantit shelf sync goodreads \
  --csv docs/goodreads_library_export.csv \
  --backfill \
  --dry-run \
  --limit 10
```

After reviewing the previews, process up to ten format legs per run:

```bash
iwantit shelf sync goodreads --confirm --limit 10
```

Omit `--backfill` for normal operation. Newly observed RSS books are queued
automatically; previously baselined books are not.

## State and retry behavior

States are:

- `baseline`: known from the initial CSV, not queued
- `pending`: ready for acquisition
- `in_progress`: leased by a sync process
- `complete`: successfully sent to Prowlarr and never selected again
- `owned`: matched in the existing ebook/audiobook inventory; never searched or grabbed
- `not_found`: no release available; retried with exponential backoff
- `error`: provider or pipeline failure; retried with exponential backoff
- `needs_choice`: ambiguous result held for manual review, not automatically retried
- `uncertain`: a process exited during acquisition; never retried automatically because
  Prowlarr's grab endpoint has no idempotency key

Inspect errors and ambiguous entries with `iwantit shelf status`. Reset failed and
unavailable entries immediately with:

```bash
iwantit shelf retry
```

Include ambiguous entries only after changing matching/ranking configuration:

```bash
iwantit shelf retry --include-choices
```

If an entry is `uncertain`, first check Prowlarr and the target download client. If
the grab is definitely absent, explicitly release it with:

```bash
iwantit shelf retry --include-uncertain
```

Resolve a `needs_choice` entry by rerunning it with the selected candidate index:

```bash
iwantit shelf resolve GOODREADS_BOOK_ID \
  --book-format ebook \
  --choice 0 \
  --confirm
```

The RSS endpoint is limited to 100 newest entries. IWantIt uses Goodreads Book ID
as its durable identity and conditional HTTP requests when supported. Polling every
15 minutes makes the feed limit irrelevant unless more than 100 books are added
between polls.

Shelf removal is non-destructive. A complete CSV snapshot marks missing books
inactive, preventing future retries; it never deletes downloaded files or cancels
an existing client job.

## systemd timer

Templates are provided in `deploy/systemd`. For a user service:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/iwantit-goodreads.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now iwantit-goodreads.timer
systemctl --user list-timers iwantit-goodreads.timer
```

The service runs with `--confirm`, which is the explicit authorization for automatic
Prowlarr grabs. Its PATH includes `~/.local/bin`, the default location used by
`uv tool install`.
