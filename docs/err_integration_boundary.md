# ERR integration boundary

ERR/xref is the owner of referential identity and subject-map semantics. It is
not a download, availability, transfer, or ownership tracker. IWantIt does not
read ERR internals or treat its event log as acquisition state.

For curated music acquisition, IWantIt accepts the ERR-owned
`err.subject/1.0` envelope at its process boundary and requires an
authority-qualified exact `music.recording`. The envelope is embedded from the
owner schema, separately validated, and preserved verbatim throughout preview,
refusal, dispatch, replay, cancellation, and result fixtures. Search hints do
not alter the subject. Original, remix, edit, dub, live, remaster, reissue, and
bootleg versions remain distinct exact ERR subjects and are never merged by
title/artist similarity.

Responsibilities remain explicit:

- IWantIt's acquisition journal owns requested, previewed, selected,
  dispatched, cancelled, uncertain, and completed workflow state.
- Private indexers and download clients own observations and transfer state.
- A successful IWantIt result contains only a minimized opaque provider
  receipt and declares `pending_err_verification` with
  `ownership_update_allowed=false`.
- ERR owns the subsequent exact artifact-to-subject verification.
- MetaMusic owns manifestation/library state and may mark an item owned only
  after that verification succeeds.
- Neither a subject envelope nor an acquisition handoff proves possession.

Canonical IWantIt schemas and consumer fixtures are published under
`schemas/curated-acquisition/v2/` and
`fixtures/curated-acquisition/v2/`. The checked-in
`err-subject-owner.schema.json` is a consumer snapshot; ERR remains its owner.
The fixture verifier proves envelope preservation and the verification-required
gate:

```bash
python3 scripts/verify_curated_acquisition_fixtures.py
```

Live `err.subject-map-batch/1.0` lookup and artifact verification are external
capabilities. Until a live consumer is available, IWantIt reports
`pending_err_verification` and never simulates ownership success.

The books boundary remains unchanged: ERR currently has no reviewed books
domain pack or possession lifecycle. `library_catalogs` providers own current
ebook/audiobook possession evidence. A future books integration must use ERR's
public API, fail conservatively, retain the local identifier/title-author
fallback unless explicitly required, and never infer ownership from identity.
