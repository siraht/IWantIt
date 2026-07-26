#!/usr/bin/env python3
"""Generate canonical IWantIt acquisition schemas and conformance fixtures."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._curated_acquisition_fixture_support import (  # noqa: E402
    OfflineRunner,
    acquisition_intent,
    acquisition_item,
    caller,
    confirmed_intent,
    err_subject,
    service_config,
)
from iwantit.acquisition import AcquisitionService  # noqa: E402
from iwantit.curated_acquisition_schema import (  # noqa: E402
    ACQUISITION_CAPABILITIES_SCHEMA,
    ACQUISITION_INTENT_SCHEMA,
    ACQUISITION_RESULT_SCHEMA,
    CANDIDATE_SCHEMA,
    CANDIDATE_SCHEMA_ID,
    ERR_SUBJECT_SCHEMA,
)


SCHEMA_DIR = Path("schemas/curated-acquisition/v2")
FIXTURE_DIR = Path("fixtures/curated-acquisition/v2")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _standalone_candidate_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": CANDIDATE_SCHEMA_ID,
        **deepcopy(CANDIDATE_SCHEMA),
    }


def _service(
    temp_dir: Path,
    name: str,
) -> tuple[AcquisitionService, OfflineRunner]:
    runner = OfflineRunner()
    service = AcquisitionService(
        service_config(temp_dir / f"{name}.sqlite3"),
        {},
        runner=runner,
    )
    return service, runner


def generate(output_root: Path) -> None:
    schema_dir = output_root / SCHEMA_DIR
    fixture_dir = output_root / FIXTURE_DIR
    schemas = {
        "intent.schema.json": ACQUISITION_INTENT_SCHEMA,
        "result.schema.json": ACQUISITION_RESULT_SCHEMA,
        "candidate.schema.json": _standalone_candidate_schema(),
        "capabilities.schema.json": ACQUISITION_CAPABILITIES_SCHEMA,
        "err-subject-owner.schema.json": ERR_SUBJECT_SCHEMA,
    }
    for name, schema in schemas.items():
        _write_json(schema_dir / name, schema)

    fixtures: dict[str, Any] = {}
    scenarios: list[dict[str, Any]] = []

    def record(
        name: str,
        request: dict[str, Any] | None,
        result: dict[str, Any],
        *,
        expected_status: str,
        expected_item_status: str | None = None,
        expected_error: str | None = None,
        intent_valid: bool = True,
    ) -> None:
        request_name = f"{name}.intent.json" if request is not None else None
        result_name = f"{name}.result.json"
        if request_name:
            fixtures[request_name] = request
        fixtures[result_name] = result
        scenarios.append(
            {
                "name": name,
                "request": request_name,
                "result": result_name,
                "intent_schema_valid": intent_valid,
                "expected_status": expected_status,
                "expected_item_status": expected_item_status,
                "expected_error": expected_error,
            }
        )

    with tempfile.TemporaryDirectory(prefix="iwantit-fixtures-") as directory:
        temp_dir = Path(directory)

        service, runner = _service(temp_dir, "explicit")
        record(
            "capabilities",
            None,
            service.capabilities(),
            expected_status="ready",
        )
        explicit = acquisition_intent(intent_id="fixture-explicit")
        preview = service.handle(explicit)
        record(
            "explicit-preview",
            explicit,
            preview,
            expected_status="previewed",
            expected_item_status="choice_required",
        )
        dispatch = confirmed_intent(explicit, preview)
        dispatched = service.handle(dispatch)
        record(
            "explicit-dispatch",
            dispatch,
            dispatched,
            expected_status="dispatched",
            expected_item_status="dispatched",
        )
        record(
            "explicit-replay",
            dispatch,
            service.handle(dispatch),
            expected_status="dispatched",
            expected_item_status="dispatched",
        )
        if len(runner.calls) != 2:
            raise AssertionError("completed dispatch replay invoked the runner")

        service, _runner = _service(temp_dir, "unconfirmed")
        unconfirmed = acquisition_intent(
            intent_id="fixture-unconfirmed",
            action="dispatch",
        )
        record(
            "refusal-unconfirmed",
            unconfirmed,
            service.handle(unconfirmed),
            expected_status="refused",
            expected_item_status="refused",
            expected_error="CONFIRMATION_REQUIRED",
        )

        service, runner = _service(temp_dir, "cancel")
        cancel_preview_intent = acquisition_intent(intent_id="fixture-cancel")
        cancel_preview = service.handle(cancel_preview_intent)
        cancel = acquisition_intent(
            intent_id="fixture-cancel",
            action="cancel",
        )
        cancelled = service.handle(cancel)
        record(
            "cancel-before-dispatch",
            cancel,
            cancelled,
            expected_status="cancelled",
            expected_item_status="cancelled",
        )
        record(
            "cancel-replay",
            cancel,
            service.handle(cancel),
            expected_status="cancelled",
            expected_item_status="cancelled",
        )
        fixtures["cancel-setup-preview.intent.json"] = cancel_preview_intent
        fixtures["cancel-setup-preview.result.json"] = cancel_preview
        if len(runner.calls) != 1:
            raise AssertionError("cancel replay invoked the runner")

        service, runner = _service(temp_dir, "partial")
        partial = acquisition_intent(
            intent_id="fixture-partial",
            items=[
                acquisition_item(
                    item_id="non-exact",
                    subject=err_subject(exactness="version_family"),
                ),
                acquisition_item(item_id="exact"),
            ],
        )
        record(
            "partial-item-error",
            partial,
            service.handle(partial),
            expected_status="partial",
            expected_item_status="refused",
            expected_error="EXACT_RECORDING_REQUIRED",
        )
        if len(runner.calls) != 1:
            raise AssertionError("partial batch discarded or executed an invalid item")

        subject_refusals = (
            (
                "refusal-bare-subject",
                "fixture-bare-subject",
                "INVALID_ITEM",
                lambda value: value.__setitem__(
                    "subject",
                    "xref:entity:01ARZ3NDEKTSV4RRFFQ69G5FAV",
                ),
                False,
            ),
            (
                "refusal-malformed-authority-subject",
                "fixture-malformed-authority",
                "INVALID_ITEM",
                lambda value: value["subject"].pop("authority_id"),
                False,
            ),
            (
                "refusal-unsupported-subject-version",
                "fixture-unsupported-subject-version",
                "INVALID_ITEM",
                lambda value: value["subject"].__setitem__(
                    "schema_version",
                    "err.subject/99.0",
                ),
                False,
            ),
            (
                "refusal-non-recording-subject",
                "fixture-non-recording",
                "EXACT_RECORDING_REQUIRED",
                lambda value: value["subject"].__setitem__(
                    "entity_kind",
                    "music.release",
                ),
                True,
            ),
            (
                "refusal-non-portable-subject",
                "fixture-non-portable",
                "NON_PORTABLE_IDENTITY_EVIDENCE",
                lambda value: value["subject"].__setitem__(
                    "portable_refs",
                    ["xref:entity:01ARZ3NDEKTSV4RRFFQ69G5FAV"],
                ),
                True,
            ),
        )
        for (
            scenario_name,
            intent_id,
            expected_error,
            mutate,
            schema_valid,
        ) in subject_refusals:
            service, runner = _service(temp_dir, scenario_name)
            refusal_item = acquisition_item()
            mutate(refusal_item)
            refusal = acquisition_intent(
                intent_id=intent_id,
                items=[refusal_item],
            )
            refusal_result = service.handle(refusal)
            record(
                scenario_name,
                refusal,
                refusal_result,
                expected_status="refused",
                expected_item_status="refused",
                expected_error=expected_error,
                intent_valid=schema_valid,
            )
            if runner.calls:
                raise AssertionError(
                    f"invalid subject reached the runner: {scenario_name}"
                )

        service, runner = _service(temp_dir, "private")
        private_item = acquisition_item()
        private_item["source_handle"] = "fixture-private-handle"
        private = acquisition_intent(
            intent_id="fixture-private-evidence",
            items=[private_item],
        )
        private_result = service.handle(private)
        record(
            "refusal-private-evidence",
            private,
            private_result,
            expected_status="refused",
            expected_item_status="refused",
            expected_error="PRIVATE_SOURCE_EVIDENCE_FORBIDDEN",
            intent_valid=False,
        )
        if "fixture-private-handle" in json.dumps(private_result):
            raise AssertionError("private evidence was echoed into a result")
        if runner.calls:
            raise AssertionError("private evidence reached the runner")

        service, runner = _service(temp_dir, "ingestion")
        ingestion = acquisition_intent(
            intent_id="fixture-ingestion-origin",
            intent_caller=caller(origin_kind="source_ingestion"),
        )
        record(
            "refusal-ingestion-origin",
            ingestion,
            service.handle(ingestion),
            expected_status="refused",
            expected_error="INVALID_INTENT",
            intent_valid=False,
        )
        if runner.calls:
            raise AssertionError("ingestion origin reached the runner")

        service, runner = _service(temp_dir, "unpaired")
        unpaired = acquisition_intent(
            intent_id="fixture-unpaired",
            intent_caller=caller(pairing_id="unpaired-instance"),
        )
        record(
            "refusal-unpaired",
            unpaired,
            service.handle(unpaired),
            expected_status="refused",
            expected_error="UNPAIRED_CALLER",
        )
        if runner.calls:
            raise AssertionError("unpaired caller reached the runner")

        service, runner = _service(temp_dir, "unknown-major")
        unknown_major = acquisition_intent(intent_id="fixture-unknown-major")
        unknown_major["schema"] = "iwantit.acquisition-intent/99"
        record(
            "refusal-unknown-major",
            unknown_major,
            service.handle(unknown_major),
            expected_status="refused",
            expected_error="UNSUPPORTED_CONTRACT_VERSION",
            intent_valid=False,
        )
        if runner.calls:
            raise AssertionError("unknown contract major reached the runner")

        service, runner = _service(temp_dir, "unsupported-provider")
        unsupported = acquisition_intent(intent_id="fixture-unsupported-provider")
        unsupported["items"][0]["constraints"]["sources"][
            "allowed_providers"
        ] = ["redacted"]
        record(
            "refusal-unsupported-provider",
            unsupported,
            service.handle(unsupported),
            expected_status="refused",
            expected_item_status="refused",
            expected_error="UNSUPPORTED_PROVIDER",
        )
        if runner.calls:
            raise AssertionError("unsupported provider reached the runner")

        service, runner = _service(temp_dir, "retry")
        retry_intent = acquisition_intent(intent_id="fixture-safe-retry")
        retry_preview = service.handle(retry_intent)
        retry_dispatch = confirmed_intent(retry_intent, retry_preview)
        runner.safe_failures_remaining = 1
        retryable = service.handle(retry_dispatch)
        record(
            "retry-safe-failure",
            retry_dispatch,
            retryable,
            expected_status="refused",
            expected_item_status="error",
            expected_error="DISPATCH_FAILED",
        )
        retry_success = service.handle(retry_dispatch)
        record(
            "retry-success",
            retry_dispatch,
            retry_success,
            expected_status="dispatched",
            expected_item_status="dispatched",
        )
        record(
            "retry-replay",
            retry_dispatch,
            service.handle(retry_dispatch),
            expected_status="dispatched",
            expected_item_status="dispatched",
        )
        fixtures["retry-setup-preview.intent.json"] = retry_intent
        fixtures["retry-setup-preview.result.json"] = retry_preview
        if len(runner.calls) != 3:
            raise AssertionError("safe retry/replay call count changed")

        service, runner = _service(temp_dir, "uncertain")
        uncertain_intent = acquisition_intent(intent_id="fixture-uncertain")
        uncertain_preview = service.handle(uncertain_intent)
        uncertain_dispatch = confirmed_intent(
            uncertain_intent,
            uncertain_preview,
        )
        runner.raise_dispatch_once = True
        uncertain = service.handle(uncertain_dispatch)
        record(
            "uncertain-dispatch",
            uncertain_dispatch,
            uncertain,
            expected_status="refused",
            expected_item_status="error",
            expected_error="DISPATCH_OUTCOME_UNCERTAIN",
        )
        record(
            "uncertain-replay",
            uncertain_dispatch,
            service.handle(uncertain_dispatch),
            expected_status="refused",
            expected_item_status="error",
            expected_error="DISPATCH_OUTCOME_UNCERTAIN",
        )
        fixtures["uncertain-setup-preview.intent.json"] = uncertain_intent
        fixtures["uncertain-setup-preview.result.json"] = uncertain_preview
        if len(runner.calls) != 2:
            raise AssertionError("uncertain replay invoked the runner")

    for name, value in sorted(fixtures.items()):
        _write_json(fixture_dir / name, value)

    manifest = {
        "schema": "iwantit.acquisition-fixture-manifest/1",
        "owner": "IWantIt",
        "contracts": {
            "intent": "iwantit.acquisition-intent/2",
            "result": "iwantit.acquisition-result/2",
            "candidate": "iwantit.acquisition-candidate/2",
            "capabilities": "iwantit.acquisition-capabilities/1",
            "subject_owner": "err.subject/1.0",
        },
        "compatibility": {
            "unknown_major": "fail_closed",
            "additive_minor_fields": "optional_only",
            "private_evidence": "not_accepted",
        },
        "scenarios": scenarios,
    }
    _write_json(fixture_dir / "manifest.json", manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT,
        help="Root under which schemas/ and fixtures/ are generated",
    )
    args = parser.parse_args()
    generate(args.output_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
