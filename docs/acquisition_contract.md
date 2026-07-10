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
A caller can also request private handling with `policy.private=true`. IWantIt
uses the stricter classification whenever either condition applies. Candidate
metadata may still contain provider-confidential information even after access
credentials are removed; sanitization does not make that content public.

The contract intentionally does not turn tracker observations into ERR
assertions. A consuming application must keep acquisition records out of any
community publication, remote inference, or telemetry path unless a future,
source-specific policy and an explicit user action permit a separately derived
payload.
