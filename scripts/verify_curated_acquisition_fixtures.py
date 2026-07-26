#!/usr/bin/env python3
"""Verify canonical curated acquisition schemas, fixtures, and invariants."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_curated_acquisition_fixtures import (  # noqa: E402
    FIXTURE_DIR,
    SCHEMA_DIR,
    generate,
)
from iwantit.curated_acquisition_schema import (  # noqa: E402
    ACQUISITION_CAPABILITIES_SCHEMA,
    ACQUISITION_INTENT_SCHEMA,
    ACQUISITION_RESULT_SCHEMA,
    MAX_RESULT_BYTES,
)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _json_files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*.json"))
    }


def _walk_dicts(value: Any):  # noqa: ANN202
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def verify(root: Path = ROOT) -> dict[str, Any]:
    fixture_dir = root / FIXTURE_DIR
    schema_dir = root / SCHEMA_DIR
    _assert(fixture_dir.is_dir(), f"missing fixture directory: {fixture_dir}")
    _assert(schema_dir.is_dir(), f"missing schema directory: {schema_dir}")

    with tempfile.TemporaryDirectory(prefix="iwantit-verify-fixtures-") as directory:
        generated_root = Path(directory)
        generate(generated_root)
        actual = {
            **{
                str(SCHEMA_DIR / key): value
                for key, value in _json_files(schema_dir).items()
            },
            **{
                str(FIXTURE_DIR / key): value
                for key, value in _json_files(fixture_dir).items()
            },
        }
        generated = {
            **{
                str(SCHEMA_DIR / key): value
                for key, value in _json_files(generated_root / SCHEMA_DIR).items()
            },
            **{
                str(FIXTURE_DIR / key): value
                for key, value in _json_files(generated_root / FIXTURE_DIR).items()
            },
        }
        _assert(
            set(actual) == set(generated),
            "committed schema/fixture file set differs from deterministic generation",
        )
        for name in sorted(generated):
            _assert(
                actual[name] == generated[name],
                f"generated fixture drift: {name}",
            )

    schema_paths = sorted(schema_dir.glob("*.json"))
    for path in schema_paths:
        Draft202012Validator.check_schema(_load(path))

    manifest = _load(fixture_dir / "manifest.json")
    _assert(
        manifest.get("schema") == "iwantit.acquisition-fixture-manifest/1",
        "unsupported fixture manifest",
    )
    scenarios = manifest.get("scenarios")
    _assert(isinstance(scenarios, list) and scenarios, "fixture manifest is empty")
    scenario_by_request = {
        scenario["request"]: scenario
        for scenario in scenarios
        if scenario.get("request")
    }

    intent_validator = Draft202012Validator(ACQUISITION_INTENT_SCHEMA)
    result_validator = Draft202012Validator(ACQUISITION_RESULT_SCHEMA)
    capabilities_validator = Draft202012Validator(
        ACQUISITION_CAPABILITIES_SCHEMA
    )

    for path in sorted(fixture_dir.glob("*.intent.json")):
        value = _load(path)
        errors = list(intent_validator.iter_errors(value))
        scenario = scenario_by_request.get(path.name)
        expected_valid = (
            scenario.get("intent_schema_valid", True)
            if scenario is not None
            else True
        )
        _assert(
            bool(not errors) is bool(expected_valid),
            f"unexpected intent validation state: {path.name}",
        )

    result_paths = sorted(fixture_dir.glob("*.result.json"))
    for path in result_paths:
        value = _load(path)
        if path.name == "capabilities.result.json":
            capabilities_validator.validate(value)
        else:
            result_validator.validate(value)
            _assert(
                len(path.read_bytes()) <= MAX_RESULT_BYTES,
                f"result exceeds published byte bound: {path.name}",
            )
            serialized = path.read_text(encoding="utf-8")
            for sentinel in (
                "fixture-private-handle",
                "fixture-only",
                "fixture-provider-receipt",
                "bearer-value",
                "download_url",
            ):
                _assert(
                    sentinel not in serialized,
                    f"private/provider sentinel leaked into {path.name}",
                )
            for mapping in _walk_dicts(value):
                if "source_url" in mapping:
                    _assert(
                        mapping["source_url"] is None,
                        f"provider URL escaped in {path.name}",
                    )

    for scenario in scenarios:
        result = _load(fixture_dir / scenario["result"])
        if scenario["name"] == "capabilities":
            actual_status = result["health"]["status"]
            error_code = None
            item_status = None
        else:
            actual_status = result["status"]
            first_item = result["items"][0] if result["items"] else None
            item_status = first_item["status"] if first_item else None
            error = result.get("error") or (
                first_item.get("error") if first_item else None
            )
            error_code = error.get("code") if error else None
            if actual_status == "dispatched":
                _assert(result["side_effects_allowed"], "dispatch hid side effects")
                for item in result["items"]:
                    _assert(
                        item["verification"]
                        == {
                            "required": True,
                            "status": "pending_err_verification",
                            "ownership_update_allowed": False,
                        },
                        "dispatch bypassed ERR verification",
                    )
                    for receipt in item["dispatch"].values():
                        reference = receipt.get("reference")
                        _assert(
                            reference is None
                            or (
                                isinstance(reference, str)
                                and reference.startswith("sha256:")
                                and len(reference) == 71
                            ),
                            "dispatch reference is not opaque",
                        )
            else:
                _assert(
                    not result["side_effects_allowed"],
                    f"non-dispatch scenario allowed side effects: {scenario['name']}",
                )
        _assert(
            actual_status == scenario["expected_status"],
            f"status mismatch for {scenario['name']}",
        )
        expected_item_status = scenario.get("expected_item_status")
        if expected_item_status is not None:
            _assert(
                item_status == expected_item_status,
                f"item status mismatch for {scenario['name']}",
            )
        _assert(
            error_code == scenario.get("expected_error"),
            f"error mismatch for {scenario['name']}",
        )

    pairs = (
        ("explicit-dispatch.result.json", "explicit-replay.result.json"),
        ("cancel-before-dispatch.result.json", "cancel-replay.result.json"),
        ("retry-success.result.json", "retry-replay.result.json"),
        ("uncertain-dispatch.result.json", "uncertain-replay.result.json"),
    )
    for first_name, second_name in pairs:
        _assert(
            _load(fixture_dir / first_name) == _load(fixture_dir / second_name),
            f"replay drift: {first_name} != {second_name}",
        )

    dispatch_intent = _load(fixture_dir / "explicit-dispatch.intent.json")
    dispatch_result = _load(fixture_dir / "explicit-dispatch.result.json")
    _assert(
        dispatch_result["items"][0]["subject"]
        == dispatch_intent["items"][0]["subject"],
        "exact ERR subject changed across acquisition",
    )
    _assert(
        dispatch_result["items"][0]["selected"]["candidate_ref"]
        == dispatch_intent["items"][0]["selection"]["candidate_ref"],
        "dispatch did not bind the retained candidate",
    )

    return {
        "status": "ok",
        "schemas": len(schema_paths),
        "fixtures": len(result_paths)
        + len(list(fixture_dir.glob("*.intent.json"))),
        "scenarios": len(scenarios),
        "replay_pairs": len(pairs),
        "max_result_bytes": MAX_RESULT_BYTES,
    }


def main() -> int:
    print(json.dumps(verify(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
