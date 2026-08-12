<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
## What this changes

<!-- One or two sentences. If it adds coverage for a stack, name the stack. -->

## How you know it is right

<!--
Evidence beats assertion, and this project's whole premise is that a confident wrong answer about
someone's production stack is worse than no answer.

For a detection change: what signal, observed where, and how you know nothing else emits it.
For a fix recommendation: what it changes, and on which stacks you verified it.
For a performance claim: before/after numbers, ideally from `perf-probe.py --diff`.
-->

## Checklist

- [ ] Vocabulary strings match the closed sets in [`docs/CONTRACTS.md`](../docs/CONTRACTS.md)
- [ ] Any new detection carries evidence and an honest confidence rating
- [ ] `unknown` is used rather than a guess where a signal cannot distinguish two stacks
- [ ] Any host policy claim cites the host's own documentation, or is marked as needing confirmation
- [ ] New catalog entries follow [`docs/catalog-entry-template.md`](../docs/catalog-entry-template.md)
- [ ] No time-sensitive facts (percentages, dated claims, version-pinned assertions)
- [ ] Checks pass locally:

```bash
python3 -m py_compile skills/*/scripts/*.py evals/run_evals.py tools/*.py
python3 tools/check_no_egress.py
python3 tools/check_skill_docs.py
python3 tools/check_plugin_manifest.py
python3 skills/wp-perf-fix/scripts/validate_plan.py --selftest
```

## Anything you are unsure about

<!-- Genuinely useful. "I could not verify this host's policy" is a better PR than a guess. -->
