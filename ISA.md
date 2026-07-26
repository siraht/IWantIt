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
unknown-authority, non-exact, non-recording, stale/unsupported-major, and
non-portable subjects item-by-item.

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
fails closed; failed attempts are retryable; pre-dispatch cancellation prevents
dispatch; post-dispatch cancellation is reported honestly as unsupported.

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
mismatch, and private-evidence rejection. A repository verifier validates
every fixture against the owner schema and scenario invariants.

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
