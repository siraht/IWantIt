Book Decision Logic

The `book_decide` step filters book candidates by ebook/audiobook preference
before ranking and final selection. By default, books use `book.default_format:
both`, so the decision step will try to select one ebook and one audiobook when
both are present.

Inputs:
- `request.preferences.book_format`, `request.preferences.format`, or `request.preferences.formats`
- query-derived `request.release_preferences.formats` and `request.release_preferences.media`
- `work.candidates` from Prowlarr

Supported values include `ebook`, `epub`, `kepub`, `mobi`, `azw3`, `pdf`,
`djvu`, `cbz`, `cbr`, `audiobook`, `m4b`, `m4a`, `mp3`, `opus`, `audible`, and
`both`.

Outputs:
- `work.candidates` enriched with `derived.book_formats` when detectable
- `filter.book_format` with requested formats and matched counts
- for `both`, `decision.selected_items` and `work.selected_items` can contain
  the top-ranked ebook plus the top-ranked audiobook

The step runs before `rank_releases` and `decide`.

Ranking priorities:
- Honor explicitly requested edition/year first.
- Otherwise prefer newer/higher editions when edition cues are visible.
- Prefer portable ebook formats (`kepub`/`epub`, then Kindle formats, then
  legacy or fixed-layout formats unless the title implies comics/layout needs).
- Prefer audiobook containers/codecs suited to long-form listening (`m4b`,
  `m4a`/`aac`, `opus`/`ogg`, then `mp3`), with bitrate scored when advertised.
- Prefer unabridged, retail, seeded, recent releases from trusted sources; penalize
  abridged, scanned/OCR-only, converted, and ancillary-file-heavy releases.
