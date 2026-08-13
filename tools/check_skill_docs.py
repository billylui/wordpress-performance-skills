#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check skill documentation for the structural rules the catalog depends on.

Three checks, each enforcing a rule that fails silently otherwise:

1. **Broken links.** A catalog entry that links to a file that does not exist sends the agent
   looking for guidance it will never find, mid-audit.

2. **Reference depth.** Agent-skill guidance requires every reference to sit one level deep from
   SKILL.md: a file reached *through* another file may be read only partially, leaving the agent
   acting on a fragment. So every reference file under the skill must also be linked directly
   from SKILL.md. Cross-links between entries are fine — both ends are indexed.

3. **Time-sensitive claims.** Market-share percentages, version-pinned assertions and calendar
   years rot, and nothing re-verifies them at read time. They belong in dated documentation, not
   in skill instructions.

Usage:
    python3 tools/check_skill_docs.py [SKILL_DIR ...]

Exit codes:
    0  clean
    1  at least one violation
    2  usage error
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Markdown inline links to local paths. Anchors and external URLs are filtered out below.
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)")

# Claims that cannot be re-verified when the agent reads them, and go stale silently.
# Each pattern is paired with what to do instead, because a bare "don't" is not actionable.
TIME_SENSITIVE_PATTERNS = (
    (
        re.compile(r"\b\d{1,3}(?:\.\d+)?\s*%\s*(?:of|market|share)", re.I),
        "market-share percentage; move it to dated documentation",
    ),
    (
        re.compile(r"\bas of\s+(?:\w+\s+)?\d{4}\b", re.I),
        "dated assertion; state the behaviour without the date",
    ),
    (
        re.compile(r"\b(?:in|since|until)\s+(?:19|20)\d{2}\b", re.I),
        "calendar year; describe the behaviour, not when it changed",
    ),
    (
        re.compile(r"\bcurrently\s+(?:the\s+)?(?:most|least|fastest|slowest|largest)\b", re.I),
        "superlative that will age; describe the mechanism instead",
    ),
)

# A script invoked through a path rooted at this repository rather than at the skill itself.
REPO_RELATIVE_SCRIPT_RE = re.compile(r"python3?\s+skills/[a-z0-9-]+/scripts/")

# A retired blanket permission. Six catalog entries carried it and the entry template instructed
# authors to write it, so it regenerates unless something refuses it. It is almost never true: a
# defect class can be host-neutral, but the change MECHANISM is not — a WP Engine GitPush reverts
# direct edits to tracked files, Pantheon's Live code is read-only, and several platforms own the
# cache drop-ins outright. An operator reading blanket permission is being told the host gate does
# not apply to them, and an incorrect permissive claim about a host is the most damaging error this
# project can make.
BLANKET_HOST_PERMISSION_RE = re.compile(r"No host-specific restriction applies", re.I)

# Lines carrying this marker are exempt: historical notes are allowed to name a version or date
# as long as they are explicitly labelled as history.
HISTORY_MARKERS = ("<details>", "historical", "old pattern", "deprecated")


def local_links(path: Path) -> list[tuple[int, str]]:
    """Return (line number, target) for each markdown link to a local path.

    Templates legitimately contain `{{PLACEHOLDER}}` link targets — the report template links a
    finding to whichever catalog entry it came from, and that path is filled in per report. A
    placeholder is a slot, not a broken link, so it is skipped rather than flagged.
    """
    found: list[tuple[int, str]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for target in LINK_RE.findall(line):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if "{{" in target and "}}" in target:
                continue
            found.append((lineno, target.split("#", 1)[0]))
    return found


def check_skill(skill_dir: Path, repo_root: Path) -> list[str]:
    problems: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return [f"{skill_dir}: no SKILL.md"]

    def rel(p: Path) -> str:
        try:
            return str(p.relative_to(repo_root))
        except ValueError:
            return str(p)

    # --- 1. every link from anywhere in the skill resolves -------------------------------
    md_files = sorted(p for p in skill_dir.rglob("*.md"))
    for path in md_files:
        for lineno, target in local_links(path):
            if not (path.parent / target).resolve().exists():
                problems.append(f"{rel(path)}:{lineno}: broken link -> {target}")

    # --- 2. no reference sits two hops from SKILL.md -------------------------------------
    indexed = {
        (skill_md.parent / target).resolve()
        for _lineno, target in local_links(skill_md)
    }
    for path in md_files:
        if path == skill_md:
            continue
        if path.resolve() not in indexed:
            problems.append(
                f"{rel(path)}: reachable only through another file; link it directly from "
                f"SKILL.md or fold it into the entry that references it"
            )

    # --- 3. no repo-root-relative script invocations --------------------------------------
    # A skill runs from the operator's project, not from this repository, so
    # `python3 skills/<name>/scripts/x.py` resolves only when someone happens to be sitting in
    # this checkout. Installed to ~/.claude/skills/ it is a "No such file" on the first command
    # of the audit — which is exactly how it failed the first time it was used for real.
    for path in md_files:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if REPO_RELATIVE_SCRIPT_RE.search(line):
                problems.append(
                    f"{rel(path)}:{lineno}: script invoked by a repo-root-relative path; resolve "
                    f"the skill directory first and use \"$SKILL_DIR/scripts/…\"\n    {line.strip()}"
                )

    # --- 4. no blanket host permission ---------------------------------------------------
    for path in md_files:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if BLANKET_HOST_PERMISSION_RE.search(line):
                problems.append(
                    f"{rel(path)}:{lineno}: blanket host permission. Say that no host prohibits "
                    f"the fix CLASS, and that the host's constraints on the change mechanism still "
                    f"apply — the deploy path that owns production varies by host.\n    {line.strip()}"
                )

    # --- 5. no time-sensitive claims -----------------------------------------------------
    for path in md_files:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            lowered = line.lower()
            if any(marker in lowered for marker in HISTORY_MARKERS):
                continue
            for pattern, advice in TIME_SENSITIVE_PATTERNS:
                if pattern.search(line):
                    problems.append(
                        f"{rel(path)}:{lineno}: time-sensitive claim ({advice})\n    {line.strip()}"
                    )
                    break
    return problems


def main(argv: list[str]) -> int:
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        return 0

    repo_root = Path(__file__).resolve().parent.parent
    if argv:
        skill_dirs = [Path(a) for a in argv]
        missing = [d for d in skill_dirs if not d.is_dir()]
        if missing:
            print(f"error: not a directory: {', '.join(str(m) for m in missing)}", file=sys.stderr)
            return 2
    else:
        skills_root = repo_root / "skills"
        skill_dirs = sorted(p for p in skills_root.glob("*") if (p / "SKILL.md").is_file())

    if not skill_dirs:
        print("skill-docs: no skills with a SKILL.md yet")
        return 0

    problems: list[str] = []
    for skill_dir in skill_dirs:
        problems.extend(check_skill(skill_dir, repo_root))

    for problem in problems:
        print(problem)

    if problems:
        print(f"\nskill-docs: FAIL — {len(problems)} problem(s) across {len(skill_dirs)} skill(s).")
        return 1

    total_files = sum(len(list(d.rglob("*.md"))) for d in skill_dirs)
    print(f"skill-docs: OK — {len(skill_dirs)} skill(s), {total_files} markdown file(s) checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
