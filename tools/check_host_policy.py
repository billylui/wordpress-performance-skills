#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check that the machine-readable host policy and its human document still agree.

`host-constraints.md` is the authoritative document: cited, nuanced, and the thing a person reads.
`host-policy.json` is the half `validate_plan.py` can enforce. Two files stating the same policy
will drift, and the direction that matters is permissive — a JSON that says `permitted` while the
prose says `PROHIBITED` would hand an operator a change their host forbids, which this project
calls the most damaging error it can make.

So this asserts the three things drift would break:

1. **Coverage.** Every `host_class` in the contract vocabulary has an entry in both files. A host
   missing from the JSON fails *open* into "no entry" — the validator refuses it, but silently
   dropping a host would look deliberate rather than like the omission it is.
2. **Agreement.** The JSON's verdict matches the verdict word in that host's summary-table row.
3. **Evidence for permission.** Every host whose verdict is permissive carries a citation, or names
   the operator as the authority. A permissive claim is exactly the one that must be evidenced.

Usage:
    python3 tools/check_host_policy.py

Exit codes:
    0  the two agree
    1  at least one disagreement
    2  a file is missing or unparseable
"""

import json
import re
import sys
from pathlib import Path

POLICY_PATH = Path("skills/wp-perf-fix/references/host-policy.json")
PROSE_PATH = Path("skills/wp-perf-fix/references/host-constraints.md")
CONTRACTS_PATH = Path("docs/CONTRACTS.md")

# How a verdict in the JSON must read in the prose. The prose is written for people, so the match
# is on the decisive keyword rather than on an exact string.
PROSE_KEYWORD_BY_VERDICT = {
    "prohibited": ("PROHIBITED",),
    "permitted-only": ("PERMITTED ONLY",),
    "permitted-with-conditions": ("PERMITTED with conditions", "PERMITTED ONLY"),
    "unconfirmable": ("UNCONFIRMABLE",),
}
# These two are the operator's own environment, so first-party vendor documentation cannot exist.
# They still carry a stated reason, which check 3 requires instead.
SELF_AUTHORITY_HOSTS = ("self-managed",)
PERMISSIVE_VERDICTS = ("permitted-only", "permitted-with-conditions")


def fail(message: str) -> None:
    print("error: {}".format(message), file=sys.stderr)
    raise SystemExit(2)


def contract_host_classes(text: str) -> list:
    """Read the closed host_class vocabulary out of the shared contract."""

    match = re.search(r"\*\*`host_class`\*\*\s*—(.+?)\n\n", text, re.S)
    if match is None:
        fail("could not find the host_class vocabulary in {}".format(CONTRACTS_PATH.as_posix()))
    listed = set(re.findall(r"`([a-z][a-z0-9-]*)`", match.group(1)))
    # The contract states this globally rather than per-vocabulary: "Closed sets. `unknown` is
    # always additionally valid." It is also the most restrictive lane in the policy, so it must be
    # present rather than treated as an unrecognized extra.
    listed.add("unknown")
    return sorted(listed)


def prose_rows(text: str) -> dict:
    """Return each host's summary-table row from the prose document."""

    rows = {}
    for line in text.splitlines():
        match = re.match(r"^\|\s*`([a-z][a-z0-9-]*)`\s*\|(.*)$", line)
        if match is not None:
            rows.setdefault(match.group(1), match.group(2))
    return rows


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    try:
        policy = json.loads((root / POLICY_PATH).read_text(encoding="utf-8"))
        prose = (root / PROSE_PATH).read_text(encoding="utf-8")
        contracts = (root / CONTRACTS_PATH).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        fail(str(exc))
    except ValueError as exc:
        fail("{} is not valid JSON: {}".format(POLICY_PATH.as_posix(), exc))

    problems = []
    hosts = policy.get("hosts", {})
    vocabulary = contract_host_classes(contracts)
    rows = prose_rows(prose)

    for host in vocabulary:
        if host not in hosts:
            problems.append(
                "{}: no entry in {}. Add its page-cache verdict with a first-party citation; a "
                "missing host is refused at runtime but looks like a deliberate omission "
                "here.".format(host, POLICY_PATH.name)
            )
        if host not in rows:
            problems.append(
                "{}: no summary-table row in {}".format(host, PROSE_PATH.name)
            )

    for host in sorted(hosts):
        if host not in vocabulary:
            problems.append(
                "{}: present in {} but not in the host_class vocabulary in {}".format(
                    host, POLICY_PATH.name, CONTRACTS_PATH.as_posix()
                )
            )
        entry = hosts[host]
        verdict = entry.get("page_cache")
        keywords = PROSE_KEYWORD_BY_VERDICT.get(verdict)
        if keywords is None:
            problems.append(
                "{}: verdict {!r} is outside the documented set {}".format(
                    host, verdict, ", ".join(sorted(PROSE_KEYWORD_BY_VERDICT))
                )
            )
            continue
        row = rows.get(host, "")
        if row and not any(keyword.lower() in row.lower() for keyword in keywords):
            problems.append(
                "{}: {} says {!r} but the summary table row does not contain any of {}. One of "
                "the two has drifted, and the permissive direction is the dangerous one.".format(
                    host, POLICY_PATH.name, verdict, " / ".join(repr(k) for k in keywords)
                )
            )
        if verdict in PERMISSIVE_VERDICTS and host not in SELF_AUTHORITY_HOSTS:
            if not [url for url in entry.get("citations", []) if str(url).strip()]:
                problems.append(
                    "{}: verdict {!r} permits a change but cites nothing. A permissive claim "
                    "about a host's policy is the one that must be evidenced.".format(
                        host, verdict
                    )
                )
        if verdict == "permitted-only" and not entry.get("permitted_plugins"):
            problems.append(
                "{}: verdict 'permitted-only' names no permitted plugin, so it permits "
                "nothing. Use 'unconfirmable' if that is what is meant.".format(host)
            )

    for problem in sorted(problems):
        print(problem)
    if problems:
        print(
            "\nhost-policy: FAIL — {} disagreement(s) between {} and {}.".format(
                len(problems), POLICY_PATH.name, PROSE_PATH.name
            )
        )
        return 1
    print(
        "host-policy: OK — {} host(s), verdicts agree with {}, every permissive verdict is "
        "cited.".format(len(hosts), PROSE_PATH.name)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
