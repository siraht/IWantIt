# Shelfmark integration notes (draft)

This doc captures the current thinking on how Shelfmark could fit into the book
workflow.

## What Shelfmark provides (per README/docs)
- A unified web interface to search and download books/audiobooks from multiple
  sources, including direct web sources plus torrent/usenet/IRC support. It is
  designed to be a single hub for discovery + downloading.
- Two search modes: **Direct** (web sources) and **Universal** (metadata
  providers like Hardcover / Open Library for cleaner results, then multi-source
  downloads).
- Built-in audiobook support, format/language filtering, file processing with
  template-based naming, and integration with Prowlarr for books/audiobooks +
  download clients.

Sources: https://github.com/calibrain/shelfmark

## Integration paths for our project

1) **Replace the current book workflow with Shelfmark dispatch**
   - Keep our identify/media-type steps, then send a normalized query
     (title/author/year + `book_format`) to Shelfmark and let it do search +
     download.
   - Benefit: Shelfmark already handles multi-source search, audiobook routing,
     format filtering, and file naming.

2) **Use Shelfmark as a book metadata resolver**
   - Query Shelfmark’s **Universal** search to normalize author/title/series.
   - Keep our Prowlarr flow for downloading, or pass the resolved query back to
     Shelfmark for download.
   - Benefit: reduces reliance on general web search for books.

3) **Delegate book download orchestration to Shelfmark**
   - Our `--book-format` / `book.default_format` maps cleanly to Shelfmark
     format filters (ebook/audiobook).
   - Pass format + language preferences and let Shelfmark handle download
     routing and file naming.

4) **Use Shelfmark’s Prowlarr integration instead of ours**
   - Shelfmark already supports Prowlarr for books/audiobooks and can route
     to download clients, so we can drop Prowlarr-specific logic in our book
     workflow once Shelfmark is downstream.

## Unknowns / validation required
- The README doesn’t mention a public API. We need to confirm whether there is:
  - a stable HTTP API,
  - a CLI entry point,
  - or internal endpoints suitable for automation.
- If there’s no API, the options are:
  - keep Prowlarr book workflow as default and add Shelfmark later,
  - or build a small adapter once endpoints are identified in code.

## Recommendation for workflow design
- Add a config toggle for books:
  - `book.source = "shelfmark" | "prowlarr"`
- Add a new `dispatch_shelfmark` step (HTTP) if a usable API is confirmed.
- If no API, defer integration and keep the current Prowlarr path.

## Next steps (if we proceed)
1) Inspect Shelfmark code/docs to locate API endpoints (if any).
2) Define request payloads for search + download.
3) Wire `dispatch_shelfmark` with retries/timeouts and update README.
