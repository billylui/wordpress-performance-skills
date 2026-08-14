#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check that the machine-readable measurement objectives and their human document agree.

`measurement-objectives.md` is the authoritative document: explanatory, ordered, and the thing a
person reads. `MEASUREMENT_OBJECTIVES` is the half `capabilities.py` can use. Two files stating the
same measurement boundary will drift, and the direction that matters is omission — a missing
constant entry silently removes a gap the operator should have been told how to unlock.

So this asserts the three things drift would break:

1. **Coverage both ways.** Every objective-table row has exactly one constant entry, and every
   entry has a row. A dropped machine entry fails *open* by removing an actionable gap.
2. **Row agreement.** The metric name and required capability for an objective match, so a rename
   cannot leave stale machine guidance behind while the prose moves on.
3. **Provider agreement and order.** Each provider list matches the prose exactly. The table is
   best first, and that order decides what the operator is told to reach for first.

Usage:
    python3 tools/check_measurement_objectives.py

Exit codes:
    0  the two agree
    1  at least one disagreement
    2  a file is missing or unparseable
"""

import re
import sys
import types
from collections.abc import Mapping, Sequence
from pathlib import Path

CAPABILITIES_PATH = Path("skills/wp-perf-audit/scripts/capabilities.py")
PROSE_PATH = Path("skills/wp-perf-audit/references/measurement-objectives.md")

# This exact heading owns the authoritative table. Stopping at the next same-level heading keeps
# an unrelated table added later in the document from becoming an objective accidentally.
OBJECTIVES_HEADING = "## The objectives"
TABLE_HEADER = (
    "Objective",
    "Metric",
    "Capability required",
    "Providers, best first",
    "If none available",
)
# The prose uses a middle dot rather than commas because provider names and qualifications can
# themselves contain punctuation. It is therefore the table's unambiguous ordering separator.
PROVIDER_SEPARATOR = " · "
# Import under a private, stable name so loading by file location cannot collide with another
# `capabilities` module already present in a caller's process.
CAPABILITIES_MODULE_NAME = "_wp_perf_capabilities_for_objective_check"
# These are the only inline markers removed before comparing human-facing table text with plain
# Python strings. Escaped markers remain literal prose.
MARKDOWN_DECORATION_PATTERN = re.compile(r"(?<!\\)(?:\*\*|__|`)")
# Markdown requires at least three hyphens in each separator cell, with optional alignment colons.
# Enforcing that shape prevents the first data row from being swallowed as a malformed header.
TABLE_SEPARATOR_CELL_PATTERN = re.compile(r":?-{3,}:?")
# Only unescaped pipes delimit cells; an escaped pipe belongs to the prose inside its cell.
TABLE_CELL_SEPARATOR_PATTERN = re.compile(r"(?<!\\)\|")


def fail(message: str) -> None:
    print("error: {}".format(message), file=sys.stderr)
    raise SystemExit(2)


def markdown_text(value: str) -> str:
    """Return the comparison text from the table's lightweight inline Markdown."""

    value = MARKDOWN_DECORATION_PATTERN.sub("", value)
    value = value.replace(r"\|", "|").replace(r"\*", "*").replace(r"\_", "_")
    return " ".join(value.split())


def table_cells(line: str) -> list:
    """Split one pipe-table row, preserving escaped pipes inside a cell."""

    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    cells = TABLE_CELL_SEPARATOR_PATTERN.split(stripped[1:-1])
    return [cell.strip() for cell in cells]


def prose_objectives(text: str) -> list:
    """Return the objective rows from the authoritative Markdown table."""

    lines = text.splitlines()
    try:
        heading_index = lines.index(OBJECTIVES_HEADING)
    except ValueError:
        fail("could not find {!r} in {}".format(OBJECTIVES_HEADING, PROSE_PATH.as_posix()))

    section = []
    for line in lines[heading_index + 1:]:
        if line.startswith("## "):
            break
        section.append(line)

    header_index = None
    for index, line in enumerate(section):
        if tuple(table_cells(line)) == TABLE_HEADER:
            header_index = index
            break
    if header_index is None:
        fail("could not find the objectives table header in {}".format(PROSE_PATH.as_posix()))
    if header_index + 1 >= len(section):
        fail("objectives table in {} has no separator row".format(PROSE_PATH.as_posix()))

    separator = table_cells(section[header_index + 1])
    if len(separator) != len(TABLE_HEADER) or not all(
        TABLE_SEPARATOR_CELL_PATTERN.fullmatch(cell) for cell in separator
    ):
        fail("objectives table in {} has an invalid separator row".format(PROSE_PATH.as_posix()))

    objectives = []
    for line in section[header_index + 2:]:
        if not line.strip():
            break
        cells = table_cells(line)
        if len(cells) != len(TABLE_HEADER):
            fail("could not parse objectives table row {!r}".format(line))
        objective, metric, capability, providers, if_none = map(markdown_text, cells)
        provider_list = [
            markdown_text(provider) for provider in cells[3].split(PROVIDER_SEPARATOR)
        ]
        if not all((objective, metric, capability, providers, if_none)) or not all(provider_list):
            fail("objectives table contains an empty required cell")
        objectives.append(
            {
                "capability": capability,
                "objective": objective,
                "metric": metric,
                "providers": provider_list,
            }
        )
    if not objectives:
        fail("objectives table in {} has no data rows".format(PROSE_PATH.as_posix()))
    return objectives


def load_capabilities(path: Path):
    """Execute capabilities.py from its SOURCE, never from cached bytecode.

    Deliberately not `spec_from_file_location` + `exec_module`. That path consults the bytecode
    cache, which is validated on the source's (mtime, size) — and both can match a file that has
    genuinely changed. Reordering two entries in a tuple leaves the byte count identical, and a
    write landing in the same clock second leaves the mtime identical, so Python serves the stale
    `.pyc` and this checker compares the prose against code that is not on disk.

    That happened here, to this checker, during a mutation test: a reordered provider list was
    restored on disk while the checker kept reporting the mutation. For a tool whose entire job is
    to catch drift between two files, reading neither of them is the one failure that matters. CI
    never sees it — a fresh checkout has no `__pycache__` — so the only machine that can hit it is
    the developer's, which is exactly where the gate is supposed to be trustworthy.
    """

    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail("could not read {}: {}".format(CAPABILITIES_PATH.as_posix(), exc))
    module = types.ModuleType(CAPABILITIES_MODULE_NAME)
    module.__file__ = str(path)
    # Register before executing: a decorator that resolves annotations through
    # `sys.modules[cls.__module__]` — `@dataclass` is the common one — raises while the class body
    # is still being built if its module is absent from that table. The private name above is what
    # keeps this registration from colliding with a real `capabilities` module.
    sys.modules[CAPABILITIES_MODULE_NAME] = module
    try:
        exec(compile(source, str(path), "exec"), module.__dict__)
    except Exception as exc:
        fail("could not import {}: {}".format(CAPABILITIES_PATH.as_posix(), exc))
    finally:
        sys.modules.pop(CAPABILITIES_MODULE_NAME, None)
    if not hasattr(module, "MEASUREMENT_OBJECTIVES"):
        fail("{} has no MEASUREMENT_OBJECTIVES constant".format(CAPABILITIES_PATH.as_posix()))
    return module.MEASUREMENT_OBJECTIVES


def machine_objectives(value) -> list:
    """Normalize the constant's mapping or ordered sequence into objective entries."""

    entries = []
    if isinstance(value, Mapping):
        source = []
        for metric, entry in value.items():
            if not isinstance(entry, Mapping):
                fail("MEASUREMENT_OBJECTIVES[{!r}] is not a mapping".format(metric))
            normalized = dict(entry)
            normalized.setdefault("metric", metric)
            source.append(normalized)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        source = list(value)
    else:
        fail("MEASUREMENT_OBJECTIVES is not a mapping or ordered sequence")

    for index, entry in enumerate(source):
        if not isinstance(entry, Mapping):
            fail("MEASUREMENT_OBJECTIVES[{}] is not a mapping".format(index))
        objective = entry.get("objective")
        metric = entry.get("metric")
        capability = entry.get("capability")
        providers = entry.get("providers")
        if not isinstance(objective, str) or not objective.strip():
            fail("MEASUREMENT_OBJECTIVES[{}] has no string objective".format(index))
        if not isinstance(metric, str) or not metric.strip():
            fail("MEASUREMENT_OBJECTIVES[{}] has no string metric".format(index))
        if not isinstance(capability, str) or not capability.strip():
            fail("MEASUREMENT_OBJECTIVES[{}] has no string capability".format(index))
        if not isinstance(providers, Sequence) or isinstance(
            providers, (str, bytes, bytearray)
        ):
            fail("MEASUREMENT_OBJECTIVES[{}] has no ordered providers sequence".format(index))
        provider_list = list(providers)
        if not provider_list or not all(
            isinstance(provider, str) and provider.strip() for provider in provider_list
        ):
            fail("MEASUREMENT_OBJECTIVES[{}] has an invalid providers sequence".format(index))
        entries.append(
            {
                "capability": capability.strip(),
                "objective": objective.strip(),
                "metric": metric.strip(),
                "providers": [provider.strip() for provider in provider_list],
            }
        )
    return entries


def keyed_by_objective(entries: list, source: str, problems: list) -> dict:
    """Key entries by their stable objective text and report ambiguous duplicates."""

    keyed = {}
    for entry in entries:
        objective = entry["objective"]
        if objective in keyed:
            problems.append("{}: duplicate objective {!r}".format(source, objective))
        else:
            keyed[objective] = entry
    return keyed


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    try:
        prose = (root / PROSE_PATH).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        fail(str(exc))
    except (OSError, UnicodeError) as exc:
        fail("could not read {}: {}".format(PROSE_PATH.as_posix(), exc))

    prose_entries = prose_objectives(prose)
    machine_entries = machine_objectives(load_capabilities(root / CAPABILITIES_PATH))
    problems = []
    prose_by_objective = keyed_by_objective(prose_entries, PROSE_PATH.name, problems)
    machine_by_objective = keyed_by_objective(
        machine_entries, "MEASUREMENT_OBJECTIVES", problems
    )

    for objective in sorted(prose_by_objective):
        prose_entry = prose_by_objective[objective]
        if objective not in machine_by_objective:
            problems.append(
                "{}: no entry in MEASUREMENT_OBJECTIVES. A dropped objective removes an "
                "actionable gap from cannot_measure, so this fails open.".format(
                    prose_entry["metric"]
                )
            )
            continue
        machine_entry = machine_by_objective[objective]
        if machine_entry["metric"] != prose_entry["metric"]:
            problems.append(
                "{}: capabilities.py names metric {!r} but {} names it {!r}".format(
                    objective,
                    machine_entry["metric"],
                    PROSE_PATH.name,
                    prose_entry["metric"],
                )
            )
        if machine_entry["capability"] != prose_entry["capability"]:
            problems.append(
                "{}: capabilities.py requires {!r} but {} requires {!r}".format(
                    prose_entry["metric"],
                    machine_entry["capability"],
                    PROSE_PATH.name,
                    prose_entry["capability"],
                )
            )
        if machine_entry["providers"] != prose_entry["providers"]:
            problems.append(
                "{}: provider order differs: capabilities.py has {!r} but {} says {!r}. The "
                "table is best first, so order is operator guidance.".format(
                    prose_entry["metric"],
                    machine_entry["providers"],
                    PROSE_PATH.name,
                    prose_entry["providers"],
                )
            )

    for objective in sorted(machine_by_objective):
        if objective not in prose_by_objective:
            problems.append(
                "{}: present in MEASUREMENT_OBJECTIVES but has no objective-table row in {}".format(
                    machine_by_objective[objective]["metric"], PROSE_PATH.name
                )
            )

    for problem in sorted(problems):
        print(problem)
    if problems:
        print(
            "\nmeasurement-objectives: FAIL — {} disagreement(s) between {} and {}.".format(
                len(problems), "MEASUREMENT_OBJECTIVES", PROSE_PATH.name
            )
        )
        return 1
    print(
        "measurement-objectives: OK — {} objective(s), metrics, capabilities, and ordered "
        "providers agree with {}.".format(len(prose_entries), PROSE_PATH.name)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
