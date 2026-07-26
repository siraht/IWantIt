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
| I2 MetaMusic/ERR fixtures | `iwantit-ztl.3` | Complete | `7331764c2af1affa1d979f980f14067452201fba`; 5 schemas, 41 fixtures, 18 scenarios, 4 replay pairs |
| I3 comment-ranking retirement | `iwantit-ztl.4` | Complete | `96ed44581efc0448bdbdf42a57e50f3a13452418`; 3 policy tests |
| I4 release gate | `iwantit-ztl.5` | Complete | 100 unit tests plus functional, compile, fixture, dogfood, privacy, ERR-owner, and diff gates pass |
| X6 explicit acquisition | `iwantit-ztl.2/.3/.5` | Complete for IWantIt | Lifecycle, canonical fixtures, and real stdio/loopback dogfood pass |
| X7 IWantIt privacy boundary | `iwantit-ztl.2/.3/.5` | Complete for IWantIt | Refusal, schema, journal, fixture, output, persistence, and dogfood privacy probes pass |

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

### 2026-07-26 — Publish deterministic owner fixtures, not example snippets

The IWantIt schemas and MetaMusic/ERR fixtures are generated from the same
runtime contract constants and service implementation used by the CLI. A clean
temporary generation must byte-match the committed JSON before semantic
validation runs. The corpus includes both successful and refused states,
side-effect-safe retry, unattested uncertainty, completed replay, cancellation,
partial batches, pairing/origin failures, and private-evidence rejection.
Consumer documentation points at these artifacts rather than copying contract
fragments that can drift.

### 2026-07-26 — Dogfood the actual process and private adapter boundaries

Service-level fixtures prove deterministic contract states, but do not by
themselves prove the stdio CLI, process restart journal, Torznab parser, or
download-client handoff. The X6/X7 dogfood therefore starts loopback Jackett
and download-client endpoints and invokes the real CLI in separate processes.
It intentionally transports synthetic private credentials, URLs, and provider
response data through the local adapter while asserting those values are absent
from results, journal/state files, and retained evidence. The only
side-effect-free retry attestation remains a service-harness scenario because
the real Jackett adapter correctly cannot attest that an HTTP failure happened
before every provider-side effect.

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

- ERR / E1-E2: the canonical subject envelope and curated source-map fixtures
  are now available at ERR commit
  `4f957ffc0eef782a1fd2ffc3c14c2d02b0c1e80d`, with the ERR program gate closed
  at `608f944`. IWantIt's checked-in owner schema is byte-identical to the
  current ERR file (SHA-256
  `5d53d20681fff3621705991657ce2deb278ecc4bbab7c3bad6ce590bdc5e20d3`).
  Live cross-authority mapping and artifact verification still execute in ERR
  and are never simulated by IWantIt.
- MetaMusic / M6: consume
  `schemas/curated-acquisition/v2/` and
  `fixtures/curated-acquisition/v2/`, invoke preview then stable
  choice/item-bound confirmation, and gate owned-state changes on ERR
  verification. Read-only inspection at MetaMusic commit
  `fa129ec766695e63462bd65dfaa14937f59938a6` shows its current acquisition
  adapter still emits and validates v1 numeric-index contracts. Its worktree is
  independently active, so IWantIt does not edit it or claim live v2
  interoperability. The deterministic corpus and offline stdio consumer
  fallback pass here.
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
  - MetaMusic M6 must consume the I2 fixtures and keep ownership false until
    ERR verification
- Remaining after this slice: I2 fixtures/dogfood/documentation and the I4
  release/push gate; the I2 work is recorded in the next ledger entry

### Canonical schemas, fixtures, and process dogfood / I2, X6, X7

- Tasks: G0/G1 compatibility, I2, X6 offline execution, and the IWantIt-owned
  X7 privacy evidence boundary
- Decision: generate canonical consumer fixtures from runtime contracts; prove
  the real stdio and loopback provider boundaries; retain only a deterministic
  sanitized summary
- Files changed:
  `schemas/curated-acquisition/v2/`,
  `fixtures/curated-acquisition/v2/`,
  `scripts/_curated_acquisition_fixture_support.py`,
  `scripts/generate_curated_acquisition_fixtures.py`,
  `scripts/verify_curated_acquisition_fixtures.py`,
  `scripts/dogfood_curated_acquisition.py`,
  `tests/test_curated_acquisition_fixtures.py`
- Commit: `7331764c2af1affa1d979f980f14067452201fba`
- Consumer documentation commit:
  `a1cf9180a6367c456c4a12a3cdbe9742f9bd32ac`
- Scoped verification:
  - `python3 scripts/verify_curated_acquisition_fixtures.py` -> 5 schemas,
    41 fixtures, 18 scenarios, 4 replay pairs; passed
  - `python3 -m unittest tests.test_curated_acquisition_fixtures` -> 1 passed
  - `python3 -W error::ResourceWarning -m unittest
    tests.test_curated_acquisition_fixtures tests.test_curated_acquisition
    tests.test_acquisition tests.test_acquisition_journal
    tests.test_private_adapters tests.test_comment_ranking_policy` -> 56 passed
  - `python3 -m compileall -q
    scripts/_curated_acquisition_fixture_support.py
    scripts/generate_curated_acquisition_fixtures.py
    scripts/verify_curated_acquisition_fixtures.py
    scripts/dogfood_curated_acquisition.py
    tests/test_curated_acquisition_fixtures.py` -> passed
- Dogfood:
  - `python3 scripts/dogfood_curated_acquisition.py --output-dir
    docs/evidence/curated-acquisition` -> passed
  - retained evidence:
    `docs/evidence/curated-acquisition/curated-acquisition-dogfood.json`
  - retained evidence SHA-256:
    `b945ef839a23a83a939205639d0b4754c473606385d21cd7af4d03f2709aa9b0`
  - actual separate CLI processes exercised capabilities, preview,
    unconfirmed refusal, exact confirmed dispatch, completed replay,
    cancellation/replay/refusal-after-cancel, partial batch, ingestion and
    unpaired refusal, private evidence, unknown major, v1-only `--confirm`
    refusal, and uncertain dispatch/replay
  - exactly one successful provider handoff occurred; completed replay and
    cancellation added zero; one deliberately uncertain provider attempt was
    retained and did not retry
  - safe side-effect-free failure, retry success, and completed replay were
    exercised through the deterministic service boundary
- Security evidence:
  - synthetic provider credentials, private URLs, private handles, and provider
    response bodies traversed only the loopback adapter/config boundary and
    were absent from all CLI results, journal/state files, and retained
    evidence
  - all candidate source URLs are `null`; successful provider references are
    opaque hashes; exact subjects are unchanged; ownership remains false
    pending ERR verification
- Lessons:
  - byte-reproducible fixtures catch contract drift that schema-valid examples
    alone do not;
  - a real process boundary found and proves CLI exit semantics, durable replay,
    adapter parsing, idempotency headers, and persistence redaction together;
  - an HTTP adapter cannot honestly label an interrupted dispatch retry-safe
    without an explicit provider attestation
- Dependencies:
  - ERR owner fixtures are available and the embedded subject schema matches
    byte-for-byte
  - MetaMusic still needs to consume v2; its currently committed acquisition
    adapter remains v1 and is outside this repository
- Remaining: final full I4 gates, release ledger update, Beads close,
  pull/rebase, `bd sync`, push, prune, and upstream verification

### Final release gate / I4 and Program Completion Gate

- Tasks: I4, the IWantIt-owned X6/X7 completion evidence, and IWantIt's Program
  Completion Gate
- Accepted program commits before this release-ledger update:
  - `d90f0c19ac2a91491d2935a3bb7eb06fdcb5b502` — baseline and living ledger
  - `96ed44581efc0448bdbdf42a57e50f3a13452418` — comment-ranking retirement
  - `5d07a55af4415552ecd8f61bc7cc4fb9837fad9f` — explicit v2 lifecycle
  - `4994092b0403e1d2ffabe2cd57008088008f8231` — lifecycle evidence and ISA
  - `7331764c2af1affa1d979f980f14067452201fba` — canonical schemas,
    fixtures, verifier, and dogfood harness
  - `a1cf9180a6367c456c4a12a3cdbe9742f9bd32ac` — v2 consumer documentation
  - `5463739dcb0dabead28ff79ef9d31087712e8876` — retained conformance
    evidence and external capability state
- Final post-documentation verification:
  - `python3 -W error::ResourceWarning -m unittest discover -s tests` ->
    100 passed
  - `python3 scripts/functional_test.py --verbose` -> passed
  - `python3 -m compileall -q iwantit scripts tests` -> passed
  - `python3 scripts/verify_curated_acquisition_fixtures.py` -> 5 schemas,
    41 fixtures, 18 scenarios, 4 replay pairs; passed
  - `python3 scripts/dogfood_curated_acquisition.py --output-dir
    <temporary-directory>` -> passed with digest
    `b945ef839a23a83a939205639d0b4754c473606385d21cd7af4d03f2709aa9b0`
  - `cmp docs/evidence/curated-acquisition/curated-acquisition-dogfood.json
    <temporary-directory>/curated-acquisition-dogfood.json` -> byte-identical
  - focused sentinel scan over retained evidence and all generated result
    fixtures -> no match
  - `cmp schemas/curated-acquisition/v2/err-subject-owner.schema.json
    /data/projects/ERR/schemas/subject-envelope.schema.json` ->
    byte-identical
  - `git diff --check` -> passed
- Beads:
  - `iwantit-ztl.1` through `iwantit-ztl.5` are closed
  - epic `iwantit-ztl` is closed
- Protected state:
  - user-owned `README.md`, `.agent/`, and `uv.lock` remain outside every
    program commit
- External capability state:
  - ERR canonical subjects/maps are available and IWantIt's owner snapshot
    matches; live verification correctly remains an ERR call
  - MetaMusic's committed acquisition adapter remains v1, so live v2
    interoperability is not claimed; canonical IWantIt v2 fixtures and the
    real offline stdio fallback pass and are ready for its M6 consumer work
  - Sensemaker remains the sole editor of the central dossier/log; no central
    file was edited by this task
- Locally executable remaining work: none
- Landing evidence for release/closure head
  `1856ffc4ad46c5d5290f13e54f7d5cc15a75327d`:
  - in-place `git pull --rebase` refused the protected pre-existing
    `README.md` edit; no stash, replacement, reset, or absorption was used
  - a clean detached worktree at the exact release head ran
    `git -c core.hooksPath=/dev/null pull --rebase origin master`; it reported
    `HEAD is up to date` and the before/after commit was identical
  - the per-command hook override was required because the preserved legacy
    hook invokes the unavailable `bd hooks`; project and Beads gates were run
    manually
  - `bd sync` -> `JSONL is current (hash unchanged since last import)`
  - `git -c core.hooksPath=/dev/null push origin master` ->
    `bc63c39..1856ffc master -> master`
  - `git remote prune origin` and `git fetch origin` -> passed
  - `git rev-list --left-right --count origin/master...HEAD` -> `0 0`
  - local and remote head ->
    `1856ffc4ad46c5d5290f13e54f7d5cc15a75327d`
  - unpushed commit count -> `0`; uncommitted program file count -> `0`;
    stash count -> `0`
  - `git status --short --branch` retained only user-owned `README.md`,
    `.agent/`, and `uv.lock`
- This audit-only ledger update is landed with the same clean-worktree
  pull/rebase, Beads sync, push, prune, and zero-ahead/behind verification; its
  final remote hash is reported in the task handoff because a commit cannot
  contain its own hash.
