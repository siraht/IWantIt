Redacted Comment Sourcing Plan (Deferred)

Purpose
- Capture decisions, learnings, and the intended implementation so a future pass can resume cleanly.
- This document is self-contained and does not require reading prior chat history.

Scope
- Implement automatic comment sourcing from Redacted to heavily weight recommended editions.
- Use release (torrent group) comments, not per-torrent comments.
- Use extracted recommendations to influence ranking with a large score boost.

Key Requirements (from product intent)
- If a user explicitly specifies a version (deluxe/anniversary/etc.), only select matching results.
- If no explicit version is requested, select best candidate by quality scoring + recommendations.
- Release priority order: Deluxe > Studio > Anniversary > Live > Bootleg.
- Comments should be sourced from the release page (torrent group) and parsed across all comment pages.

Current State (what exists in code)
- Steps already added in code:
  - extract_release_preferences
  - redacted_enrich
  - redacted_comments
  - apply_recommendations
  - filter_by_version
- redacted_enrich uses Redacted API:
  - GET /ajax.php?action=torrentgroup&id=<group_id>
  - Attaches group + torrent metadata to each candidate.
- apply_recommendations:
  - Attempts to boost rank when comments mention catalog number, label, media, remaster title, or year.
- filter_by_version:
  - If request.explicit_version is true, filters candidates to only those matching user-requested version.
- decide:
  - Auto-selects when explicit version is requested and matches exist.
  - Auto-selects for FLAC > V0 > 320 when those are the only formats left.
- Release priority scoring added to music quality rules.

Redacted API Reality Check
- The Redacted API endpoint `ajax.php?action=torrentgroup&id=<group_id>` returns only:
  - response.group
  - response.torrents
  - No comments included in the JSON response.
- This means API key access alone cannot fetch comments.

Confirmed: Release page HTML (session cookie) required
- Fetching `https://redacted.sh/torrents.php?id=<group_id>` with a valid session cookie returns HTML.
- HTML contains comments and page navigation for comments.
- API key does not permit the HTML endpoint; only an authenticated session cookie does.

Session Cookie Approach (deferred)
- Add to secrets:
  - redacted.session_cookie
- Use cookie-based requests to `/torrents.php?id=<group_id>`
- Parse comment pages from HTML:
  - Page links look like: torrents.php?page=<N>&id=<group_id>#comments
- Comments are stored in HTML in tables with class="forum_post" and a div id="content<post_id>".

Observed HTML structure (example)
- Comments appear in blocks like:
  - <table class="forum_post ..." id="post815004">
  - Inside: <td class="body"> <div id="content815004"> ... </div>
- The content is plain HTML with nested blockquotes for quoted text.

Parser Strategy (recommended)
- Use HTMLParser to extract text from divs with id starting with "content" (excluding preview).
- Strip nested quotes and preserve text for recommendation extraction.
- Store as a list of strings per group_id:
  - data.redacted.comments[group_id] = [comment1, comment2, ...]

Pagination Strategy
- Extract max comment page from HTML using regex:
  - torrents.php?page=(\d+)&amp;id=<group_id>#comments
- If max_pages in config is N:
  - Fetch last N pages (because newer comments often include recommendations)
- If max_pages = 0 or "all":
  - Fetch all pages from 1..max.

Caching
- Use cache namespace: redacted_comments
- Cache per group_id for 1 day (ttl_seconds: 86400) or adjustable.

Scoring Rules for Recommendations
- High-weight scoring that dominates normal quality score.
- Recommended signals to match in comments:
  - catalog numbers (highest weight)
  - record label
  - remaster title (e.g., “Black Triangle”)
  - media (CD/Vinyl/SACD)
  - year
- Use normalized text matching (lowercase, punctuation stripped).

Explicit Version Handling
- If user specifies catalog number, label, edition, media, or format:
  - Filter candidates to only those matching.
  - Auto-select best-ranked among matches.
- If nothing matches, return choices instead of auto-select.

Config Shape (intended)
- redacted:
  - url
  - api_key
  - session_cookie
  - release_type_map (for release category inference)
- steps:
  - redacted_enrich (API)
  - redacted_comments (HTML fallback)
  - apply_recommendations
  - filter_by_version

Known Gaps / Open Questions
- Comments are not available via Redacted JSON API; HTML scrape is required.
- Need to ensure scraping respects rate limits and site terms.
- Comment HTML parsing needs to remove quoted text to avoid biasing recommendations.
- Must ensure session cookie is stored securely (secrets.yaml) and redacted in logs.

Suggested Next Implementation Steps
1) Add session-cookie HTML fetcher for comment pages.
2) Implement robust HTML comment extraction.
3) Confirm comment pagination detection against multiple releases.
4) Add recommendation weighting in rank_releases (already wired).
5) Validate with “Dark Side of the Moon” and confirm the comment-based recommendation boosts.

Testing Plan
- Use a known release with many comments (e.g., DSOTM group id = 1).
- Fetch comments with session cookie.
- Confirm detection of recommended catalog numbers in comments.
- Verify that candidates matching those recommendations receive large score boosts.

Security Notes
- Session cookie grants full site access; store only in secrets.yaml.
- Ensure output JSON redacts cookies if ever surfaced.
- Avoid saving raw HTML to disk unless explicitly enabled.

Status
- Comment sourcing is currently disabled in default workflows.
- redacted_comments + apply_recommendations are still present in code but not wired.

Learnings (from attempted implementation)
- Redacted JSON API `ajax.php?action=torrentgroup&id=<group_id>` does NOT include comments.
- HTML release page `/torrents.php?id=<group_id>` DOES include comments but requires a session cookie.
- API key access cannot fetch the HTML page; it returns: "this page is not yet permitted for API usage".
- HTML includes comment pagination links (page numbers). Example pattern:
  - torrents.php?page=<N>&id=<group_id>#comments
- Comments are stored in tables with class `forum_post` and a div id `content<post_id>`.
- HTML parsing should target div ids that match `content\d+` (exclude contentpreview).
- Initial parsing captured too much content; limiting to `content\d+` reduces noise.
- Pagination detection via regex should parse all page numbers and take max.
- Fetching all pages for DSOTM is large; limit to the last N pages (configurable) to reduce load.

Next steps (when re-enabled)
1) Re-enable `redacted_comments` and `apply_recommendations` in the music workflow.
2) Use session cookie to fetch HTML comments for the release page.
3) Parse comments (content divs) into text blobs.
4) Weight recommendations heavily (catalog numbers, labels, media, year).
5) Add safety: redact session cookie from outputs/logs.
