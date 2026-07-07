Book Decision Logic

The `book_decide` step filters book candidates by ebook/audiobook preference
before ranking and final selection. By default, books use `book.default_format:
both`, so the decision step will try to select one ebook and one audiobook when
both are present.

Inputs:
- `request.preferences.book_format`, `request.preferences.format`, or `request.preferences.formats`
- query-derived `request.release_preferences.formats` and `request.release_preferences.media`
- `work.candidates` from Prowlarr

Supported values include `ebook`, `epub`, `mobi`, `azw3`, `pdf`, `audiobook`,
`m4b`, `mp3`, `audible`, and `both`.

Outputs:
- `work.candidates` enriched with `derived.book_formats` when detectable
- `filter.book_format` with requested formats and matched counts
- for `both`, `decision.selected_items` and `work.selected_items` can contain
  the top-ranked ebook plus the top-ranked audiobook

The step runs before `rank_releases` and `decide`.
