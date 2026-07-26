# Curated Source Acquisition Integration Plan

Program: `PROP-0001-curated-music-source-aggregation`

IWantIt scope: G0/G1, I0-I4, X6, the IWantIt privacy boundary in X7, and the
IWantIt portions of the Program Completion Gate.

Last updated: 2026-07-26 UTC

## Completion truth

IWantIt work is complete only when every locally executable requirement is
implemented, tested, exercised through an offline functional scenario,
documented, committed, and pushed. An external dependency is complete only as
an honest capability boundary when the blocker is outside this repository, the
contract exposes it, a supported fallback remains usable, setup or approval is
documented, and no mock success is claimed.

The central proposal dossier and coordination log are owned by the Sensemaker
task. This repository records dependency and unblock information here and in
Beads; it does not edit the central dossier.

## Protected pre-existing state

Baseline commit and branch:

- Branch: `master`
- HEAD: `bc63c39f84cb3c02b005bdb1fdd1926b71a72919`
- Upstream: `origin/master`
- Pre-existing modified file: `README.md`
- Pre-existing untracked paths: `.agent/`, `uv.lock`

Those paths are user-owned and excluded from this program's feature commits.
No stash, reset, cleanup, formatter, or bulk staging operation may absorb or
discard them.

## Baseline

Recorded 2026-07-26 UTC:

- Beads directory: `.beads`
- `bd` executable: `/home/ubuntu/.local/bin/bd`
- `bd --version`: `br 0.2.16`
- `bd onboard`: unavailable; the installed compatibility command reports
  `unrecognized subcommand 'onboard'`
- `bd ready --json`: no pre-existing ready issues
- New epic: `iwantit-ztl`
- New work items: `iwantit-ztl.1` through `iwantit-ztl.5`
- Python command named `python`: unavailable
- Python fallback: `python3 3.13.7`
- Unit baseline: `python3 -m unittest discover -s tests` -> 73 passed
- Functional baseline: `python3 scripts/functional_test.py --verbose` ->
  `Functional tests passed.`
- Compile baseline: `python3 -m compileall -q iwantit scripts tests` -> passed
- Existing contract versions:
  `iwantit.acquisition-intent/1`, `iwantit.acquisition-result/1`, and
  `iwantit.acquisition-candidate/1`
- Existing journal: local SQLite dispatch idempotency, opt-in by configuration
- Relevant services checked with `systemctl`: `iwantit-goodreads.timer`,
  `iwantit-goodreads.service`, and `prowlarr` were inactive; the IWantIt units
  were not installed on this host

Baseline classification:

- The test suite and offline functional harness pass.
- The missing `python` alias and unsupported `bd onboard` command are local
  tool capability differences, not product failures; equivalent supported
  commands are recorded above.
- No live provider, MetaMusic, or ERR service is required for the offline
  release gate. Live side effects remain prohibited during dogfood.

## Contract ownership and compatibility

IWantIt owns:

- acquisition intent, result, candidate, capability, and typed error schemas;
- bounded batch size and payload size;
- preview, explicit choice, confirmation, dispatch, cancellation, retry, and
  idempotent replay semantics;
- minimized acquisition and dispatch result fixtures.

ERR owns authority-qualified subject and subject-map semantics. IWantIt accepts
the versioned authority-qualified exact subject envelope at its process
boundary and treats title/artist fields only as search hints, never identity.

MetaMusic owns manifestation/library state and must verify a returned artifact
against the exact ERR subject before changing owned state. IWantIt returns a
verification-required receipt and never claims that ownership has changed.

Compatibility rules:

- additive changes within a supported major version must remain optional;
- unknown major versions fail closed;
- request and response schemas use closed objects at privacy-sensitive
  boundaries;
- limits and supported versions are published without secrets;
- batch failures are item-scoped so valid items are retained;
- replay keys bind the exact subject, constraints, choice, and confirmation.

## Invariants

- Source ingestion or recommendation ranking can never dispatch acquisition.
- A dispatch requires a prior preview, an explicit candidate choice, and a
  separate explicit confirmation bound to that preview and choice.
- Recording/version subjects are exact and authority-qualified. A bare local
  ERR/xref ID is rejected.
- Original, remix, edit, dub, live, remaster, reissue, and bootleg identities
  are never merged from title/artist text.
- Private source comments, excerpts, handles, URLs, cookies, and credentials
  are not valid acquisition fields and never appear in results, logs, exports,
  fixtures, error evidence, idempotency fingerprints, or ERR verification
  evidence.
- Completed dispatch replay never invokes a provider twice.
- Cancellation is honest: pre-dispatch cancellation prevents dispatch;
  provider-side cancellation is reported unsupported unless an adapter can
  attest it.
- Refusal and unconfirmed actions have no side effects.
- Results contain only the minimum data needed for choice, dispatch receipt,
  and downstream exact-subject verification.

## Work status

| Program task | Beads | Status | Exit evidence |
|---|---|---|---|
| I0 baseline, Beads, plan | `iwantit-ztl.1` | Complete | `d90f0c19ac2a91491d2935a3bb7eb06fdcb5b502` |
| I1 contract hardening | `iwantit-ztl.2` | Complete | `5d07a55af4415552ecd8f61bc7cc4fb9837fad9f`; 55 scoped and 99 full tests |
| I2 MetaMusic/ERR fixtures | `iwantit-ztl.3` | In progress | Canonical positive/negative fixtures and consumer conformance pending |
| I3 comment-ranking retirement | `iwantit-ztl.4` | Complete | `96ed44581efc0448bdbdf42a57e50f3a13452418`; 3 policy tests |
| I4 release gate | `iwantit-ztl.5` | Pending | Full gates, evidence, Beads close, sync/rebase/push |
| X6 explicit acquisition | `iwantit-ztl.2/.3/.5` | In progress | Lifecycle implemented; canonical fixtures and retained dogfood pending |
| X7 IWantIt privacy boundary | `iwantit-ztl.2/.3/.5` | In progress | Contract/journal negative tests pass; fixture and dogfood evidence pending |

## Planned implementation slices

1. Baseline and ledger
   - Create Beads hierarchy and this living plan.
   - Freeze protected dirty paths and baseline evidence.
2. Contract kernel
   - Add authority-qualified exact subjects, bounded batches, typed item
     errors, capabilities, trusted local pairing metadata, and unknown-version
     refusal.
   - Keep the v1 interface available for existing local consumers while
     publishing a new major version for curated-source integrations.
3. Lifecycle journal
   - Persist sanitized previews.
   - Bind dispatch to preview result and candidate reference.
   - Guarantee idempotent replay and conflict refusal.
   - Add pre-dispatch cancel and honest post-dispatch cancellation state.
4. Canonical fixtures and conformance
   - Publish schemas plus positive, negative, refusal, replay, cancellation,
     partial-error, and privacy fixtures.
   - Validate every fixture and run consumer-style offline dogfood.
5. Semantics and release
   - Supersede comment-as-endorsement and large-boost guidance.
   - Run scoped and full gates, update this ledger with exact evidence, close
     Beads accurately, sync, rebase, push, and verify upstream state.

## Decisions and rationale

### 2026-07-26 — Preserve v1 and introduce a hardened major version

The existing v1 contract is already consumed by local workflows and models an
unqualified `recording.ref`. Silently changing that field would misrepresent a
breaking identity rule as backward compatible. The curated-source boundary
therefore gets a new major contract while v1 remains a documented legacy local
surface. Curated-source and MetaMusic fixtures use only the hardened version.

### 2026-07-26 — Local stdio is the only supported integration transport

IWantIt currently exposes a CLI/stdin boundary, not a network service. Pairing
is therefore an allowlisted installation mapping plus the host process/OS
boundary; no bearer credential is placed in acquisition JSON. Network
transport authentication is explicitly unsupported rather than simulated.

### 2026-07-26 — Candidate choice must bind to a retained preview

Re-running search and selecting a numeric index can dispatch a different
result after provider reordering. A confirmed dispatch must bind a stable
candidate reference to a retained sanitized preview result. Numeric position
may remain display metadata but is not dispatch authority.

### 2026-07-26 — Treat unattested dispatch outcomes as uncertain

A process can fail after a provider accepts a request but before IWantIt
durably records the response. Automatically reclaiming an expired dispatch
lease could enqueue a duplicate. Curated v2 therefore replays completed
results, retries only failures explicitly attested as side-effect-free, and
converts expired or exception-interrupted dispatches to a non-retryable
`DISPATCH_OUTCOME_UNCERTAIN` state requiring provider reconciliation.

### 2026-07-26 — Close every privacy-sensitive result object

The v2 result schema closes candidate metadata, dispatch receipts, capabilities,
and nested identity handoffs. MetaMusic receives no provider URL or raw
provider reference: candidate URLs are always `null` and provider references
are one-way opaque hashes. Results enforce a published byte bound and retain
valid item results when another item is refused.

### 2026-07-26 — Use the canonical ERR subject owner schema

IWantIt embeds and separately validates ERR's
`schemas/subject-envelope.schema.json` from ERR commit
`30698f89dcbba442501da9e4aec3d374bac195d7`. The exact subject remains
`music.recording` with `exactness=exact`; original/remix/edit/live/remaster
granularity is carried by distinct exact ERR subjects, not a title/artist
comparison in IWantIt.

### 2026-07-26 — Preserve stale Git hooks and use scoped overrides

Repository-local Git hooks are legacy `bd-shim` scripts that call the removed
`bd hooks` command. The installed `bd` is `br 0.2.16`; `bd onboard` and
`bd hooks` are unavailable. Commits and the final push use a one-command
`core.hooksPath=/dev/null` override only after manual Beads and project gates,
leaving user-owned `.git/hooks` unchanged. `bd doctor` also reports
pre-existing legacy JSONL IDs that its newer validator rejects; issue database
commands remain functional, so this program does not rewrite unrelated issue
history.

## Dependencies and unblock messages

- ERR / E1-E2: publish the canonical authority-qualified subject and
  `err.subject-map-batch/1` fixtures. Until then IWantIt can validate its
  authority-qualified exact input envelope and preserve it verbatim, but it
  cannot claim live cross-authority mapping or artifact identity verification.
- MetaMusic / M6: consume the IWantIt canonical intent/result fixtures, invoke
  preview then explicit choice/confirmation, and gate owned-state changes on
  ERR verification. Until a consumer build is available, IWantIt uses an
  offline consumer conformance harness and reports live integration as
  externally blocked.
- Sensemaker: never call IWantIt from capture, ingestion, ranking, or automatic
  promotion. Only MetaMusic's separate explicit acquisition UI may form an
  acquisition intent.
- Central coordination log: Sensemaker is the sole editor. The Sensemaker task
  should copy the dependency statements above when it records the next
  cross-project checkpoint.

## Evidence ledger

Entries are appended after each accepted slice. Retained evidence paths must
contain only sanitized/offline data.

### Baseline / I0

- Tasks: G0, I0
- Decision: preserve existing dirty state; use `python3` and the installed
  Beads-compatible command set
- Files changed: `.beads/issues.jsonl`,
  `docs/curated-source-integration-plan.md`
- Commit: `d90f0c19ac2a91491d2935a3bb7eb06fdcb5b502`
- Scoped verification:
  - `python3 -m unittest discover -s tests` -> 73 passed
  - `python3 scripts/functional_test.py --verbose` -> passed
  - `python3 -m compileall -q iwantit scripts tests` -> passed
  - `git diff --check` -> passed before feature edits
- Dogfood: existing offline stubbed-provider functional harness passed
- Lesson: `bd onboard` and `python` are unavailable in this environment; the
  remaining required Beads commands and `python3` work
- Dependency: canonical ERR subject-map fixtures and MetaMusic M6 consumer are
  external to this repository
- Remaining: all implementation slices after I0

### Comment-ranking retirement / I3

- Tasks: I3
- Decision: private comments are never fetched or ranked in IWantIt;
  compatibility steps are network-free policy no-ops
- Files changed: `docs/redacted_comment_sourcing_plan.md`,
  `iwantit/step_metadata.py`, `iwantit/steps/builtin.py`,
  `tests/test_comment_ranking_policy.py`
- Commit: `96ed44581efc0448bdbdf42a57e50f3a13452418`
- Scoped verification:
  - `python3 -m unittest tests.test_comment_ranking_policy` -> 3 passed
- Dogfood: compatibility calls produce only `CURATION_BOUNDARY` and
  `COMMENT_RANKING_DISABLED` without network requests or score changes
- Lesson: a mention is not endorsement, preference, identity proof, or
  acquisition intent
- Dependency: any private source observation/stance work remains
  Sensemaker-owned
- Remaining: no locally executable I3 work

### Explicit lifecycle / I1

- Tasks: G0.2, G1.1-G1.3, I1, X6 lifecycle, X7 IWantIt contract/journal
  boundary
- Decision: introduce closed v2 contracts while preserving local v1; bind
  dispatch to an exact retained candidate; fail uncertain rather than risking
  duplicate queue operations
- Files changed: `iwantit/acquisition.py`,
  `iwantit/acquisition_candidate.py`, `iwantit/cli.py`,
  `iwantit/curated_acquisition.py`,
  `iwantit/curated_acquisition_journal.py`,
  `iwantit/curated_acquisition_schema.py`, `iwantit/steps/builtin.py`,
  `tests/test_acquisition.py`, `tests/test_curated_acquisition.py`
- Commit: `5d07a55af4415552ecd8f61bc7cc4fb9837fad9f`
- Scoped verification:
  - `python3 -W error::ResourceWarning -m unittest
    tests.test_curated_acquisition tests.test_acquisition
    tests.test_acquisition_journal tests.test_private_adapters
    tests.test_comment_ranking_policy` -> 55 passed
- Full phase verification:
  - `python3 -W error::ResourceWarning -m unittest discover -s tests` ->
    99 passed
  - `python3 scripts/functional_test.py --verbose` -> passed
  - `python3 -m compileall -q iwantit scripts tests` -> passed
  - `git diff --check` -> passed
- Dogfood: deterministic service-level preview/refusal/dispatch/replay/cancel
  scenarios pass; retained CLI/consumer dogfood is the next I2 slice
- Security evidence: provider URLs are absent from v2 candidates, dispatch
  references are opaque hashes, forbidden source evidence never enters the
  SQLite journal, and exception sentinels are absent from results
- Lessons:
  - green legacy tests did not prove closed nested result contracts;
  - expired dispatch leases are an uncertainty boundary, not automatic retry
    authority;
  - CLI exit status must treat `refused` and `partial` as failures
- Dependency:
  - ERR subject envelopes are available at ERR commit `30698f8`; live
    `err.subject-map-batch/1.0` artifact verification remains external
  - MetaMusic M6 must consume the forthcoming I2 fixtures and keep ownership
    false until ERR verification
- Remaining: I2 fixtures/dogfood/documentation and the I4 release/push gate
