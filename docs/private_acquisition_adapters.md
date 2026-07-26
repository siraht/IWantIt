# Private acquisition adapters

IWantIt owns search and acquisition execution for Prowlarr, Jackett, and
Soulseek. These connectors are local/private control-plane integrations. Their
responses are observations, not identity, ownership, permission, or
authorization evidence. They are never eligible for ERR/community publication
or remote inference.

All three paths preserve the same interaction:

1. MetaMusic sends an `iwantit.acquisition-intent/2` preview containing an
   exact authority-qualified `err.subject/1.0` recording.
2. IWantIt searches enabled sources and returns only
   `iwantit.acquisition-candidate/2` projections with no provider URL.
3. The user selects an exact candidate and explicitly confirms it.
4. MetaMusic resubmits the same intent and item IDs with `action=dispatch`,
   the retained `preview_result_id`, the chosen `candidate_ref`, and a separate
   confirmation bound to both.
5. IWantIt journals the item before a provider-side action. Completed replays
   return the prior sanitized result instead of enqueueing a duplicate.
6. A successful result remains `pending_err_verification` and cannot authorize
   a MetaMusic ownership update by itself.

The legacy v1 numeric-index flow remains available for existing local callers
only. MetaMusic curated-source consumers must use v2.

`IWANTIT_PRIVATE_ACQUISITION_DISABLED=1` is the process-wide emergency stop.
It disables search and dispatch for Prowlarr, Jackett, and Soulseek. Each
provider also has an `enabled` switch. Optional adapters must be set to
`enabled: true`; they do not activate merely because an endpoint is present.

## Secret references

Keep secrets in process environment, an environment file readable only by the
service account, or the host secret manager. Do not paste them into MetaMusic,
chat, intent JSON, logs, or command history. Config interpolation resolves
`${ENV:NAME}` at process startup.

```yaml
acquisition:
  idempotency_enabled: true
  # Omit for ~/.local/state/iwantit/acquisition-dispatch.sqlite3.
  idempotency_path: null
  # An expired v2 dispatch lease requires reconciliation; it is never retry authority.
  lease_seconds: 900
  trusted_callers:
    - application: metamusic
      instance_id: metamusic-local-1
      pairing_id: pairing-local-1
      pairing_revision: 1
      workspace_id: workspace-1
      actor_id: actor-1
      active: true

prowlarr:
  enabled: true
  url: http://127.0.0.1:9696
  api_key: ${ENV:PROWLARR_API_KEY}

jackett:
  enabled: true
  url: http://127.0.0.1:9117
  api_key: ${ENV:JACKETT_API_KEY}
  indexer: all
  max_results: 100
  categories:
    music: [3000]
  dispatch:
    # An explicitly configured download-client API; Jackett stays the indexer.
    url: ${ENV:JACKETT_DOWNLOAD_CLIENT_URL}
    headers:
      Authorization: Bearer ${ENV:JACKETT_DOWNLOAD_CLIENT_TOKEN}
    url_field: urls

soulseek:
  enabled: true
  # slskd is the documented local API implementation.
  url: http://127.0.0.1:5030
  api_key: ${ENV:SLSKD_API_KEY}
  search_timeout: 8
  max_results: 100
  poll_interval: 0.25

rate_limits:
  prowlarr: {requests_per_minute: 60}
  jackett: {requests_per_minute: 30}
  soulseek: {requests_per_minute: 20}
concurrency:
  providers:
    prowlarr: 2
    jackett: 1
    soulseek: 1
```

Clear-text HTTP is accepted only for loopback, private IPs, `localhost`, and
`.local` names. A non-local endpoint must use TLS unless the operator makes the
exception visible with `allow_remote: true`. This exception does not weaken
redaction or publication policy.

## Connector behavior

### Prowlarr

The existing `/api/v1/search` and confirmed search-grab flow remains the
preferred multi-indexer integration. Requests use `X-Api-Key`; candidates retain
grab coordinates only inside the transient pipeline. Prowlarr's configured
download client remains responsible for acquisition.

Official reference: [Prowlarr search API](https://wiki.servarr.com/en/prowlarr/search).

### Jackett

Search uses Jackett's documented Torznab endpoint:

`/api/v2.0/indexers/{indexer}/results/torznab/api`

The adapter parses a bounded XML response and projects title, indexer, size,
file count, and observed peer counts. It does not expose the Torznab download
URL. A confirmed dispatch sends only the selected URL to the explicitly
configured download-client endpoint. Jackett does not become a hidden checkout
or automatic acquisition authority.

Official reference: [Jackett API usage](https://github.com/Jackett/Jackett#api-usage).

### Soulseek through slskd

Search and transfer operations use slskd's documented v0 API. Search is a
bounded `POST /api/v0/searches`, followed by response polling. A confirmed
choice uses `POST /api/v0/transfers/downloads/batches`. The batch UUID is derived
from the acquisition idempotency key, so slskd can recognize a replay. Search
and transfer cancellation use slskd's documented DELETE routes.

The candidate projection never exposes usernames, remote paths, search ids, or
transfer coordinates. The result reports only an opaque local receipt.

Official references: [slskd repository](https://github.com/slskd/slskd) and
[slskd configuration/security](https://github.com/slskd/slskd/blob/master/docs/config.md).

## Contract drift and failure semantics

- Invalid Jackett XML and non-array slskd responses are contract-drift errors,
  never successful empty searches.
- Provider errors are reduced to provider, count, and error type in acquisition
  results. Raw bodies, access links, cookies, usernames, and credentials are not
  exported.
- Retry budgets are bounded. Provider concurrency and request rates are
  configurable per connector.
- An exact-version request with no exact match produces no candidate unless
  substitution is explicitly allowed by a legacy local request. Curated v2
  requires `exact_version=true` and `allow_substitution=false`.
- Cross-provider results are kept separate. Filename similarity never merges
  private dispatch coordinates or turns observations into canonical identity.
- A failed v2 dispatch may be retried only when the failure explicitly attests
  that no side effect was possible. A completed one is replayed.
- An adapter exception, unattested failure, or abandoned in-progress lease
  becomes non-retryable `DISPATCH_OUTCOME_UNCERTAIN`; reconcile the provider
  before any new intent.
- Reusing stable intent/item identifiers for a different subject, constraint,
  policy, preview, selection, or confirmation fails closed.
- Pre-dispatch cancellation is durable. Post-dispatch provider cancellation is
  honestly reported unsupported by the cross-provider v2 contract.

## Verification

Run the offline conformance and process-restart suite:

```bash
python3 -W error::ResourceWarning -m unittest \
  tests.test_private_adapters tests.test_acquisition_journal \
  tests.test_acquisition tests.test_curated_acquisition
python3 scripts/verify_curated_acquisition_fixtures.py
python3 scripts/dogfood_curated_acquisition.py --output-dir <evidence-directory>
```

Fixtures cover Torznab XML, slskd JSON, v2 positive/negative consumer
contracts, and restart-safe replay without making live provider calls. The
dogfood harness invokes the actual CLI in separate processes against a
loopback Jackett and download-client boundary. Live searches should be
performed only after the operator verifies the local endpoint, trusted caller
pairing, rate budget, source rules, rights policy, and download destination.
