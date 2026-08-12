<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Handoff — a predictable report contract for audit and fix

**Status:** OPEN · **Opened:** 2026-08-13 · **Owner:** maintainer

## The problem, in the operator's words

> "Why don't I see those common metrics like what we can see from PageSpeed being the final
> output? The audit structure is not very organized and kinda random. We need a professional
> format and boundary to make sure any model or any harness can produce very predictable audit
> and fix outcomes."

And, relatedly:

> "Different models or different harnesses have different tools available. How can we instruct
> the model what tool we need and what objective we want, so the skills adapt dynamically?"

Both come from the same root cause. **The JSON that scripts emit is under contract; the human
deliverable is not.** `docs/CONTRACTS.md` fixes every field a script produces, but the report is
a loose template, so each run invents its own shape. The first real audit produced good content
in an ad hoc structure, and the metrics a reader expects to see first were not visible anywhere.

## What already shipped toward this

**`skills/wp-perf-audit/references/measurement-objectives.md`** — the capability half, merged.
For each number the audit reports it states the objective, the capability required, known
providers in preference order, how to detect them per-session, and the honest answer when none
exists. It also records four traps already paid for in real runs.

That answers the second question. **The first is not built.**

## What to build

### 1. `skills/wp-perf-audit/references/report-contract.md`

A fixed report structure, in the same spirit as `docs/CONTRACTS.md` — mandatory sections in a
fixed order, so two different models produce the same document shape.

It must open with a **scorecard whose rows are fixed and always present**. The current failure is
that unmeasured metrics simply vanish from the output; they must instead appear with an explicit
`unmeasured` state and a reason. An empty labelled slot is a complete answer; a missing row is
not.

```
| Metric | Value | Rating | Source |
|---|---|---|---|
| LCP | 4.9 s | poor | lab · Chrome DevTools MCP |
| INP | unmeasured | — | no interaction driven; load-only pass |
| CLS | 0.02 | good | lab · Chrome DevTools MCP |
| TTFB (origin) | 4,461 ms | — | perf-probe, cache-buster |
| TTFB (edge) | 172 ms | — | perf-probe, bare URL |
| Page weight | 18.1 MB | — | perf-probe (floor — asset cap applied) |
| Requests | 696 | — | perf-probe |
```

`measurement-objectives.md` already names the source for every row; the contract binds them to
fixed slots.

### 2. Ratings from a published table, not per-run judgement

**Researched 2026-08-13, cite rather than re-derive.** Core Web Vitals thresholds, evaluated at
the **75th percentile of field data**:

| Metric | Good | Needs improvement | Poor |
|---|---|---|---|
| LCP | < 2.5 s | 2.5 – 4.0 s | > 4.0 s |
| INP | < 200 ms | 200 – 500 ms | > 500 ms |
| CLS | < 0.1 | 0.1 – 0.25 | > 0.25 |

Lighthouse v12 performance-score weights, useful for explaining *which* metric to attack first:
**TBT 30% · LCP 25% · CLS 25% · FCP 10% · Speed Index 10%.**

Sources: [web.dev Core Web Vitals](https://web.dev/articles/vitals),
[Lighthouse scoring](https://github.com/GoogleChrome/lighthouse/blob/main/docs/v8-perf-faq.md).

**Carry the lab-versus-field caveat into the contract.** The thresholds are defined against
field data at p75. Rating a single lab run against them is the common practice and a useful
approximation, but it is not the same statement, and every row must name its source so nobody
reads one lab run as a field verdict.

### 3. Rewrite `findings-report-template.md` to match

It currently has the two mandatory honesty sections, which are good and must survive:
**"What could not be checked"** and **"What did not work"**. Add the scorecard at the top and fix
the section order. Keep the placeholder syntax — `tools/check_skill_docs.py` already skips
`{{PLACEHOLDER}}` link targets.

### 4. `tools/check_report.py` — make it enforceable, not aspirational

A template is advice; a checker is a contract. Validate a draft report before it is published:
every mandatory section present and in order, every scorecard row present, every row either a
value with a rating from the table or an explicit `unmeasured` with a reason, and no rating
invented for a metric with no value.

This is the same plan-validate-execute shape the fix skill already uses, applied to the
deliverable. It is what makes "any model produces a predictable outcome" true rather than hoped
for. The agent runs it on its own draft.

**Test it against the real report** at `sspe-website` PR #67 — a genuine, good-quality audit
written before the contract existed. What it fails on is the specification working.

### 5. The fix skill needs the same treatment

`wp-perf-fix` step 9 (Record) should emit **the identical scorecard, before and after, with a
delta column**. That is what an operator expects from a fix and it is what makes a null result
legible. Reuse the same contract file rather than writing a second one.

## Constraints that must not be broken

- **Never estimate a metric.** An invented number is the one failure this project cannot
  tolerate. `unmeasured` with a reason is a complete answer.
- **Every reference stays one level deep from `SKILL.md`** and must be linked from it, or
  `check_skill_docs.py` fails the build. A forward reference to an unwritten file also fails —
  that happened while drafting this.
- **No time-sensitive claims** in skill files; CI greps for them. The threshold table is stable
  enough to state, but do not write "as of 2026".
- Body budget: `SKILL.md` under 500 lines.

## Everything else still open

Tracked in [pre-publication.md](pre-publication.md): the repository is still private;
`wp-perf-fix` has never run against a production host; the eval fixture matrix is not exercised
across builder × cache combinations; execution is verified only on Claude Code; distribution and
outreach are deliberately not started.

Two more from this session:

- **The `sspe-website` audit PR #67 is open and unreviewed.** It is a genuine audit of a live
  client site and the best available test artifact for the report contract. Its worktree was left
  at `wt-perf` in that session's scratchpad.
- **A dead host can still hang a payload walk.** `--max-assets` caps the count, but the real
  stall on that site was font CSS pointing at a staging domain that resolved and never answered,
  burning a 25-second timeout per request. A per-host circuit breaker — stop requesting a host
  after N consecutive timeouts — would fix the cause rather than the symptom.

## Re-verify ground truth before acting

```bash
cd /Users/billylui/Development/wordpress-performance-skills
python3 tools/check_skill_docs.py
python3 tools/check_no_egress.py
python3 tools/check_plugin_manifest.py
python3 skills/wp-perf-fix/scripts/validate_plan.py --selftest
python3 tools/adversarial_gate_tests.py
npx -y skills-ref@latest validate ./skills/wp-perf-audit
```

Expected at the time of writing: all clean, validator 11/11, adversarial 34/34 with 1 skipped.
