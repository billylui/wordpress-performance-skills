# SPDX-License-Identifier: GPL-2.0-or-later
"""Emit and grade agent-agnostic evaluation scenarios for wp-perf-skills.

The runner never invokes an agent. Without --transcript it emits the selected
prompt and rubric. With --transcript it grades one selected scenario. Natural
language rubric items are intentionally left for human or judge-model review.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


# This version changes only when the runner report shape changes incompatibly.
REPORT_SCHEMA_VERSION = "1.0"
# Scenario IDs become filenames and report keys, so keep them portable.
SCENARIO_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# These explicit prefixes are the only automatic grading rules. Unprefixed
# prose is semantic and must be reviewed by a person or judge model.
CONTAINS_PREFIX = "contains:"
NOT_CONTAINS_PREFIX = "not_contains:"

REQUIRED_FIELDS = (
    "expected_behavior",
    "files",
    "fixture",
    "id",
    "must_not",
    "query",
    "skills",
)
LIST_FIELDS = ("skills", "files", "expected_behavior", "must_not")

EXIT_OK = 0
EXIT_USAGE = 2


class EvalError(Exception):
    """An actionable input or output error that should not produce a traceback."""


class EvalArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that raises an actionable error instead of exiting early."""

    def error(self, message: str) -> None:
        raise EvalError(message)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = EvalArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="record or emit the no-skill control run",
    )
    parser.add_argument("--scenario", metavar="ID", help="select one scenario")
    parser.add_argument(
        "--list",
        action="store_true",
        help="list validated scenario IDs and exit",
    )
    parser.add_argument(
        "--transcript",
        metavar="PATH",
        help="grade a transcript file; use - to read stdin (requires --scenario)",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        help="write the machine-readable report; use - for stdout",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress the human-readable summary; requires --json",
    )
    return parser.parse_args(argv)


def scenario_directory() -> Path:
    return Path(__file__).resolve().parent / "scenarios"


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def validate_string_list(value: Any, field: str, source: str) -> List[str]:
    if not isinstance(value, list):
        raise EvalError("{}: '{}' must be an array of strings".format(source, field))
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise EvalError(
                "{}: '{}[{}]' must be a non-empty string".format(source, field, index)
            )
    return value


def validate_scenario(document: Any, source: str) -> Dict[str, Any]:
    if not isinstance(document, dict):
        raise EvalError("{}: top-level JSON value must be an object".format(source))

    fields = tuple(sorted(document.keys()))
    if fields != REQUIRED_FIELDS:
        missing = sorted(set(REQUIRED_FIELDS) - set(document.keys()))
        extra = sorted(set(document.keys()) - set(REQUIRED_FIELDS))
        details = []
        if missing:
            details.append("missing fields: {}".format(", ".join(missing)))
        if extra:
            details.append("unexpected fields: {}".format(", ".join(extra)))
        raise EvalError("{}: malformed scenario ({})".format(source, "; ".join(details)))

    for field in ("id", "query", "fixture"):
        if not isinstance(document[field], str) or not document[field].strip():
            raise EvalError("{}: '{}' must be a non-empty string".format(source, field))

    for field in LIST_FIELDS:
        validate_string_list(document[field], field, source)

    if not document["skills"]:
        raise EvalError("{}: 'skills' must name at least one skill".format(source))
    if not document["expected_behavior"]:
        raise EvalError("{}: 'expected_behavior' must not be empty".format(source))
    if not SCENARIO_ID_PATTERN.fullmatch(document["id"]):
        raise EvalError(
            "{}: 'id' must use lowercase letters, digits, and single hyphens".format(source)
        )

    filename_id = Path(source).stem
    if filename_id != document["id"]:
        raise EvalError(
            "{}: filename stem must match scenario id '{}'".format(source, document["id"])
        )
    return document


def load_scenarios(directory: Path) -> List[Dict[str, Any]]:
    try:
        paths = sorted(directory.glob("*.json"), key=lambda item: item.name)
    except OSError as exc:
        raise EvalError("cannot scan scenario directory {}: {}".format(display_path(directory), exc))
    if not paths:
        raise EvalError("no scenario documents found in {}".format(display_path(directory)))

    scenarios = []
    seen_ids = set()
    for path in paths:
        source = display_path(path)
        try:
            with path.open("r", encoding="utf-8") as handle:
                document = json.load(handle)
        except json.JSONDecodeError as exc:
            raise EvalError(
                "{}: invalid JSON at line {}, column {}: {}".format(
                    source, exc.lineno, exc.colno, exc.msg
                )
            )
        except (OSError, UnicodeError) as exc:
            raise EvalError("{}: cannot read scenario: {}".format(source, exc))
        scenario = validate_scenario(document, source)
        if scenario["id"] in seen_ids:
            raise EvalError("{}: duplicate scenario id '{}'".format(source, scenario["id"]))
        seen_ids.add(scenario["id"])
        scenarios.append(scenario)
    return sorted(scenarios, key=lambda item: item["id"])


def select_scenarios(
    scenarios: List[Dict[str, Any]], scenario_id: Optional[str]
) -> List[Dict[str, Any]]:
    if scenario_id is None:
        return scenarios
    selected = [item for item in scenarios if item["id"] == scenario_id]
    if not selected:
        available = ", ".join(item["id"] for item in scenarios)
        raise EvalError("unknown scenario '{}'; available: {}".format(scenario_id, available))
    return selected


def read_transcript(path_text: str) -> Tuple[str, str]:
    if path_text == "-":
        try:
            return sys.stdin.read(), "stdin"
        except (OSError, UnicodeError) as exc:
            raise EvalError("cannot read transcript from stdin: {}".format(exc))

    path = Path(path_text)
    try:
        return path.read_text(encoding="utf-8"), display_path(path)
    except (OSError, UnicodeError) as exc:
        raise EvalError("cannot read transcript {}: {}".format(display_path(path), exc))


def matcher_text(rubric: str, prefix: str) -> Optional[str]:
    if not rubric.casefold().startswith(prefix.casefold()):
        return None
    text = rubric[len(prefix) :].strip()
    if not text:
        raise EvalError("rubric matcher '{}' requires non-empty text".format(prefix))
    return text


def grade_item(kind: str, rubric: str, transcript: str) -> Dict[str, str]:
    folded_transcript = transcript.casefold()
    if kind == "expected_behavior":
        text = matcher_text(rubric, CONTAINS_PREFIX)
        if text is not None:
            matched = text.casefold() in folded_transcript
            return {
                "detail": (
                    "required text found"
                    if matched
                    else "unmet expectation: required text was not found"
                ),
                "matcher": "case-insensitive substring",
                "rubric": rubric,
                "status": "pass" if matched else "fail",
            }
    elif kind == "must_not":
        text = matcher_text(rubric, NOT_CONTAINS_PREFIX)
        if text is not None:
            matched = text.casefold() in folded_transcript
            return {
                "detail": (
                    "prohibited text was found" if matched else "prohibited text was not found"
                ),
                "matcher": "case-insensitive substring",
                "rubric": rubric,
                "status": "fail" if matched else "pass",
            }
    else:
        raise EvalError("internal error: unsupported rubric kind '{}'".format(kind))

    return {
        "detail": "semantic judgement required; submit this rubric to a human or judge model",
        "matcher": "human_or_judge_model",
        "rubric": rubric,
        "status": "needs_review",
    }


def aggregate_status(checks: List[Dict[str, str]]) -> str:
    statuses = {check["status"] for check in checks}
    if "fail" in statuses:
        return "fail"
    if "needs_review" in statuses:
        return "needs_review"
    return "pass"


def build_result(
    scenario: Dict[str, Any],
    baseline: bool,
    transcript: Optional[str],
    transcript_source: Optional[str],
) -> Dict[str, Any]:
    result = {
        "checks": [],
        "fixture": scenario["fixture"],
        "id": scenario["id"],
        "prompt": scenario["query"],
        "rubric": {
            "expected_behavior": scenario["expected_behavior"],
            "must_not": scenario["must_not"],
        },
        "skills": [] if baseline else scenario["skills"],
        "status": "awaiting_transcript",
        "transcript": None,
        "transcript_sha256": None,
        "transcript_source": None,
    }
    if transcript is None:
        return result

    checks = []
    for rubric in scenario["expected_behavior"]:
        item = grade_item("expected_behavior", rubric, transcript)
        item["kind"] = "expected_behavior"
        checks.append(item)
    for rubric in scenario["must_not"]:
        item = grade_item("must_not", rubric, transcript)
        item["kind"] = "must_not"
        checks.append(item)

    result["checks"] = checks
    result["status"] = aggregate_status(checks)
    result["transcript"] = transcript
    result["transcript_sha256"] = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
    result["transcript_source"] = transcript_source
    return result


def build_report(
    scenarios: List[Dict[str, Any]],
    baseline: bool,
    transcript: Optional[str],
    transcript_source: Optional[str],
) -> Dict[str, Any]:
    results = [
        build_result(item, baseline, transcript, transcript_source) for item in scenarios
    ]
    statuses = {result["status"] for result in results}
    if "fail" in statuses:
        status = "fail"
    elif "needs_review" in statuses:
        status = "needs_review"
    elif "awaiting_transcript" in statuses:
        status = "awaiting_transcript"
    else:
        status = "pass"
    return {
        "mode": "baseline" if baseline else "skill",
        "results": results,
        "runner": "run_evals",
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": status,
    }


def human_summary(report: Dict[str, Any]) -> str:
    lines = [
        "Evaluation mode: {}".format(report["mode"]),
        "Overall status: {}".format(report["status"]),
        "",
    ]
    for result in report["results"]:
        skills = ", ".join(result["skills"]) if result["skills"] else "none (control)"
        lines.extend(
            [
                "{}: {}".format(result["id"], result["status"]),
                "  fixture: {}".format(result["fixture"]),
                "  skills: {}".format(skills),
                "  prompt: {}".format(result["prompt"]),
            ]
        )
        if result["status"] == "awaiting_transcript":
            lines.append("  rubric:")
            for rubric in result["rubric"]["expected_behavior"]:
                lines.append("    expected: {}".format(rubric))
            for rubric in result["rubric"]["must_not"]:
                lines.append("    must not: {}".format(rubric))
        else:
            for check in result["checks"]:
                lines.append(
                    "  {} [{}]: {}".format(check["kind"], check["status"], check["rubric"])
                )
                if check["status"] != "pass":
                    lines.append("    {}".format(check["detail"]))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def json_document(report: Dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def write_outputs(report: Dict[str, Any], json_path: Optional[str], quiet: bool) -> None:
    summary = human_summary(report)
    if json_path == "-":
        sys.stdout.write(json_document(report))
        if not quiet:
            sys.stderr.write(summary)
        return

    if json_path is not None:
        path = Path(json_path)
        try:
            path.write_text(json_document(report), encoding="utf-8")
        except OSError as exc:
            raise EvalError("cannot write JSON report {}: {}".format(display_path(path), exc))
    if not quiet:
        sys.stdout.write(summary)


def validate_cli(args: argparse.Namespace) -> None:
    if args.quiet and args.json is None:
        raise EvalError("--quiet requires --json")
    if args.transcript is not None and args.scenario is None:
        raise EvalError("--transcript requires --scenario so one transcript cannot be misapplied")
    if args.list and any(
        (args.baseline, args.scenario is not None, args.transcript is not None, args.json is not None)
    ):
        raise EvalError("--list cannot be combined with run or output options")


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    validate_cli(args)
    scenarios = load_scenarios(scenario_directory())
    if args.list:
        for scenario in scenarios:
            sys.stdout.write("{}\n".format(scenario["id"]))
        return EXIT_OK

    selected = select_scenarios(scenarios, args.scenario)
    transcript = None
    transcript_source = None
    if args.transcript is not None:
        transcript, transcript_source = read_transcript(args.transcript)
        if not transcript.strip():
            raise EvalError("transcript is empty; provide the agent's complete response")

    report = build_report(selected, args.baseline, transcript, transcript_source)
    write_outputs(report, args.json, args.quiet)
    return EXIT_OK


def main() -> int:
    try:
        return run()
    except EvalError as exc:
        sys.stderr.write("error: {}\n".format(exc))
        return EXIT_USAGE
    except BrokenPipeError:
        return EXIT_OK
    except (OSError, UnicodeError) as exc:
        sys.stderr.write("error: input/output failure: {}\n".format(exc))
        return EXIT_USAGE
    except KeyboardInterrupt:
        sys.stderr.write("error: interrupted by operator\n")
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
