<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Performance audit — {{SITE}}

<!--
  The report template. Its shape is fixed by report-contract.md, and scripts/check_report.py
  enforces that shape — run it on the draft before publishing.

  Two sections make this different from every other audit report and must never be dropped:
  "What could not be checked" and "What did not work". An audit that only lists wins is a sales
  document. Fill every section; write "none" rather than deleting one.
-->

**Audited:** {{DATE}} · **Access tier:** {{TIER}} ({{TIER_NAME}}) · **Tooling:** {{TOOLS}}

## Scorecard

The numbers a reader looks for first. Every row is always present. A metric nobody measured says
`unmeasured` with the reason in **Source** — never a blank, never an estimate, and never a rating.

Ratings come from the published table in [report-contract.md](report-contract.md), evaluated at the
75th percentile of field data. Only LCP, INP and CLS have one; every other row carries `—`. **Say
`lab` or `field` in Source for the three rated rows** — a single lab run is a useful approximation of
a field threshold, not the same statement, and the reader has to be able to tell which they are
holding.

| Metric | Value | Rating | Source |
|---|---|---|---|
| LCP | {{LCP}} | {{LCP_RATING}} | {{LCP_SOURCE}} |
| INP | {{INP}} | {{INP_RATING}} | {{INP_SOURCE}} |
| CLS | {{CLS}} | {{CLS_RATING}} | {{CLS_SOURCE}} |
| FCP | {{FCP}} | — | {{FCP_SOURCE}} |
| TBT | {{TBT}} | — | {{TBT_SOURCE}} |
| Speed Index | {{SPEED_INDEX}} | — | {{SPEED_INDEX_SOURCE}} |
| TTFB (origin) | {{ORIGIN_TTFB}} | — | {{ORIGIN_TTFB_SOURCE}} |
| TTFB (edge) | {{EDGE_TTFB}} | — | {{EDGE_TTFB_SOURCE}} |
| Page weight | {{TOTAL_WEIGHT}} | — | {{WEIGHT_SOURCE}} |
| Requests | {{REQUESTS}} | — | {{REQUESTS_SOURCE}} |

<!--
  If the payload walk was capped or did not finish, say so in the Page weight Source cell: that
  total is a floor over a sample, not a page weight.
  Add extra rows here when you have them — field/CrUX data, a second URL, a per-template breakdown.
  They are validated by the same rules.
-->

{{SCORECARD_NOTES}}

## Stack

What this site actually runs on. Confidence is stated because it changes how much weight a finding
deserves — and `Source` names what produced that confidence, because the same word means different
things behind a public probe and behind a command you ran.

Most rows come from `fingerprint.py`. Any row you confirmed at a higher access tier says so
instead — `WP-CLI tier 2`, `host control panel`, `operator` — because `fingerprint.py` reads public
HTTP responses only, and a managed host's gateway cache or a server-side object cache does not
appear in one. Writing `fingerprint.py` next to a value it rated `unknown` is the specific error
this column exists to stop.

| Layer | Detected | Confidence | Source |
|---|---|---|---|
| Builder / editor | {{BUILDER}} | {{BUILDER_CONF}} | {{BUILDER_SRC}} |
| Theme | {{THEME}} ({{THEME_TYPE}}) | {{THEME_CONF}} | {{THEME_SRC}} |
| Host | {{HOST_CLASS}} | {{HOST_CONF}} | {{HOST_SRC}} |
| Server | {{SERVER}} | {{SERVER_CONF}} | {{SERVER_SRC}} |
| Edge / CDN | {{CDN}} | {{CDN_CONF}} | {{CDN_SRC}} |
| Server cache | {{SERVER_CACHE}} | {{SERVER_CACHE_CONF}} | {{SERVER_CACHE_SRC}} |
| Page-cache plugin | {{PAGE_CACHE}} | {{PAGE_CACHE_CONF}} | {{PAGE_CACHE_SRC}} |
| Object cache | {{OBJECT_CACHE}} | {{OBJECT_CACHE_CONF}} | {{OBJECT_CACHE_SRC}} |
| Multilingual | {{MULTILINGUAL}} | {{ML_CONF}} | {{ML_SRC}} |
| WooCommerce | {{WOO}} | {{WOO_CONF}} | {{WOO_SRC}} |

{{STACK_NOTES}}

## Baseline

Origin and edge are reported separately and must stay that way. A cached site's slow origin and
its slow visitor experience are different problems with different fixes; a blended number hides
which one this site has.

| Page | Origin TTFB | Edge TTFB | Cache | Requests | Weight |
|---|---|---|---|---|---|
| {{URL}} | {{ORIGIN_TTFB}} ms | {{EDGE_TTFB}} ms | {{CACHE_STATUS}} | {{REQUESTS}} | {{TOTAL_KB}} KB |

{{BASELINE_NOTES}}

## Findings

Ranked by how much they are expected to move a real metric — not by how easy they are to fix, and
not by how many of them there are. Each names the evidence it rests on.

### 1. {{FINDING_TITLE}}

- **Layer:** {{LAYER}} · **Class:** [`{{CATALOG_ENTRY}}`]({{CATALOG_PATH}})
- **Evidence:** {{EVIDENCE}}
- **Expected effect:** {{EXPECTED_EFFECT}}
- **Fix:** {{FIX}}
- **Risk / constraint:** {{RISK}}
  <!-- If the host forbids the obvious fix, say so here and give the permitted path instead. -->

## Disproven

<!--
  Optional but recommended. Hypotheses that were tested and rejected, so the next audit does not
  re-open a settled question. Delete this heading if there were none — it is the one section here
  that is not mandatory.
-->

- {{DISPROVEN_CLAIM}} — {{DISPROVING_EVIDENCE}}

## What could not be checked

**Do not delete this section.** These are the questions this audit had no way to answer at its
access tier or with the tooling available. Anyone reading the findings above needs to know the
audit's boundary, or they will read silence as absence.

| Not checked | Why | What would be needed |
|---|---|---|
| {{UNCHECKED_ITEM}} | {{UNCHECKED_REASON}} | {{UNCHECKED_REQUIREMENT}} |

## Changes applied

Only for sessions that used the fix skill; write `none — read-only audit` otherwise. Every row needs
a rollback that has been verified to exist, not merely to have been intended.

| # | Change | Layer purged | Verified how | Rollback |
|---|---|---|---|---|
| 1 | {{CHANGE}} | {{PURGE_LAYER}} | {{VERIFICATION}} | {{ROLLBACK}} |

## Result

Before and after, on the same scorecard rows, measured warm under the same conditions. Empty for a
read-only audit.

| Metric | Before | After | Δ |
|---|---|---|---|
| {{METRIC}} | {{BEFORE}} | {{AFTER}} | {{DELTA}} |

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
