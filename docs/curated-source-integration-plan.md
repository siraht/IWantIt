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
| I0 baseline, Beads, plan | `iwantit-ztl.1` | In progress | Baseline above; initial plan commit pending |
| I1 contract hardening | `iwantit-ztl.2` | Pending | Scoped tests, schemas, lifecycle dogfood, commit |
| I2 MetaMusic/ERR fixtures | `iwantit-ztl.3` | Pending | Canonical positive/negative fixtures and consumer conformance |
| I3 comment-ranking retirement | `iwantit-ztl.4` | Pending | Supersession document and regression coverage |
| I4 release gate | `iwantit-ztl.5` | Pending | Full gates, evidence, Beads close, sync/rebase/push |
| X6 explicit acquisition | `iwantit-ztl.2/.3/.5` | Pending | Preview/refusal/confirm-once/replay/verification-required |
| X7 IWantIt privacy boundary | `iwantit-ztl.2/.3/.5` | Pending | Forbidden-field and secret-leak negative tests |

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
- Commit: pending
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
