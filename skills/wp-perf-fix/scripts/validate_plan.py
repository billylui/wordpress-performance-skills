# SPDX-License-Identifier: GPL-2.0-or-later
"""Fail closed when a WordPress change plan is unsafe at the requested gate.

Usage:
  python3 validate_plan.py PLAN.json [--stack STACK.json] [--repo-root PATH]
                           [--preflight] [--json OUT] [--quiet]
  python3 validate_plan.py --selftest

The validator performs no network access and never changes a target site.  Exit
0 means the plan passed the selected gate; exit 1 means that gate refused it.
"""

import argparse
import copy
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import urlsplit


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
# Approval is a contract-derived requirement for every executable change; a
# plan under inspection cannot weaken the gate by declaring approval optional.
EXECUTABLE_CHANGE_REQUIRES_APPROVAL = True
# A rollback snapshot is contract-derived for every executable change; this
# requirement remains true before the artifact is captured and at execution.
EXECUTABLE_CHANGE_REQUIRES_SNAPSHOT = True
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
# path (tier 3); raw options require exact CLI read/write and rollback (tier 2);
# exposed plugin settings, builder content, and media require admin (tier 1).
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
    "wp-option": 2,
}
# The contract permits direct changes generally, but executable PHP-bearing
# file targets must reach staging-first before production execution.
MINIMUM_RISK_LANE_BY_TARGET_KIND: Mapping[str, str] = {
    "builder-content": "direct",
    "dns-or-cdn-setting": "direct",
    "media": "direct",
    "mu-plugin": "staging-first",
    "plugin-file": "staging-first",
    "plugin-setting": "direct",
    "server-config": "direct",
    "theme-file": "staging-first",
    "wp-option": "direct",
}
# Change kinds that live in files, so staging can be promoted by pushing FILES ONLY. Everything
# else lives in the database and must be RE-APPLIED on production: Kinsta documents that a
# database push loses "comments, new content, purchases on ecommerce sites, sign-ups on membership
# sites, and forum posts" made since the staging copy. A page-speed win is not worth lost orders,
# and a large share of performance fixes are database changes.
FILE_BACKED_TARGET_KINDS = ("theme-file", "plugin-file", "mu-plugin")
# A code change with no staging is the one real risk here: a PHP fatal takes the whole site down.
# It is still permitted — most WordPress sites have no staging, and refusing would make the skill
# unusable rather than safe — but the plan must say which compensating controls were applied.
COMPENSATING_CONTROL_KEYS = ("mechanism", "verification", "rollback_trigger")

# The machine-readable half of host-constraints.md, loaded from the skill's own references/ so an
# installed copy carries it. tools/check_host_policy.py fails the build if the two ever disagree.
HOST_POLICY_FILENAME = "host-policy.json"
# A page-cache verdict only applies to a change that targets a plugin. Other kinds are not yet
# encoded, and silently gating them on a page-cache table would refuse unrelated work.
PAGE_CACHE_TARGET_KINDS = ("plugin-setting", "plugin-file")

# Numeric ranks make minimum-lane comparisons explicit; prohibited is handled
# as an unconditional refusal and therefore intentionally has no rank.
RISK_LANE_RANK: Mapping[str, int] = {
    "direct": 0,
    "staging-first": 1,
}

# The stack profile contract fixes both membership and order for cache-layer entries.
STACK_CACHE_LAYER_ORDER = CACHE_LAYERS
# Cache-layer presence may be corroborated at medium confidence, but a single
# low-confidence signal cannot authorize a purge.
#
# There is deliberately no equivalent confidence gate for host_class: the plan's
# host_class is the operator's declaration and the fingerprint is a contradiction
# check, so gating on the fingerprint's confidence blocked correct plans while
# leaving genuine contradictions unexamined. See cross_check_stack.
CACHE_CROSSCHECK_CONFIDENCES = ("high", "medium")
# WordPress site origins must be HTTP(S); other URI schemes cannot bind a live
# fingerprint to a production change plan.
ORIGIN_SCHEMES = ("http", "https")
# Effective default ports make an omitted port compare equal to the explicit
# default while preserving scheme as part of the origin.
DEFAULT_PORT_BY_ORIGIN_SCHEME: Mapping[str, int] = {
    "http": 80,
    "https": 443,
}
# TCP port zero is not a usable remote service port for a production target.
MINIMUM_USABLE_ORIGIN_PORT = 1
# TCP port numbers are unsigned 16-bit values; larger values are unusable.
MAXIMUM_USABLE_ORIGIN_PORT = 65535

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
    change: Mapping[str, Any],
    change_id: str,
    plan_path: Path,
    execution_readiness: bool,
    problems: List[Problem],
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
    else:
        snapshot_required = snapshot.get("required")
        if type(snapshot_required) is not bool:
            add_problem(
                problems,
                change_id,
                "snapshot",
                "snapshot.required must be a boolean",
            )
        elif snapshot_required is not EXECUTABLE_CHANGE_REQUIRES_SNAPSHOT:
            add_problem(
                problems,
                change_id,
                "snapshot",
                "snapshot.required is false but every executable change requires a snapshot",
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

    if not is_non_empty_string(artifact):
        add_problem(
            problems,
            change_id,
            "snapshot",
            "snapshot.artifact must name the required rollback snapshot",
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

    if not execution_readiness:
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
    change: Mapping[str, Any],
    change_id: str,
    execution_readiness: bool,
    problems: List[Problem],
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
    elif required is not EXECUTABLE_CHANGE_REQUIRES_APPROVAL:
        add_problem(
            problems,
            change_id,
            "approval",
            "approval.required is false but every executable change requires approval",
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

    if execution_readiness and granted is not True:
        add_problem(
            problems,
            change_id,
            "approval",
            "execution readiness requires approval.granted to be exactly boolean true",
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


def validate_risk_lane(
    change: Mapping[str, Any], change_id: str, problems: List[Problem]
) -> None:
    """Derive the minimum lane from target.kind, never from plan assertions."""

    risk_lane = change.get("risk_lane")
    if risk_lane not in RISK_LANES:
        add_problem(
            problems,
            change_id,
            "risk_lane",
            "risk_lane must be one of {}".format(" | ".join(RISK_LANES)),
        )
        return
    if risk_lane == "prohibited":
        add_problem(
            problems,
            change_id,
            "risk_lane",
            "risk_lane is prohibited; the whole plan is refused because it was built on an unsafe understanding of the environment",
        )
        return

    target = change.get("target")
    kind = target.get("kind") if isinstance(target, dict) else None
    if not isinstance(kind, str):
        return
    minimum_lane = MINIMUM_RISK_LANE_BY_TARGET_KIND.get(kind)
    if minimum_lane is None:
        return
    if RISK_LANE_RANK[str(risk_lane)] < RISK_LANE_RANK[minimum_lane]:
        add_problem(
            problems,
            change_id,
            "risk_lane",
            "target.kind {!r} requires risk_lane {!r} at minimum, found {!r}".format(
                kind, minimum_lane, risk_lane
            ),
        )


def has_compensating_controls(value: Any) -> bool:
    """Accept only a fully stated set of controls, never a bare assertion of care."""

    if not isinstance(value, dict):
        return False
    return all(is_non_empty_string(value.get(key)) for key in COMPENSATING_CONTROL_KEYS)


def validate_staging(
    change: Mapping[str, Any],
    change_id: str,
    plan_staging: Any,
    problems: List[Problem],
) -> None:
    """Require staging OR stated compensating controls for a code change — never neither.

    Staging is a capability, not a precondition. Most WordPress sites have none, and refusing to
    work on them would make this skill unused rather than safe; the audit side already settled the
    same question by treating tier 0 as complete rather than degraded.

    So this never refuses a change for lacking staging. It refuses a code change that has neither
    staging nor a stated plan for surviving without it, because that combination is how a PHP fatal
    reaches a production site nobody could roll back quickly.

    Deliberately scoped to file-backed targets. A `wp-option` or `plugin-setting` change is
    reversible by setting the value back, and its snapshot already captures the prior value.
    """

    target = change.get("target")
    kind = target.get("kind") if isinstance(target, dict) else None
    if kind not in FILE_BACKED_TARGET_KINDS:
        return

    declared = isinstance(plan_staging, dict) and is_non_empty_string(plan_staging.get("url"))
    if declared:
        if not is_non_empty_string(plan_staging.get("confirmed_by")):
            add_problem(
                problems,
                change_id,
                "staging",
                "staging.url is declared but staging.confirmed_by is empty. Name something a human "
                "could check — a control-panel environment, a host support response, or how the "
                "operator created it. Nothing observable from outside proves a URL is this site's "
                "staging environment, and being wrong points this write at another installation.",
            )
        return

    if has_compensating_controls(change.get("compensating_controls")):
        return

    add_problem(
        problems,
        change_id,
        "staging",
        "target.kind {!r} changes code on a site with no declared staging, and the change states no "
        "compensating controls. This is not a refusal of the work — most WordPress sites have no "
        "staging — but a PHP fatal here takes the whole site down, so say how that is being managed: "
        "compensating_controls needs {}. Check first whether the host provides one-click staging; "
        "several managed hosts do. See references/staging.md.".format(
            kind, ", ".join(repr(key) for key in COMPENSATING_CONTROL_KEYS)
        ),
    )


def validate_plan_sequence_rationale(document: Mapping[str, Any], problems: List[Problem]) -> None:
    """Require a stated ordering when a plan queues more than one change."""

    changes = document.get("changes")
    if not isinstance(changes, list) or len(changes) < 2:
        return
    if is_non_empty_string(document.get("sequence_rationale")):
        return
    add_problem(
        problems,
        "plan",
        "sequence",
        "this plan queues {} changes but has no sequence_rationale. The queue is executed one "
        "change at a time, so the order is a decision: say why this one — what each change depends "
        "on, and what would be mis-attributed if they ran in another order. A plan with several "
        "changes and no stated reasoning is an unordered pile.".format(len(changes)),
    )


def load_host_policy() -> Mapping[str, Any]:
    """Load the machine-readable host policy, or refuse the run.

    A missing or malformed policy file is not "no policy, so no problem" — it is the gate being
    absent, and this validator has already shipped one fail-open class. `ValidationInputError`
    exits with the unreadable code rather than letting a plan through unchecked.
    """

    path = Path(__file__).resolve().parent.parent / "references" / HOST_POLICY_FILENAME
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValidationInputError(
            "host policy {} is missing; the host-constraint gate cannot run and no plan can be "
            "validated without it".format(path.as_posix())
        )
    except (OSError, ValueError) as exc:
        raise ValidationInputError(
            "host policy {} could not be read: {}".format(path.as_posix(), exc)
        )
    hosts = document.get("hosts")
    plugins = document.get("page_cache_plugins")
    if not isinstance(hosts, dict) or not isinstance(plugins, list):
        raise ValidationInputError(
            "host policy {} is malformed: it needs a 'hosts' object and a 'page_cache_plugins' "
            "list".format(path.as_posix())
        )
    return document


def validate_host_policy(
    change: Mapping[str, Any],
    change_id: str,
    plan_host_class: Any,
    policy: Optional[Mapping[str, Any]],
    problems: List[Problem],
) -> None:
    """Refuse a page-cache change the host's published policy forbids.

    Until this existed, the gate the whole skill advertises was a label check: a change was refused
    only when the PLAN had already marked its risk_lane `prohibited`, and the agent wrote that
    label. A plan declaring host_class `wpengine` while activating WP Rocket — a page cache WP
    Engine's own disallowed list forbids — passed with zero problems.

    The verdict is computed from the policy table and the change's own target. Nothing in the plan
    can assert it, for the same reason `approval.required: false` is refused rather than obeyed.

    Scope: this covers a target whose identifier is a recognized page-cache plugin. A cache shipped
    under an unrecognized slug is not gated here, which the policy file records as a known limit.
    """

    if policy is None:
        return
    target = change.get("target")
    if not isinstance(target, dict):
        return
    kind = target.get("kind")
    identifier = target.get("identifier")
    if kind not in PAGE_CACHE_TARGET_KINDS or not isinstance(identifier, str):
        return
    slug = identifier.strip().lower()
    if slug not in {str(name).lower() for name in policy.get("page_cache_plugins", [])}:
        return

    hosts = policy.get("hosts", {})
    entry = hosts.get(plan_host_class) if isinstance(plan_host_class, str) else None
    if not isinstance(entry, dict):
        # An unmapped host is the restrictive lane, not an exemption.
        add_problem(
            problems,
            change_id,
            "host_policy",
            "host_class {!r} has no entry in {}, so its page-cache policy is unknown and the "
            "change is refused. Identify the provider, add its verdict with a first-party "
            "citation, or supply host_confirmation.".format(plan_host_class, HOST_POLICY_FILENAME),
        )
        return

    verdict = entry.get("page_cache")
    permitted = {str(name).lower() for name in entry.get("permitted_plugins", [])}
    reason = str(entry.get("reason", "")).strip()
    citations = [str(url) for url in entry.get("citations", []) if str(url).strip()]
    cite = " Cited: {}".format(", ".join(citations)) if citations else ""

    if verdict == "prohibited":
        add_problem(
            problems,
            change_id,
            "host_policy",
            "host {!r} prohibits page-cache plugin changes, so {!r} is refused. {}{} Operator "
            "confirmation cannot override a published prohibition; propose the host's own caching "
            "controls instead.".format(plan_host_class, slug, reason, cite),
        )
        return

    if verdict == "permitted-only" and slug in permitted:
        return

    confirmation = change.get("host_confirmation")
    if is_valid_host_confirmation(confirmation):
        return

    if verdict == "permitted-only":
        detail = "host {!r} permits only {} as a page cache".format(
            plan_host_class, ", ".join(sorted(permitted)) or "no named plugin"
        )
    elif verdict == "permitted-with-conditions":
        detail = "host {!r} permits a page cache only under stated conditions".format(
            plan_host_class
        )
    else:
        detail = "host {!r} has no first-party documentation settling this".format(plan_host_class)

    add_problem(
        problems,
        change_id,
        "host_policy",
        "{}, so {!r} is prohibited until confirmed. {}{} To proceed, obtain confirmation for the "
        "exact product and plugin and record it as host_confirmation with a non-empty 'source' "
        "naming the documentation or support response, and a 'scope' saying what was "
        "confirmed.".format(detail, slug, reason, cite),
    )


def is_valid_host_confirmation(value: Any) -> bool:
    """Accept only a confirmation a human could go and check.

    The field carries EVIDENCE, never a verdict. A plan that could state its own verdict would be
    the fail-open shape this validator already shipped once, in a more dangerous place.
    """

    if not isinstance(value, dict):
        return False
    return all(is_non_empty_string(value.get(key)) for key in ("source", "scope"))


def validate_change(
    change: Any,
    index: int,
    plan_path: Path,
    repo_root: Path,
    plan_tier: Any,
    present_layers: Set[str],
    plan_reports_cache: bool,
    execution_readiness: bool,
    problems: List[Problem],
    plan_host_class: Any = None,
    host_policy: Optional[Mapping[str, Any]] = None,
    plan_staging: Any = None,
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

    validate_risk_lane(change, change_id, problems)

    validate_host_policy(change, change_id, plan_host_class, host_policy, problems)

    validate_staging(change, change_id, plan_staging, problems)

    validate_snapshot(
        change,
        change_id,
        plan_path,
        execution_readiness,
        problems,
    )
    validate_approval(change, change_id, execution_readiness, problems)
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


def normalized_origin(value: Any) -> Optional[str]:
    """Return a comparable HTTP(S) scheme/host/effective-port origin."""

    if not is_non_empty_string(value):
        return None
    assert isinstance(value, str)
    try:
        parsed = urlsplit(value.strip())
        scheme = parsed.scheme.casefold()
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if scheme not in ORIGIN_SCHEMES or not hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if any(character.isspace() for character in hostname) or "\\" in hostname:
        return None

    normalized_host = hostname.casefold()
    effective_port = port if port is not None else DEFAULT_PORT_BY_ORIGIN_SCHEME[scheme]
    if not MINIMUM_USABLE_ORIGIN_PORT <= effective_port <= MAXIMUM_USABLE_ORIGIN_PORT:
        return None
    display_host = (
        "[{}]".format(normalized_host) if ":" in normalized_host else normalized_host
    )
    return "{}://{}:{}".format(scheme, display_host, effective_port)


# Path segments that make a URL's server-side resolution ambiguous. A proxy or web server may
# collapse these before routing, so any normalization chosen here could disagree with whatever
# actually served the request — and the disagreement is exactly what an attacker would aim for.
AMBIGUOUS_PATH_SEGMENTS = frozenset({".", ".."})

# Percent-encodings that can decode into a path separator or a dot segment on some servers.
AMBIGUOUS_PATH_ENCODINGS = ("%2f", "%5c", "%2e")


def canonical_site_identity(value: Any) -> Optional[str]:
    """Return a canonical identity string for a WordPress site URL, or None if unusable.

    **URL strings cannot be made to prove installation identity by comparison alone.** Three
    review rounds established that the hard way: comparing origins treats
    `https://example.com/site-a/` and `/site-b/` as one site; adding path containment then
    treats a parent installation at `/` as containing a separate one mounted at `/shop/`; and
    dot segments such as `/site-a/../site-b/` resolve server-side to a sibling while still
    looking contained.

    So this does not infer containment at all. It canonicalizes, and the caller compares for
    EQUALITY. Both sides of that comparison are produced by this project's own tools, which can
    carry the identical site string by construction, so nothing is lost by refusing to guess.

    Ambiguity is refused rather than normalized: a path with a dot segment or an encoded
    separator returns None, because this code cannot know how the origin resolved it.
    """

    if not is_non_empty_string(value):
        return None
    assert isinstance(value, str)
    origin = normalized_origin(value)
    if origin is None:
        return None
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None

    raw_path = parsed.path
    lowered = raw_path.casefold()
    if any(encoding in lowered for encoding in AMBIGUOUS_PATH_ENCODINGS):
        return None
    segments = [segment for segment in raw_path.split("/") if segment]
    if any(segment in AMBIGUOUS_PATH_SEGMENTS for segment in segments):
        return None
    return "{}/{}".format(origin, "/".join(segments))


def identifies_same_installation(site_url: Any, probed_url: Any) -> Optional[bool]:
    """Whether two URLs name the same WordPress installation.

    Exact canonical equality — see `canonical_site_identity` for why containment was abandoned.
    Returns None when either URL is unusable or ambiguous, so the caller can report *why* rather
    than reporting a mismatch it cannot justify.
    """

    site_identity = canonical_site_identity(site_url)
    probed_identity = canonical_site_identity(probed_url)
    if site_identity is None or probed_identity is None:
        return None
    return site_identity == probed_identity


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

    plan_origin = normalized_origin(document.get("site"))
    stack_origin = normalized_origin(stack.get("target"))
    if plan_origin is None:
        add_problem(
            problems,
            "plan",
            "stack_origin",
            "plan site {!r} has no usable HTTP(S) origin for stack binding".format(
                document.get("site")
            ),
        )
    if stack_origin is None:
        add_problem(
            problems,
            "plan",
            "stack_origin",
            "stack target {!r} has no usable HTTP(S) origin for plan binding".format(
                stack.get("target")
            ),
        )
    elif plan_origin is not None and identifies_same_installation(
        document.get("site"), stack.get("target")
    ) is not True:
        add_problem(
            problems,
            "plan",
            "stack_origin",
            # Show the full URLs, not the origins: when two installations share an origin the
            # path is the only thing that differs, and an origin-only message would read as
            # though the two were identical.
            "stack target {1!r} is not inside the installation rooted at plan site {0!r}".format(
                document.get("site"), stack.get("target")
            ),
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
        # The plan's host_class is the OPERATOR'S DECLARATION, and the fingerprint is a
        # contradiction check — not the other way round. The operator pays the hosting bill and
        # knows what they are on; header sniffing is corroboration.
        #
        # Requiring the fingerprint to be high-confidence before any write deadlocked the common
        # case. Detection is deliberately rated `medium` when a marker is not vendor-namespaced —
        # GoDaddy Managed WordPress is identified by `x-gateway-*`, which is real evidence but
        # not exclusive — so a real GoDaddy site could never authorize a fix at all.
        #
        # Worse, the old rule made the disagreement check unreachable: at medium confidence the
        # helper returned None, so the branch that catches "this plan was built for a different
        # host" never ran. It blocked the safe case and skipped the dangerous one.
        #
        # Now: agreement at any confidence proceeds, disagreement at any confidence refuses, and
        # an unknown host leaves the operator's declaration standing alone — the same shape as
        # --local-root, where inference that cannot reach certainty defers to a human assertion.
        host_signal = profile.get("host_class")
        plan_host = document.get("host_class")
        stack_host = (
            host_signal.get("value") if isinstance(host_signal, dict) else None
        )
        if not is_non_empty_string(stack_host) or stack_host == "unknown":
            pass  # No independent reading; the operator's declaration stands unchallenged.
        elif plan_host != stack_host:
            confidence = (
                host_signal.get("confidence") if isinstance(host_signal, dict) else "unknown"
            )
            add_problem(
                problems,
                "plan",
                "stack_host_class",
                "plan declares host_class {!r} but the fingerprint of this site reads {!r} "
                "({} confidence) — resolve which is correct before changing anything, because "
                "host_class selects the constraints that decide what is permitted".format(
                    plan_host, stack_host, confidence
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
    preflight: bool = False,
) -> List[Problem]:
    """Apply every safety rule and return all problems without short-circuiting."""

    problems: List[Problem] = []
    # Loaded once per run. A missing or malformed policy raises rather than degrading to "no
    # policy, no problem" — an absent gate must stop the run, not wave it through.
    host_policy = load_host_policy()
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
                not preflight,
                problems,
                document.get("host_class"),
                host_policy,
                document.get("staging"),
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

    validate_plan_sequence_rationale(document, problems)

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

    selftest_origin = "{}://{}-{}/".format("https", "selftest", "site")
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
        "site": selftest_origin,
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
    """Exercise accepted and unsafe plans using temporary fixtures."""

    lines = ["validate_plan.py self-test"]
    passed = 0
    total = 0
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

            total += 1
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

            cases: List[
                Tuple[str, Dict[str, Any], str, Optional[Dict[str, Any]]]
            ] = []

            prohibited = copy.deepcopy(base)
            prohibited["changes"][0]["risk_lane"] = "prohibited"
            cases.append(
                ("prohibited change refused", prohibited, "risk_lane", None)
            )

            missing_snapshot = copy.deepcopy(base)
            missing_snapshot["changes"][0]["snapshot"]["artifact"] = "missing.bak"
            cases.append(
                ("missing snapshot refused", missing_snapshot, "snapshot", None)
            )

            approval_not_granted = copy.deepcopy(base)
            approval_not_granted["changes"][0]["approval"]["granted"] = False
            cases.append(
                (
                    "ungranted approval refused",
                    approval_not_granted,
                    "approval",
                    None,
                )
            )

            wrong_purge = copy.deepcopy(base)
            wrong_purge["changes"][0]["purge_layers"] = ["edge"]
            cases.append(
                (
                    "purge of a layer not present refused",
                    wrong_purge,
                    "purge_layers",
                    None,
                )
            )

            approval_not_required = copy.deepcopy(base)
            approval_not_required["changes"][0]["approval"] = {
                "granted": False,
                "required": False,
            }
            cases.append(
                (
                    "plan-declared optional approval refused",
                    approval_not_required,
                    "approval",
                    None,
                )
            )

            snapshot_not_required = copy.deepcopy(base)
            snapshot_not_required["changes"][0]["snapshot"] = {
                "artifact": "missing.bak",
                "required": False,
            }
            cases.append(
                (
                    "plan-declared optional snapshot refused",
                    snapshot_not_required,
                    "snapshot",
                    None,
                )
            )

            direct_theme_file = copy.deepcopy(base)
            direct_theme_file["tier"] = 3
            direct_theme_file["changes"][0]["target"] = {
                "identifier": "functions.php",
                "kind": "theme-file",
            }
            cases.append(
                (
                    "direct theme-file change refused",
                    direct_theme_file,
                    "risk_lane",
                    None,
                )
            )

            mismatched_stack = {
                "cache_layers": [
                    {
                        "confidence": "none",
                        "evidence": [],
                        "layer": "edge",
                        "value": "unknown",
                    },
                    {
                        "confidence": "high",
                        "evidence": ["probe: self-test server cache detected"],
                        "layer": "server",
                        "value": "nginx-fastcgi",
                    },
                    {
                        "confidence": "none",
                        "evidence": [],
                        "layer": "page-plugin",
                        "value": "unknown",
                    },
                    {
                        "confidence": "none",
                        "evidence": [],
                        "layer": "object",
                        "value": "unknown",
                    },
                ],
                "profile": {
                    "host_class": {
                        "confidence": "high",
                        "evidence": ["probe: self-test host confirmed"],
                        "value": "self-managed",
                    }
                },
                "schema_version": SCHEMA_VERSION,
                "target": "{}://{}-{}/".format("https", "selftest", "url"),
                "tool": "fingerprint",
            }
            cases.append(
                (
                    "stack origin mismatch refused",
                    copy.deepcopy(base),
                    "stack_origin",
                    mismatched_stack,
                )
            )

            tier_one_option = copy.deepcopy(base)
            tier_one_option["changes"][0]["target"] = {
                "identifier": "selftest-option",
                "kind": "wp-option",
            }
            cases.append(
                (
                    "tier 1 raw wp-option change refused",
                    tier_one_option,
                    "tier",
                    None,
                )
            )

            for label, case, expected_rule, case_stack in cases:
                total += 1
                case_problems = validate_plan(case, plan_path, root, case_stack)
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

            pending_readiness = copy.deepcopy(base)
            pending_readiness["changes"][0]["approval"]["granted"] = False
            pending_readiness["changes"][0]["snapshot"][
                "artifact"
            ] = "pending-snapshot.bak"
            total += 1
            preflight_problems = validate_plan(
                pending_readiness,
                plan_path,
                root,
                preflight=True,
            )
            readiness_problems = validate_plan(pending_readiness, plan_path, root)
            readiness_rules = {problem.rule for problem in readiness_problems}
            if (
                not preflight_problems
                and "approval" in readiness_rules
                and "snapshot" in readiness_rules
            ):
                passed += 1
                lines.append(
                    "[PASS] preflight accepts pending approval and snapshot; execution readiness refuses them ({} problem(s))".format(
                        len(readiness_problems)
                    )
                )
            else:
                lines.append(
                    "[FAIL] preflight/readiness split ({} preflight problem(s), {} readiness problem(s))".format(
                        len(preflight_problems), len(readiness_problems)
                    )
                )
                lines.extend(render_selftest_problems(preflight_problems))
            lines.extend(render_selftest_problems(readiness_problems))
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
        "--preflight",
        action="store_true",
        help="defer approval-granted and snapshot-file readiness checks",
    )
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
        ) or args.quiet or args.preflight:
            raise UsageError("--selftest cannot be combined with other options")
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
    problems = validate_plan(
        document,
        plan_path,
        repo_root,
        stack,
        preflight=args.preflight,
    )
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
