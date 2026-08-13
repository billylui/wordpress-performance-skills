#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run the wp-perf-audit report checker from a checkout of this repository.

The checker itself lives in the skill, at `skills/wp-perf-audit/scripts/check_report.py`, because
that is the copy an agent actually has: a skill installed to `~/.claude/skills/wp-perf-audit/` or
`.agents/skills/wp-perf-audit/` ships its own `scripts/` directory and nothing else. A checker the
agent cannot reach mid-audit would enforce the report contract only in this repository's CI, which
is the one place no report gets written.

This file is a convenience for anyone working from a checkout — CI, or a contributor at the
repository root. It loads the skill's module by path rather than by name, because importing
`check_report` from here would find this file instead of the one it is trying to run.

Usage:
    python3 tools/check_report.py REPORT.md
    python3 tools/check_report.py --template skills/wp-perf-audit/references/findings-report-template.md
    python3 tools/check_report.py --selftest

Every flag and exit code is the skill script's; see its --help.
"""

import importlib.util
import sys
from pathlib import Path

CHECKER_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "wp-perf-audit"
    / "scripts"
    / "check_report.py"
)

# Matches the skill script's own vocabulary, so a caller sees one set of exit codes.
EXIT_UNREADABLE = 4


def load_checker():
    """Import the skill's checker by path, or explain why it could not be found."""

    if not CHECKER_PATH.is_file():
        raise ImportError("no such file: {}".format(CHECKER_PATH.as_posix()))
    spec = importlib.util.spec_from_file_location("wp_perf_check_report", CHECKER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError("no loader for {}".format(CHECKER_PATH.as_posix()))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    # Only the load is guarded. The checker's own main() already contains every failure and
    # returns an exit code, so wrapping the call too would relabel a validation bug as a loading
    # failure and send the reader to the wrong file.
    try:
        checker = load_checker()
    except Exception as exc:  # Defensive CLI boundary: never expose a raw traceback.
        sys.stderr.write(
            "check_report.py: could not load the checker from the skill: {}\n"
            "Run it directly instead: python3 skills/wp-perf-audit/scripts/check_report.py\n".format(exc)
        )
        return EXIT_UNREADABLE
    return checker.main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
