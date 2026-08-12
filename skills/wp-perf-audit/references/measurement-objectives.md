<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Measurement objectives and the capabilities they need

This file exists so the audit produces the same **outputs** on every harness, even though no two
harnesses offer the same **tools**.

Each objective below states what number is wanted and why, the capability required to obtain it,
the known providers in preference order, and — the part that matters most — **the honest answer
when nothing can provide it**. An agent should read the objective and choose from what its own
session actually has, rather than looking for a tool this document happens to name.

## Contents

- [How to use this](#how-to-use-this)
- [The objectives](#the-objectives)
- [Providers, and how to tell whether you have one](#providers-and-how-to-tell-whether-you-have-one)
- [Known traps](#known-traps)

## How to use this

1. Read the objective, not the tool name. The objective is stable; tool availability is not.
2. Take the first provider your session actually has. Do not assume a provider exists because it
   is listed, and do not skip a lower-preference provider that is present.
3. If no provider is available, the objective is **unmeasured**. Record it as unmeasured with the
   reason, in the slot it belongs to in
   [findings-report-template.md](findings-report-template.md) — an empty slot with a stated
   reason, never an omitted row.
4. **Never estimate, infer, or carry over a number from another tool or another run.** An
   invented metric is the one failure this project cannot tolerate; an empty slot with a reason
   is a complete answer.

## The objectives

| Objective | Metric | Capability required | Providers, best first | If none available |
|---|---|---|---|---|
| How soon does the main content appear? | **LCP** | A real browser that reports paint timing, with the page **visible** | Chrome DevTools MCP · Lighthouse CLI · PageSpeed Insights API (operator key) · any browser automation exposing `PerformanceObserver` | Report `unmeasured`. TTFB and payload do **not** substitute — they are inputs to LCP, not proxies for it. |
| How responsive is it to input? | **INP** | A browser **plus a real interaction**; a load-only pass cannot produce it | Chrome DevTools MCP with a driven interaction · field data from PSI/CrUX | Report `unmeasured`. State whether the blocker was the tool or the absence of an interaction — they are different problems. |
| How much does layout jump? | **CLS** | A browser that reports layout-shift entries | Chrome DevTools MCP · Lighthouse CLI · PSI API | Report `unmeasured`. |
| How long does the server take to respond? | **TTFB, origin and edge** | HTTP client that can time first byte and set a cache-buster | `perf-probe.py` (bundled — always available where this skill runs) | Not applicable: this is the one objective the skill can always meet. |
| How heavy is the page? | **Transferred bytes, requests** | HTTP client that can walk referenced resources | `perf-probe.py` (bundled) | Not applicable. Note `asset_cap_applied` if the walk was capped — that total is a floor. |
| What is the site built on? | **Stack profile** | HTTP client | `fingerprint.py` (bundled) | Not applicable. |
| Which element is the largest paint? | **LCP element attribution** | Browser that reports the LCP entry's element | Chrome DevTools MCP · browser automation reading the `largest-contentful-paint` entry | Report `unmeasured`. This attribution is what distinguishes a gated-LCP finding from a heavy-asset finding, so without it, say the cause is undetermined rather than guessing. |
| What do real users experience? | **Field data** | Access to CrUX, via PSI API or the CrUX API | PageSpeed Insights API (operator key) · CrUX API | Report `unavailable`, and say whether the cause is a missing key or the site being below Google's traffic threshold. Small sites legitimately have none; that is not a failure. |

## Providers, and how to tell whether you have one

Detection is per-session and must be checked, not assumed.

**Chrome DevTools MCP** — an MCP server, so it will not appear on `PATH`. Look for tools named
for it in your own tool list. `capabilities.py` reports it as `present: false` when it cannot
confirm one locally, and distinguishes *confirmed absent* from *not confirmable from here* —
treat the latter as "check your own tool list" rather than as absence.

**Lighthouse CLI** — `lighthouse --version` on `PATH`. `capabilities.py` probes for it.

**PageSpeed Insights API** — needs a key the operator supplies. `capabilities.py` reports only
whether a key-shaped environment variable is *set*, never its value. A key is operator-supplied
input, so calling PSI with it does not breach the no-egress guarantee — but say in the report
that the site URL was sent to a third party.

**Generic browser automation** — any tool that can evaluate JavaScript in a real page will do:
register a `PerformanceObserver` for `largest-contentful-paint` and `layout-shift`. This is the
fallback that works on the widest range of harnesses.

**No browser at all** — a legitimate and common state. The audit remains complete for TTFB,
payload, stack and cache-layer findings; only the browser-dependent rows are `unmeasured`.

## Known traps

**A hidden or backgrounded browser pane suppresses paint recording.** Observed on a real audit:
the page reported `document.visibilityState === "hidden"`, and no `largest-contentful-paint`
entry was ever emitted even though the browser supported the entry type. The API was fine; the
pane was the blocker. **Check `visibilityState` before concluding a browser cannot measure LCP**,
and if it is hidden, say so rather than reporting the metric as unsupported.

**A load-only pass cannot produce INP.** INP measures real interactions. Driving one interaction
gives a single-interaction reading, which is informative but is not the field metric. Say which
you have.

**Lab and field are different measurements.** The published thresholds are defined against the
**75th percentile of field data**. A lab number rated against them is a useful approximation and
the common practice, but it is not the same statement. Label every scorecard row with its source
so nobody reads a single lab run as a field verdict.

**One dead host can hang an entire walk.** On a real audit, font CSS pointed at a staging domain
that resolved but never responded, and every font request burned a 25-second timeout. If a walk
is slow, check whether one unreachable host is responsible before capping or abandoning it.
