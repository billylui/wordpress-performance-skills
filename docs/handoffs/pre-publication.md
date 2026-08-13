<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Handoff — pre-publication

**Status:** OPEN · **Opened:** 2026-08-12 · **Owner:** maintainer

Everything needed to *build* v0.1 has shipped. This records what is deliberately not done, so
nobody re-derives it and nobody assumes it was finished.

## What already shipped (LIVE — do not redo)

All four phases are merged to `main` and CI is green there.

| PR | Landed |
|---|---|
| [#1](https://github.com/billylui/wordpress-performance-skills/pull/1) | Measurement spine: `fingerprint.py`, `perf-probe.py`, `capabilities.py`, eval harness |
| [#2](https://github.com/billylui/wordpress-performance-skills/pull/2) | `wp-perf-audit`, 20-entry defect catalog, reference library |
| [#3](https://github.com/billylui/wordpress-performance-skills/pull/3) | `wp-perf-fix`, host-constraint gate, `validate_plan.py` |
| [#4](https://github.com/billylui/wordpress-performance-skills/pull/4) | Packaging, install path, anonymized case study |

Four review checkpoints ran at `xhigh`, converging 12 → 5 → 4 → 1 findings. Records are in
`~/.claude/.codex-reviews/checkpoint-wordpress-performance-skills-*.md`.

Verification standing on `main`: compile on Python 3.9 and 3.13; `check_no_egress`;
`check_skill_docs` across 32 files; `check_plugin_manifest`; `validate_plan.py --selftest` 11/11;
`tools/adversarial_gate_tests.py` 30/30 with 1 skipped.

Repository presentation is complete: description, 12 topics, homepage, community health files
(README, LICENSE, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, CHANGELOG, `llms.txt`), issue and PR
templates, five Mermaid diagrams. License is detected as GPL-2.0. Wiki and Projects are disabled.

## Open items

### 1. The repository is still PRIVATE

Making it public is a publishing decision that has not been taken. Nothing technical blocks it.

### 2. `wp-perf-fix` has never run against a production host

**Problem:** the guarded write loop is exercised only against local fixtures and unit-level
gates. Its host-constraint tables, purge paths and rollback procedures have not been executed on
a real managed host.

**Why it matters:** this is the half that changes production sites. The catalog's per-host purge
instructions in particular are documentation-derived, not execution-verified.

**Fix:** run one low-risk change end-to-end on a site the maintainer controls — ideally the
smallest possible fix, on a host with a documented disallowed-plugin policy, so the gate is
exercised as well as the loop.

**Re-verify ground truth before acting:**

```bash
python3 skills/wp-perf-audit/scripts/fingerprint.py <URL> --json stack.json
python3 skills/wp-perf-fix/scripts/validate_plan.py plan.json --stack stack.json --preflight
```

### 3. The eval fixture matrix is not exercised across builder × cache combinations

**Problem:** `evals/fixtures/` can instantiate the stack matrix, but only a subset has been run.
Stacks nobody has pointed the audit at may be misread.

**Fix:** run the seeded-defect fixture across at least *{Elementor, Block/FSE, Divi, classic}* ×
*{page-cache plugin, server-level cache, no cache}*, and record which combinations were covered.

### 4. One adversarial case is skipped by design

`tools/adversarial_gate_tests.py` skips the end-to-end non-HTML probe case unless
`WP_PERF_TEST_NONHTML_URL` names an HTTPS endpoint serving non-HTML. It is not defaulted to a
third-party host because the project promises no undeclared egress. The predicate itself is
covered in-process; only the CLI path is unproven.

### 5. Cross-harness usability — researched, not exhaustively tested

**What is established.** Both skills pass `skills-ref validate`, the reference implementation
from the Agent Skills specification's own library, and that check runs in CI. The negative
control was confirmed: the validator rejects a deliberately malformed skill, so the pass is
meaningful. The cross-agent `skills` CLI reads this repository, reports `Found 2 skills`, and
lists both with their descriptions — and it auto-detects the running agent, so per-agent install
paths are its problem rather than ours. Both skills declare their runtime requirements in the
spec's `compatibility` field, where a conforming client can read them before executing anything.

**What is not.** Installation and execution have only been exercised on **Claude Code**. "Loads
and runs correctly on Codex, Cursor, Copilot or Gemini CLI" remains an untested claim, however
strong the format-level evidence is.

**Fix:** install on one other agent and run a tier-0 audit. Roughly ten minutes, and it converts
the strongest remaining assumption into evidence.

### 6. The escaped-bug taxonomy exists; the release contract is not yet exercised

`docs/TESTING.md` now holds the release contract and a backfilled taxonomy — one row per defect that
reached a real run without a test catching it first, each naming its **miss-class** rather than the
bug, so it predicts the next one instead of only recording the last.

Writing it did what a taxonomy is for: it found that the bot-User-Agent fix had shipped with **no
regression lock at all**. Nothing asserted the default was a browser string, so a refactor could have
reverted it and every check would still have passed. That gap is now closed.

**What remains:** the contract has never been *run* as a gate. No `docs/walkthroughs/<gate-id>.md`
report exists, and the two rows that cannot be automated — the per-host policy citations, WP-CAT-01
and WP-HOST-01 — have therefore never been exercised as a checklist row rather than as review habit.

**Fix:** run `/release-gate` once against `docs/TESTING.md` and keep the report, so the first real
use is not also the first release that depends on it.

### 7. The `sspe-website` audit PR #67 is open and unreviewed

A genuine audit of a live client site, written before the report contract existed. It was used as the
test artifact while building `check_report.py` and fails that checker on section shape and on every
scorecard row — which is the specification working, not a defect in the audit. The audit itself has
not been reviewed or merged, and nothing in this repository changed it.

### 8. Distribution and outreach — not started, deliberately

Each of these publishes under the maintainer's identity and should not be automated:

- A PR to [`WordPress/agent-skills`](https://github.com/WordPress/agent-skills) proposing this as
  the frontend/live-site companion. The highest-authority link available in this niche, and a
  genuine contribution — their `wp-performance` skill excludes exactly what this covers.
- Listings on skills.sh, the agent-skill awesome-lists, lobehub, and the agentskills.io showcase.
  Distribution and LLM-discoverability in one action.

Both should wait until the repository is public.

## Notes for whoever picks this up

The catalog's per-host claims are cited to first-party documentation wherever they could be
verified, and marked "confirm with the host" wherever they could not. **Preserve that
distinction.** An incorrect permissive claim about a host's policy is the most damaging error
this project can make, and the fail-closed default exists because of it.
