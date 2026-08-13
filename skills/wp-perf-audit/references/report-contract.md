<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# The report contract

The JSON these scripts emit is under contract in [docs/CONTRACTS.md](https://github.com/billylui/wordpress-performance-skills/blob/main/docs/CONTRACTS.md)
(absolute, so it resolves even when this skill is copied on its own). This file does the same job for
the **human deliverable**: it fixes the sections, their order, and the metrics that must appear, so
two different models on two different harnesses produce the same document.

`findings-report-template.md` is this contract as a fill-in-the-blanks document.
`scripts/check_report.py` is this contract as an executable check. When the three disagree, the
checker wins — it is the only one that runs.

## Contents

- [Why a contract and not just a template](#why-a-contract-and-not-just-a-template)
- [Mandatory sections, in order](#mandatory-sections-in-order)
- [The scorecard](#the-scorecard)
- [Rating a metric](#rating-a-metric)
- [`unmeasured` is a complete answer](#unmeasured-is-a-complete-answer)
- [The same rows on every harness](#the-same-rows-on-every-harness)
- [Validating a draft](#validating-a-draft)

## Why a contract and not just a template

A real audit produced good content in an ad hoc shape: Core Web Vitals collapsed into a single
`UNMEASURED` line, no rating anywhere, no statement of where each number came from, and page weight
missing entirely because the payload walk had not finished. Nothing in it was dishonest. It was
simply not the same document the next audit would produce, and the metrics a reader looks for first
were not visible.

The failure mode worth naming: **an unmeasured metric disappeared instead of appearing with a
reason.** A reader cannot tell the difference between "we measured LCP and it was fine" and "nobody
measured LCP", because both look like silence. Fixing that is most of the value here.

One more thing this design accounts for. A skill's `SKILL.md` is loaded once, when the skill
activates, and is not re-read later — so an instruction near the top of a long procedure has to
survive an entire audit's worth of intervening measurement output before the report gets written.
That is a lot to ask of any model. `check_report.py` exists because a script's output arrives in
context at the moment it matters, and a paragraph read an hour ago does not.

## Mandatory sections, in order

Every section below appears in every report, as an H2, in this relative order. Extra sections may be
added between them — a report that needs `## Suggested order` or `## Reproducibility` should have
it. What is not permitted is dropping one: **write `none` rather than deleting a heading**, because a
missing section reads as "nothing to say here" when it usually means "not checked".

| # | Section | Why it exists |
|---|---|---|
| 1 | `## Scorecard` | The numbers a reader looks for first. Always first, always complete. |
| 2 | `## Stack` | A finding only means something against the stack it was found on. |
| 3 | `## Baseline` | Origin and edge TTFB stay separate; a blended number hides which problem the site has. |
| 4 | `## Findings` | Ranked by expected effect on a metric, each naming its evidence. |
| 5 | `## What could not be checked` | The audit's boundary. Without it, silence reads as absence. |
| 6 | `## Changes applied` | `none — read-only audit` when no fix ran. |
| 7 | `## Result` | Before, after, delta. Empty for a read-only audit. |
| 8 | `## What did not work` | Targets missed, fixes that moved nothing, findings that proved wrong. |
| 9 | `## Deliberate decisions` | Things that look like oversights in the numbers but were chosen. |
| 10 | `## Still open` | Ranked, with an honest note on whether each is worth doing. |

Sections 5 and 8 are the two this report format exists for. A report containing only wins is a sales
document, and the next person to touch the site pays for the omission. The checker refuses a draft
where either heading is present but empty, because a bare heading is the easiest way to satisfy the
letter of the rule and none of its purpose.

**Recommended optional section:** `## Disproven`, placed before section 5, for hypotheses that were
tested and rejected. A real audit invented this heading because it had nowhere else to record that
autoload bloat was measured and found not to be the bottleneck. Naming the slot here saves the next
report from re-inventing it, and saves the next audit from re-opening a settled question.

## The scorecard

Four columns, exactly:

```
| Metric | Value | Rating | Source |
```

Ten rows, always present, in this order:

| Metric | Rated | Typical source |
|---|---|---|
| LCP | yes | browser paint timing |
| INP | yes | browser plus a driven interaction |
| CLS | yes | browser layout-shift entries |
| FCP | no | browser or Lighthouse |
| TBT | no | Lighthouse |
| Speed Index | no | Lighthouse |
| TTFB (origin) | no | `perf-probe.py`, cache-buster |
| TTFB (edge) | no | `perf-probe.py`, bare URL |
| Page weight | no | `perf-probe.py` |
| Requests | no | `perf-probe.py` |

Extra rows are allowed and are validated by the same rules — field data from CrUX, a second URL, a
per-template breakdown. Only the ten above are required.

A worked example, mixing measured and unmeasured rows:

```
| Metric | Value | Rating | Source |
|---|---|---|---|
| LCP | 4.9 s | poor | lab · Chrome DevTools MCP |
| INP | unmeasured | — | no interaction driven; load-only pass |
| CLS | 0.02 | good | lab · Chrome DevTools MCP |
| FCP | 1.8 s | — | lab · Chrome DevTools MCP |
| TBT | unmeasured | — | no Lighthouse available in this session |
| Speed Index | unmeasured | — | no Lighthouse available in this session |
| TTFB (origin) | 4,461 ms | — | perf-probe, cache-buster |
| TTFB (edge) | 172 ms | — | perf-probe, bare URL |
| Page weight | 18.1 MB | — | perf-probe (floor — asset cap applied) |
| Requests | 696 | — | perf-probe |
```

Note the page-weight row. `asset_cap_applied` or a walk that could not finish makes the total a
**floor over a sample**, not a page weight, and the `Source` cell says so. Reporting it as a plain
number would be the same class of error as inventing one.

## Rating a metric

Ratings come from a published table, never from per-run judgement. Two models looking at the same
4.9-second LCP have to reach the same word, and "poor" has to mean the same thing in every report.

Core Web Vitals thresholds, evaluated at the **75th percentile of field data**:

| Metric | Good | Needs improvement | Poor |
|---|---|---|---|
| LCP | 2.5 s or less | above 2.5 s, up to 4.0 s | above 4.0 s |
| INP | 200 ms or less | above 200 ms, up to 500 ms | above 500 ms |
| CLS | 0.1 or less | above 0.1, up to 0.25 | above 0.25 |

**The good boundary is inclusive.** The published definitions read "200 milliseconds or less" and
"0.1 or less", so a metric landing exactly on 2.5 s, 200 ms or 0.1 is `good`, not
`needs-improvement`. Written as `< 2.5 s` this is easy to get backwards, and the checker did until
a review compared the wording against the source.

The rating vocabulary is closed: `good`, `needs-improvement`, `poor`, or `—`. An ASCII `-` is
accepted wherever `—` is, because the em dash is awkward to type on many keyboards and a hyphen in
a Rating column is unambiguous. What matters is that no rating was claimed.

Sources: [web.dev Core Web Vitals](https://web.dev/articles/vitals) ·
[Lighthouse scoring](https://github.com/GoogleChrome/lighthouse/blob/main/docs/v8-perf-faq.md).

**Everything else carries `—`, and the checker refuses a rating word on it.** There is no published
threshold table here for FCP, TBT, Speed Index, TTFB, page weight or request count, and a rating with
no table behind it is an invented number wearing a word. Those rows still earn their slots: FCP, TBT
and Speed Index are inputs to the Lighthouse performance score, weighted TBT 30, LCP 25, CLS 25,
FCP 10, Speed Index 10 — which is the most useful guide available to *which* metric to attack first.
A page whose score is dominated by TBT needs main-thread work, not a smaller hero image.

**Lab and field are different measurements, and the report has to say which it has.** The thresholds
above are defined against field data at the 75th percentile. Rating a single lab run against them is
the common practice and a useful approximation, but it is not the same statement — one load on one
machine on one connection is not what a population of real users experienced. So the `Source` cell on
the LCP, INP and CLS rows must declare `lab` or `field`, and the checker enforces it. Everything else
in the report can be read correctly only once that word is present.

## `unmeasured` is a complete answer

**Never estimate, infer, or carry a number over from another tool or another run.** An invented
metric is the one failure this project cannot tolerate — it is worse than an empty slot, because a
reader cannot tell it apart from a real measurement and will make decisions on it.

A row that could not be measured takes the literal value `unmeasured`, a rating of `—`, and a
**reason** in the `Source` cell. Use `unavailable` instead when the data source exists but has
nothing for this site — field data for a site below the traffic threshold is `unavailable`, not
`unmeasured`.

The reason has to say what was actually missing, because the fixes differ:

| Weak reason | Useful reason |
|---|---|
| `not available` | `no browser-capable tool in this session` |
| `could not measure` | `browser pane hidden; visibilityState was "hidden", so no paint entries were recorded` |
| `n/a` | `load-only pass; INP needs a driven interaction` |

[measurement-objectives.md](measurement-objectives.md) states, per metric, the capability required,
the providers in preference order, and the honest answer when none is available. Read it when
deciding whether a row is genuinely unmeasurable in this session or merely unmeasured so far.

## The same rows on every harness

No two agent harnesses offer the same tools. A session with Chrome DevTools MCP fills the LCP row; a
session with nothing but a shell does not. That difference is real and must not be papered over.

What this contract fixes is that the difference shows up **in one place**: the `Value` and `Source`
cells. The rows themselves, their order, and the sections around them are identical everywhere. A
reader comparing two reports from two harnesses can see immediately which one had a browser, instead
of having to notice that three rows are missing from one of them.

This is why the objectives are keyed to **capabilities** rather than to named tools or named
harnesses. "A browser that reports paint timing" stays true as tools come and go; "use Chrome
DevTools MCP" is wrong on the harness that does not have it, and rots on the one that renames it.

## Validating a draft

A template is advice. Run the checker before publishing:

```bash
python3 "$SKILL_DIR/scripts/check_report.py" report.md
```

It reports every violation at once, and its messages name what a conforming report would look like —
the expected rows, the expected section order, the permitted rating words — so a failure is
actionable without reading this file again.

It also refuses a draft that still carries `{{PLACEHOLDER}}` slots anywhere, not only in the
scorecard. A report copied from the template with just the numbers filled in is not finished, and
publishing on a clean exit would otherwise hand an operator a half-written document the checker had
blessed. And when a fix run fills in `## Result`, that table must carry the same ten rows the
scorecard does — a metric that did not move is the result an operator most needs to see.

Treat it as a loop, not a gate at the end: draft, check, fix what it names, check again, and publish
only on a clean run. A non-zero exit means the report is not finished.

Exit codes follow the repo convention: `0` conformant, `1` violations found, `2` usage error,
`4` the report could not be read.
