<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# A missing target is routed to the wrong checkpoint

**Status:** OPEN · **Opened:** 2026-08-14 · **Owner:** unassigned

Small, real, and deliberately not fixed in the session that found it. Read "Why this is open" before
picking it up — the reason is about the session, not the defect.

## Re-verify ground truth before acting

```bash
# Match the tier-0 unlock, not a metric name: the label is "LCP" when no provider is present and
# "Largest Contentful Paint (LCP)" when one is, so a grep for the metric reproduces the issue only
# on some machines.
python3 skills/wp-perf-audit/scripts/capabilities.py | grep -B 3 "Tier 0: public"
grep -n "GAP_KIND_ACCESS, True" skills/wp-perf-audit/scripts/capabilities.py
```

## The defect

Run `capabilities.py` with no `--target`, and every objective needing a URL is re-keyed to an
`access` gap with `unlock: ["Tier 0: public"]`. That part is right: without a site there is nothing
to measure, so the URL is the actionable prerequisite, not a browser.

The rendering is wrong. `OPERATOR_SUPPLY_REPORT[(access, True)]` reads *"ask the operator to grant
this access, at SKILL.md step 4b once you can name what it would resolve"* — correct for tiers 1–3,
wrong for tier 0. **Step 4b comes after fingerprinting and measurement, both of which need the URL**,
so the guidance defers the one thing blocking the run to a checkpoint the run cannot reach.

## Scope, honestly

`SKILL.md` step 2 always invokes `capabilities.py --target <URL>`, so the audit path does not hit
this. It shows up when the script is run bare, which is a real thing an operator does when kicking
the tyres, but not the documented flow. **Wording infelicity in a degenerate invocation, not a
defect in the audit.**

## The fix — stated as an outcome, deliberately not as an implementation

Tier-0 gaps need their own supply wording: *supply this before the audit can begin*, as against
tier 1–3's *ask at step 4b*.

**This section used to prescribe a mechanism. A review found the prescription wrong in two ways, so
it has been removed rather than corrected** — the useful thing to hand over is the outcome and the
traps, not an implementation nobody has run.

What the prescription got wrong, kept because both are live traps for whoever picks this up:

1. It said to carry the integer tier through `access_gaps()`. **The re-keyed objective gaps never
   pass through `access_gaps()`** — they originate in `measurement_gaps()` and are converted inline
   in `measurement_boundaries`. Following the instruction would have left exactly the gaps this
   handoff is about still routed to step 4b.
2. Those dictionaries are serialized into `cannot_measure` unchanged, so adding a tier field to them
   **publishes an undocumented schema field** — precisely the defect fixed in the same commit that
   created this handoff. Either update the capability schema in `docs/CONTRACTS.md` first, or keep
   the routing metadata out of the serialized profile entirely.

Also avoid the obvious shortcut of branching on the `"Tier 0: public"` string inside `unlock`: a
guard keyed to a display string is the matcher shape behind both WP-ESC-12 and WP-ESC-15.

**Acceptance:** a tier-0 gap's rendered supply line must not mention step 4b, and a tier-2 gap's
still must — both directions, or the case is worthless. Exercise it with a provider both present and
absent, since the gap's metric label differs between those states.

## Why this is open rather than fixed

It was found by the fourth review round of one shipment. That shipment produced **fourteen P2
findings across four rounds**, and the pattern by the end was unambiguous: each of the last three
fixes introduced two or three new defects of its own. This finding is itself the third attempt at
one item — the no-target guidance — after a first attempt that changed only prose and a second that
fixed the structure but not the routing.

The convergence protocol answers that with stop-and-hand-off, and the value of honouring it is
higher than the value of a three-line wording change in a path the documented flow never takes. A
fresh session will fix this in ten minutes without the accumulated tunnel vision that made the last
three attempts partial.
