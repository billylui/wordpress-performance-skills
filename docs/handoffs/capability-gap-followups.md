<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Capability gap list: two defects the ship review left open

**Status:** OPEN · **Opened:** 2026-08-14 · **Owner:** unassigned

Both are in the `cannot_measure` gap list added on `capability-gap-negotiation`. Neither is a
safety defect — they are honesty and contract defects in newly emitted output — but both were found
by an independent review and neither is fixed.

## Re-verify ground truth before acting

```bash
python3 skills/wp-perf-audit/scripts/capabilities.py --quiet --json - | python3 -m json.tool | head -40
grep -n '"kind"' docs/CONTRACTS.md skills/wp-perf-audit/scripts/capabilities.py
```

## 1. `kind` is emitted but not in the contract — WP-SCHEMA-01 fails

`capabilities.py` emits `cannot_measure[].kind`, taking `provider` or `access`. `docs/CONTRACTS.md`
still describes schema 1.1 entries without it; the only `kind` in the contract is the unrelated
`target.kind` on a change plan.

This matters beyond tidiness. `SKILL.md` now uses the discriminator to decide which of the two
operator conversations a gap belongs to — providers at step 2, access at step 4b — so a consumer
implementing the published contract cannot make the distinction the procedure depends on.

**Fix:** document the field and its closed vocabulary in the capability schema, and decide whether
it warrants 1.2. The contract changes first; that is the rule this broke.

## 2. With no `--target`, provider gaps are structurally unactionable

Run without `--target` and with no browser or key, LCP/INP/CLS/field-data gaps keep
`kind: "provider"` and an `unlock` listing only Lighthouse/MCP/PSI — none of which can produce a
measurement when there is no URL to measure. Only `blocked_by` mentions the missing target, and
only in prose.

An earlier attempt "fixed" this by prepending the URL sentence to `blocked_by` and leaving the
structured fields alone. **That is why this is a sibling and not a new finding:** the human string
changed and the machine-readable guidance did not, so anything consuming the structure is still
told to go and install Lighthouse.

**Fix:** make the target a structured prerequisite — either emit a Tier-0 access gap for those
metrics too, or let a gap carry more than one prerequisite. The acceptance test is that nothing
consuming only `kind` and `unlock` is told to supply a provider that cannot help.

## Why these are handed off rather than fixed

This shipment ran three review rounds and produced eleven P2 findings, two of them siblings of
earlier fixes. The convergence protocol answers a sibling with stop-and-hand-off, not another
attempt, and it was reached twice. Continuing to patch under those conditions produces the spiral
the rule exists to prevent — and the evidence for that is finding 2 above, which is itself a
too-shallow fix of an earlier finding.

## Resume the ship from here

**Nothing from this shipment is merged.** Two PRs are open and stacked, both green in CI, both
blocked on the two findings above. The operator chose to hold and fix properly rather than waive.

| | |
|---|---|
| PR #33 | `schema-operation-and-tier-evidence` → `main` |
| PR #34 | `capability-gap-negotiation` → #33's branch |
| Gate report | `docs/walkthroughs/fafe639.md`, verdict NOT-READY |
| Review records | `~/.claude/.codex-reviews/checkpoint-wordpress-performance-skills-2026081*` — three rounds |

**They cannot be split.** The fixes for #33's own defects — `fingerprint.py`'s over-broad
`x-gateway-` match, `check_report.py`'s case-sensitive Stack rule, the GoDaddy revert — all live on
#34's branch. Merging #33 alone ships the defective versions. It is both or neither.

Order to resume in:

1. Fix item 1 (document `kind`). This alone flips WP-SCHEMA-01 to PASS and is pure contract work.
2. Fix item 2 (structured prerequisite), against the acceptance test stated above.
3. Re-review the fix — `codex exec -c model_reasoning_effort="xhigh" review --base <pre-fix sha>`,
   no prompt argument alongside `--base`.
4. Re-run `/release-gate`; it writes a new report keyed to the new HEAD. WP-SMOKE-01 needs a live
   probe of a real public site — the last one used `https://wordpress.org`.
5. Merge #33, then #34 (GitHub retargets it to `main` automatically), then delete both branches.

**Read `docs/walkthroughs/fafe639.md` before starting.** It records which rows were evidenced how,
including two whose evidence differs from what the row suggests, and it corrects one row it
originally passed in error.

## What already shipped and is LIVE — do not redo

Everything else in `b5557a1..HEAD` passed the gate: operation-scoped host gating, approval
evidence, the relaxed stack cross-check, the report provenance rule, the objectives drift checker,
the source-not-bytecode loader fix, and the access-tier gaps restored to `cannot_measure`
(5 gaps → 16, partition complete). 138/138 adversarial cases, every other checker exit 0.
