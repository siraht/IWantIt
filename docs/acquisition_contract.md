# Acquisition contract

`iwantit acquire --stdin` accepts `iwantit.acquisition-intent/1` and returns
`iwantit.acquisition-result/1`. Preview never confirms a provider-side action;
dispatch requires `confirmation.approved=true`.

Every result includes a `privacy` object. This is a downstream enforcement
contract, not a display hint:

- `classification=local_private` means the result may be handled only inside
  the caller's private installation.
- `persistence=sanitized_local` permits local persistence only after IWantIt's
  recursive credential and sensitive-URL sanitization.
- `community_publish_allowed=false` excludes the result and its provider
  payloads from public/community datasets.
- `remote_inference_allowed=false` excludes the result from remote model,
  embedding, and recommendation calls.
- `provider_payloads_exportable=false` prevents raw provider payload export.

Prowlarr and Redacted are declared `local_private` in the provider registry.
A separately enabled Jackett or Soulseek/slskd adapter is also declared
`local_private`. The process-wide `IWANTIT_PRIVATE_ACQUISITION_DISABLED=1` kill
switch applies to Prowlarr, Jackett, and Soulseek search and dispatch.
A caller can also request private handling with `policy.private=true`. IWantIt
uses the stricter classification whenever either condition applies. Candidate
metadata may still contain provider-confidential information even after access
credentials are removed; sanitization does not make that content public.

The contract intentionally does not turn tracker observations into ERR
assertions. A consuming application must keep acquisition records out of any
community publication, remote inference, or telemetry path unless a future,
source-specific policy and an explicit user action permit a separately derived
payload.

## Candidate projection

Private provider responses are never returned verbatim. Each option is projected
to the closed `iwantit.acquisition-candidate/1` shape containing only:

- a content-derived candidate reference, position, display title, source, and
  credential-free source URL;
- normalized release title/artists/year/label/catalog number/tags;
- normalized edition format/encoding/media/remaster/file count/size;
- observed seeder/leecher/snatch availability; and
- numeric ranking plus non-payload reason labels.

Download URLs, raw Prowlarr results, Redacted group/torrent bodies, comments,
usernames, provider response bodies, and grab requests/responses are excluded.
Search provenance retains only query, result count, and error type. Dispatch
provenance retains only provider, status, count, and an opaque returned reference
when one exists. This is data minimization in addition to credential redaction;
sanitizing a raw provider payload would not make that payload exportable.

Confirmed dispatch is keyed by `intent_id` plus a fingerprint of the recording,
desired version/format, policy, and selected candidate. Its local SQLite journal
prevents duplicate provider actions across retries and process restarts. Reusing
an intent id for different acquisition coordinates is rejected. Failed attempts
remain retryable; completed sanitized results are replayed without another
provider call.
