<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Catalog entry template

Every file under `skills/wp-perf-audit/references/catalog/` follows this shape. The consistency
is not cosmetic: the audit skill reads exactly one entry per suspected defect and must find the
same sections in the same order every time, whatever stack it is standing on.

## Contents

- [Why the shape is fixed](#why-the-shape-is-fixed)
- [Hard rules](#hard-rules)
- [The template](#the-template)
- [Writing the Detect section](#writing-the-detect-section)
- [Writing the Fix section](#writing-the-fix-section)

## Why the shape is fixed

An entry is read at two different moments by two different skills. `wp-perf-audit` reads
**Symptom → Detect → Attribute** while deciding whether the defect is present and how much it
costs. `wp-perf-fix` reads **Fix → Verify → Rollback** while changing something. The entry has
to serve both without either skill loading the other's half by accident, so the boundary between
them is a heading, not a judgement call.

Stack-specific knowledge lives in **sections inside the entry**, never in a separate
`adapters/` file. References must stay one level deep from `SKILL.md`, because an agent that
reaches a file through another file may read only part of it and act on the fragment. One entry,
read whole, is the unit.

## Hard rules

1. **Table of contents at the top.** Required for any file over 100 lines, and every real entry
   will be. It is what lets an agent previewing the file see the full scope.
2. **`unknown` over a guess, everywhere.** If a signal cannot distinguish two stacks, say so and
   give the next check that would. Never let the reader infer certainty you do not have.
3. **Every detection names its evidence.** A header, a class token, a file path, a query result —
   something checkable. "Look for slow loading" is not a detection.
4. **No time-sensitive facts.** No market-share percentages, no "as of version X", no dated
   claims. Those rot and this file cannot be re-verified at read time. Version-specific behaviour
   goes in a collapsed `<details>` block labelled as historical.
5. **The Fix section is host-aware or it is wrong.** A fix the platform will strip out, or that
   fights the host's own cache, is worse than no fix. If a change is prohibited on some hosting,
   that belongs in Fix, not in a footnote.
6. **Cross-link, don't duplicate.** Backend profiling depth belongs to
   [`WordPress/agent-skills`](https://github.com/WordPress/agent-skills). Link it and move on.
7. **Every claim about what a browser or WordPress does must be checkable.** Prefer "the element
   carries `opacity: 0` until the script runs, so no paint is recorded" over "animations hurt LCP".

## The template

```markdown
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# <Defect class name>

<One sentence: what is wrong, stated as a mechanism rather than a symptom.>

## Contents
- Symptom
- Detect
- Attribute
- Fix
- Verify
- Rollback
- Gotchas

## Symptom

What the operator notices, and what the measurement shows. Name the metric this moves —
LCP, INP, CLS, TTFB, or transferred bytes — and say plainly when it moves *nothing*
measurable, because a real catalog contains entries that are usually not worth fixing.

## Detect

### At tier 0 (public URL only)
<The check that needs nothing but the page. State the exact signal.>

### At tier 1+ (admin / REST)
<What extra certainty admin access buys. Omit the heading if it buys nothing.>

### At tier 2+ (WP-CLI / SSH)
<Same. Omit if nothing.>

### By stack
| Stack | Signal | Confidence | Notes |
|---|---|---|---|
| Elementor | `.elementor-invisible` on the LCP element | high | |
| Divi | ... | | |
| Block editor / FSE | ... | | |
| Classic, no builder | ... | | |

Only list stacks where the signal genuinely differs. A row saying "same as generic" is noise;
leave it out and say so once above the table.

## Attribute

How to tell this defect is actually causing the number, rather than merely co-occurring with it.
This is the section that stops an audit reporting ten findings that are really one. Say what
would *disprove* the attribution.

## Fix

### The change
<The smallest change that resolves the mechanism.>

### Host constraints
| Host class | Permitted | Path |
|---|---|---|
| WP Engine | ... | ... |
| Kinsta | ... | ... |
| Server-level cache only | ... | ... |

If no host prohibits anything here, write "No host-specific restriction applies." — do not
delete the section, because its absence reads as "not checked".

### Risk
What this can break, and who notices first.

## Verify

The measurement that proves it worked, and the layer that must be purged before that
measurement means anything. Re-measure warm: a reading taken immediately after a cache flush is
transient and not comparable.

## Rollback

The exact restoration, and what artifact must have been captured beforehand for it to be possible.

## Gotchas

Things that are true and surprising. Prefer ones that have actually bitten someone.
```

## Writing the Detect section

Tier and stack are different axes and both matter. Tier is *how much access the operator has*;
stack is *what software is running*. A signal available at tier 0 on Elementor may need tier 2 on
a block theme, and the table exists so the agent does not have to reason that out under
uncertainty.

Where a signal is genuinely stack-independent, say so once and skip the table entirely. Padding
the table with identical rows makes the real differences harder to see.

## Writing the Fix section

Order fixes by the mechanism they address, not by convenience. The recurring lesson from real
campaigns is that **the largest wins are usually configuration, not assets** — a font nothing
references, an animation holding the largest element invisible. An entry that jumps to
"compress the images" when the mechanism is a visibility gate is teaching the wrong reflex.

State the smallest change that resolves the mechanism. If a bigger change is also worth making,
that is a separate entry, cross-linked.
