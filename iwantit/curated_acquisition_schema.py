"""Canonical JSON Schemas for the curated-source acquisition boundary."""

from __future__ import annotations

from typing import Any

INTENT_SCHEMA_ID = "iwantit.acquisition-intent/2"
RESULT_SCHEMA_ID = "iwantit.acquisition-result/2"
CANDIDATE_SCHEMA_ID = "iwantit.acquisition-candidate/2"
CAPABILITIES_SCHEMA_ID = "iwantit.acquisition-capabilities/1"
ERR_SUBJECT_SCHEMA_ID = "err.subject/1.0"

MAX_BATCH_ITEMS = 25
MAX_PAYLOAD_BYTES = 262_144
MAX_CANDIDATES_PER_ITEM = 100
MAX_RESULT_BYTES = 2_097_152

_SAFE_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_HASH = r"^sha256:[0-9a-f]{64}$"
_PROVIDER = r"^[a-z][a-z0-9_-]{0,63}$"

# Owner fixture: ERR commit 30698f89dcbba442501da9e4aec3d374bac195d7,
# schemas/subject-envelope.schema.json. IWantIt validates this exact owner
# contract separately so ERR can remain its schema authority.
ERR_SUBJECT_SCHEMA: dict[str, Any] = {
    "$defs": {
        "AuthorityRevision": {
            "additionalProperties": False,
            "properties": {
                "event_hash": {"pattern": _HASH, "title": "Event Hash", "type": "string"},
                "sequence": {"minimum": 0, "title": "Sequence", "type": "integer"},
            },
            "required": ["sequence", "event_hash"],
            "title": "AuthorityRevision",
            "type": "object",
        },
        "SubjectExactness": {
            "enum": ["exact", "version_family", "related", "unknown"],
            "title": "SubjectExactness",
            "type": "string",
        },
    },
    "$id": "https://xref.local/schemas/subject-envelope/1.0",
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "additionalProperties": False,
    "properties": {
        "authority_id": {
            "pattern": r"^xref:authority:[0-9A-HJKMNP-TV-Z]{26}$",
            "title": "Authority Id",
            "type": "string",
        },
        "authority_revision": {"$ref": "#/$defs/AuthorityRevision"},
        "entity_kind": {
            "maxLength": 120,
            "minLength": 1,
            "title": "Entity Kind",
            "type": "string",
        },
        "exactness": {"$ref": "#/$defs/SubjectExactness"},
        "identity_explanation_hash": {
            "pattern": _HASH,
            "title": "Identity Explanation Hash",
            "type": "string",
        },
        "local_id": {
            "pattern": r"^xref:entity:[0-9A-HJKMNP-TV-Z]{26}$",
            "title": "Local Id",
            "type": "string",
        },
        "portable_refs": {
            "default": [],
            "items": {"type": "string"},
            "maxItems": 64,
            "title": "Portable Refs",
            "type": "array",
        },
        "schema_version": {
            "const": ERR_SUBJECT_SCHEMA_ID,
            "default": ERR_SUBJECT_SCHEMA_ID,
            "title": "Schema Version",
            "type": "string",
        },
    },
    "required": [
        "authority_id",
        "authority_revision",
        "entity_kind",
        "exactness",
        "local_id",
        "identity_explanation_hash",
    ],
    "title": "SubjectEnvelope",
    "type": "object",
}

CALLER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "application",
        "instance_id",
        "pairing_id",
        "pairing_revision",
        "workspace_id",
        "actor_id",
        "origin",
    ],
    "properties": {
        "application": {"const": "metamusic"},
        "instance_id": {"type": "string", "pattern": _SAFE_ID},
        "pairing_id": {"type": "string", "pattern": _SAFE_ID},
        "pairing_revision": {"type": "integer", "minimum": 1},
        "workspace_id": {"type": "string", "pattern": _SAFE_ID},
        "actor_id": {"type": "string", "pattern": _SAFE_ID},
        "origin": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "interaction_id"],
            "properties": {
                "kind": {"const": "explicit_user_acquisition"},
                "interaction_id": {"type": "string", "pattern": _SAFE_ID},
            },
        },
    },
}

SEARCH_HINTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["artist", "title"],
    "properties": {
        "artist": {"type": "string", "minLength": 1, "maxLength": 300},
        "title": {"type": "string", "minLength": 1, "maxLength": 300},
        "version": {"type": "string", "minLength": 1, "maxLength": 300},
        "release": {"type": "string", "minLength": 1, "maxLength": 300},
        "year": {"type": "integer", "minimum": 1800, "maximum": 3000},
    },
}

CONSTRAINTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "sources",
        "formats",
        "exact_version",
        "allow_substitution",
        "rights",
        "policy",
        "destination",
    ],
    "properties": {
        "sources": {
            "type": "object",
            "additionalProperties": False,
            "required": ["allowed_providers"],
            "properties": {
                "allowed_providers": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 16,
                    "uniqueItems": True,
                    "items": {"type": "string", "pattern": _PROVIDER},
                },
                "excluded_providers": {
                    "type": "array",
                    "maxItems": 16,
                    "uniqueItems": True,
                    "items": {"type": "string", "pattern": _PROVIDER},
                },
            },
        },
        "formats": {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1, "maxLength": 40},
        },
        "media": {
            "type": "array",
            "maxItems": 16,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1, "maxLength": 40},
        },
        "exact_version": {"const": True},
        "allow_substitution": {"const": False},
        "rights": {
            "type": "object",
            "additionalProperties": False,
            "required": ["basis", "policy_ref"],
            "properties": {
                "basis": {
                    "enum": [
                        "user_authorized",
                        "licensed_download",
                        "personal_archive",
                    ]
                },
                "policy_ref": {"type": "string", "pattern": _SAFE_ID},
            },
        },
        "policy": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "authorized_sources_only",
                "private",
                "policy_version",
            ],
            "properties": {
                "authorized_sources_only": {"const": True},
                "private": {"type": "boolean"},
                "policy_version": {"type": "string", "pattern": _SAFE_ID},
            },
        },
        "destination": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "ref"],
            "properties": {
                "kind": {"enum": ["metamusic_staging", "library_import"]},
                "ref": {"type": "string", "pattern": _SAFE_ID},
            },
        },
    },
}

SELECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["preview_result_id", "candidate_ref"],
    "properties": {
        "preview_result_id": {"type": "string", "pattern": _HASH},
        "candidate_ref": {"type": "string", "pattern": _HASH},
    },
}

CONFIRMATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "approved",
        "confirmation_id",
        "confirmed_at",
        "preview_result_id",
        "candidate_ref",
    ],
    "properties": {
        "approved": {"const": True},
        "confirmation_id": {"type": "string", "pattern": _SAFE_ID},
        "confirmed_at": {"type": "string", "format": "date-time"},
        "preview_result_id": {"type": "string", "pattern": _HASH},
        "candidate_ref": {"type": "string", "pattern": _HASH},
    },
}

ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["item_id", "subject", "search_hints", "constraints"],
    "properties": {
        "item_id": {"type": "string", "pattern": _SAFE_ID},
        "subject": ERR_SUBJECT_SCHEMA,
        "search_hints": SEARCH_HINTS_SCHEMA,
        "constraints": CONSTRAINTS_SCHEMA,
        "selection": SELECTION_SCHEMA,
        "confirmation": CONFIRMATION_SCHEMA,
    },
}

ACQUISITION_INTENT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": INTENT_SCHEMA_ID,
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema",
        "intent_id",
        "idempotency_key",
        "action",
        "caller",
        "items",
    ],
    "properties": {
        "schema": {"const": INTENT_SCHEMA_ID},
        "intent_id": {"type": "string", "pattern": _SAFE_ID},
        "idempotency_key": {"type": "string", "pattern": _SAFE_ID},
        "action": {"enum": ["preview", "dispatch", "cancel"]},
        "caller": CALLER_SCHEMA,
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_BATCH_ITEMS,
            "items": ITEM_SCHEMA,
        },
    },
}

ERROR_SCHEMA: dict[str, Any] = {
    "type": ["object", "null"],
    "additionalProperties": False,
    "required": ["code", "message", "retryable", "category", "item_id"],
    "properties": {
        "code": {"type": "string", "pattern": r"^[A-Z][A-Z0-9_]{1,79}$"},
        "message": {"type": "string", "minLength": 1, "maxLength": 500},
        "retryable": {"type": "boolean"},
        "category": {
            "enum": [
                "contract",
                "identity",
                "pairing",
                "confirmation",
                "conflict",
                "provider",
                "cancellation",
            ]
        },
        "item_id": {"type": ["string", "null"], "maxLength": 128},
    },
}

CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema",
        "candidate_ref",
        "position",
        "title",
        "source",
        "source_url",
        "release",
        "edition",
        "availability",
        "ranking",
    ],
    "properties": {
        "schema": {"const": CANDIDATE_SCHEMA_ID},
        "candidate_ref": {"type": "string", "pattern": _HASH},
        "position": {"type": ["integer", "null"], "minimum": 0},
        "title": {"type": "string", "maxLength": 500},
        "source": {"type": "string", "maxLength": 120},
        "source_url": {"type": "null"},
        "release": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "title",
                "artists",
                "year",
                "label",
                "catalog_number",
                "tags",
            ],
            "properties": {
                "title": {"type": "string", "maxLength": 500},
                "artists": {
                    "type": "array",
                    "maxItems": 32,
                    "items": {"type": "string", "maxLength": 300},
                },
                "year": {
                    "type": ["integer", "null"],
                    "minimum": 0,
                    "maximum": 3000,
                },
                "label": {"type": ["string", "null"], "maxLength": 300},
                "catalog_number": {
                    "type": ["string", "null"],
                    "maxLength": 300,
                },
                "tags": {
                    "type": "array",
                    "maxItems": 64,
                    "items": {"type": "string", "maxLength": 120},
                },
            },
        },
        "edition": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "format",
                "encoding",
                "media",
                "remaster_year",
                "remaster_title",
                "file_count",
                "size_bytes",
            ],
            "properties": {
                "format": {"type": ["string", "null"], "maxLength": 120},
                "encoding": {"type": ["string", "null"], "maxLength": 120},
                "media": {"type": ["string", "null"], "maxLength": 120},
                "remaster_year": {
                    "type": ["integer", "null"],
                    "minimum": 0,
                    "maximum": 3000,
                },
                "remaster_title": {
                    "type": ["string", "null"],
                    "maxLength": 300,
                },
                "file_count": {
                    "type": ["integer", "null"],
                    "minimum": 0,
                },
                "size_bytes": {
                    "type": ["integer", "null"],
                    "minimum": 0,
                },
            },
        },
        "availability": {
            "type": "object",
            "additionalProperties": False,
            "required": ["state", "seeders", "leechers", "snatches"],
            "properties": {
                "state": {"const": "observed"},
                "seeders": {"type": ["integer", "null"], "minimum": 0},
                "leechers": {"type": ["integer", "null"], "minimum": 0},
                "snatches": {"type": ["integer", "null"], "minimum": 0},
            },
        },
        "ranking": {
            "type": "object",
            "additionalProperties": False,
            "required": ["score", "rejected", "reasons"],
            "properties": {
                "score": {"type": ["number", "null"]},
                "rejected": {"type": "boolean"},
                "reasons": {
                    "type": "array",
                    "maxItems": 32,
                    "items": {"type": "string", "maxLength": 200},
                },
            },
        },
    },
}

ITEM_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "item_id",
        "subject",
        "status",
        "preview_result_id",
        "candidates",
        "selected",
        "dispatch",
        "verification",
        "error",
    ],
    "properties": {
        "item_id": {"type": "string", "maxLength": 128},
        "subject": {"anyOf": [ERR_SUBJECT_SCHEMA, {"type": "null"}]},
        "status": {
            "enum": [
                "choice_required",
                "no_candidates",
                "dispatched",
                "cancelled",
                "refused",
                "error",
                "already_in_progress",
            ]
        },
        "preview_result_id": {"type": ["string", "null"], "pattern": _HASH},
        "candidates": {
            "type": "array",
            "maxItems": MAX_CANDIDATES_PER_ITEM,
            "items": CANDIDATE_SCHEMA,
        },
        "selected": {"anyOf": [CANDIDATE_SCHEMA, {"type": "null"}]},
        "dispatch": {
            "type": "object",
            "additionalProperties": False,
            "maxProperties": 16,
            "patternProperties": {
                _PROVIDER: {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["status", "count", "reference"],
                    "properties": {
                        "status": {"const": "ok"},
                        "count": {"type": "integer", "minimum": 1},
                        "reference": {
                            "type": ["string", "null"],
                            "pattern": _HASH,
                        },
                    },
                }
            },
        },
        "verification": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "required",
                "status",
                "ownership_update_allowed",
            ],
            "properties": {
                "required": {"type": "boolean"},
                "status": {
                    "enum": ["not_applicable", "pending_err_verification"]
                },
                "ownership_update_allowed": {"const": False},
            },
        },
        "error": ERROR_SCHEMA,
    },
}

PRIVACY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "classification",
        "persistence",
        "community_publish_allowed",
        "remote_inference_allowed",
        "provider_payloads_exportable",
        "private_source_evidence_accepted",
    ],
    "properties": {
        "classification": {"enum": ["restricted", "local_private"]},
        "persistence": {"const": "sanitized_local"},
        "community_publish_allowed": {"const": False},
        "remote_inference_allowed": {"const": False},
        "provider_payloads_exportable": {"const": False},
        "private_source_evidence_accepted": {"const": False},
    },
}

ACQUISITION_RESULT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": RESULT_SCHEMA_ID,
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema",
        "result_id",
        "intent_id",
        "action",
        "status",
        "side_effects_allowed",
        "items",
        "privacy",
        "error",
    ],
    "properties": {
        "schema": {"const": RESULT_SCHEMA_ID},
        "result_id": {"type": "string", "pattern": _HASH},
        "intent_id": {"type": ["string", "null"], "maxLength": 128},
        "action": {"enum": ["preview", "dispatch", "cancel", "unknown"]},
        "status": {"enum": ["previewed", "dispatched", "cancelled", "partial", "refused"]},
        "side_effects_allowed": {"type": "boolean"},
        "items": {
            "type": "array",
            "maxItems": MAX_BATCH_ITEMS,
            "items": ITEM_RESULT_SCHEMA,
        },
        "privacy": PRIVACY_SCHEMA,
        "error": ERROR_SCHEMA,
    },
}

ACQUISITION_CAPABILITIES_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": CAPABILITIES_SCHEMA_ID,
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema",
        "contracts",
        "limits",
        "actions",
        "providers",
        "pairing",
        "idempotency",
        "cancellation",
        "health",
    ],
    "properties": {
        "schema": {"const": CAPABILITIES_SCHEMA_ID},
        "contracts": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "intent",
                "result",
                "candidate",
                "subject",
                "legacy_local_intent",
            ],
            "properties": {
                "intent": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "result": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "candidate": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "subject": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "legacy_local_intent": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        "limits": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "max_batch_items",
                "max_payload_bytes",
                "max_result_bytes",
                "max_candidates_per_item",
            ],
            "properties": {
                "max_batch_items": {"type": "integer", "minimum": 1},
                "max_payload_bytes": {"type": "integer", "minimum": 1},
                "max_result_bytes": {"type": "integer", "minimum": 1},
                "max_candidates_per_item": {"type": "integer", "minimum": 1},
            },
        },
        "actions": {
            "type": "array",
            "uniqueItems": True,
            "items": {"enum": ["preview", "dispatch", "cancel"]},
        },
        "providers": {
            "type": "object",
            "additionalProperties": False,
            "required": ["supported", "configured_active"],
            "properties": {
                "supported": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {"type": "string", "pattern": _PROVIDER},
                },
                "configured_active": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {"type": "string", "pattern": _PROVIDER},
                },
            },
        },
        "pairing": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "required",
                "transport",
                "authentication",
                "credential_in_payload",
            ],
            "properties": {
                "required": {"const": True},
                "transport": {"const": "local_stdio"},
                "authentication": {
                    "const": "host_process_plus_allowlist"
                },
                "credential_in_payload": {"const": False},
            },
        },
        "idempotency": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "required_for_v2",
                "durable_across_restart",
                "completed_dispatch_replay",
                "conflicting_reuse",
                "abandoned_dispatch",
            ],
            "properties": {
                "required_for_v2": {"const": True},
                "durable_across_restart": {"const": True},
                "completed_dispatch_replay": {"const": True},
                "conflicting_reuse": {"const": "refused"},
                "abandoned_dispatch": {
                    "const": "reconciliation_required"
                },
            },
        },
        "cancellation": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "before_dispatch",
                "after_dispatch",
                "after_dispatch_state",
            ],
            "properties": {
                "before_dispatch": {"const": True},
                "after_dispatch": {"const": False},
                "after_dispatch_state": {"const": "unsupported"},
            },
        },
        "health": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "status",
                "configured_pairings",
                "journal_available",
                "private_payloads_in_health",
            ],
            "properties": {
                "status": {
                    "enum": [
                        "ready",
                        "idempotency_required",
                        "pairing_required",
                    ]
                },
                "configured_pairings": {
                    "type": "integer",
                    "minimum": 0,
                },
                "journal_available": {"type": "boolean"},
                "private_payloads_in_health": {"const": False},
            },
        },
    },
}
