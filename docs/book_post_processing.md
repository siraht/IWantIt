# Book download normalization

Book acquisition is fail-closed at three boundaries:

1. The requested format leg must match an explicit release-title format or a
   Prowlarr ebook/audiobook category.
2. The requested leg selects the download client; release-title guessing cannot
   redirect it.
3. A release GUID already dispatched for another leg is rejected.

English requests reject explicit Russian/Cyrillic releases. Unclassified results
remain unavailable instead of falling back to the wrong format.

Ranking is format-specific. Ebooks prefer MyAnonamouse, AlphaRatio, PreToMe,
then RuTracker; audiobooks prefer MyAnonamouse, AudioNews, Bitspyder, then
RuTracker. Redacted has no priority bonus and is capability-limited to explicitly
validated audiobook releases; it can never supply an ebook or an unclassified
book result. Explicit Russian releases are rejected by the default book rules.
Collection-like titles are not rejected by name alone: the normalizer inspects
their payload and quarantines archives containing multiple distinct books.

`iwantit books normalize` audits downloaded releases without writing. Add
`--apply` to copy validated outputs into the configured ingest roots. Source files
remain untouched so active torrents can continue seeding.

The normalizer:

- validates EPUB structure and non-empty ebook files;
- recursively unwraps ZIP-to-RAR and multipart scene releases;
- rejects path traversal, corrupt/password-protected archives, zero-byte files,
  apparent multi-book collections, and foreign-language releases;
- stages ebooks in the CWA ingest directory;
- copies misplaced audiobook folders to an Audiobookshelf recovery directory;
- records source signatures so successful releases are not processed twice.

Example:

```yaml
book_processing:
  enabled: true
  ssh_host: media@example.lan
  ebook_root: /media/ebooks
  audiobook_root: /media/audiobooks
  ebook_ingest_root: /app/calibre-web/ingest
  state_path: /app/iwantit/book-processing.json
  min_mtime_epoch: 0
```

The supplied Goodreads systemd service runs normalization after every successful
shelf synchronization. Catalog reconciliation promotes `dispatched` legs to
`owned` only after the normalized media appears in Calibre or Audiobookshelf.
