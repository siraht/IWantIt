"""Policy-gated adapters for private, locally controlled acquisition services.

Provider payloads in this module are deliberately short lived.  Callers receive a
small common candidate shape while access URLs and usernames remain under
``_private`` until an explicitly confirmed dispatch.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urljoin, urlparse
from xml.etree import ElementTree

import requests

from .registry import provider_concurrency, provider_rate_limit
from .util import enforce_rate_limit, provider_slot, request_with_retry


class AdapterPolicyError(RuntimeError):
    """Raised when a private connector is disabled or configured unsafely."""


class AdapterContractError(RuntimeError):
    """Raised when a provider response no longer matches its documented shape."""


@dataclass(frozen=True)
class RequestBudget:
    timeout: float
    retries: int
    backoff_seconds: float
    max_results: int


def private_execution_allowed(config: dict[str, Any], provider: str) -> bool:
    """Apply the process-wide kill switch and a provider-level disable flag."""
    if os.environ.get("IWANTIT_PRIVATE_ACQUISITION_DISABLED", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return False
    section = config.get(provider)
    return isinstance(section, dict) and section.get("enabled", True) is not False


def connector_enabled(config: dict[str, Any], provider: str) -> bool:
    """Return true only for an explicitly enabled optional connector."""

    section = config.get(provider)
    return (
        private_execution_allowed(config, provider)
        and isinstance(section, dict)
        and section.get("enabled") is True
    )


def validate_private_endpoint(config: dict[str, Any], provider: str) -> str:
    """Validate a connector base URL without silently trusting clear-text WAN hosts."""

    section = config.get(provider) or {}
    url = str(section.get("url") or "").rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise AdapterPolicyError(f"{provider}: url must be an absolute HTTP(S) URL")
    hostname = parsed.hostname.lower()
    local = hostname == "localhost"
    try:
        local = local or ipaddress.ip_address(hostname).is_private
    except ValueError:
        local = local or hostname.endswith(".local")
    if parsed.scheme != "https" and not local and section.get("allow_remote") is not True:
        raise AdapterPolicyError(
            f"{provider}: clear-text non-local endpoint denied; use TLS or allow_remote=true"
        )
    return url


def _budget(section: dict[str, Any]) -> RequestBudget:
    return RequestBudget(
        timeout=max(1.0, min(float(section.get("timeout", 20)), 120.0)),
        retries=max(0, min(int(section.get("retries", 1)), 5)),
        backoff_seconds=max(0.0, min(float(section.get("retry_backoff_seconds", 0.5)), 10.0)),
        max_results=max(1, min(int(section.get("max_results", 100)), 1000)),
    )


def _provider_request(
    config: dict[str, Any],
    provider: str,
    method: str,
    url: str,
    *,
    timeout: float,
    retries: int,
    backoff_seconds: float,
    **kwargs: Any,
) -> requests.Response:
    with provider_slot(provider, provider_concurrency(config, provider)):
        enforce_rate_limit(provider, provider_rate_limit(config, provider))
        return request_with_retry(
            method,
            url,
            timeout=timeout,
            retries=retries,
            backoff_seconds=backoff_seconds,
            max_backoff_seconds=8.0,
            **kwargs,
        )


def _opaque_reference(provider: str, *values: Any) -> str:
    material = "\x1f".join(str(value) for value in values)
    return f"{provider}:sha256:{hashlib.sha256(material.encode()).hexdigest()}"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ElementTree.Element, name: str) -> str | None:
    wanted = name.lower()
    for child in element:
        if _local_name(child.tag) == wanted and child.text:
            return child.text.strip()
    return None


def _attribute(element: ElementTree.Element, name: str) -> str | None:
    wanted = name.lower()
    for child in element:
        if _local_name(child.tag) != "attr":
            continue
        attrs = {_local_name(key): value for key, value in child.attrib.items()}
        if attrs.get("name", "").lower() == wanted:
            return attrs.get("value")
    return None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


class JackettAdapter:
    """Read Jackett's documented Torznab feed and hand off an explicit choice."""

    provider = "jackett"

    def __init__(self, config: dict[str, Any]) -> None:
        if not connector_enabled(config, self.provider):
            raise AdapterPolicyError("jackett: connector disabled")
        self.config = config
        self.section = config[self.provider]
        self.base_url = validate_private_endpoint(config, self.provider)
        self.budget = _budget(self.section)

    def search(self, query: str, *, categories: list[int] | None = None) -> list[dict[str, Any]]:
        indexer = quote(str(self.section.get("indexer") or "all"), safe="!:+,")
        url = f"{self.base_url}/api/v2.0/indexers/{indexer}/results/torznab/api"
        params: dict[str, Any] = {
            "apikey": self.section.get("api_key"),
            "t": "search",
            "q": query,
        }
        if categories:
            params["cat"] = ",".join(str(value) for value in categories)
        response = _provider_request(
            self.config,
            self.provider,
            "GET",
            url,
            params=params,
            timeout=self.budget.timeout,
            retries=self.budget.retries,
            backoff_seconds=self.budget.backoff_seconds,
        )
        response.raise_for_status()
        if len(response.content) > int(self.section.get("max_response_bytes", 5_000_000)):
            raise AdapterContractError("jackett: response exceeded configured size limit")
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise AdapterContractError("jackett: invalid Torznab XML") from exc
        items = [item for item in root.iter() if _local_name(item.tag) == "item"]
        candidates: list[dict[str, Any]] = []
        for item in items[: self.budget.max_results]:
            title = _child_text(item, "title")
            link = _child_text(item, "link") or _child_text(item, "enclosure")
            guid = _child_text(item, "guid")
            if not title or not (link or guid):
                continue
            download_url = link or guid
            candidates.append(
                {
                    "title": title,
                    "provider": self.provider,
                    "indexer": _attribute(item, "indexer") or "Jackett",
                    "guid": guid,
                    "info_url": _child_text(item, "comments") or guid,
                    "size": _integer(_child_text(item, "size")),
                    "seeders": _integer(_attribute(item, "seeders")),
                    "leechers": _integer(_attribute(item, "peers")),
                    "file_count": _integer(_attribute(item, "files")),
                    "_private": {
                        "provider": self.provider,
                        "download_url": download_url,
                    },
                }
            )
        return candidates

    def dispatch(self, candidate: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        dispatch = self.section.get("dispatch") or {}
        endpoint = str(dispatch.get("url") or "")
        private = candidate.get("_private") or {}
        download_url = private.get("download_url")
        if not endpoint or not download_url:
            raise AdapterPolicyError(
                "jackett: dispatch requires an explicit download-client URL and selected link"
            )
        # The download client owns the file retrieval. IWantIt sends only the selected URL.
        headers = dict(dispatch.get("headers") or {})
        headers.setdefault("Idempotency-Key", idempotency_key)
        body_key = str(dispatch.get("url_field") or "urls")
        body_value: Any = [download_url] if body_key == "urls" else download_url
        response = _provider_request(
            self.config,
            self.provider,
            str(dispatch.get("method") or "POST").upper(),
            endpoint,
            headers=headers,
            json={body_key: body_value},
            timeout=self.budget.timeout,
            retries=self.budget.retries,
            backoff_seconds=self.budget.backoff_seconds,
        )
        response.raise_for_status()
        return {
            "status": "ok",
            "count": 1,
            "id": _opaque_reference(self.provider, idempotency_key, candidate.get("title")),
        }


class SoulseekAdapter:
    """Use the documented slskd v0 search and batch-download API."""

    provider = "soulseek"

    def __init__(self, config: dict[str, Any]) -> None:
        if not connector_enabled(config, self.provider):
            raise AdapterPolicyError("soulseek: connector disabled")
        self.config = config
        self.section = config[self.provider]
        self.base_url = validate_private_endpoint(config, self.provider)
        self.budget = _budget(self.section)

    def _headers(self) -> dict[str, str]:
        api_key = str(self.section.get("api_key") or "")
        if not api_key:
            raise AdapterPolicyError("soulseek: api_key is required")
        return {"X-API-Key": api_key}

    def search(self, query: str) -> list[dict[str, Any]]:
        search_id = str(uuid.uuid4())
        timeout_seconds = max(1, min(int(self.section.get("search_timeout", 8)), 60))
        response = _provider_request(
            self.config,
            self.provider,
            "POST",
            f"{self.base_url}/api/v0/searches",
            headers=self._headers(),
            json={
                "id": search_id,
                "searchText": query,
                "searchTimeout": timeout_seconds,
                "fileLimit": self.budget.max_results,
                "filterResponses": True,
            },
            timeout=self.budget.timeout,
            retries=self.budget.retries,
            backoff_seconds=self.budget.backoff_seconds,
        )
        response.raise_for_status()
        returned = response.json()
        if isinstance(returned, dict) and returned.get("id"):
            search_id = str(returned["id"])
        deadline = time.monotonic() + timeout_seconds
        responses: Any = []
        while True:
            polled = _provider_request(
                self.config,
                self.provider,
                "GET",
                f"{self.base_url}/api/v0/searches/{quote(search_id, safe='')}/responses",
                headers=self._headers(),
                timeout=self.budget.timeout,
                retries=self.budget.retries,
                backoff_seconds=self.budget.backoff_seconds,
            )
            polled.raise_for_status()
            responses = polled.json()
            if not isinstance(responses, list):
                raise AdapterContractError("soulseek: search responses must be an array")
            if responses or time.monotonic() >= deadline:
                break
            time.sleep(max(0.05, min(float(self.section.get("poll_interval", 0.25)), 2.0)))
        candidates: list[dict[str, Any]] = []
        for peer in responses:
            if not isinstance(peer, dict):
                continue
            username = peer.get("username")
            files = peer.get("files") or []
            if not username or not isinstance(files, list):
                continue
            for file in files:
                if len(candidates) >= self.budget.max_results:
                    break
                if not isinstance(file, dict):
                    continue
                filename = file.get("filename")
                size = _integer(file.get("size"))
                if not filename or size is None:
                    continue
                candidates.append(
                    {
                        "title": str(filename).replace("\\", "/").rsplit("/", 1)[-1],
                        "provider": self.provider,
                        "indexer": "Soulseek via slskd",
                        "size": size,
                        "bitrate": _integer(file.get("bitRate") or file.get("bitrate")),
                        "availability": "observed",
                        "_private": {
                            "provider": self.provider,
                            "username": username,
                            "filename": filename,
                            "size": size,
                            "search_id": search_id,
                        },
                    }
                )
        return candidates

    def cancel_search(self, search_id: str) -> None:
        response = _provider_request(
            self.config,
            self.provider,
            "DELETE",
            f"{self.base_url}/api/v0/searches/{quote(search_id, safe='')}",
            headers=self._headers(),
            timeout=self.budget.timeout,
            retries=self.budget.retries,
            backoff_seconds=self.budget.backoff_seconds,
        )
        if response.status_code not in {204, 404}:
            response.raise_for_status()

    def dispatch(self, candidate: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
        private = candidate.get("_private") or {}
        username = private.get("username")
        filename = private.get("filename")
        size = _integer(private.get("size"))
        if not username or not filename or size is None:
            raise AdapterContractError("soulseek: selected candidate lacks transfer coordinates")
        batch_id = str(uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key))
        response = _provider_request(
            self.config,
            self.provider,
            "POST",
            f"{self.base_url}/api/v0/transfers/downloads/batches",
            headers=self._headers(),
            json={
                "id": batch_id,
                "username": username,
                "files": [{"filename": filename, "size": size}],
            },
            timeout=self.budget.timeout,
            retries=self.budget.retries,
            backoff_seconds=self.budget.backoff_seconds,
        )
        # slskd returns 200 for an idempotent replay and 201 for a new batch.
        if response.status_code not in {200, 201, 207}:
            response.raise_for_status()
        return {"status": "ok", "count": 1, "id": f"soulseek:batch:{batch_id}"}

    def cancel_transfer(self, username: str, transfer_id: str) -> None:
        response = _provider_request(
            self.config,
            self.provider,
            "DELETE",
            f"{self.base_url}/api/v0/transfers/downloads/"
            f"{quote(username, safe='')}/{quote(transfer_id, safe='')}",
            headers=self._headers(),
            params={"remove": False},
            timeout=self.budget.timeout,
            retries=self.budget.retries,
            backoff_seconds=self.budget.backoff_seconds,
        )
        if response.status_code not in {204, 404}:
            response.raise_for_status()


def adapter_for(config: dict[str, Any], provider: str) -> JackettAdapter | SoulseekAdapter:
    if provider == "jackett":
        return JackettAdapter(config)
    if provider in {"soulseek", "slskd"}:
        return SoulseekAdapter(config)
    raise AdapterPolicyError(f"unsupported private adapter: {provider}")
