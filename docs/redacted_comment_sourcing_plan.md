# Redacted Comment Sourcing Plan — Superseded

Status: superseded by the Curated Music Sources architecture on 2026-07-26.

The former design proposed fetching private Redacted release comments and
giving editions a large ranking boost when a catalog number, label, medium,
remaster title, or year appeared in those comments. That design is retired.
It confused a text mention with endorsement, lacked stance and quote/repost
context, created an unbounded ranking signal, and placed private curation
capture in the acquisition executor.

## Current decision

IWantIt does not fetch, persist, export, or rank from private comments.

- `redacted_comments` remains only as a compatibility step name and returns
  the `CURATION_BOUNDARY` policy warning without making a request.
- `apply_recommendations` remains only as a compatibility step name and
  returns `COMMENT_RANKING_DISABLED` without changing candidate scores.
- Neither step is present in the default workflow.
- Session cookies, comment bodies, excerpts, usernames, handles, source URLs,
  and cached HTML are invalid acquisition-contract data.

IWantIt may use provider metadata necessary to search for and present an
explicit acquisition candidate. It must not interpret comments, popularity,
mention volume, or private community activity as permission, preference,
identity proof, or acquisition intent.

## Ownership boundary

Sensemaker owns any future private current-tab capture, observation revision,
claim extraction, stance review, inbox state, and source-usefulness
evaluation. Such a feature must satisfy that project's actor scope, retention,
export, purge, backup-erasure, and connector-policy gates.

If a comment is captured there:

- the default stance is `unknown`;
- quoted or reposted text is distinct from the author's own stance;
- comment presence alone never makes a candidate eligible or positive;
- source usefulness can change only from attributable exposure and explicit
  outcomes with uncertainty and bounded contribution; and
- raw private evidence stays inside Sensemaker's privacy boundary.

Only after the user separately reviews an exact recording/version and invokes
MetaMusic's explicit acquisition action may MetaMusic form an IWantIt
acquisition intent. That intent contains the authority-qualified exact ERR
subject, acquisition constraints, preview choice, and confirmation. It never
contains the source comment or enough provenance to reconstruct it.

## Historical findings retained for context

The retired spike established:

- Redacted's JSON torrent-group response does not contain release comments.
- The HTML release page can contain comments but requires a privileged session
  cookie.
- A session cookie has broader account authority than an API key.
- Parsing nested quotes and pagination is insufficient to determine stance,
  independence, or personal relevance.
- Caching raw comments would expand the private-data retention and
  backup-erasure surface.

These findings are reasons not to implement the old plan in IWantIt. They are
not instructions to resume cookie-backed scraping.

## Reconsideration gate

This decision may be revisited only through a new architecture decision that:

1. keeps capture and ranking outside IWantIt;
2. demonstrates permitted site-specific access and deletion handling;
3. separates mention, stance, identity, exposure, outcome, and acquisition;
4. proves private evidence cannot cross into IWantIt, MetaMusic origins, ERR
   community evidence, logs, exports, remote inference, or restored backups;
5. uses a bounded, prospective, exposure-aware evaluation instead of a large
   heuristic boost; and
6. retains manual capture as an honest fallback.

Until then, the compatibility steps remain fail-safe no-ops.
