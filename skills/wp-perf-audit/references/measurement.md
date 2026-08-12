<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Measurement

Performance numbers are useful only when the measurement path, cache state, sample set, and
expected response to a change are explicit. Preserve those conditions before comparing runs.

## Contents

- [Lab versus field](#lab-versus-field)
- [Origin versus edge](#origin-versus-edge)
- [Warm versus cold](#warm-versus-cold)
- [Medians and variance](#medians-and-variance)
- [Set the expected metric first](#set-the-expected-metric-first)
- [Referenced bytes and the font-preload trap](#referenced-bytes-and-the-font-preload-trap)
- [Unmeasured is not zero](#unmeasured-is-not-zero)
- [A repeatable comparison protocol](#a-repeatable-comparison-protocol)
- [Reporting checklist](#reporting-checklist)

## Lab versus field

A **lab** run measures a page under controlled conditions. It is reproducible, can be run against
any publicly reachable site, and is the correct basis for before/after work when the same tool,
page, viewport, network profile, cache state, and interaction path are preserved.

**Field** data is aggregated from real visitors. It reflects their devices, networks, geography,
cache states, and interactions, but it exists only when the page or origin has enough eligible
traffic to be included by the field-data provider. A small site may have no field data at all.
That absence is not an error and does not mean the metrics are zero.

When field data is absent, say plainly:

> No field data was available for this page or origin. The findings and before/after comparison
> therefore use lab measurements as their entire basis.

Do not substitute origin-level field data for page-level data without labelling the different
scope. Do not compare a lab number directly with a field percentile as if both observations were
made under the same conditions.

## Origin versus edge

`perf-probe.py --site URL [--repeats N] [--quick] [--json PATH]` keeps two TTFB paths separate:

| Output | Request | Meaning |
|---|---|---|
| `origin_ttfb_ms` | The page URL with a unique `_wp_perf_probe` value on every sample | The uncached application path the probe uses to expose WordPress render time |
| `edge_ttfb_ms` | The bare page URL | The visitor-facing path, including any responding cache layer |

For origin samples, the cache-buster is unique per request. If a recognized cache header still
reports `HIT`, the script excludes that sample from `origin_ttfb_samples_ms` and records an error
that the cache-buster may be ignored. Review the raw samples and errors before treating the origin
median as real WordPress render time.

For edge samples, the bare URL is intentional: it measures what a visitor requests. The output also
preserves the normalized `cache_status` and the raw `cache_header` name so the report can say which
public signal supported `HIT`, `MISS`, `BYPASS`, `DYNAMIC`, or `unknown`.

Never blend origin and edge TTFB. Their difference is diagnostic:

- Slow origin with fast edge means visitor delivery is currently protected by a cache, while
  misses, bypasses, and uncached paths still pay the application cost.
- Fast origin with slow edge points away from WordPress render time and toward the edge, network,
  redirect, TLS, or another visitor-facing path.
- Slow values on both paths justify investigating both layers; one average would hide that fact.

## Warm versus cold

A **cold** request populates one or more empty cache layers. A **warm** request uses layers already
populated for that URL, variant, and viewport where applicable. Neither state is inherently wrong,
but they answer different questions.

The flush rule is strict:

> A measurement taken immediately after a cache flush is transient and is not comparable with a
> warm baseline. Warm the same page and re-measure before declaring a regression.

This applies after any purge of an edge, `server`, `page-plugin`, or `object` cache layer. It also
applies after a deploy or settings save that invalidates generated CSS or page cache. Record what
was purged and how the page was warmed. Do not silently mix the first post-flush request into the
warm sample set. Immediate post-flush readings have caused false regression calls in two real
campaigns; the warning is operational evidence, not a theoretical nicety.

When cold behavior itself matters, measure and label it as a separate scenario. Keep cold-to-cold
and warm-to-warm comparisons distinct.

## Medians and variance

`perf-probe.py` reports the median of the successful timing samples in `origin_ttfb_ms` and
`edge_ttfb_ms`. It also ships every accepted value in `origin_ttfb_samples_ms` and
`edge_ttfb_samples_ms`. The median prevents one outlier from controlling the headline while the
raw arrays keep that outlier visible.

Use `--repeats N` to select the timing sample count. A failed request is not invented as a numeric
sample; inspect each URL's `errors` array to see what was excluded.

High variance across otherwise identical requests is itself a finding. It can indicate periodic
work, contention, inconsistent cache routing, a remote dependency, or another intermittent cause.
Do not collapse that evidence into "the median looks acceptable." If periodic backend work is a
candidate, continue with [cron and scheduled work](catalog/backend/cron.md) at the access tier that
can verify it.

Report variance in a checkable form: show the raw samples, identify whether they are origin or edge,
and state that the URL, cache state, viewport, and test path were held constant. If those conditions
changed, the spread is not clean evidence of runtime variance.

## Set the expected metric first

Before making a change, write down the mechanism and the metric expected to move. This prevents a
real improvement from being judged by an unrelated number and makes a no-change result useful.

| Change mechanism | Primary expected movement | Useful guardrail |
|---|---|---|
| Reduce PHP, query, or uncached render work | Lower `origin_ttfb_ms` | `edge_ttfb_ms` and cache status remain understood |
| Repair visitor-facing cache delivery | Lower warm `edge_ttfb_ms`, more expected `HIT` responses | Origin samples do not regress |
| Remove a referenced CSS or JS resource | Lower matching payload bucket and usually request count | Rendering and interaction still work |
| Reduce an image or font transfer | Lower `img_kb` or `font_kb` | LCP and visual fidelity do not regress |
| Remove render blocking around the largest element | Lower measured lab LCP | CLS and interaction remain acceptable |
| Reserve space or remove an unstable insertion | Lower measured lab CLS | Content and controls remain available |
| Shorten an interaction's main-thread work | Lower measured interaction latency or INP | The interaction completes correctly |

The scripts in this project do not produce LCP, INP, or CLS. Those expectations require an
actually available browser path; see [Chrome DevTools MCP](chrome-devtools-mcp.md).

A fix that moves nothing is information, not failure. Check, in order:

1. Was the changed mechanism on the measured page and viewport?
2. Was the right cache layer purged, then warmed before the comparison?
3. Was the expected metric actually measured in both runs?
4. Did an `unknown`, error, unsized resource, or incomplete discovery hide part of the effect?
5. Was the suspected mechanism merely correlated rather than causal?

If the conditions are sound and the intended metric still does not move, withdraw or weaken the
attribution. Do not shop for a different metric after the change.

## Referenced bytes and the font-preload trap

The full payload walk parses HTML resources, inline CSS, linked stylesheets, CSS imports, and CSS
`url(...)` references. Its `font_kb` is therefore a **referenced-bytes** total, not a count of bytes
that a particular browser necessarily requested during one rendering trace.

Removing an unused font `<link rel="preload">` may correctly stop an eager browser request while
leaving `font_kb` unchanged. The `@font-face` source remains declared in CSS by design, so the
payload walk still discovers and sizes it. This is the measurement trap: an unchanged referenced
total does not disprove removal of the preload.

For that change, set the expected evidence before editing:

- The preload is absent from returned HTML.
- A browser network trace no longer initiates the eager font request on the tested path.
- Referenced `font_kb` may remain unchanged while the `@font-face` source remains declared.

See [fonts preloaded but unused](catalog/frontend/fonts-preloaded-unused.md) for detection,
attribution, fix, verification, and rollback.

## Unmeasured is not zero

Payload totals contain only bytes that `perf-probe.py` actually sized. A resource is first tried
with HEAD; when HEAD fails, returns an unusable response, or omits a valid `content-length`, the
script falls back to a bounded GET and counts transferred bytes. If neither path produces a usable
size, the resource is excluded from the byte sum and counted in `unsized_resources`.

Read the related fields together:

- `unsized_resources` counts resources that were discovered but could not be sized.
- The URL's `errors` array names the failed resources and sizing reason.
- `discovery_incomplete: true` means a stylesheet could not be read or the CSS import-depth bound
  was reached, so some referenced resources may be unknown even in number.
- `total_kb` is a measured floor when any resource is unsized or discovery is incomplete.
- `unsized_resources: 0` means every discovered resource was sized; it does not override
  `discovery_incomplete`.

Never replace an unknown value with zero, never describe a partial total as the complete page
weight, and never compare totals without checking both runs' missing-measurement fields.

In `--quick` mode, payload discovery and resource sizing are skipped. The HTML transfer can still
be reported, but the absent CSS, JavaScript, image, font, and other totals are not zero-byte pages.

## A repeatable comparison protocol

1. Choose the exact URLs, viewport, browser or CLI path, cache state, and repeat count.
2. State the suspected mechanism and the one primary metric expected to move.
3. Capture a baseline JSON document and preserve raw timing samples, errors,
   `unsized_resources`, and `discovery_incomplete`.
4. Make one attributable change through an authorized path.
5. Purge only the layers the change invalidates.
6. Warm each measured URL outside the warm sample set.
7. Repeat the same measurement conditions and label the result.
8. For CLI documents, use `perf-probe.py --diff A.json B.json`; the command refuses documents
   whose `schema_version` values differ.
9. Interpret the primary metric first, then check guardrails and missing measurement.
10. Keep or roll back the change according to the predeclared success condition.

## Reporting checklist

- Label every number as lab or field and name its page/origin scope.
- Keep origin and edge TTFB separate.
- Label cache state and do not compare immediate post-flush readings with warm readings.
- Include the median and raw timing samples when variance matters.
- State the expected metric before the change and report a no-movement result honestly.
- Explain the unused-font-preload exception when referenced font bytes stay unchanged.
- Report `unsized_resources`, `discovery_incomplete`, and relevant errors beside payload totals.
- Use "unmeasured," never zero, for a metric the session did not produce.
