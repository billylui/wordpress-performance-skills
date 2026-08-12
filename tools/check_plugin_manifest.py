#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check that the plugin manifests and the documented install command agree.

Installation is the one path where a mistake is both silent and total: a malformed or
inconsistent manifest does not degrade the skill, it prevents anyone from getting it at all, and
the error surfaces on a stranger's machine rather than in this repo.

Three things have to line up, and nothing enforces them at authoring time:

1. `.claude-plugin/marketplace.json` has the shape a marketplace expects.
2. The plugin entry's `name` matches `.claude-plugin/plugin.json`.
3. The README's `/plugin install <plugin>@<marketplace>` line matches both, because that string
   is the user-facing contract — a rename on one side turns the documented command into a
   confusing failure.

A `source` of `"./"` also means the plugin *is* this repository, so `skills/*/SKILL.md` must
actually exist here for the install to deliver anything.

Usage:
    python3 tools/check_plugin_manifest.py

Exit codes:
    0  consistent
    1  at least one inconsistency
    2  a manifest is missing or unparseable
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REQUIRED_MARKETPLACE_KEYS = ("name", "owner", "plugins")
REQUIRED_PLUGIN_ENTRY_KEYS = ("name", "source", "description", "version")


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"error: {path} not found", file=sys.stderr)
        raise SystemExit(2)
    except json.JSONDecodeError as exc:
        print(f"error: {path} is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(2)


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    marketplace = load(root / ".claude-plugin" / "marketplace.json")
    plugin = load(root / ".claude-plugin" / "plugin.json")

    problems: list[str] = []

    for key in REQUIRED_MARKETPLACE_KEYS:
        if key not in marketplace:
            problems.append(f"marketplace.json is missing required key '{key}'")

    entries = marketplace.get("plugins")
    if not isinstance(entries, list) or not entries:
        problems.append("marketplace.json has no non-empty 'plugins' array")
        entries = []

    for index, entry in enumerate(entries):
        for key in REQUIRED_PLUGIN_ENTRY_KEYS:
            if key not in entry:
                problems.append(f"plugins[{index}] is missing required key '{key}'")

    if entries:
        entry = entries[0]
        if entry.get("name") != plugin.get("name"):
            problems.append(
                f"name mismatch: marketplace entry '{entry.get('name')}' "
                f"vs plugin.json '{plugin.get('name')}' — install would fail"
            )

        # A relative source means the plugin is this repo, so the skills must be here.
        if str(entry.get("source", "")).startswith("."):
            skills = sorted(p.parent.name for p in (root / "skills").glob("*/SKILL.md"))
            if not skills:
                problems.append(
                    "plugin source is this repository but no skills/*/SKILL.md exists"
                )

        expected = f"/plugin install {entry.get('name')}@{marketplace.get('name')}"
        readme = (root / "README.md").read_text(encoding="utf-8")
        if expected not in readme:
            problems.append(
                f"README does not document the install command that these manifests "
                f"actually produce; expected the line: {expected}"
            )

    for problem in problems:
        print(f"FAIL: {problem}")

    if problems:
        print(f"\nplugin-manifest: FAIL — {len(problems)} inconsistency(ies).")
        return 1

    skills = sorted(p.parent.name for p in (root / "skills").glob("*/SKILL.md"))
    print(
        f"plugin-manifest: OK — {len(entries)} plugin(s), {len(skills)} skill(s) "
        f"({', '.join(skills)}), install command matches."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
