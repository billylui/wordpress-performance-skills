# SPDX-License-Identifier: GPL-2.0-or-later
"""Fail closed when a production WordPress change plan is not safe to execute.

Usage:
  python3 validate_plan.py PLAN.json [--stack STACK.json] [--repo-root PATH]
                           [--json OUT] [--quiet]
  python3 validate_plan.py --selftest

The validator performs no network access and never changes a target site.  Exit
0 means the plan passed every gate; exit 1 means it must not be executed.
"""

import argparse
import copy
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple


# This is the only change-plan schema this validator knows how to prove safe.
SCHEMA_VERSION = "1.0"
# The tool version identifies this implementation without changing the plan schema.
TOOL_VERSION = "0.1.0"

EXIT_VALID = 0
EXIT_INVALID = 1
EXIT_USAGE = 2
EXIT_UNREADABLE = 4

# These keys are required by docs/CONTRACTS.md "Schema: change plan".
REQUIRED_PLAN_KEYS = (
    "baseline_metrics",
    "cache_layers_present",
    "changes",
    "generated_at",
    "host_class",
    "schema_version",
    "site",
    "tier",
    "tool",
    "tool_version",
)
# A change missing any of these fields cannot be safely executed or rolled back.
REQUIRED_CHANGE_KEYS = (
    "approval",
    "catalog_entry",
    "expected_effect",
    "id",
    "purge_layers",
    "risk_lane",
    "rollback",
    "snapshot",
    "summary",
    "target",
)

RISK_LANES = ("direct", "prohibited", "staging-first")
CACHE_LAYERS = ("edge", "server", "page-plugin", "object")
# Cache values are closed per layer in docs/CONTRACTS.md; accepting an invented
# value would let a hand-written document masquerade as a real fingerprint.
CACHE_VALUES_BY_LAYER: Mapping[str, Tuple[str, ...]] = {
    "edge": (
        "akamai",
        "aws-cloudfront",
        "bunny",
        "cloudflare",
        "cloudflare-apo",
        "fastly",
        "keycdn",
        "none",
        "other",
        "quic-cloud",
        "stackpath",
        "unknown",
    ),
    "server": (
        "batcache",
        "litespeed",
        "nginx-fastcgi",
        "none",
        "unknown",
        "varnish",
    ),
    "page-plugin": (
        "breeze",
        "cache-enabler",
        "litespeed-cache",
        "none",
        "sg-optimizer",
        "surge",
        "unknown",
        "w3-total-cache",
        "wp-fastest-cache",
        "wp-rocket",
        "wp-super-cache",
    ),
    "object": (
        "apcu",
        "memcached",
        "none",
        "object-cache-pro",
        "redis",
        "unknown",
    ),
}
# `unknown` is additionally valid for closed vocabularies under the shared contract.
HOST_CLASSES = (
    "bluehost",
    "cloudways",
    "flywheel",
    "godaddy",
    "hostinger",
    "kinsta",
    "other",
    "pantheon",
    "pressable",
    "rocket-net",
    "self-managed",
    "shared-cpanel",
    "siteground",
    "unknown",
    "wpcom",
    "wpengine",
    "wpvip",
)

# Tier minima follow the capability contract: code files require a confirmed deploy
# path (tier 3); WordPress options, plugin settings, and builder content can use a
# confirmed admin or CLI path (minimum tier 1); media requires admin (tier 1).
# None is deliberate: server and DNS/CDN configuration are outside wp-perf-fix, so
# no skill access tier is sufficient and the validator must route them to an operator.
MINIMUM_TIER_BY_TARGET_KIND: Mapping[str, Optional[int]] = {
    "builder-content": 1,
    "dns-or-cdn-setting": None,
    "media": 1,
    "mu-plugin": 3,
    "plugin-file": 3,
    "plugin-setting": 1,
    "server-config": None,
    "theme-file": 3,
    "wp-option": 1,
}

# The stack profile contract fixes both membership and order for cache-layer entries.
STACK_CACHE_LAYER_ORDER = CACHE_LAYERS
# Public host detection is authoritative for a production write only at high
# confidence; the fingerprint's low-confidence hostname heuristic is a lead to
# confirm, not permission. Cache-layer presence may also be corroborated at
# medium confidence, but a single low-confidence signal cannot authorize a purge.
HOST_CROSSCHECK_CONFIDENCES = ("high",)
CACHE_CROSSCHECK_CONFIDENCES = ("high", "medium")

CATALOG_RELATIVE_PATH = Path("skills/wp-perf-audit/references/catalog")


class ValidationInputError(Exception):
    """An input or output error that should be reported without a traceback."""


class UsageError(Exception):
    """A command-line error that should return the usage exit code."""


class DuplicateKeyError(ValueError):
    """JSON contained an ambiguous duplicate object key."""


class GateArgumentParser(argparse.ArgumentParser):
    """Raise usage errors so the CLI boundary controls all error output."""

    def error(self, message: str) -> None:
        raise UsageError(message)


@dataclass(frozen=True)
class Problem:
    """One deterministic, actionable gate failure."""

    change_id: str
    rule: str
    message: str


def reject_duplicate_keys(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    """Reject ambiguous JSON objects instead of silently accepting the last value."""

    document: Dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise DuplicateKeyError("duplicate object key {!r}".format(key))
        document[key] = value
    return document


def reject_non_finite_number(value: str) -> None:
    """Reject NaN and infinities, which are not valid JSON numbers."""

    raise ValueError("non-finite number {!r} is not valid JSON".format(value))


def load_json_document(path: Path, label: str) -> Any:
    """Read strict JSON from disk with explicit, sanitized errors."""

    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(
                handle,
                object_pairs_hook=reject_duplicate_keys,
                parse_constant=reject_non_finite_number,
            )
    except json.JSONDecodeError as exc:
        raise ValidationInputError(
            "{} {} is not valid JSON at line {}, column {}: {}".format(
                label, path.as_posix(), exc.lineno, exc.colno, exc.msg
            )
        )
    except (DuplicateKeyError, ValueError) as exc:
        raise ValidationInputError(
            "{} {} is not valid JSON: {}".format(label, path.as_posix(), exc)
        )
    except (OSError, UnicodeError) as exc:
        raise ValidationInputError(
            "cannot read {} {}: {}".format(label, path.as_posix(), exc)
        )


def add_problem(
    problems: List[Problem], change_id: str, rule: str, message: str
) -> None:
    problems.append(Problem(change_id=change_id, rule=rule, message=message))


def sorted_problems(problems: Sequence[Problem]) -> List[Problem]:
    """Return stable ordering independent of dictionary or filesystem ordering."""

    return sorted(
        problems,
        key=lambda item: (item.change_id, item.rule, item.message),
    )


def is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_non_empty_string(
    value: Any,
    field: str,
    change_id: str,
    rule: str,
    problems: List[Problem],
) -> bool:
    if not is_non_empty_string(value):
        add_problem(
            problems,
            change_id,
            rule,
            "{} must be a non-empty string".format(field),
        )
        return False
    return True


def change_label(change: Mapping[str, Any], index: int) -> str:
    value = change.get("id")
    if is_non_empty_string(value):
        return str(value).strip()
    return "changes[{}]".format(index)


def validate_snapshot(
    change: Mapping[str, Any], change_id: str, plan_path: Path, problems: List[Problem]
) -> None:
    snapshot = change.get("snapshot")
    if not isinstance(snapshot, dict):
        add_problem(
            problems,
            change_id,
            "snapshot",
            "snapshot must be an object with required and artifact fields",
        )
        return

    if "required" not in snapshot:
        add_problem(problems, change_id, "snapshot", "snapshot.required is missing")
        snapshot_required = None
    else:
        snapshot_required = snapshot.get("required")
        if type(snapshot_required) is not bool:
            add_problem(
                problems,
                change_id,
                "snapshot",
                "snapshot.required must be a boolean",
            )

    if "artifact" not in snapshot:
        add_problem(problems, change_id, "snapshot", "snapshot.artifact is missing")
        artifact = None
    else:
        artifact = snapshot.get("artifact")
        if artifact is not None and not isinstance(artifact, str):
            add_problem(
                problems,
                change_id,
                "snapshot",
                "snapshot.artifact must be a string or null",
            )

    if snapshot_required is not True:
        return
    if not is_non_empty_string(artifact):
        add_problem(
            problems,
            change_id,
            "snapshot",
            "snapshot.required is true but snapshot.artifact is not set",
        )
        return
    assert isinstance(artifact, str)
    if "\\" in artifact:
        add_problem(
            problems,
            change_id,
            "snapshot",
            "snapshot.artifact must use forward slashes",
        )
        return

    artifact_path = Path(artifact)
    if not artifact_path.is_absolute():
        artifact_path = plan_path.parent / artifact_path
    try:
        if not artifact_path.is_file():
            add_problem(
                problems,
                change_id,
                "snapshot",
                "snapshot artifact does not exist as a file: {}".format(
                    artifact_path.as_posix()
                ),
            )
            return
        if artifact_path.stat().st_size <= 0:
            add_problem(
                problems,
                change_id,
                "snapshot",
                "snapshot artifact is empty: {}".format(artifact_path.as_posix()),
            )
    except OSError as exc:
        add_problem(
            problems,
            change_id,
            "snapshot",
            "snapshot artifact could not be verified at {}: {}".format(
                artifact_path.as_posix(), exc
            ),
        )


def validate_approval(
    change: Mapping[str, Any], change_id: str, problems: List[Problem]
) -> None:
    approval = change.get("approval")
    if not isinstance(approval, dict):
        add_problem(
            problems,
            change_id,
            "approval",
            "approval must be an object with required and granted fields",
        )
        return

    required = approval.get("required")
    granted = approval.get("granted")
    if "required" not in approval:
        add_problem(problems, change_id, "approval", "approval.required is missing")
    elif type(required) is not bool:
        add_problem(
            problems,
            change_id,
            "approval",
            "approval.required must be a boolean",
        )
    if "granted" not in approval:
        add_problem(problems, change_id, "approval", "approval.granted is missing")
    elif type(granted) is not bool:
        add_problem(
            problems,
            change_id,
            "approval",
            "approval.granted must be a boolean",
        )

    if required is True and granted is not True:
        add_problem(
            problems,
            change_id,
            "approval",
            "approval.required is true but approval.granted is not exactly boolean true",
        )


def validate_purge_layers(
    change: Mapping[str, Any],
    change_id: str,
    present_layers: Set[str],
    plan_reports_cache: bool,
    problems: List[Problem],
) -> None:
    purge_layers = change.get("purge_layers")
    if not isinstance(purge_layers, list):
        add_problem(
            problems,
            change_id,
            "purge_layers",
            "purge_layers must be an array",
        )
        return
    if plan_reports_cache and not purge_layers:
        add_problem(
            problems,
            change_id,
            "purge_layers",
            "purge_layers must not be empty when cache_layers_present is non-empty",
        )

    seen: Set[str] = set()
    for index, layer in enumerate(purge_layers):
        if not isinstance(layer, str) or layer not in CACHE_LAYERS:
            add_problem(
                problems,
                change_id,
                "purge_layers",
                "purge_layers[{}] must be one of {}".format(
                    index, " | ".join(CACHE_LAYERS)
                ),
            )
            continue
        if layer in seen:
            add_problem(
                problems,
                change_id,
                "purge_layers",
                "purge_layers contains duplicate layer {!r}".format(layer),
            )
        seen.add(layer)
        if layer not in present_layers:
            add_problem(
                problems,
                change_id,
                "purge_layers",
                "purge layer {!r} is not listed in cache_layers_present".format(layer),
            )


def validate_expected_effect(
    change: Mapping[str, Any], change_id: str, problems: List[Problem]
) -> None:
    expected_effect = change.get("expected_effect")
    if not isinstance(expected_effect, dict):
        add_problem(
            problems,
            change_id,
            "expected_effect",
            "expected_effect must be an object with metric, url, and direction",
        )
        return
    for field in ("metric", "url", "direction"):
        validate_non_empty_string(
            expected_effect.get(field),
            "expected_effect.{}".format(field),
            change_id,
            "expected_effect",
            problems,
        )


def resolve_catalog_entry(
    value: Any,
    change_id: str,
    repo_root: Path,
    problems: List[Problem],
) -> None:
    if not validate_non_empty_string(
        value, "catalog_entry", change_id, "catalog_entry", problems
    ):
        return
    assert isinstance(value, str)
    if "\\" in value:
        add_problem(
            problems,
            change_id,
            "catalog_entry",
            "catalog_entry must use forward slashes",
        )
        return
    relative = Path(value)
    if relative.is_absolute():
        add_problem(
            problems,
            change_id,
            "catalog_entry",
            "catalog_entry must be relative to {}".format(
                CATALOG_RELATIVE_PATH.as_posix()
            ),
        )
        return

    catalog_root = repo_root / CATALOG_RELATIVE_PATH
    candidate = catalog_root / relative
    try:
        resolved_root = catalog_root.resolve(strict=True)
        resolved_candidate = candidate.resolve(strict=True)
        resolved_candidate.relative_to(resolved_root)
        if not resolved_candidate.is_file():
            raise OSError("resolved path is not a file")
    except (OSError, RuntimeError, ValueError) as exc:
        add_problem(
            problems,
            change_id,
            "catalog_entry",
            "catalog_entry does not resolve to a file under {}: {} ({})".format(
                CATALOG_RELATIVE_PATH.as_posix(), value, exc
            ),
        )


def validate_target_and_tier(
    change: Mapping[str, Any],
    change_id: str,
    plan_tier: Any,
    problems: List[Problem],
) -> None:
    target = change.get("target")
    if not isinstance(target, dict):
        add_problem(
            problems,
            change_id,
            "target.kind",
            "target must be an object with kind and identifier",
        )
        return

    kind = target.get("kind")
    if not isinstance(kind, str) or kind not in MINIMUM_TIER_BY_TARGET_KIND:
        add_problem(
            problems,
            change_id,
            "target.kind",
            "target.kind must be one of {}".format(
                " | ".join(sorted(MINIMUM_TIER_BY_TARGET_KIND))
            ),
        )
    else:
        minimum_tier = MINIMUM_TIER_BY_TARGET_KIND[str(kind)]
        if minimum_tier is None:
            add_problem(
                problems,
                change_id,
                "tier",
                "target.kind {!r} is outside wp-perf-fix; no tier is sufficient and the operator must act".format(
                    kind
                ),
            )
        elif type(plan_tier) is not int:
            add_problem(
                problems,
                change_id,
                "tier",
                "plan tier is not a confirmed integer, so tier {} for target.kind {!r} cannot be established".format(
                    minimum_tier, kind
                ),
            )
        elif plan_tier < minimum_tier:
            add_problem(
                problems,
                change_id,
                "tier",
                "target.kind {!r} requires tier {} but the plan has tier {}".format(
                    kind, minimum_tier, plan_tier
                ),
            )

    validate_non_empty_string(
        target.get("identifier"),
        "target.identifier",
        change_id,
        "target.kind",
        problems,
    )


def validate_change(
    change: Any,
    index: int,
    plan_path: Path,
    repo_root: Path,
    plan_tier: Any,
    present_layers: Set[str],
    plan_reports_cache: bool,
    problems: List[Problem],
) -> Optional[str]:
    if not isinstance(change, dict):
        change_id = "changes[{}]".format(index)
        add_problem(
            problems,
            change_id,
            "document_shape",
            "change entry must be an object",
        )
        return None

    change_id = change_label(change, index)
    for key in REQUIRED_CHANGE_KEYS:
        if key not in change:
            add_problem(
                problems,
                change_id,
                "document_shape",
                "change is missing required key {!r}".format(key),
            )

    raw_id = change.get("id")
    if not is_non_empty_string(raw_id):
        add_problem(
            problems,
            change_id,
            "document_shape",
            "change.id must be a non-empty string",
        )
        usable_id = None
    else:
        assert isinstance(raw_id, str)
        usable_id = raw_id
        if raw_id != raw_id.strip():
            add_problem(
                problems,
                change_id,
                "document_shape",
                "change.id must not have leading or trailing whitespace",
            )

    validate_non_empty_string(
        change.get("summary"),
        "summary",
        change_id,
        "document_shape",
        problems,
    )
    validate_non_empty_string(
        change.get("rollback"),
        "rollback",
        change_id,
        "document_shape",
        problems,
    )

    risk_lane = change.get("risk_lane")
    if risk_lane not in RISK_LANES:
        add_problem(
            problems,
            change_id,
            "risk_lane",
            "risk_lane must be one of {}".format(" | ".join(RISK_LANES)),
        )
    elif risk_lane == "prohibited":
        add_problem(
            problems,
            change_id,
            "risk_lane",
            "risk_lane is prohibited; the whole plan is refused because it was built on an unsafe understanding of the environment",
        )

    validate_snapshot(change, change_id, plan_path, problems)
    validate_approval(change, change_id, problems)
    validate_purge_layers(
        change,
        change_id,
        present_layers,
        plan_reports_cache,
        problems,
    )
    validate_expected_effect(change, change_id, problems)
    resolve_catalog_entry(change.get("catalog_entry"), change_id, repo_root, problems)
    validate_target_and_tier(change, change_id, plan_tier, problems)
    return usable_id


def validate_plan_cache_layers(
    value: Any, problems: List[Problem]
) -> Tuple[Set[str], bool]:
    present_layers: Set[str] = set()
    if not isinstance(value, list):
        add_problem(
            problems,
            "plan",
            "document_shape",
            "cache_layers_present must be an array",
        )
        return present_layers, False

    for index, layer in enumerate(value):
        if not isinstance(layer, str) or layer not in CACHE_LAYERS:
            add_problem(
                problems,
                "plan",
                "document_shape",
                "cache_layers_present[{}] must be one of {}".format(
                    index, " | ".join(CACHE_LAYERS)
                ),
            )
            continue
        if layer in present_layers:
            add_problem(
                problems,
                "plan",
                "document_shape",
                "cache_layers_present contains duplicate layer {!r}".format(layer),
            )
        present_layers.add(layer)
    return present_layers, bool(value)


def known_signal_value(
    signal: Any, field: str, rule: str, problems: List[Problem]
) -> Optional[str]:
    if not isinstance(signal, dict):
        add_problem(
            problems,
            "plan",
            rule,
            "stack {} must be an evidence-bearing signal object".format(field),
        )
        return None
    value = signal.get("value")
    confidence = signal.get("confidence")
    evidence = signal.get("evidence")
    if not is_non_empty_string(value) or value == "unknown":
        add_problem(
            problems,
            "plan",
            rule,
            "stack {} is unknown, so it cannot be positively cross-checked".format(field),
        )
        return None
    if confidence not in HOST_CROSSCHECK_CONFIDENCES:
        add_problem(
            problems,
            "plan",
            rule,
            "stack {} is not high-confidence, so it cannot authorize a production write".format(
                field
            ),
        )
        return None
    if not isinstance(evidence, list) or not evidence or not all(
        is_non_empty_string(item) for item in evidence
    ):
        add_problem(
            problems,
            "plan",
            rule,
            "stack {} has a known value without non-empty evidence".format(field),
        )
        return None
    return str(value)


def stack_cache_layers(stack: Mapping[str, Any], problems: List[Problem]) -> Optional[Set[str]]:
    entries = stack.get("cache_layers")
    if not isinstance(entries, list):
        add_problem(
            problems,
            "plan",
            "stack_cache_layers",
            "stack cache_layers must be an array",
        )
        return None
    if len(entries) != len(STACK_CACHE_LAYER_ORDER):
        add_problem(
            problems,
            "plan",
            "stack_cache_layers",
            "stack cache_layers must contain exactly one entry for each layer",
        )
        return None

    found: Set[str] = set()
    reliable = True
    for index, expected_layer in enumerate(STACK_CACHE_LAYER_ORDER):
        entry = entries[index]
        if not isinstance(entry, dict):
            add_problem(
                problems,
                "plan",
                "stack_cache_layers",
                "stack cache_layers[{}] must be an object".format(index),
            )
            reliable = False
            continue
        layer = entry.get("layer")
        if layer != expected_layer:
            add_problem(
                problems,
                "plan",
                "stack_cache_layers",
                "stack cache_layers[{}].layer must be {!r}, found {!r}".format(
                    index, expected_layer, layer
                ),
            )
            reliable = False
            continue
        value = entry.get("value")
        confidence = entry.get("confidence")
        evidence = entry.get("evidence")
        if not is_non_empty_string(value):
            add_problem(
                problems,
                "plan",
                "stack_cache_layers",
                "stack cache layer {!r} has no usable value".format(layer),
            )
            reliable = False
            continue
        if value not in CACHE_VALUES_BY_LAYER[expected_layer]:
            add_problem(
                problems,
                "plan",
                "stack_cache_layers",
                "stack cache layer {!r} has out-of-vocabulary value {!r}".format(
                    layer, value
                ),
            )
            reliable = False
            continue

        if value == "unknown":
            if confidence != "none" or evidence != []:
                add_problem(
                    problems,
                    "plan",
                    "stack_cache_layers",
                    "unknown stack cache layer {!r} must have confidence 'none' and empty evidence".format(
                        layer
                    ),
                )
                reliable = False
            continue

        if confidence not in CACHE_CROSSCHECK_CONFIDENCES or not isinstance(evidence, list) or not evidence or not all(
            is_non_empty_string(item) for item in evidence
        ):
            add_problem(
                problems,
                "plan",
                "stack_cache_layers",
                "known stack cache layer {!r} must have high or medium confidence and non-empty evidence".format(
                    layer
                ),
            )
            reliable = False
            continue
        if value != "none":
            found.add(str(layer))
    return found if reliable else None


def cross_check_stack(
    document: Mapping[str, Any], stack: Any, problems: List[Problem]
) -> None:
    if not isinstance(stack, dict):
        add_problem(
            problems,
            "plan",
            "stack_shape",
            "stack profile top-level JSON value must be an object",
        )
        return
    if stack.get("schema_version") != SCHEMA_VERSION:
        add_problem(
            problems,
            "plan",
            "stack_shape",
            "stack schema_version must be {!r}, found {!r}".format(
                SCHEMA_VERSION, stack.get("schema_version")
            ),
        )
    if stack.get("tool") != "fingerprint":
        add_problem(
            problems,
            "plan",
            "stack_shape",
            "stack tool must be 'fingerprint', found {!r}".format(stack.get("tool")),
        )

    profile = stack.get("profile")
    if not isinstance(profile, dict):
        add_problem(
            problems,
            "plan",
            "stack_host_class",
            "stack profile must be an object",
        )
    else:
        stack_host = known_signal_value(
            profile.get("host_class"),
            "profile.host_class",
            "stack_host_class",
            problems,
        )
        plan_host = document.get("host_class")
        if stack_host is not None and plan_host != stack_host:
            add_problem(
                problems,
                "plan",
                "stack_host_class",
                "plan host_class {!r} does not match stack host_class {!r}".format(
                    plan_host, stack_host
                ),
            )

    found_layers = stack_cache_layers(stack, problems)
    plan_layers = document.get("cache_layers_present")
    if found_layers is not None and isinstance(plan_layers, list):
        comparable_plan_layers = {
            layer for layer in plan_layers if isinstance(layer, str) and layer in CACHE_LAYERS
        }
        if comparable_plan_layers != found_layers or len(comparable_plan_layers) != len(plan_layers):
            add_problem(
                problems,
                "plan",
                "stack_cache_layers",
                "plan cache_layers_present {} does not match stack layers actually found {}".format(
                    sorted(comparable_plan_layers), sorted(found_layers)
                ),
            )


def validate_plan(
    document: Any,
    plan_path: Path,
    repo_root: Path,
    stack: Optional[Any] = None,
) -> List[Problem]:
    """Apply every safety rule and return all problems without short-circuiting."""

    problems: List[Problem] = []
    if not isinstance(document, dict):
        add_problem(
            problems,
            "plan",
            "document_shape",
            "top-level JSON value must be an object",
        )
        return sorted_problems(problems)

    for key in REQUIRED_PLAN_KEYS:
        if key not in document:
            add_problem(
                problems,
                "plan",
                "document_shape",
                "plan is missing required key {!r}".format(key),
            )

    if document.get("schema_version") != SCHEMA_VERSION:
        add_problem(
            problems,
            "plan",
            "document_shape",
            "schema_version must be {!r}, found {!r}".format(
                SCHEMA_VERSION, document.get("schema_version")
            ),
        )
    if document.get("tool") != "change-plan":
        add_problem(
            problems,
            "plan",
            "document_shape",
            "tool must be 'change-plan', found {!r}".format(document.get("tool")),
        )
    for field in ("tool_version", "generated_at", "site", "baseline_metrics"):
        validate_non_empty_string(
            document.get(field), field, "plan", "document_shape", problems
        )

    host_class = document.get("host_class")
    if host_class not in HOST_CLASSES:
        add_problem(
            problems,
            "plan",
            "document_shape",
            "host_class must be a closed-vocabulary value, found {!r}".format(
                host_class
            ),
        )

    tier = document.get("tier")
    if type(tier) is not int or tier < 0 or tier > 3:
        add_problem(
            problems,
            "plan",
            "document_shape",
            "tier must be a confirmed integer from 0 through 3",
        )

    present_layers, plan_reports_cache = validate_plan_cache_layers(
        document.get("cache_layers_present"), problems
    )

    changes = document.get("changes")
    if not isinstance(changes, list):
        add_problem(
            problems,
            "plan",
            "document_shape",
            "changes must be a non-empty array",
        )
    elif not changes:
        add_problem(
            problems,
            "plan",
            "document_shape",
            "changes must contain at least one change",
        )
    else:
        seen_ids: Dict[str, int] = {}
        for index, change in enumerate(changes):
            usable_id = validate_change(
                change,
                index,
                plan_path,
                repo_root,
                tier,
                present_layers,
                plan_reports_cache,
                problems,
            )
            if usable_id is None:
                continue
            if usable_id in seen_ids:
                add_problem(
                    problems,
                    usable_id.strip(),
                    "document_shape",
                    "change.id {!r} duplicates changes[{}]".format(
                        usable_id, seen_ids[usable_id]
                    ),
                )
            else:
                seen_ids[usable_id] = index

    if stack is not None:
        cross_check_stack(document, stack, problems)
    return sorted_problems(problems)


def machine_summary(plan_path: Path, problems: Sequence[Problem]) -> Dict[str, Any]:
    ordered = sorted_problems(problems)
    return {
        "plan": plan_path.as_posix(),
        "problem_count": len(ordered),
        "problems": [
            {
                "change_id": problem.change_id,
                "message": problem.message,
                "rule": problem.rule,
            }
            for problem in ordered
        ],
        "schema_version": SCHEMA_VERSION,
        "status": "valid" if not ordered else "invalid",
        "tool": "validate-plan",
        "tool_version": TOOL_VERSION,
        "valid": not ordered,
    }


def human_report(plan_path: Path, problems: Sequence[Problem]) -> str:
    ordered = sorted_problems(problems)
    if not ordered:
        return "Change plan VALID: {}\nProblems: 0\n".format(plan_path.as_posix())
    lines = [
        "Change plan INVALID: {}".format(plan_path.as_posix()),
        "Problems: {}".format(len(ordered)),
    ]
    lines.extend(
        "  - [change {}] rule {}: {}".format(
            problem.change_id, problem.rule, problem.message
        )
        for problem in ordered
    )
    return "\n".join(lines) + "\n"


def json_text(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def write_outputs(
    plan_path: Path,
    problems: Sequence[Problem],
    json_destination: Optional[str],
    quiet: bool,
) -> None:
    destination = json_destination
    if quiet and destination is None:
        destination = "-"

    report = human_report(plan_path, problems)
    summary = json_text(machine_summary(plan_path, problems))
    if not quiet:
        report_stream = sys.stderr if destination == "-" else sys.stdout
        report_stream.write(report)

    if destination == "-":
        sys.stdout.write(summary)
    elif destination is not None:
        output_path = Path(destination)
        try:
            with output_path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(summary)
        except (OSError, UnicodeError) as exc:
            raise ValidationInputError(
                "cannot write JSON output {}: {}".format(output_path.as_posix(), exc)
            )


def selftest_plan() -> Dict[str, Any]:
    """Return a complete plan that each refusal case mutates independently."""

    return {
        "baseline_metrics": "baseline.json",
        "cache_layers_present": ["server"],
        "changes": [
            {
                "approval": {"granted": True, "required": True},
                "catalog_entry": "frontend/selftest.md",
                "expected_effect": {
                    "direction": "decrease",
                    "metric": "edge_ttfb_ms",
                    "url": "selftest-url",
                },
                "id": "c1",
                "purge_layers": ["server"],
                "risk_lane": "direct",
                "rollback": "Restore snapshot.bak and purge server.",
                "snapshot": {"artifact": "snapshot.bak", "required": True},
                "summary": "Change one cache setting.",
                "target": {"identifier": "cache-setting", "kind": "plugin-setting"},
            }
        ],
        "generated_at": "selftest",
        "host_class": "self-managed",
        "schema_version": SCHEMA_VERSION,
        "site": "selftest-site",
        "tier": 1,
        "tool": "change-plan",
        "tool_version": TOOL_VERSION,
    }


def render_selftest_problems(problems: Sequence[Problem]) -> List[str]:
    return [
        "       - [change {}] rule {}: {}".format(
            problem.change_id, problem.rule, problem.message
        )
        for problem in sorted_problems(problems)
    ]


def run_selftest() -> int:
    """Exercise one accepted plan and four unsafe plans using temporary fixtures."""

    lines = ["validate_plan.py self-test"]
    passed = 0
    total = 5
    try:
        with tempfile.TemporaryDirectory(prefix="validate-plan-selftest-") as temp_name:
            root = Path(temp_name)
            catalog = root / CATALOG_RELATIVE_PATH / "frontend"
            catalog.mkdir(parents=True)
            (catalog / "selftest.md").write_text(
                "<!-- SPDX-License-Identifier: GPL-2.0-or-later -->\n# Self-test\n",
                encoding="utf-8",
            )
            (root / "snapshot.bak").write_bytes(b"verified snapshot\n")
            plan_path = root / "plan.json"
            base = selftest_plan()

            valid_problems = validate_plan(base, plan_path, root)
            if not valid_problems:
                passed += 1
                lines.append("[PASS] valid plan accepted (0 problems)")
            else:
                lines.append(
                    "[FAIL] valid plan rejected ({} problem(s))".format(
                        len(valid_problems)
                    )
                )
                lines.extend(render_selftest_problems(valid_problems))

            cases: List[Tuple[str, Dict[str, Any], str]] = []

            prohibited = copy.deepcopy(base)
            prohibited["changes"][0]["risk_lane"] = "prohibited"
            cases.append(("prohibited change refused", prohibited, "risk_lane"))

            missing_snapshot = copy.deepcopy(base)
            missing_snapshot["changes"][0]["snapshot"]["artifact"] = "missing.bak"
            cases.append(("missing snapshot refused", missing_snapshot, "snapshot"))

            approval_not_granted = copy.deepcopy(base)
            approval_not_granted["changes"][0]["approval"]["granted"] = False
            cases.append(("ungranted approval refused", approval_not_granted, "approval"))

            wrong_purge = copy.deepcopy(base)
            wrong_purge["changes"][0]["purge_layers"] = ["edge"]
            cases.append(
                ("purge of a layer not present refused", wrong_purge, "purge_layers")
            )

            for label, case, expected_rule in cases:
                case_problems = validate_plan(case, plan_path, root)
                has_expected_rule = any(
                    problem.rule == expected_rule for problem in case_problems
                )
                if case_problems and has_expected_rule:
                    passed += 1
                    lines.append(
                        "[PASS] {} ({} problem(s))".format(label, len(case_problems))
                    )
                else:
                    lines.append(
                        "[FAIL] {} (expected rule {}, got {} problem(s))".format(
                            label, expected_rule, len(case_problems)
                        )
                    )
                lines.extend(render_selftest_problems(case_problems))
    except (OSError, UnicodeError) as exc:
        lines.append("[FAIL] self-test fixture setup failed: {}".format(exc))

    status = "PASS" if passed == total else "FAIL"
    lines.append("Self-test result: {} ({}/{})".format(status, passed, total))
    sys.stdout.write("\n".join(lines) + "\n")
    return EXIT_VALID if passed == total else EXIT_INVALID


def inferred_repo_root() -> Path:
    """Infer the repository root from skills/wp-perf-fix/scripts/validate_plan.py."""

    return Path(__file__).resolve().parents[3]


def build_parser() -> argparse.ArgumentParser:
    parser = GateArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("plan", nargs="?", metavar="PLAN.json", help="change plan to validate")
    parser.add_argument("--stack", metavar="STACK.json", help="fingerprint profile to cross-check")
    parser.add_argument(
        "--repo-root",
        metavar="PATH",
        help="repository root used to resolve catalog entries",
    )
    parser.add_argument("--json", metavar="OUT", help="write JSON summary; - means stdout")
    parser.add_argument("--quiet", action="store_true", help="suppress human report; JSON only")
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run built-in acceptance and refusal cases",
    )
    return parser


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.selftest:
        if any(
            value is not None
            for value in (args.plan, args.stack, args.repo_root, args.json)
        ) or args.quiet:
            raise UsageError("--selftest cannot be combined with plan or output options")
        return run_selftest()
    if args.plan is None:
        raise UsageError("PLAN.json is required unless --selftest is used")

    plan_path = Path(args.plan)
    repo_root = Path(args.repo_root) if args.repo_root else inferred_repo_root()
    try:
        if not repo_root.is_dir():
            raise UsageError(
                "--repo-root is not a directory: {}".format(repo_root.as_posix())
            )
    except OSError as exc:
        raise UsageError(
            "--repo-root cannot be inspected at {}: {}".format(
                repo_root.as_posix(), exc
            )
        )

    document = load_json_document(plan_path, "plan")
    stack = (
        load_json_document(Path(args.stack), "stack profile")
        if args.stack is not None
        else None
    )
    problems = validate_plan(document, plan_path, repo_root, stack)
    write_outputs(plan_path, problems, args.json, args.quiet)
    return EXIT_VALID if not problems else EXIT_INVALID


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Contain all failures so production operators never receive a traceback."""

    try:
        return run(argv)
    except UsageError as exc:
        sys.stderr.write("validate_plan.py: usage error: {}\n".format(exc))
        return EXIT_USAGE
    except ValidationInputError as exc:
        sys.stderr.write("validate_plan.py: {}\n".format(exc))
        return EXIT_UNREADABLE
    except BrokenPipeError:
        return EXIT_VALID
    except KeyboardInterrupt:
        sys.stderr.write("validate_plan.py: interrupted by operator\n")
        return EXIT_UNREADABLE
    except Exception as exc:  # Defensive CLI boundary: never expose a raw traceback.
        sys.stderr.write("validate_plan.py: validation could not complete: {}\n".format(exc))
        return EXIT_UNREADABLE


if __name__ == "__main__":
    sys.exit(main())
