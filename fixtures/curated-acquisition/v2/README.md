# Curated acquisition v2 fixtures

This directory is the canonical IWantIt-owned conformance corpus for
MetaMusic callers and ERR ownership-verification consumers. It covers the
explicit preview, retained choice, item-bound confirmation, dispatch, replay,
cancellation, partial batch, safe retry, uncertain outcome, pairing,
version-negotiation, provider, ingestion-origin, and private-evidence paths.

The adjacent `manifest.json` records the expected status and typed error for
each scenario. Subjects use the ERR-owned `err.subject/1.0` envelope and must
remain exact `music.recording` identities. Successful dispatch results remain
`pending_err_verification` and never assert that ownership changed.

Generate and verify from the repository root:

```bash
python3 scripts/generate_curated_acquisition_fixtures.py
python3 scripts/verify_curated_acquisition_fixtures.py
```

Generation is deterministic. Do not hand-edit JSON artifacts; change the
contract or generator and regenerate them. The verifier byte-compares a fresh
generation, validates every schema/result, and enforces replay, identity,
bounded-output, and private-data exclusion invariants.
