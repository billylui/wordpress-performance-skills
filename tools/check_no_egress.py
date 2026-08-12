#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Fail the build if any shipped script can reach a third-party host.

This enforces invariant 2 of docs/CONTRACTS.md — the no-telemetry guarantee. Operators point
these scripts at production WordPress sites, sometimes with credentials in the environment. The
promise is that nothing here talks to anyone except the target site the operator named. A promise
in a README is a wish; this is the check that makes it a property of the repo.

What counts as a violation: a hostname or URL literal, in a scanned file, that is not in
ALLOWED_HOSTS and does not come from operator input at runtime.

Usage:
    python3 tools/check_no_egress.py [PATH ...]

Exit codes:
    0  clean
    1  at least one violation (details on stdout)
    2  usage error
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Directories whose contents ship to operators and therefore get scanned. Documentation and this
# tool itself are excluded: prose naming a vendor is not an egress path, and the allowlist below
# would otherwise have to contain every host the docs mention.
SCAN_DIRS = ("skills", "evals", "templates")

# Extensions that can actually perform a request. A .md file cannot make a network call.
SCAN_SUFFIXES = (".py", ".sh", ".mjs", ".js", ".yml", ".yaml")

# Hosts that are safe by construction:
#   - RFC 2606 reserved example domains, which resolve to a documentation sink and are the
#     correct placeholder in usage strings and test fixtures.
#   - Loopback, used by the local evaluation fixtures.
# Anything else must come from operator input at runtime, never from a literal in the source.
ALLOWED_HOSTS = frozenset(
    {
        "example.com",
        "example.org",
        "example.net",
        "www.example.com",
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "host.docker.internal",
        # XML/SVG namespace URIs are identifiers, not fetch targets. No parser resolves them
        # over the network, so an "http://www.w3.org/2000/svg" attribute is inert.
        "www.w3.org",
    }
)

# A scheme-qualified URL: the unambiguous egress shape.
URL_RE = re.compile(r"""["'`]?(?:https?|wss?|ftp)://([A-Za-z0-9._~-]+(?::\d+)?)""")

# A bare quoted hostname with a plausible public TLD. Deliberately conservative: it requires at
# least one dot and a 2+ character alphabetic TLD, so it will not fire on "utf-8" or "wp-content".
BARE_HOST_RE = re.compile(r"""["']((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})["']""")

# Filenames look exactly like hostnames — "blocking.css" and "wp-load.php" both parse as
# label-dot-TLD. Anything whose final segment is a known file extension is a filename, not a
# host, so it never reaches the allowlist check. Scheme-qualified URLs are matched by URL_RE
# and are unaffected by this list, so a genuine "https://evil.io/x.css" is still caught.
FILE_EXTENSIONS = frozenset(
    """
    bmp css csv gif gz html ico ini jpeg jpg js json log map md mjs mo otf pdf php png po py
    sh sql svg tar template ts tsx txt webp woff woff2 xml yaml yml zip
    """.split()
)

# Lines carrying this marker are exempt. Use it only where a host literal is provably inert —
# and say why on the same line, because a reviewer will read it.
ALLOW_MARKER = "no-egress-ok:"


def host_of(candidate: str) -> str:
    """Strip any port so 'localhost:8081' matches the allowlist entry 'localhost'."""
    return candidate.rsplit(":", 1)[0] if candidate.count(":") == 1 else candidate


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return (line number, offending host, source line) for each violation in one file."""
    violations: list[tuple[int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"warning: could not read {path}: {exc}", file=sys.stderr)
        return violations

    for lineno, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        found = {host_of(m) for m in URL_RE.findall(line)}
        found |= {
            host_of(m)
            for m in BARE_HOST_RE.findall(line)
            if m.rsplit(".", 1)[-1].lower() not in FILE_EXTENSIONS
        }
        for host in sorted(found):
            if host.lower() not in ALLOWED_HOSTS:
                violations.append((lineno, host, line.strip()))
    return violations


def iter_targets(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(p for p in root.rglob("*") if p.is_file() and p.suffix in SCAN_SUFFIXES)
    return sorted(set(files))


def main(argv: list[str]) -> int:
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        return 0

    repo_root = Path(__file__).resolve().parent.parent
    if argv:
        roots = [Path(a) for a in argv]
        missing = [r for r in roots if not r.exists()]
        if missing:
            print(f"error: no such path: {', '.join(str(m) for m in missing)}", file=sys.stderr)
            return 2
    else:
        roots = [repo_root / d for d in SCAN_DIRS]

    targets = iter_targets(roots)
    if not targets:
        print("no-egress: nothing to scan yet (no shipped scripts found)")
        return 0

    total = 0
    for path in targets:
        for lineno, host, line in scan_file(path):
            total += 1
            try:
                shown = path.relative_to(repo_root)
            except ValueError:
                shown = path
            print(f"{shown}:{lineno}: disallowed host '{host}'\n    {line}")

    if total:
        print(
            f"\nno-egress: FAIL — {total} disallowed host literal(s) across {len(targets)} file(s).\n"
            "These scripts must talk only to the site the operator names. If a literal is provably\n"
            f"inert, mark that line with '{ALLOW_MARKER} <reason>'; otherwise take the host out.",
        )
        return 1

    print(f"no-egress: OK — {len(targets)} file(s) scanned, no disallowed host literals.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
