# Acquisition contract

`iwantit acquire --stdin` uses `iwantit.acquisition-intent/2` and returns
`iwantit.acquisition-result/2` for curated-source integrations. The canonical
machine-readable schemas are under `schemas/curated-acquisition/v2/`.
`iwantit acquire --capabilities` publishes supported versions, limits,
configured providers, pairing health, replay, and cancellation behavior
without disclosing credentials.

The older `iwantit.acquisition-intent/1` and result/candidate v1 shapes remain
available only for existing local consumers. They do not satisfy the
MetaMusic/ERR curated-source boundary. The CLI `--confirm` switch is v1-only
and cannot approve a v2 item.

## Identity and caller boundary

Every v2 item carries the ERR-owned `err.subject/1.0` envelope. IWantIt accepts
only an authority-qualified, exact `music.recording` subject with portable
identity references. It preserves that subject verbatim in preview, refusal,
dispatch, replay, cancellation, and downstream verification output. Artist,
title, release, version, and year are search hints—not identity evidence—and
cannot merge an original, remix, edit, dub, live recording, remaster, reissue,
or bootleg.

The supported transport is local stdio. Each request names the MetaMusic
installation, workspace, actor, and pairing revision, while the corresponding
pairing is allowlisted in local IWantIt configuration. No bearer credential is
placed in the intent. Only `caller.origin.kind=explicit_user_acquisition` is
valid. Source ingestion, recommendation ranking, automatic promotion, and
unpaired callers fail before provider execution.

## Explicit lifecycle

The lifecycle is item-scoped and fail-closed:

1. `action=preview` performs read-only search and returns a stable
   `preview_result_id` plus bounded candidate projections.
2. The user chooses a candidate by its content-derived `candidate_ref`.
3. A separate confirmation binds its own ID and timestamp to the same preview
   and candidate.
4. `action=dispatch` succeeds only if the retained preview, choice, and
   confirmation all match.
5. A successful provider handoff returns the unchanged exact subject, an
   opaque receipt, and
   `verification.status=pending_err_verification` with
   `ownership_update_allowed=false`.
6. MetaMusic may update owned state only after its separate ERR artifact
   verification succeeds.

Preview, refusal, and cancellation have `side_effects_allowed=false`. A batch
may be `partial`: an invalid item receives a typed item error while valid items
remain available. Unknown contract majors and unsupported providers return
typed refusals.

Stable intent/item identifiers and idempotency keys bind the caller, exact
subject, constraints, retained choice, and confirmation. Completed dispatches
replay the byte-equivalent sanitized result without another provider action.
Conflicting reuse fails closed. Only a failure explicitly attested as
`retryable=true` and `side_effects_possible=false` may be retried. An exception,
expired dispatch lease, or provider response without that attestation becomes
non-retryable `DISPATCH_OUTCOME_UNCERTAIN` and requires provider
reconciliation. Pre-dispatch cancellation is durable; provider-side
post-dispatch cancellation is reported as unsupported.

## Candidate and privacy projection

Private provider responses are never returned verbatim. Each choice uses the
closed `iwantit.acquisition-candidate/2` shape containing only:

- a stable candidate reference, position, bounded display title, and source
  label;
- normalized release and edition fields;
- bounded availability observations; and
- bounded numeric ranking with non-payload reason labels.

`source_url` is always `null` in v2. Download URLs, raw search bodies, comments,
excerpts, handles, usernames, cookies, credentials, provider response bodies,
and dispatch coordinates are excluded. Dispatch references are one-way hashes
of the local provider receipt, never raw provider IDs.

Private source evidence keys are not accepted in an item. Refusals do not echo
their values and occur before journal persistence. Result schemas close nested
candidate, receipt, error, capability, and verification objects and enforce a
two-MiB result bound.

Provider data remains `local_private` with sanitized local persistence only:
community publication, remote inference, raw provider export, and use as ERR
ownership or identity evidence are forbidden. The process-wide
`IWANTIT_PRIVATE_ACQUISITION_DISABLED=1` kill switch still disables private
search and dispatch.

## Consumer fixtures and verification

The versioned corpus under `fixtures/curated-acquisition/v2/` is canonical for
MetaMusic and ERR consumers. It includes capabilities, preview, explicit
dispatch, replay, cancellation, partial errors, safe retry, uncertain outcome,
pairing, origin, provider, version, and private-evidence cases.

```bash
python3 scripts/verify_curated_acquisition_fixtures.py
python3 scripts/dogfood_curated_acquisition.py --output-dir <evidence-directory>
```

The verifier regenerates the JSON byte-for-byte, validates the owner schemas,
and enforces replay, exact-subject, bounded-output, ERR-verification, and
private-data invariants. The dogfood command runs the real stdio CLI in
separate processes against loopback provider boundaries and writes only a
sanitized evidence summary.
