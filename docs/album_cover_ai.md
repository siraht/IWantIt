# Album Cover Recognition Notes

Goal: resolve an album (or track) from an image-only input when OCR yields little or no text.

Proposed step design
- Add a step before identify: `cover_identify` (external command preferred).
- Inputs: `request.image_path`, `request.input`, existing `request.query`/`ocr.text`.
- Outputs: set `work.candidates` (ranked) and optionally `work.title`.

Suggested pipeline
1) OCR (tesseract) for text.
2) If OCR is weak, compute a perceptual hash (pHash) and store in state cache.
3) Run vision model or embeddings to get a coarse label (artist/album hints).
4) Query metadata sources (MusicBrainz, Discogs, your tracker API) using hints.
5) Re-rank candidates with image similarity (optional) and return top N.

Caching
- Cache by pHash to avoid repeat API calls.
- Store in `~/.local/state/iwantit/cache/cover_hash.json` mapping hash -> candidates.

Interfaces
- External step reads JSON on stdin, writes JSON on stdout.
- It should only add/modify `work.candidates` and `work.title`.

Safety
- Keep this step optional and off by default.
- Avoid sending full-size images if a privacy-sensitive source is used; downscale first.
