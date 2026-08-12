<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Performance audit — {{SITE}}

<!--
  The report template. Two sections make this different from every other audit report and must
  never be dropped: "What could not be checked" and "What did not work". An audit that only
  lists wins is a sales document. Fill every section; write "none" rather than deleting one.
-->

**Audited:** {{DATE}} · **Access tier:** {{TIER}} ({{TIER_NAME}}) · **Tooling:** {{TOOLS}}

## Stack

What this site actually runs on, from `fingerprint.py`. Confidence is stated because it changes
how much weight a finding deserves.

| Layer | Detected | Confidence |
|---|---|---|
| Builder / editor | {{BUILDER}} | {{BUILDER_CONF}} |
| Theme | {{THEME}} ({{THEME_TYPE}}) | {{THEME_CONF}} |
| Host | {{HOST_CLASS}} | {{HOST_CONF}} |
| Server | {{SERVER}} | {{SERVER_CONF}} |
| Edge / CDN | {{CDN}} | {{CDN_CONF}} |
| Server cache | {{SERVER_CACHE}} | {{SERVER_CACHE_CONF}} |
| Page-cache plugin | {{PAGE_CACHE}} | {{PAGE_CACHE_CONF}} |
| Object cache | {{OBJECT_CACHE}} | {{OBJECT_CACHE_CONF}} |
| Multilingual | {{MULTILINGUAL}} | {{ML_CONF}} |
| WooCommerce | {{WOO}} | {{WOO_CONF}} |

{{STACK_NOTES}}

## Baseline

Origin and edge are reported separately and must stay that way. A cached site's slow origin and
its slow visitor experience are different problems with different fixes; a blended number hides
which one this site has.

| Page | Origin TTFB | Edge TTFB | Cache | Requests | Weight |
|---|---|---|---|---|---|
| {{URL}} | {{ORIGIN_TTFB}} ms | {{EDGE_TTFB}} ms | {{CACHE_STATUS}} | {{REQUESTS}} | {{TOTAL_KB}} KB |

{{CWV_TABLE}}

<!-- If no browser-capable tool was available, say so here explicitly. Do not silently omit CWV. -->

## Findings, ranked by expected impact

Ranked by how much they are expected to move a real metric — not by how easy they are to fix, and
not by how many of them there are. Each names the evidence it rests on.

### 1. {{FINDING_TITLE}}

- **Layer:** {{LAYER}} · **Class:** [`{{CATALOG_ENTRY}}`]({{CATALOG_PATH}})
- **Evidence:** {{EVIDENCE}}
- **Expected effect:** {{EXPECTED_EFFECT}}
- **Fix:** {{FIX}}
- **Risk / constraint:** {{RISK}}
  <!-- If the host forbids the obvious fix, say so here and give the permitted path instead. -->

## What could not be checked

**Do not delete this section.** These are the questions this audit had no way to answer at its
access tier or with the tooling available. Anyone reading the findings above needs to know the
audit's boundary, or they will read silence as absence.

| Not checked | Why | What would be needed |
|---|---|---|
| {{UNCHECKED_ITEM}} | {{UNCHECKED_REASON}} | {{UNCHECKED_REQUIREMENT}} |

## Changes applied

Only for sessions that used the fix skill. Every row needs a rollback that has been verified to
exist, not merely to have been intended.

| # | Change | Layer purged | Verified how | Rollback |
|---|---|---|---|---|
| 1 | {{CHANGE}} | {{PURGE_LAYER}} | {{VERIFICATION}} | {{ROLLBACK}} |

## Result

| Page | Metric | Before | After | Change |
|---|---|---|---|---|
| {{URL}} | {{METRIC}} | {{BEFORE}} | {{AFTER}} | {{DELTA}} |

## What did not work

**Do not delete this section either.** Record every target that was missed, every fix that did
not produce its expected effect, and every finding that turned out to be wrong on investigation.

State the attribution honestly: how much was pre-existing and out of scope, and how much was this
work falling short. A report that only contains wins is not a report, and the next person to touch
this site is the one who pays for the omission.

| Intended | Achieved | Attribution |
|---|---|---|
| {{TARGET}} | {{ACTUAL}} | {{ATTRIBUTION}} |

## Deliberate decisions

Things that look like oversights in the numbers but were chosen, with the reason. Keeping a heavy
hero video because it is the brand's signature experience is a legitimate decision; leaving it
undocumented is what makes the next audit repeat the argument.

- {{DECISION}} — {{RATIONALE}}

## Still open

Ranked, with an honest note on whether each is worth doing.

1. {{OPEN_ITEM}} — {{OPEN_NOTE}}
