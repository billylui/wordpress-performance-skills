#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Validate a Markdown performance-audit report against the report contract.

Usage:
  python3 check_report.py REPORT.md [--json OUT] [--quiet]
  python3 check_report.py --template FILE.md [--json OUT] [--quiet]
  python3 check_report.py --selftest

The contract is skills/wp-perf-audit/references/report-contract.md. Template
mode permits a whole-cell {{PLACEHOLDER}} while still requiring every section,
the section order, the scorecard header, and every mandatory metric row.

Exit codes: 0 conformant; 1 violations found; 2 usage error; 4 unreadable.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple


# The tool version identifies this implementation's machine-readable output.
TOOL_VERSION = "0.1.0"

# Exit codes are fixed by the repository CLI contract.
EXIT_VALID = 0
EXIT_INVALID = 1
EXIT_USAGE = 2
EXIT_UNREADABLE = 4

# These headings and this order are fixed by report-contract.md.
REQUIRED_SECTIONS = (
    "Scorecard",
    "Stack",
    "Baseline",
    "Findings",
    "What could not be checked",
    "Changes applied",
    "Result",
    "What did not work",
    "Deliberate decisions",
    "Still open",
)

# These scorecard rows and this order are fixed by report-contract.md.
REQUIRED_METRICS = (
    "LCP",
    "INP",
    "CLS",
    "FCP",
    "TBT",
    "Speed Index",
    "TTFB (origin)",
    "TTFB (edge)",
    "Page weight",
    "Requests",
)

# The scorecard contract fixes exactly these four columns.
SCORECARD_COLUMNS = ("Metric", "Value", "Rating", "Source")
# Stack tables remain free-form; these exact headers alone trigger the provenance rule in the
# report contract. Keeping them named makes it clear that no other Stack table shape is fixed.
STACK_CONFIDENCE_COLUMN = "Confidence"
STACK_SOURCE_COLUMN = "Source"

# Violations about the report's shape rather than the content of one cell. The human report
# prints the full required order once when any of these fire, so the individual messages can name
# only what is wrong instead of restating the whole contract each time.
STRUCTURAL_RULES = frozenset(
    (
        "scorecard_absent",
        "scorecard_required_row",
        "scorecard_row_order",
        "section_order",
        "section_presence",
        "section_scorecard_first",
    )
)
# Only these metrics have a published threshold table in the report contract.
RATEABLE_METRICS = ("lcp", "inp", "cls")
# Rating words are a closed vocabulary; a dash means deliberately unrated.
RATING_WORDS = ("good", "needs-improvement", "poor")
EM_DASH = "—"
# Both dashes mean "no rating". The em dash is what the contract shows, but it is awkward to type
# on many keyboards and an ASCII hyphen in a Rating column is unambiguous, so both are accepted and
# the contract says so. What matters is that no rating was claimed, not which character says it.
# Accepting one and rejecting the other in the same table — which is what this did, depending on
# whether the row was measured — is worse than either rule applied consistently.
UNRATED_MARKS = (EM_DASH, "-")
# The contract names these two explicit states for data that is not measured.
UNMEASURED_VALUES = ("unmeasured", "unavailable")

# Thresholds come directly from report-contract.md. The good boundary is INCLUSIVE: the published
# definitions read "200 milliseconds or less" and "0.1 or less", so a metric sitting exactly on the
# boundary is good. Naming these AT_OR_BELOW rather than BELOW keeps that readable at every call.
# Decimal, not float, because 0.1 has no exact binary representation and CLS is compared against it.
LCP_GOOD_AT_OR_BELOW_SECONDS = Decimal("2.5")
LCP_POOR_ABOVE_SECONDS = Decimal("4.0")
INP_GOOD_AT_OR_BELOW_MILLISECONDS = Decimal("200")
INP_POOR_ABOVE_MILLISECONDS = Decimal("500")
CLS_GOOD_AT_OR_BELOW = Decimal("0.1")
CLS_POOR_ABOVE = Decimal("0.25")
# A Markdown table delimiter needs at least three hyphens per column.
MIN_TABLE_SEPARATOR_HYPHENS = 3
# Unit normalization uses the exact SI conversion between seconds and milliseconds.
MILLISECONDS_PER_SECOND = Decimal("1000")

HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
HEADING_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
NUMBER_RE = re.compile(
    r"^[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)"
    r"(?:[eE][+-]?\d+)?(?:[ \t]*([A-Za-z%]+))?$"
)
PLACEHOLDER_RE = re.compile(r"^\{\{[^{}\r\n]+\}\}$")
# The same slot syntax anywhere in a line, not just filling a whole cell — used to catch an
# unfinished draft outside the scorecard, where a placeholder sits in prose rather than a table.
ANY_PLACEHOLDER_RE = re.compile(r"\{\{[^{}\r\n]+\}\}")
LAB_OR_FIELD_RE = re.compile(r"\b(?:lab|field)\b", re.IGNORECASE)
# Stack headers are free-form Markdown, so lightweight inline decoration is
# ignored when identifying the Confidence and Source columns.
LIGHTWEIGHT_MARKDOWN_DECORATION_RE = re.compile(r"(?:\*\*|__|`)")


class ValidationInputError(Exception):
    """An input or output error that should be reported without a traceback."""


class UsageError(Exception):
    """A command-line error that should return the usage exit code."""


class GateArgumentParser(argparse.ArgumentParser):
    """Raise usage errors so the CLI boundary controls all error output."""

    def error(self, message: str) -> None:
        raise UsageError(message)


@dataclass(frozen=True)
class Problem:
    """One deterministic, actionable report-contract violation."""

    subject: str
    rule: str
    message: str


@dataclass(frozen=True)
class Heading:
    """One visible Markdown heading."""

    line_index: int
    level: int
    title: str


@dataclass(frozen=True)
class ScorecardRow:
    """One parsed four-cell scorecard row."""

    line_number: int
    metric: str
    value: str
    rating: str
    source: str


def add_problem(
    problems: List[Problem], subject: str, rule: str, message: str
) -> None:
    problems.append(Problem(subject=subject, rule=rule, message=message))


def sorted_problems(problems: Sequence[Problem]) -> List[Problem]:
    """Return a stable ordering independent of parsing implementation details."""

    return sorted(
        problems,
        key=lambda item: (item.rule, item.subject.casefold(), item.message),
    )


def required_section_order() -> str:
    return ", ".join(REQUIRED_SECTIONS)


def required_metric_order() -> str:
    return ", ".join(REQUIRED_METRICS)


def normalize_metric(value: str) -> str:
    """Normalize case, spacing, and lightweight Markdown for table identity."""

    undecorated = LIGHTWEIGHT_MARKDOWN_DECORATION_RE.sub("", value)
    return " ".join(undecorated.split()).casefold()


def without_html_comments(value: str) -> str:
    """Remove comments because comments do not count as report content."""

    return HTML_COMMENT_RE.sub("", value)


def visible_lines(document: str) -> Tuple[List[str], List[bool]]:
    """Return comment-free lines and mark lines hidden inside fenced code blocks."""

    comment_free = HTML_COMMENT_RE.sub(
        lambda match: "\n" * match.group(0).count("\n"), document
    )
    lines = comment_free.splitlines()
    hidden = [False] * len(lines)
    fence_character: Optional[str] = None
    fence_length = 0
    for index, line in enumerate(lines):
        match = FENCE_RE.match(line)
        if fence_character is None:
            if match is not None:
                marker = match.group(1)
                fence_character = marker[0]
                fence_length = len(marker)
                hidden[index] = True
        else:
            hidden[index] = True
            stripped = line.lstrip()
            closing = re.match(
                r"^({0}{{{1},}})[ \t]*$".format(
                    re.escape(fence_character), fence_length
                ),
                stripped,
            )
            if closing is not None:
                fence_character = None
                fence_length = 0
    return lines, hidden


def parse_headings(lines: Sequence[str], hidden: Sequence[bool]) -> List[Heading]:
    """Parse visible ATX headings without treating fenced examples as sections."""

    headings: List[Heading] = []
    for index, line in enumerate(lines):
        if hidden[index]:
            continue
        match = HEADING_RE.match(line)
        if match is None:
            continue
        title = re.sub(r"[ \t]+#+[ \t]*$", "", match.group(2)).strip()
        headings.append(
            Heading(line_index=index, level=len(match.group(1)), title=title)
        )
    return headings


def split_table_row(line: str) -> Optional[List[str]]:
    """Split a Markdown table row, preserving escaped pipe characters in cells."""

    if "|" not in line:
        return None
    cells: List[str] = []
    cell: List[str] = []
    escaped = False
    for character in line.strip():
        if escaped:
            cell.append(character)
            escaped = False
        elif character == "\\":
            cell.append(character)
            escaped = True
        elif character == "|":
            cells.append("".join(cell).strip())
            cell = []
        else:
            cell.append(character)
    cells.append("".join(cell).strip())
    stripped = line.strip()
    if stripped.startswith("|") and cells and cells[0] == "":
        cells = cells[1:]
    if stripped.endswith("|") and cells and cells[-1] == "":
        cells = cells[:-1]
    return cells


def is_table_separator(
    cells: Sequence[str], expected_column_count: int = len(SCORECARD_COLUMNS)
) -> bool:
    """Return whether the expected cells form a Markdown delimiter row."""

    if len(cells) != expected_column_count:
        return False
    minimum = MIN_TABLE_SEPARATOR_HYPHENS
    pattern = re.compile(r"^:?-{{{},}}:?$".format(minimum))
    return all(
        pattern.match("".join(cell.split())) is not None for cell in cells
    )


def parse_scorecard_rows(
    lines: Sequence[str],
    hidden: Sequence[bool],
    start_index: int,
    end_index: int,
    problems: List[Problem],
) -> List[ScorecardRow]:
    """Find the contract table and return every well-shaped data row."""

    header_index: Optional[int] = None
    candidate: Optional[Tuple[int, List[str]]] = None
    for index in range(start_index, end_index):
        if hidden[index] or lines[index].startswith(("    ", "\t")):
            continue
        cells = split_table_row(lines[index])
        if cells is None:
            continue
        if tuple(cells) == SCORECARD_COLUMNS:
            header_index = index
            break
        if (
            cells
            and normalize_metric(cells[0]) == normalize_metric(SCORECARD_COLUMNS[0])
            and candidate is None
        ):
            candidate = (index, cells)

    if header_index is None:
        found = ""
        if candidate is not None:
            found = " Found columns: {}.".format(" | ".join(candidate[1]))
        add_problem(
            problems,
            "scorecard",
            "scorecard_header",
            "scorecard: missing the exact four-column header 'Metric | Value | Rating | Source'.{} Use those columns in that order, with no additions or omissions.".format(
                found
            ),
        )
        return []

    separator_index = header_index + 1
    if separator_index >= end_index or hidden[separator_index]:
        separator_cells = None
    else:
        separator_cells = split_table_row(lines[separator_index])
    if separator_cells is None or not is_table_separator(separator_cells):
        add_problem(
            problems,
            "scorecard",
            "scorecard_header",
            "scorecard: the header at line {} must be followed immediately by a four-column Markdown separator such as '|---|---|---|---|'.".format(
                header_index + 1
            ),
        )
        return []

    rows: List[ScorecardRow] = []
    for index in range(separator_index + 1, end_index):
        if hidden[index] or not lines[index].strip():
            break
        cells = split_table_row(lines[index])
        if cells is None:
            break
        if len(cells) != len(SCORECARD_COLUMNS):
            add_problem(
                problems,
                "scorecard",
                "scorecard_row_shape",
                "scorecard table row at line {} has {} columns; every row must have exactly 'Metric | Value | Rating | Source'.".format(
                    index + 1, len(cells)
                ),
            )
            continue
        rows.append(
            ScorecardRow(
                line_number=index + 1,
                metric=cells[0],
                value=cells[1],
                rating=cells[2],
                source=cells[3],
            )
        )
    return rows


def is_placeholder(value: str, template_mode: bool) -> bool:
    return template_mode and PLACEHOLDER_RE.match(value.strip()) is not None


def parse_measured_value(value: str) -> Optional[Tuple[Decimal, str]]:
    """Parse a measured number with valid grouping and an optional unit."""

    match = NUMBER_RE.match(value.strip())
    if match is None:
        return None
    number_text = value.strip()
    unit = match.group(1) or ""
    if unit:
        number_text = number_text[: match.start(1)].strip()
    try:
        number = Decimal(number_text.replace(",", ""))
    except ArithmeticError:
        return None
    return number, unit.casefold()


def expected_rating(metric: str, value: Decimal) -> Tuple[str, str]:
    """Return the contract rating and an explanation of its exact boundary."""

    if metric == "lcp":
        lower = LCP_GOOD_AT_OR_BELOW_SECONDS
        upper = LCP_POOR_ABOVE_SECONDS
        unit = "s"
    elif metric == "inp":
        lower = INP_GOOD_AT_OR_BELOW_MILLISECONDS
        upper = INP_POOR_ABOVE_MILLISECONDS
        unit = "ms"
    else:
        lower = CLS_GOOD_AT_OR_BELOW
        upper = CLS_POOR_ABOVE
        unit = ""

    # The published thresholds are inclusive at the good boundary: INP is defined as "200
    # milliseconds or less" and CLS as "0.1 or less", and LCP as occurring "within 2.5 seconds".
    # A metric sitting exactly on the boundary is therefore good, not needs-improvement.
    suffix = " {}".format(unit) if unit else ""
    if value <= lower:
        return "good", "good is {}{} or less".format(lower, suffix)
    if value > upper:
        return "poor", "poor is more than {}{}".format(upper, suffix)
    return (
        "needs-improvement",
        "needs-improvement is above {}{} and up to {}{}".format(lower, suffix, upper, suffix),
    )


def normalized_rateable_value(
    row: ScorecardRow,
    metric: str,
    number: Decimal,
    unit: str,
    problems: List[Problem],
) -> Optional[Decimal]:
    """Normalize LCP/INP units and reject units the threshold table cannot use."""

    label = row.metric.strip() or "<blank>"
    if metric == "lcp":
        if unit == "s":
            return number
        if unit == "ms":
            return number / MILLISECONDS_PER_SECOND
        expected_units = "'s' or 'ms'"
    elif metric == "inp":
        if unit == "ms":
            return number
        if unit == "s":
            return number * MILLISECONDS_PER_SECOND
        expected_units = "'ms' or 's'"
    else:
        if unit == "":
            return number
        expected_units = "no unit"

    shown_unit = "no unit" if not unit else "unit {!r}".format(unit)
    add_problem(
        problems,
        label,
        "scorecard_value_unit",
        "scorecard row {!r}: value {!r} uses {}; {} requires {} so its published rating can be checked.".format(
            label, row.value, shown_unit, label, expected_units
        ),
    )
    return None


def validate_rating_vocabulary(
    row: ScorecardRow, template_mode: bool, problems: List[Problem]
) -> bool:
    """Validate vocabulary independently when value-dependent checks cannot run."""

    rating = row.rating.strip()
    if is_placeholder(rating, template_mode):
        return True
    if rating in RATING_WORDS or rating in UNRATED_MARKS:
        return True
    label = row.metric.strip() or "<blank>"
    add_problem(
        problems,
        label,
        "scorecard_rating_vocabulary",
        "scorecard row {!r}: rating {!r} is outside the closed vocabulary. Use 'good', 'needs-improvement', 'poor', or '—' (an ASCII '-' is accepted too).".format(
            label, rating
        ),
    )
    return False


def validate_scorecard_row(
    row: ScorecardRow, template_mode: bool, problems: List[Problem]
) -> None:
    """Apply value, rating, threshold, and source rules to one scorecard row."""

    label = row.metric.strip() or "<blank>"
    metric = normalize_metric(row.metric)
    value_text = row.value.strip()
    rating = row.rating.strip()
    source = without_html_comments(row.source).strip()

    value_placeholder = is_placeholder(value_text, template_mode)
    rating_placeholder = is_placeholder(rating, template_mode)
    source_placeholder = is_placeholder(row.source, template_mode)
    unresolved_source_placeholder = (
        not template_mode and PLACEHOLDER_RE.match(row.source.strip()) is not None
    )
    if unresolved_source_placeholder:
        add_problem(
            problems,
            label,
            "scorecard_source",
            "scorecard row {!r}: Source {!r} is an unresolved placeholder. Fill it with a real measurement source or unmeasured reason; use --template only when validating the shipped template.".format(
                label, row.source.strip()
            ),
        )
    if value_placeholder:
        if not source_placeholder and not source:
            add_problem(
                problems,
                label,
                "scorecard_source",
                "scorecard row {!r}: Source is empty. Use a non-empty measurement source or unmeasured reason, or a whole-cell placeholder in template mode.".format(
                    label
                ),
            )
        if metric not in RATEABLE_METRICS and not rating_placeholder:
            if rating.casefold() in RATING_WORDS:
                add_problem(
                    problems,
                    label,
                    "scorecard_rating_metric",
                    "scorecard row {!r}: rating {!r} is not permitted for this metric — only LCP, INP and CLS have a published threshold table. Use '—'.".format(
                        label, rating
                    ),
                )
            elif rating not in UNRATED_MARKS:
                validate_rating_vocabulary(row, template_mode, problems)
        else:
            validate_rating_vocabulary(row, template_mode, problems)
        return

    measured = parse_measured_value(value_text)
    unmeasured = value_text.casefold() in UNMEASURED_VALUES
    if measured is None and not unmeasured:
        shown = "blank" if not value_text else repr(value_text)
        add_problem(
            problems,
            label,
            "scorecard_value",
            "scorecard row {!r}: value is {}. Use a measured number with an optional unit, or the literal 'unmeasured'/'unavailable'; blank, '—', 'n/a' and 'TBD' are not valid measurement states.".format(
                label, shown
            ),
        )
        if rating.casefold() in RATING_WORDS and not rating_placeholder:
            add_problem(
                problems,
                label,
                "scorecard_rating_value",
                "scorecard row {!r}: value {!r} is not measured, so rating {!r} is invented. Supply a measured number or use 'unmeasured'/'unavailable' with rating '—'.".format(
                    label, value_text, rating
                ),
            )
            if metric not in RATEABLE_METRICS:
                add_problem(
                    problems,
                    label,
                    "scorecard_rating_metric",
                    "scorecard row {!r}: rating {!r} is not permitted for this metric — only LCP, INP and CLS have a published threshold table. Use '—'.".format(
                        label, rating
                    ),
                )
        else:
            validate_rating_vocabulary(row, template_mode, problems)
        return

    if unmeasured:
        if not rating_placeholder and rating not in UNRATED_MARKS:
            add_problem(
                problems,
                label,
                "scorecard_rating_value",
                "scorecard row {!r}: value is {!r} so rating must be '—', not {!r}. An unmeasured metric never carries a rating.".format(
                    label, value_text, rating
                ),
            )
            if metric not in RATEABLE_METRICS and rating.casefold() in RATING_WORDS:
                add_problem(
                    problems,
                    label,
                    "scorecard_rating_metric",
                    "scorecard row {!r}: rating {!r} is also not permitted for this metric — only LCP, INP and CLS have a published threshold table. Use '—'.".format(
                        label, rating
                    ),
                )
        if not source_placeholder and not source:
            add_problem(
                problems,
                label,
                "scorecard_source_reason",
                "scorecard row {!r}: value is {!r} but Source is empty. State the concrete reason the metric could not be measured; an unmeasured value without a reason hides the audit boundary.".format(
                    label, value_text
                ),
            )
        return

    assert measured is not None
    number, unit = measured
    if not source_placeholder and not source:
        add_problem(
            problems,
            label,
            "scorecard_source",
            "scorecard row {!r}: measured value {!r} needs a non-empty Source naming where the measurement came from.".format(
                label, value_text
            ),
        )

    if metric not in RATEABLE_METRICS:
        if rating_placeholder:
            return
        if rating.casefold() in RATING_WORDS:
            add_problem(
                problems,
                label,
                "scorecard_rating_metric",
                "scorecard row {!r}: rating {!r} is not permitted for this metric — only LCP, INP and CLS have a published threshold table. Use '—'.".format(
                    label, rating
                ),
            )
        elif rating not in UNRATED_MARKS:
            validate_rating_vocabulary(row, template_mode, problems)
        return

    if not source_placeholder and source and LAB_OR_FIELD_RE.search(source) is None:
        add_problem(
            problems,
            label,
            "scorecard_source_kind",
            "scorecard row {!r}: Source {!r} must contain the word 'lab' or 'field'. Rated LCP, INP and CLS must say which kind of measurement supports the value.".format(
                label, row.source.strip()
            ),
        )

    normalized = normalized_rateable_value(
        row, metric, number, unit, problems
    )
    if rating_placeholder or normalized is None:
        return
    if rating not in RATING_WORDS:
        if rating in UNRATED_MARKS:
            expected, explanation = expected_rating(metric, normalized)
            add_problem(
                problems,
                label,
                "scorecard_rating_threshold",
                "scorecard row {!r}: measured value {} rates as {!r} ({}), but the row is unrated. Use {!r}.".format(
                    label, value_text, expected, explanation, expected
                ),
            )
        else:
            validate_rating_vocabulary(row, template_mode, problems)
        return


    expected, explanation = expected_rating(metric, normalized)
    if rating != expected:
        add_problem(
            problems,
            label,
            "scorecard_rating_threshold",
            "scorecard row {!r}: value {} rates as {!r} ({}), but the row says {!r}.".format(
                label, value_text, expected, explanation, rating
            ),
        )


def validate_required_rows(
    rows: Sequence[ScorecardRow], problems: List[Problem]
) -> None:
    """Require the ten contract rows in their relative order; extra rows remain legal."""

    first_position: Dict[str, int] = {}
    required_by_normalized = {
        normalize_metric(metric): metric for metric in REQUIRED_METRICS
    }
    for index, row in enumerate(rows):
        normalized = normalize_metric(row.metric)
        if normalized in required_by_normalized and normalized not in first_position:
            first_position[normalized] = index

    for metric in REQUIRED_METRICS:
        normalized = normalize_metric(metric)
        if normalized not in first_position:
            add_problem(
                problems,
                metric,
                "scorecard_required_row",
                "scorecard: missing required row {!r}. A metric nobody measured still gets its "
                "row, with the value 'unmeasured', a rating of '—', and the reason in Source.".format(
                    metric
                ),
            )

    present = [
        metric
        for metric in REQUIRED_METRICS
        if normalize_metric(metric) in first_position
    ]
    by_position = sorted(
        present, key=lambda metric: first_position[normalize_metric(metric)]
    )
    rank = {metric: index for index, metric in enumerate(REQUIRED_METRICS)}
    for previous, current in zip(by_position, by_position[1:]):
        if rank[current] < rank[previous]:
            add_problem(
                problems,
                "scorecard",
                "scorecard_row_order",
                "scorecard rows out of order: {!r} appears before {!r}. Required row order: {}. Extra rows may appear between them.".format(
                    previous, current, required_metric_order()
                ),
            )
            break


def validate_sections(
    document: str,
    lines: Sequence[str],
    headings: Sequence[Heading],
    problems: List[Problem],
) -> Dict[str, Heading]:
    """Require mandatory H2 sections, order them, and check honesty content."""

    first: Dict[str, Heading] = {}
    h2_headings = [heading for heading in headings if heading.level == 2]
    for heading in h2_headings:
        if heading.title in REQUIRED_SECTIONS and heading.title not in first:
            first[heading.title] = heading

    for section in REQUIRED_SECTIONS:
        if section not in first:
            add_problem(
                problems,
                section,
                "section_presence",
                "missing required section '## {}'. Write the heading with 'none' under it rather "
                "than omitting it — an absent section reads as 'nothing to say here' when it "
                "usually means 'not checked'.".format(section),
            )

    scorecard = first.get("Scorecard")
    if scorecard is not None and h2_headings and h2_headings[0].line_index != scorecard.line_index:
        add_problem(
            problems,
            "Scorecard",
            "section_scorecard_first",
            "section '## Scorecard' must be the first H2 heading; found '## {}' first. Put Scorecard first, then keep this required order: {}.".format(
                h2_headings[0].title, required_section_order()
            ),
        )

    present = [section for section in REQUIRED_SECTIONS if section in first]
    by_position = sorted(present, key=lambda section: first[section].line_index)
    rank = {section: index for index, section in enumerate(REQUIRED_SECTIONS)}
    for previous, current in zip(by_position, by_position[1:]):
        if rank[current] < rank[previous]:
            add_problem(
                problems,
                "sections",
                "section_order",
                "sections out of order: '## {}' appears before '## {}'. Required order: {}.".format(
                    previous, current, required_section_order()
                ),
            )
            break

    original_lines = document.splitlines()
    for section in ("What could not be checked", "What did not work"):
        heading = first.get(section)
        if heading is None:
            continue
        # A section ends at the next heading of the SAME level or higher, never at one nested
        # inside it. Ending at any heading treated "## What did not work" followed by
        # "### Attempt 1" as empty and refused a perfectly well-structured report — punishing the
        # authors who organize this section most carefully.
        end_index = len(original_lines)
        for candidate in headings:
            if candidate.line_index > heading.line_index and candidate.level <= heading.level:
                end_index = candidate.line_index
                break
        body = "\n".join(original_lines[heading.line_index + 1 : end_index])
        if not without_html_comments(body).strip():
            add_problem(
                problems,
                section,
                "section_honesty_content",
                "section '## {}' is present but empty. Write 'none' rather than leaving it blank — a bare heading reads as 'nothing went wrong', which is rarely true.".format(
                    section
                ),
            )
    return first


def validate_no_placeholders(
    lines: Sequence[str],
    hidden: Sequence[bool],
    template_mode: bool,
    problems: List[Problem],
) -> None:
    """Refuse a report that still carries unfilled template slots.

    The skill tells the agent to publish on a clean exit, so anything this accepts is something an
    operator can receive. A draft copied from the template with only the scorecard completed used
    to pass with `{{FINDING_TITLE}}` and `{{ROLLBACK}}` still in it — a half-written report that
    the checker had blessed, which is worse than one that was never checked.

    Fenced blocks are exempt: the contract and the template legitimately show placeholder syntax
    in examples.
    """

    if template_mode:
        return
    seen: Dict[str, int] = {}
    for index, line in enumerate(lines):
        if hidden[index]:
            continue
        for match in ANY_PLACEHOLDER_RE.finditer(line):
            seen.setdefault(match.group(0), index + 1)
    for placeholder in sorted(seen):
        add_problem(
            problems,
            placeholder,
            "unfilled_placeholder",
            "line {}: {} is still a template placeholder. Replace it with the real value, or "
            "with 'none' if there is nothing to report — publishing the slot itself tells the "
            "reader nothing.".format(seen[placeholder], placeholder),
        )


def validate_stack_section(
    lines: Sequence[str],
    hidden: Sequence[bool],
    headings: Sequence[Heading],
    sections: Mapping[str, Heading],
    template_mode: bool,
    problems: List[Problem],
) -> None:
    """Require provenance only for Stack tables that claim confidence."""

    heading = sections.get("Stack")
    if heading is None:
        return
    end_index = len(lines)
    for candidate in headings:
        if candidate.line_index > heading.line_index and candidate.level <= heading.level:
            end_index = candidate.line_index
            break

    index = heading.line_index + 1
    while index + 1 < min(end_index, len(lines)):
        if hidden[index] or lines[index].startswith(("    ", "\t")):
            index += 1
            continue
        header_cells = split_table_row(lines[index])
        separator_cells = (
            None if hidden[index + 1] else split_table_row(lines[index + 1])
        )
        if (
            not header_cells
            or separator_cells is None
            or not is_table_separator(separator_cells, len(header_cells))
        ):
            index += 1
            continue

        table_line = index + 1
        normalized_header_cells = [normalize_metric(cell) for cell in header_cells]
        confidence_column = normalize_metric(STACK_CONFIDENCE_COLUMN)
        source_column = normalize_metric(STACK_SOURCE_COLUMN)
        if confidence_column not in normalized_header_cells:
            index += 2
            continue
        if source_column not in normalized_header_cells:
            add_problem(
                problems,
                "Stack",
                "stack_source_column",
                "section '## Stack' table at line {} has a Confidence column but no Source "
                "column. Add Source to that table and name the tool or access tier behind "
                "every row's confidence.".format(table_line),
            )
            index += 2
            continue

        source_index = normalized_header_cells.index(source_column)
        row_index = index + 2
        while row_index < min(end_index, len(lines)):
            if hidden[row_index] or not lines[row_index].strip():
                break
            row_cells = split_table_row(lines[row_index])
            if row_cells is None:
                break
            source_cell = row_cells[source_index] if source_index < len(row_cells) else ""
            source = without_html_comments(source_cell).strip()
            source_placeholder = is_placeholder(source_cell, template_mode)
            unresolved_source_placeholder = (
                not template_mode
                and PLACEHOLDER_RE.match(source_cell.strip()) is not None
            )
            label = row_cells[0].strip() if row_cells and row_cells[0].strip() else "<blank>"
            if unresolved_source_placeholder:
                add_problem(
                    problems,
                    label,
                    "stack_source",
                    "section '## Stack' table row {!r} at line {} has Source {!r}, an "
                    "unresolved placeholder. Fill it with the tool or access tier behind the "
                    "row's Confidence; use --template only when validating the shipped "
                    "template.".format(label, row_index + 1, source_cell.strip()),
                )
            if not source_placeholder and not source:
                add_problem(
                    problems,
                    label,
                    "stack_source",
                    "section '## Stack' table row {!r} at line {} has an empty Source. Name "
                    "the tool or access tier behind the row's Confidence, or use a whole-cell "
                    "placeholder in --template mode.".format(label, row_index + 1),
                )
            row_index += 1
        index = max(row_index, index + 2)


def validate_result_section(
    lines: Sequence[str],
    hidden: Sequence[bool],
    headings: Sequence[Heading],
    sections: Mapping[str, Heading],
    template_mode: bool,
    problems: List[Problem],
) -> None:
    """Require a fix report's before/after table to carry every scorecard row.

    `wp-perf-fix` step 9 promises the same ten rows again, with a delta column. Only checking the
    scorecard let a fix report ship a Result table holding two flattering rows and omitting the
    metrics that did not move — which is the precise failure the before/after table exists to
    prevent, since a change that moved nothing is exactly what an operator needs to see.

    A read-only audit has nothing to put here, so a Result section that reports no rows at all is
    accepted: this rule constrains fix reports, and only once they start filling the table.
    """

    heading = sections.get("Result")
    if heading is None:
        return
    end_index = len(lines)
    for candidate in headings:
        if candidate.line_index > heading.line_index and candidate.level <= heading.level:
            end_index = candidate.line_index
            break

    present: Dict[str, int] = {}
    for index in range(heading.line_index + 1, min(end_index, len(lines))):
        if hidden[index]:
            continue
        cells = split_table_row(lines[index])
        if not cells or is_table_separator(cells):
            continue
        name = normalize_metric(cells[0])
        if name in ("metric", "page"):
            continue
        present.setdefault(name, index + 1)

    required = {normalize_metric(metric): metric for metric in REQUIRED_METRICS}
    matched = [key for key in required if key in present]
    if not matched:
        # Either a read-only audit, or a fix report that has not filled the table yet. Both are
        # outside this rule; the scorecard has already been checked either way.
        return

    missing = [required[key] for key in required if key not in present]
    if missing and not template_mode:
        add_problem(
            problems,
            "Result",
            "result_missing_rows",
            "section '## Result' reports a before/after for some metrics but omits {}. A fix "
            "report carries the same {} rows as the scorecard, because a metric that did not "
            "move is the result an operator most needs to see. Required rows, in order: {}.".format(
                ", ".join(repr(name) for name in missing),
                len(REQUIRED_METRICS),
                required_metric_order(),
            ),
        )


def validate_report(document: str, template_mode: bool = False) -> List[Problem]:
    """Apply every report rule and return all violations without short-circuiting."""

    problems: List[Problem] = []
    lines, hidden = visible_lines(document)
    headings = parse_headings(lines, hidden)
    sections = validate_sections(document, lines, headings, problems)
    validate_no_placeholders(lines, hidden, template_mode, problems)

    scorecard = sections.get("Scorecard")
    if scorecard is not None:
        end_index = len(lines)
        for heading in headings:
            if heading.level == 2 and heading.line_index > scorecard.line_index:
                end_index = heading.line_index
                break
        rows = parse_scorecard_rows(
            lines,
            hidden,
            scorecard.line_index + 1,
            end_index,
            problems,
        )
        validate_required_rows(rows, problems)
        for row in rows:
            validate_scorecard_row(row, template_mode, problems)
    else:
        # Without the heading there is no table to walk, but staying silent about the rows is the
        # worse failure: the author fixes the heading, re-runs, and only then discovers that ten
        # specific rows are required. Report the whole shape now so one pass is enough. This is
        # exactly the case a real audit hit — it had no scorecard at all.
        add_problem(
            problems,
            "Scorecard",
            "scorecard_absent",
            "no '## Scorecard' section, so no rows could be checked. It opens the report and "
            "carries these {} rows in this order: {}. Header: | {} |. Every row is always "
            "present; one nobody measured says 'unmeasured' with the reason in Source.".format(
                len(REQUIRED_METRICS),
                required_metric_order(),
                " | ".join(SCORECARD_COLUMNS),
            ),
        )

    validate_stack_section(
        lines, hidden, headings, sections, template_mode, problems
    )
    validate_result_section(lines, hidden, headings, sections, template_mode, problems)
    return sorted_problems(problems)


def machine_summary(
    report_path: Path,
    problems: Sequence[Problem],
    template_mode: bool,
) -> Dict[str, object]:
    ordered = sorted_problems(problems)
    return {
        "problem_count": len(ordered),
        "problems": [
            {
                "message": problem.message,
                "rule": problem.rule,
                "subject": problem.subject,
            }
            for problem in ordered
        ],
        "report": report_path.as_posix(),
        # Carried in every document so a machine consumer gets the contract's shape without
        # parsing it back out of the prose in each message.
        "required_scorecard_rows": list(REQUIRED_METRICS),
        "required_sections": list(REQUIRED_SECTIONS),
        "scorecard_columns": list(SCORECARD_COLUMNS),
        "status": "conformant" if not ordered else "invalid",
        "template_mode": template_mode,
        "tool": "check-report",
        "tool_version": TOOL_VERSION,
        "valid": not ordered,
    }


def human_report(report_path: Path, problems: Sequence[Problem]) -> str:
    ordered = sorted_problems(problems)
    if not ordered:
        return "Performance report CONFORMANT: {}\nProblems: 0\n".format(
            report_path.as_posix()
        )
    lines = [
        "Performance report INVALID: {}".format(report_path.as_posix()),
        "Problems: {}".format(len(ordered)),
    ]
    # State the required shape once, as a preamble, rather than repeating it inside every
    # presence and ordering message. Ten copies of the same forty-word sentence bury the one
    # line that says which section is actually missing.
    if any(problem.rule in STRUCTURAL_RULES for problem in ordered):
        lines.extend(
            [
                "",
                "Required section order: {}".format(required_section_order()),
                "  Extra H2 sections may appear between them.",
                "Required scorecard rows, in order: {}".format(required_metric_order()),
                "  Header: | {} |. Extra rows may appear between them.".format(
                    " | ".join(SCORECARD_COLUMNS)
                ),
                "",
            ]
        )
    lines.extend(
        "  - rule {}: {}".format(problem.rule, problem.message)
        for problem in ordered
    )
    return "\n".join(lines) + "\n"


def json_text(document: Mapping[str, object]) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def write_outputs(
    report_path: Path,
    problems: Sequence[Problem],
    template_mode: bool,
    json_destination: Optional[str],
    quiet: bool,
) -> None:
    destination = json_destination
    if quiet and destination is None:
        destination = "-"

    report = human_report(report_path, problems)
    summary = json_text(machine_summary(report_path, problems, template_mode))
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
                "cannot write JSON output {}: {}".format(
                    output_path.as_posix(), exc
                )
            )


def selftest_report() -> str:
    """Return one known-good in-memory report for independent mutations."""

    return """# Performance audit

## Scorecard

| Metric | Value | Rating | Source |
|---|---|---|---|
| LCP | 2.4 s | good | lab browser timing |
| INP | 250 ms | needs-improvement | field interaction data |
| CLS | 0.25 | needs-improvement | lab layout shifts |
| FCP | 1.8 s | — | lab browser timing |
| TBT | unavailable | — | no audit runner in this session |
| Speed Index | 3.2 s | — | audit runner |
| TTFB (origin) | 1,250 ms | — | cache-busted probe |
| TTFB (edge) | 172 ms | — | bare-request probe |
| Page weight | 18.1 MB | — | payload walk |
| Requests | 696 | — | payload walk |

## Stack

none

## Baseline

none

## Findings

none

## What could not be checked

none

## Changes applied

none — read-only audit

## Result

none

## What did not work

none

## Deliberate decisions

none

## Still open

none
"""


def render_selftest_problems(problems: Sequence[Problem]) -> List[str]:
    return [
        "       - rule {}: {}".format(problem.rule, problem.message)
        for problem in sorted_problems(problems)
    ]


def run_selftest() -> int:
    """Exercise every contract rule using one-change in-memory fixtures."""

    base = selftest_report()
    cases: List[Tuple[str, str, bool, Optional[str]]] = []
    cases.append(("valid report accepted", base, False, None))
    cases.append(
        (
            "missing scorecard section refused",
            base.replace("## Scorecard\n", "", 1),
            False,
            "section_presence",
        )
    )
    cases.append(
        (
            # A missing scorecard must still teach the ten rows. Reporting only the absent heading
            # costs the author a whole extra round-trip, and this is the shape a real audit had.
            "missing scorecard still names the required rows",
            base.replace("## Scorecard\n", "", 1),
            False,
            "scorecard_absent",
        )
    )
    cases.append(
        (
            "scorecard not first refused",
            base.replace(
                "## Scorecard", "## Suggested order\n\nnone\n\n## Scorecard", 1
            ),
            False,
            "section_scorecard_first",
        )
    )
    cases.append(
        (
            "mandatory row deleted refused",
            base.replace(
                "| Requests | 696 | — | payload walk |\n", "", 1
            ),
            False,
            "scorecard_required_row",
        )
    )
    cases.append(
        (
            "mandatory sections in wrong relative order refused",
            base.replace("## Stack", "## TEMP", 1)
            .replace("## Baseline", "## Stack", 1)
            .replace("## TEMP", "## Baseline", 1),
            False,
            "section_order",
        )
    )
    cases.append(
        (
            "extra section accepted",
            base.replace(
                "## What could not be checked",
                "## Suggested order\n\nmeasure first\n\n## What could not be checked",
                1,
            ),
            False,
            None,
        )
    )
    cases.append(
        (
            "unmeasured row carrying a rating refused",
            base.replace(
                "| INP | 250 ms | needs-improvement | field interaction data |",
                "| INP | unmeasured | poor | no driven interaction |",
                1,
            ),
            False,
            "scorecard_rating_value",
        )
    )
    cases.append(
        (
            "rating on non-rateable TTFB refused",
            base.replace(
                "| TTFB (edge) | 172 ms | — | bare-request probe |",
                "| TTFB (edge) | 172 ms | good | bare-request probe |",
                1,
            ),
            False,
            "scorecard_rating_metric",
        )
    )
    cases.append(
        (
            "LCP 4.9 s labelled good refused",
            base.replace(
                "| LCP | 2.4 s | good | lab browser timing |",
                "| LCP | 4.9 s | good | lab browser timing |",
                1,
            ),
            False,
            "scorecard_rating_threshold",
        )
    )
    cases.append(
        (
            "unmeasured row with empty reason refused",
            base.replace(
                "| TBT | unavailable | — | no audit runner in this session |",
                "| TBT | unmeasured | — | |",
                1,
            ),
            False,
            "scorecard_source_reason",
        )
    )
    cases.append(
        (
            "blank value cell refused",
            base.replace(
                "| FCP | 1.8 s | — | lab browser timing |",
                "| FCP | | — | lab browser timing |",
                1,
            ),
            False,
            "scorecard_value",
        )
    )
    cases.append(
        (
            "empty honesty section refused",
            base.replace(
                "## What did not work\n\nnone\n\n## Deliberate decisions",
                "## What did not work\n\n## Deliberate decisions",
                1,
            ),
            False,
            "section_honesty_content",
        )
    )
    cases.append(
        (
            "measured LCP without lab or field source refused",
            base.replace("lab browser timing", "browser timing", 1),
            False,
            "scorecard_source_kind",
        )
    )

    template = base
    for old, new in (
        ("2.4 s", "{{LCP}}"),
        ("good", "{{LCP_RATING}}"),
        ("lab browser timing", "{{LCP_SOURCE}}"),
    ):
        template = template.replace(old, new, 1)
    cases.append(("template placeholders accepted", template, True, None))
    cases.append(
        (
            "a Stack table with Confidence and no Source column is refused",
            base.replace(
                "## Stack\n\nnone\n",
                "## Stack\n\n| Layer | Value | Confidence |\n|---|---|---|\n"
                "| Server cache | enabled | high |\n",
                1,
            ),
            False,
            "stack_source_column",
        )
    )
    cases.append(
        (
            "a Stack table with Confidence and an empty Source cell is refused",
            base.replace(
                "## Stack\n\nnone\n",
                "## Stack\n\n| Layer | Value | Confidence | Source |\n|---|---|---|---|\n"
                "| Server cache | enabled | high | |\n",
                1,
            ),
            False,
            "stack_source",
        )
    )
    cases.append(
        (
            "CONTROL: a Stack table with Confidence and filled Source cells is ACCEPTED",
            base.replace(
                "## Stack\n\nnone\n",
                "## Stack\n\n| Layer | Value | Confidence | Source |\n|---|---|---|---|\n"
                "| Server cache | enabled | high | WP-CLI tier 2 |\n"
                "| CDN | unknown | none | fingerprint.py |\n",
                1,
            ),
            False,
            None,
        )
    )
    cases.append(
        (
            "CONTROL: a Stack table without Confidence is ACCEPTED",
            base.replace(
                "## Stack\n\nnone\n",
                "## Stack\n\n| Layer | Value |\n|---|---|\n"
                "| Server cache | unknown |\n",
                1,
            ),
            False,
            None,
        )
    )
    cases.append(
        (
            "CONTROL: a prose-only Stack section is ACCEPTED",
            base,
            False,
            None,
        )
    )
    cases.append(
        (
            "CONTROL: a whole-cell Stack Source placeholder is accepted in --template mode",
            base.replace(
                "## Stack\n\nnone\n",
                "## Stack\n\n| Layer | Confidence | Source |\n|---|---|---|\n"
                "| Server cache | high | {{STACK_SOURCE}} |\n",
                1,
            ),
            True,
            None,
        )
    )
    cases.append(
        (
            # The published definitions are inclusive at the good boundary ("200 milliseconds or
            # less", "0.1 or less"), so a metric sitting exactly on it is good. This case asserted
            # the opposite until a review checked the wording against the source.
            "LCP boundary 2.5 s labelled good is ACCEPTED",
            base.replace("| LCP | 2.4 s |", "| LCP | 2.5 s |", 1),
            False,
            None,
        )
    )
    cases.append(
        (
            "INP boundary 200 ms labelled good is ACCEPTED",
            base.replace("| INP | 250 ms | needs-improvement |", "| INP | 200 ms | good |", 1),
            False,
            None,
        )
    )
    cases.append(
        (
            "CLS boundary 0.1 labelled good is ACCEPTED",
            base.replace("| CLS | 0.25 | needs-improvement |", "| CLS | 0.1 | good |", 1),
            False,
            None,
        )
    )
    cases.append(
        (
            # A draft copied from the template and only partly filled used to pass, and the skill
            # tells the agent to publish on a clean exit — so the checker was blessing an
            # unfinished report.
            "an unfilled placeholder outside the scorecard is refused",
            base.replace("## Deliberate decisions\n", "## Deliberate decisions\n\n- {{DECISION}}\n", 1),
            False,
            "unfilled_placeholder",
        )
    )
    cases.append(
        (
            "CONTROL: the same placeholder is accepted in --template mode",
            base.replace("## Deliberate decisions\n", "## Deliberate decisions\n\n- {{DECISION}}\n", 1),
            True,
            None,
        )
    )
    cases.append(
        (
            # An H3 inside an honesty section used to end it, so a well-organized report was
            # refused for being "empty" — punishing exactly the authors who structure it best.
            "an honesty section with an H3 subsection is ACCEPTED",
            base.replace(
                "## What did not work\n",
                "## What did not work\n\n### Attempt 1 — the payload walk\n",
                1,
            ),
            False,
            None,
        )
    )
    cases.append(
        (
            # A fix report must carry every scorecard row again, or a change that moved nothing
            # can be left out of the before/after table that exists to surface it.
            "a Result table that reports some metrics but omits others is refused",
            base.replace(
                "## Result\n\nnone\n",
                "## Result\n\n| Metric | Before | After | Δ |\n|---|---|---|---|\n"
                "| LCP | 4.9 s | 2.1 s | −2.8 s |\n",
                1,
            ),
            False,
            "result_missing_rows",
        )
    )
    cases.append(
        (
            "CONTROL: a read-only audit's empty Result section is accepted",
            base,
            False,
            None,
        )
    )
    cases.append(
        (
            "an ASCII hyphen is accepted as 'unrated' on a measured row too",
            base.replace("| Requests | 696 | — |", "| Requests | 696 | - |", 1),
            False,
            None,
        )
    )

    lines = ["check_report.py self-test"]
    passed = 0
    for label, report, template_mode, expected_rule in cases:
        problems = validate_report(report, template_mode=template_mode)
        if expected_rule is None:
            success = not problems
        else:
            success = any(problem.rule == expected_rule for problem in problems)
        if success:
            passed += 1
            count = "0 problems" if not problems else "{} problem(s)".format(
                len(problems)
            )
            lines.append("[PASS] {} ({})".format(label, count))
        else:
            expectation = "0 problems" if expected_rule is None else "rule {}".format(
                expected_rule
            )
            lines.append(
                "[FAIL] {} (expected {}, got {} problem(s))".format(
                    label, expectation, len(problems)
                )
            )
        lines.extend(render_selftest_problems(problems))

    total = len(cases)
    status = "PASS" if passed == total else "FAIL"
    lines.append("Self-test result: {} ({}/{})".format(status, passed, total))
    sys.stdout.write("\n".join(lines) + "\n")
    return EXIT_VALID if passed == total else EXIT_INVALID


def load_report(path: Path) -> str:
    """Read a UTF-8 Markdown report with a sanitized failure message."""

    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValidationInputError(
            "cannot read report {}: {}".format(path.as_posix(), exc)
        )


def build_parser() -> argparse.ArgumentParser:
    parser = GateArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "report", nargs="?", metavar="REPORT.md", help="Markdown report to validate"
    )
    parser.add_argument(
        "--template",
        metavar="FILE.md",
        help="validate a report template while permitting whole-cell placeholders",
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
        if (
            args.report is not None
            or args.template is not None
            or args.json is not None
            or args.quiet
        ):
            raise UsageError("--selftest cannot be combined with other arguments")
        return run_selftest()
    if args.report is not None and args.template is not None:
        raise UsageError("REPORT.md and --template are mutually exclusive")
    if args.report is None and args.template is None:
        raise UsageError("REPORT.md or --template FILE.md is required")

    template_mode = args.template is not None
    report_path = Path(args.template if template_mode else args.report)
    document = load_report(report_path)
    problems = validate_report(document, template_mode=template_mode)
    write_outputs(
        report_path,
        problems,
        template_mode,
        args.json,
        args.quiet,
    )
    return EXIT_VALID if not problems else EXIT_INVALID


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Contain all failures so report authors never receive a traceback."""

    try:
        return run(argv)
    except UsageError as exc:
        sys.stderr.write("check_report.py: usage error: {}\n".format(exc))
        return EXIT_USAGE
    except ValidationInputError as exc:
        sys.stderr.write("check_report.py: {}\n".format(exc))
        return EXIT_UNREADABLE
    except BrokenPipeError:
        return EXIT_VALID
    except KeyboardInterrupt:
        sys.stderr.write("check_report.py: interrupted by operator\n")
        return EXIT_UNREADABLE
    except Exception as exc:  # Defensive CLI boundary: never expose a raw traceback.
        sys.stderr.write(
            "check_report.py: validation could not complete: {}\n".format(exc)
        )
        return EXIT_UNREADABLE


if __name__ == "__main__":
    sys.exit(main())
