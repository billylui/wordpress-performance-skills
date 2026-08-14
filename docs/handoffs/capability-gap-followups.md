<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Capability gap list: two defects the ship review found, and how they were closed

**Status:** DONE · **Opened:** 2026-08-14 · **Closed:** 2026-08-14

Both are fixed. This file is kept rather than deleted because the second one is a worked example of
a fix that looked finished and was not, and the taxonomy row that came out of it points here.

## 1. `kind` was emitted but not in the contract — WP-SCHEMA-01 failed

`capabilities.py` emitted `cannot_measure[].kind` (`provider` | `access`) in five places while
`docs/CONTRACTS.md` never gained the field; the only `kind` in the contract was the unrelated
`target.kind`. `SKILL.md` uses the discriminator to choose between the step-2 provider ask and the
step-4b access ask, so a consumer implementing the published contract could not make the
distinction the procedure depends on.

**Closed:** the capability schema now defines `kind`, its closed vocabulary, and the rule that
`unlock` holds provider names on a provider gap and an access tier on an access gap, never mixed.
The contract changed first, which is the rule this broke in the first place.

## 2. With no `--target`, gaps named a prerequisite that could not help

Run without `--target`, the LCP/INP/CLS/field-data gaps kept `kind: "provider"` and an `unlock`
listing Lighthouse/MCP/PSI — none of which can measure anything when there is no URL. Supplying one
would only have revealed the missing target on the next run.

**The first attempt at this was the instructive part.** It prepended the missing target to the human
`blocked_by` string and left `kind` and `unlock` untouched, so anything reading the structured
fields was still told to install a tool that could not help. The review called it a *sibling* of the
original finding, correctly: the sentence changed and the defect did not.

**Closed:** with no confirmed target, every objective that needs one is re-keyed to the access ask
in full — `kind`, `capability`, `unlock` and `operator_can_supply`, not just the string. The
provider requirement is not lost; `blocked_by` names it, and the gap re-emits as a provider gap once
a target exists, which is the order the operator has to satisfy them in anyway.

## Evidence

```
adversarial: 145/145, 1 declared skip     (was 138 — 7 new cases, 4 of them controls)
```

- With no target: no gap's `unlock` names a tool; every gap is `kind: access`; the five re-keyed
  objective gaps name **both** prerequisites in `blocked_by`.
- **CONTROL** — with a target: provider gaps still exist (`CLS`, `Field data`, `INP`, `LCP`,
  `LCP element attribution`) and still list real tools. Without this control, re-keying everything
  to `access` unconditionally would have passed the first three cases while destroying the step-2
  ask.
- **CONTROL** — in both states the gaps are unique and disjoint from `can_measure`, so the two
  lists stay the mutually exclusive partition the contract calls the audit's boundary.
- **Mutation-tested.** Restoring the prose-only fix fails exactly the two structural cases while
  the `blocked_by` case keeps passing — a prose fix passes a prose test and fails a structure test,
  which is the whole point of the pair.

## What this cost, recorded so the next session inherits it

Three review rounds, eleven P2 findings, two of them siblings of earlier fixes. The convergence
protocol's stop rule fired twice and the ship was held rather than waived. The signal that mattered
was never the count — it was that each round found a previous fix of mine had been shallower than I
claimed. See taxonomy row WP-ESC-18.
