<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# A missing target is routed to the wrong checkpoint

**Status:** OPEN · **Opened:** 2026-08-14 · **Owner:** unassigned

Small, real, and deliberately not fixed in the session that found it. Read "Why this is open" before
picking it up — the reason is about the session, not the defect.

## Re-verify ground truth before acting

```bash
python3 skills/wp-perf-audit/scripts/capabilities.py | grep -A 3 "^  - LCP:"
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

## The fix

Tier-0 gaps need their own supply wording: *supply this before the audit can begin*, as against
tier 1–3's *ask at step 4b*. The obvious implementation — branching on the `"Tier 0: public"` string
inside `unlock` — is the matcher-shaped trap this repo has been bitten by twice (WP-ESC-12,
WP-ESC-15): a guard keyed to a display string. `access_gaps()` already receives the `tier` as an
integer, so carry that through instead of re-deriving it from prose.

Acceptance: a tier-0 gap's rendered supply line must not mention step 4b; a tier-2 gap's still must.
Both directions, or the case is worthless.

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
