# Ideal State — Curated Source Acquisition Boundary

Program: `PROP-0001-curated-music-source-aggregation`

Scope: IWantIt-owned G0/G1, I0–I4, X6, the IWantIt boundary in X7, and the
IWantIt portions of the Program Completion Gate.

The central proposal dossier and coordination log remain Sensemaker-owned.
IWantIt records its dependencies in Beads and
`docs/curated-source-integration-plan.md`.

## Ideal State Criteria

### ISC-IW-01 — Protected baseline

All pre-existing user-owned dirty paths are identified and absent from every
program feature commit.

Probe:

```bash
git status --short
git show --name-only --format= <program-commit>
```

Pass evidence must show that `README.md`, `.agent/`, and `uv.lock` remain
user-owned and were not absorbed into program commits.

### ISC-IW-02 — Authority-qualified exact identity

The curated acquisition contract accepts the canonical ERR owner fixture for
an authority-qualified exact `music.recording` subject and refuses bare,
structurally invalid, unsupported-schema, non-exact, non-recording, and
non-portable subjects item-by-item. Authority freshness, trust, and
cross-authority mapping remain ERR-owned; IWantIt does not invent an authority
allowlist or claim to verify staleness.

Probe:

```bash
python3 -m unittest tests.test_curated_acquisition
python3 scripts/verify_curated_acquisition_fixtures.py
```

### ISC-IW-03 — Explicit acquisition state machine

Preview has no side effects; dispatch requires a retained preview, a stable
candidate choice, and a separate explicit confirmation bound to both; source
ingestion and unpaired callers fail before provider execution.

Probe:

```bash
python3 -m unittest tests.test_curated_acquisition
python3 scripts/dogfood_curated_acquisition.py --output-dir <temporary-directory>
```

### ISC-IW-04 — Replay, retry, and cancellation

Stable intent/result/item IDs and idempotency keys survive process restart;
completed dispatch replays without another provider call; conflicting reuse
fails closed; only failures attested as side-effect-free are retryable;
unattested or abandoned dispatches require reconciliation; pre-dispatch
cancellation prevents dispatch; post-dispatch cancellation is reported
honestly as unsupported.

Probe:

```bash
python3 -m unittest tests.test_curated_acquisition tests.test_acquisition_journal
python3 scripts/dogfood_curated_acquisition.py --output-dir <temporary-directory>
```

### ISC-IW-05 — Bounded partial batch contract

Capabilities publish supported versions and limits without secrets; unknown
major versions fail closed; bounded batches retain valid item results when
other items fail with typed, item-scoped errors.

Probe:

```bash
python3 -m unittest tests.test_curated_acquisition
python3 scripts/verify_curated_acquisition_fixtures.py
```

### ISC-IW-06 — Private evidence exclusion

Private source comments, excerpts, handles, source URLs, cookies, credentials,
provider payloads, and restricted dispatch coordinates are rejected or
minimized out of intent/result schemas, logs, fixture evidence, journal state,
exports, and ERR verification evidence. Refusals do not echo secret values.

Probe:

```bash
python3 -m unittest tests.test_curated_acquisition tests.test_acquisition \
  tests.test_acquisition_journal tests.test_private_adapters \
  tests.test_comment_ranking_policy
python3 scripts/verify_curated_acquisition_fixtures.py
rg -n -i 'secret-curator|private-comment|cookie-value|bearer-value' \
  fixtures docs tests scripts iwantit
```

Any retained test sentinel must appear only in test input construction and
must not appear in generated dogfood or conformance evidence.

### ISC-IW-07 — Minimized ownership handoff

A successful dispatch returns only a sanitized opaque provider receipt, the
unchanged exact ERR subject, and an explicit
`pending_err_verification`/`ownership_update_allowed=false` gate. IWantIt
never claims ownership changed.

Probe:

```bash
python3 -m unittest tests.test_curated_acquisition
python3 scripts/verify_curated_acquisition_fixtures.py
```

### ISC-IW-08 — Canonical consumer fixtures

IWantIt publishes versioned schemas and positive and negative fixtures for
MetaMusic and ERR consumers covering capabilities, preview, refusal,
confirmation, dispatch, replay, cancellation, partial item errors, authority
qualification/structural errors, and private-evidence rejection. A repository
verifier validates every fixture against the owner schema and scenario
invariants.

Probe:

```bash
python3 scripts/verify_curated_acquisition_fixtures.py
```

### ISC-IW-09 — Comment-ranking assumptions retired

Private comments are not fetched or ranked in IWantIt, compatibility steps are
network-free fail-safe no-ops, and documentation assigns capture/stance/ranking
to Sensemaker without treating mention as endorsement.

Probe:

```bash
python3 -m unittest tests.test_comment_ranking_policy
```

### ISC-IW-10 — Offline X6/X7 dogfood

An offline functional run proves preview, safe refusal, confirmed dispatch
exactly once, replay, cancellation, retry, partial batch handling, ERR
verification-required state, and secret/private-evidence non-leakage. Evidence
is retained in a tracked sanitized artifact or recorded by deterministic
command and digest in the local plan.

Probe:

```bash
python3 scripts/dogfood_curated_acquisition.py --output-dir <temporary-directory>
```

### ISC-IW-11 — Full project gates

All unit tests, the existing functional harness, compilation, fixture
verification, offline dogfood, and whitespace checks pass after the final code
state.

Probe:

```bash
python3 -m unittest discover -s tests
python3 scripts/functional_test.py --verbose
python3 -m compileall -q iwantit scripts tests
python3 scripts/verify_curated_acquisition_fixtures.py
python3 scripts/dogfood_curated_acquisition.py --output-dir <temporary-directory>
git diff --check
```

### ISC-IW-12 — Ledgers, commits, and push

Beads and the local integration plan contain current statuses, rationale,
decisions, lessons, exact commits, exact tests, dogfood evidence, dependencies,
and honest blockers. Program changes are granular commits. The mandatory
pull/rebase, `bd sync`, push, remote prune, and clean/up-to-date verification
succeed, leaving only known user-owned dirty paths.

Probe:

```bash
bd show iwantit-ztl --json
bd sync
git log --oneline origin/master..HEAD
git status --short --branch
git rev-list --left-right --count origin/master...HEAD
git stash list
```

## Completion Rule

The Goal is complete only when every ISC above has direct passing evidence and
no locally executable program work remains. ERR/MetaMusic live integration may
remain external only if the canonical fixtures and offline fallback pass, the
capability state is honest, and Beads plus the local plan name the exact
dependency without claiming live success.

## Verification Evidence

Evidence run: 2026-07-26 UTC, completion-gate remediation.

Evidence applies to the corrected worktree after the LifeOS stop hook found
that prior passing results were recorded only in
`docs/curated-source-integration-plan.md`, not under the ISCs themselves.
Commands below were rerun rather than copied from the earlier release.

### ISC-IW-01 — PASS: protected baseline

- `git diff --name-only
  bc63c39f84cb3c02b005bdb1fdd1926b71a72919..08053d8bb8e91df4d4e63b2307a0215c9887d722
  | rg '^(README\.md|\.agent(?:/|$)|uv\.lock)$'` -> no output.
- `git status --short` identified `README.md`, `.agent/`, and `uv.lock` as the
  same protected user-owned paths. The additional paths were only the scoped
  completion-remediation files.
- Every remediation stage uses explicit paths. No protected path is staged,
  stashed, reset, replaced, or included in a program commit.
- Final committed-range and remote probes are repeated in ISC-IW-12 before
  completion.

### ISC-IW-02 — PASS: authority-qualified exact identity

- `python3 -W error::ResourceWarning -m unittest -v
  tests.test_curated_acquisition` -> 22 passed.
- Direct named evidence includes
  `test_subject_boundary_returns_typed_minimized_refusals`,
  `test_invalid_subject_is_item_scoped_and_valid_item_survives`, and
  `test_unknown_major_version_returns_typed_refusal`.
- Those tests exercised bare subject strings, malformed authority envelopes,
  unsupported subject schema versions, non-exact subjects, non-recording
  subjects, non-portable references, and unsupported acquisition majors. All
  returned schema-valid typed refusals and made zero provider calls.
- `python3 scripts/verify_curated_acquisition_fixtures.py` -> status `ok`,
  5 schemas, 51 fixtures, 23 scenarios, and 4 replay pairs.
- `cmp schemas/curated-acquisition/v2/err-subject-owner.schema.json
  /data/projects/ERR/schemas/subject-envelope.schema.json` -> identical.
- Authority freshness/trust remains an explicit ERR capability boundary, not a
  deferred IWantIt claim.

### ISC-IW-03 — PASS: explicit acquisition state machine

- The 22-test lifecycle probe passed, including preview-without-dispatch,
  stable candidate-reference selection, missing preview/confirmation refusal,
  and ingestion/unpaired refusal before provider execution.
- `python3 scripts/dogfood_curated_acquisition.py --output-dir
  <temporary-directory>` -> `status=passed`.
- Dogfood used separate real CLI processes and verified preview,
  unconfirmed refusal, item-bound confirmation, exact dispatch, and completed
  replay against loopback Jackett/download-client boundaries.

### ISC-IW-04 — PASS: replay, retry, and cancellation

- `python3 -W error::ResourceWarning -m unittest
  tests.test_curated_acquisition tests.test_acquisition_journal` -> 26 passed.
- Named lifecycle coverage passed for cross-instance replay, conflicting
  reuse, side-effect-free retry, expired-lease reconciliation, unattested
  uncertainty, pre-dispatch cancellation/replay, and honest post-dispatch
  cancellation refusal.
- Dogfood proved exactly one successful provider handoff, zero handoffs for
  completed replay/cancellation, one retained uncertain attempt without retry,
  and a safe-failure retry followed by replay without another runner call.

### ISC-IW-05 — PASS: bounded partial batch contract

- The 22-test lifecycle probe passed capability/limit, duplicate-ID,
  unsupported-provider, byte-bound, unknown-major, and valid-item-survives
  partial-batch cases.
- The fixture verifier passed all 51 artifacts/23 scenarios against the closed
  schemas and the 2,097,152-byte published result limit.
- The actual CLI dogfood returned `partial` while preserving the valid exact
  item after refusing a non-exact neighbor.

### ISC-IW-06 — PASS: private evidence exclusion

- `python3 -W error::ResourceWarning -m unittest
  tests.test_curated_acquisition tests.test_acquisition
  tests.test_acquisition_journal tests.test_private_adapters
  tests.test_comment_ranking_policy` -> 56 passed.
- The declared broad `rg` probe found synthetic sentinels only in test-input
  construction/assertions and verifier source:
  `scripts/_curated_acquisition_fixture_support.py`,
  `scripts/verify_curated_acquisition_fixtures.py`, and
  `tests/test_curated_acquisition.py`.
- A stricter scan for all dogfood secrets, private handles/provider URLs,
  fixture receipts, `bearer-value`, and `download_url` across
  `docs/evidence/curated-acquisition` and every generated `*.result.json`
  returned no matches.
- Dogfood itself inspected its SQLite journal, state/cache files, and all CLI
  outputs before emitting evidence; all private-value/provider-URL absence
  assertions passed.

### ISC-IW-07 — PASS: minimized ownership handoff

- The lifecycle probe passed exact subject preservation, one-way hashed
  dispatch receipt, and result-schema closure.
- Fixture verification passed every dispatched output with unchanged subject,
  `verification.required=true`,
  `status=pending_err_verification`, and
  `ownership_update_allowed=false`.
- Dogfood independently observed the same state after a real CLI/provider
  handoff. No ownership-success claim exists in IWantIt.

### ISC-IW-08 — PASS: canonical consumer fixtures

- `python3 scripts/verify_curated_acquisition_fixtures.py` regenerated the
  corpus in a temporary directory, byte-compared it to the committed JSON, and
  returned 5 schemas, 51 fixtures, 23 scenarios, 4 replay pairs, status `ok`.
- Positive and negative scenarios cover capabilities, preview, confirmation,
  dispatch, completed replay, cancel/replay, partial items, bare/malformed/
  unsupported/non-recording/non-portable subjects, pairing, origin, provider,
  private evidence, safe retry, and uncertain replay.

### ISC-IW-09 — PASS: comment-ranking assumptions retired

- `python3 -W error::ResourceWarning -m unittest
  tests.test_comment_ranking_policy` -> 3 passed.
- The tests prove the compatibility steps are network-free no-ops, emit the
  policy warnings, and do not change candidate scores.

### ISC-IW-10 — PASS: offline X6/X7 dogfood

- `python3 scripts/dogfood_curated_acquisition.py --output-dir
  <temporary-directory>` -> passed.
- Result digest:
  `sha256:a21d885f9eb98bbb233aea8ab8760633744995528504f571c66968ad221b1bde`.
- `cmp docs/evidence/curated-acquisition/curated-acquisition-dogfood.json
  <temporary-directory>/curated-acquisition-dogfood.json` -> identical.
- Retained evidence:
  `docs/evidence/curated-acquisition/curated-acquisition-dogfood.json`.

### ISC-IW-11 — PASS: full project gates

- `python3 -W error::ResourceWarning -m unittest discover -s tests` ->
  101 passed.
- `python3 scripts/functional_test.py --verbose` ->
  `Functional tests passed.`
- `python3 -m compileall -q iwantit scripts tests` -> passed.
- `python3 scripts/verify_curated_acquisition_fixtures.py` -> 5 schemas,
  51 fixtures, 23 scenarios, 4 replay pairs, status `ok`.
- Fresh dogfood plus retained-evidence `cmp` -> passed.
- `git diff --check` -> passed.

### ISC-IW-12 — EXPLICITLY DEFERRED: remediation landing

- Prior release evidence at
  `08053d8bb8e91df4d4e63b2307a0215c9887d722` passed `bd sync`, push,
  remote prune/fetch, zero ahead/behind, zero unpushed commits, zero stashes,
  and protected-path preservation.
- The LifeOS hook requires this new per-criterion evidence and its
  subject-refusal regression to be committed and pushed. Claiming PASS before
  that landing would be circular and false.
- Deferral owner: this task. Impact: the Goal remains active and Beads I4/epic
  remain `in_progress`; no completion claim is permitted.
- Resolution probe: close Beads after all post-edit gates, commit only scoped
  files, clean-worktree pull/rebase without disturbing protected paths,
  `bd sync`, push, prune/fetch, verify local equals remote with `0 0`, verify
  no protected path in the full program range, then replace this deferral with
  direct PASS evidence and land that audit annotation.
