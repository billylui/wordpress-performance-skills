<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Contributing

The most valuable contribution to this project is **coverage of a stack we get wrong**. WordPress
runs on an enormous variety of builders, hosts, and caching arrangements, and no single maintainer
has seen them all. If the audit misidentifies your setup, or gives advice that would break it,
that is the bug report we most want.

## Before anything else: read the contracts

[`docs/CONTRACTS.md`](docs/CONTRACTS.md) is the authority for JSON schemas, the evidence model,
CLI conventions, exit codes, and the closed vocabularies. A change that deviates from it is wrong
even if it works. If the contract itself is wrong, change the contract in the same pull request
and say why.

Three invariants are worth restating here because they are the ones people break:

1. **`unknown` is a first-class value. Never guess.** A confidently wrong claim about someone's
   production stack is worse than no claim at all. This is the single most important rule.
2. **Every claim carries evidence.** No bare values — use the signal object. If a detector cannot
   say *why* it believes something, it does not get to believe it.
3. **Standard library only, and no egress.** No `pip install`, and no network destination except
   the operator's target. `python3 tools/check_no_egress.py` enforces the second one.

## Adding support for a builder, host, or cache layer

This is the common case, and it is deliberately cheap. The catalog is organized as **universal
defect classes with per-stack sections inlined**, so new coverage is almost always a new section
rather than a new file.

1. **Add the value to the vocabulary** in `docs/CONTRACTS.md`. Vocabularies are closed sets; an
   unlisted value is a contract violation.
2. **Add detection** to `skills/wp-perf-audit/scripts/fingerprint.py`, with evidence strings and
   an honest confidence rating. Apply the rubric in the contract: `high` means a signal that
   effectively nothing else can produce. If two products emit the same header, neither gets
   `high` from that header alone.
3. **Add a section to each catalog entry the stack changes.** Do not create an `adapters/` file:
   references must stay one level deep from `SKILL.md`, because an agent may only partially read
   a file reached through another file, and act on incomplete information.
4. **Add a host constraint** if the stack forbids something. This is not documentation — it is a
   gate the fix skill enforces. Getting it wrong can break somebody's production site, or have the platform strip the plugin
   out from under them.
5. **Add an eval scenario** under `evals/scenarios/` proving the detection works and that nothing
   is invented.

## Evidence, not folklore

WordPress performance advice is full of confidently repeated claims that were true on one host in
one year. A pull request that changes what the tool *tells people to do* should say how you know.

Good: *"On this host, `x-cache: HIT` is emitted by the platform proxy and not by any plugin — here
are response headers from two sites, one with no caching plugin installed."*

Not good: *"Everyone knows this header means WP Rocket."*

Numbers are better than adjectives. If you claim a fix helps, a before/after from
`perf-probe.py --diff` is the most persuasive thing you can attach.

## Running the checks

```bash
python3 -m py_compile skills/**/*.py evals/*.py tools/*.py
python3 tools/check_no_egress.py
python3 evals/run_evals.py --list
```

CI runs these on Python 3.9 and 3.13. **3.9 is the floor and it is not negotiable**: a large share
of real WordPress sites run on older infrastructure, and operators frequently run these scripts on
the very box being audited. If you need a newer syntax feature, you almost certainly do not.

## Style

- Comments explain *why*, not *what*. The code already says what it does.
- Name your constants and justify them. A bare `TIMEOUT = 47` will be sent back.
- Scripts handle their own errors with an actionable message. Never let a traceback reach the
  operator.
- Deterministic output: sort keys and lists. Comparing a before to an after is the whole point.
- Forward slashes in every path, in code and in docs.
- SPDX header on every new file: `# SPDX-License-Identifier: GPL-2.0-or-later`.

## Licensing

Contributions are accepted under [GPL-2.0-or-later](LICENSE), matching the WordPress ecosystem
norm. By opening a pull request you agree your contribution ships under that license.

## Scope

This project is a **complement** to [`WordPress/agent-skills`](https://github.com/WordPress/agent-skills),
not a competitor. It covers the live-site, browser-visible, builder-and-host-aware half that the
official `wp-performance` skill explicitly excludes. If your contribution is really about
profiling a local checkout with WP-CLI, it will land better upstream — and we would rather link to
it there than duplicate it here.
