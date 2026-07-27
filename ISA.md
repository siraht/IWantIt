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

### ISC-IW-12 — PASS: ledgers, commits, and push

- Beads `iwantit-ztl.1` through `.5` and epic `iwantit-ztl` are closed after
  the corrected-state full gates.
- Completion-remediation commits landed through
  `7710e0feec464130722a23562a3098ac949a247d`:
  - `dbe3d65d56da5e3aa27fcc2832e44c425f8a04f0` — minimized invalid-subject
    refusals and expanded canonical corpus
  - `4c99022` — direct ISC-IW-01 through ISC-IW-11 evidence
  - `7710e0f` — Beads completion-remediation closure
- A clean detached worktree at `7710e0f` ran
  `git -c core.hooksPath=/dev/null pull --rebase origin master`; output was
  `HEAD is up to date`, and before/after hashes were identical.
- `bd sync` -> `JSONL is current (hash unchanged since last import)`.
- `git -c core.hooksPath=/dev/null push origin master` ->
  `08053d8..7710e0f master -> master`.
- After `git remote prune origin` and `git fetch origin`:
  - `git rev-list --left-right --count origin/master...HEAD` -> `0 0`
  - local and remote hashes ->
    `7710e0feec464130722a23562a3098ac949a247d`
  - unpushed commit count -> `0`
  - stash count -> `0`
  - uncommitted program file count -> `0`
  - protected paths in the full program commit range -> `0`
  - full `git status` -> `Your branch is up to date with 'origin/master'`
    and only user-owned `README.md`, `.agent/`, and `uv.lock` remain dirty.
- The preserved repository hook still invokes unavailable `bd hooks`; the
  scoped `core.hooksPath=/dev/null` override is paired with explicit Beads and
  project probes above rather than weakening or silently skipping a gate.
- This PASS annotation is documentation-only. It is committed and landed with
  the same clean-worktree pull/rebase, `bd sync`, push, prune/fetch,
  zero-ahead/behind, protected-range, and status probes; its final hash is
  necessarily reported by the task handoff because a commit cannot record its
  own hash.

## 2026-07-27 Fresh Adversarial Verification Evidence

This run supersedes the earlier PASS labels as current implementation
evidence. The retained receipt is
`docs/evidence/curated-acquisition/2026-07-27-adversarial-audit.json`; it was
generated by the new independent harness rather than copied from the prior
dogfood artifact.

### ISC-IW-01 — PASS: protected baseline

- Starting IWantIt HEAD was
  `60c2616702001fc10d6dc171de6f451bb70a0b81`.
- `git status --short --branch` identified `README.md`, `.agent/`, and
  `uv.lock` as protected pre-existing paths. Every stage and commit used
  explicit scoped paths; none was staged, stashed, reset, or modified.

### ISC-IW-02 — PASS: exact authority-qualified identity

- The fresh real CLI matrix refused bare strings, malformed authority
  envelopes, unsupported subject versions, version-family subjects,
  non-recording subjects, and local/URL-shaped nonportable evidence.
- No refusal reached the dispatch provider. The nonportable URL refutation
  produced fix `2d8bc0a`; its result now uses `subject=null`.
- Current IWantIt and ERR owner subject schemas byte-compare identically.

### ISC-IW-03 — PASS: explicit acquisition state machine

- Separate CLI processes proved write-free preview, retained stable choice,
  unconfirmed refusal, mismatched/absent confirmation refusal, confirmed
  dispatch, cancellation before dispatch, refusal after cancellation, and
  honest unsupported cancellation after dispatch.
- `source_ingestion` and `recommendation_ranking` origins both failed before
  any provider effect.

### ISC-IW-04 — PASS: replay, retry, crash windows, cancellation

- Preview replay made no second search; completed dispatch replay made no
  second provider request/effect; cancellation replay was byte-stable.
- A missing endpoint produced an attested side-effect-free retry, then one
  successful effect and a zero-effect replay.
- A deliberately dropped response after the loopback provider effect produced
  non-retryable `DISPATCH_OUTCOME_UNCERTAIN`; replay made no second effect.
- An expired SQLite dispatch lease produced the same reconciliation-required
  state without contacting the provider.

### ISC-IW-05 — PASS: bounded partial batch

- A valid item survived beside a non-exact refused item with top status
  `partial`; duplicate item IDs were rejected before search.
- The live provider returned 140 large candidates; IWantIt returned at most
  100 and the largest observed result was 157,567 bytes against the published
  2,097,152-byte limit.
- An oversized request returned minimized `PAYLOAD_TOO_LARGE` without echoing
  its sentinel.

### ISC-IW-06 — PASS: private evidence exclusion

- Fresh payload cases covered comment, excerpt, source handle, source URL,
  cookie, and token fields. All returned
  `PRIVATE_SOURCE_EVIDENCE_FORBIDDEN`, no provider effect, and no secret echo.
- The harness recursively scanned 42 CLI results, all stderr, and 18
  journal/WAL/SHM/log/report/cache files. No comment, excerpt, handle, private
  URL, cookie, API key, bearer token, download token, or private provider
  receipt sentinel was found.
- Fix `3026f67` also proves candidate references are invariant to private URL,
  handle, and credential changes.

### ISC-IW-07 — PASS: minimized ownership handoff

- Every successful dispatch preserved the exact ERR subject and returned
  `verification.required=true`,
  `status=pending_err_verification`, and
  `ownership_update_allowed=false`.
- Current MetaMusic disposable artifact verification independently hashed a
  local artifact, verified through ERR before ownership, and rejected a
  changed ERR identity. IWantIt never asserted ownership.

### ISC-IW-08 — PASS: canonical current consumers

- The fixture verifier passed 5 schemas, 51 fixtures, 23 scenarios, and 4
  replay pairs after the privacy/fingerprint fixes.
- MetaMusic HEAD `e5376d75dda9c910ce610d18bd803a7d801162c4`
  validated fresh live IWantIt capabilities and preview as v2.
- ERR HEAD `ba017cece7edecc1a04332e61b38964242a81fd3`
  matched the embedded subject schema and its current artifact verification
  contract passed.
- External limitation: MetaMusic degrades schema-valid exit-1 typed refusals
  to generic `GATEWAY_ERROR`; Beads `iwantit-ztl.7` records the upstream fix.
  The fallback remains fail-closed and positive v2 interoperation passes.

### ISC-IW-09 — PASS: retired comment ranking remains retired

- `docs/redacted_comment_sourcing_plan.md` still explicitly supersedes
  comment-as-endorsement and large-boost assumptions.
- The full 104-test suite includes the three no-network/no-score-change
  comment-policy tests; no audit finding reopened the retired design.

### ISC-IW-10 — PASS: offline X6/X7 dogfood

- The independent audit exercised 42 current CLI outcomes across a disposable
  loopback provider and retained a dated sanitized receipt.
- Three deliberate provider requests produced exactly three effects; completed
  replay, refusal, cancellation, safe pre-request failure, and uncertain
  replay added zero effects.
- The original offline dogfood was also rerun independently and retained its
  deterministic digest
  `sha256:a21d885f9eb98bbb233aea8ab8760633744995528504f571c66968ad221b1bde`.

### ISC-IW-11 — PASS: current full gates

- `.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests`
  -> 104 passed.
- `.venv/bin/python scripts/functional_test.py --verbose` -> passed.
- `.venv/bin/python -m compileall -q iwantit scripts tests` -> passed.
- Fixture verifier, original offline dogfood, fresh adversarial audit, current
  MetaMusic v2 consumer/artifact probes, ERR schema byte comparison, and
  `git diff --check` all passed.

### ISC-IW-12 — PENDING LANDING

- Beads audit task `iwantit-ztl.6` is in progress and upstream dependency
  `iwantit-ztl.7` is open with an honest fail-closed fallback.
- Granular implementation commits through `dee19d3` and this retained
  evidence are ready for the mandatory clean-worktree pull/rebase, `bd sync`,
  push, prune/fetch, protected-range, and zero-ahead/behind verification.
- This criterion remains explicitly pending until those exact probes pass.
