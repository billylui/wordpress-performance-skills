<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Remote HTTP calls in page rendering

A slow synchronous remote API call with an excessive timeout or no response cache places a third
party's latency and failures in WordPress's render path.

## Contents

- [Symptom](#symptom)
- [Detect](#detect)
- [Attribute](#attribute)
- [Fix](#fix)
- [Verify](#verify)
- [Rollback](#rollback)
- [Gotchas](#gotchas)

## Symptom

Most uncached requests may be acceptable while occasional origin TTFB samples are catastrophic.
The long delays can coincide with a third-party degradation even though the site's own payload and
frontend work have not changed.

## Detect

### At tier 0 (public URL only)

Run `python3 skills/wp-perf-audit/scripts/perf-probe.py --site "$SITE_URL" --repeats 9 --quick --json baseline.json` and inspect the
raw `origin_ttfb_samples_ms` alongside the median `origin_ttfb_ms`. Repeat for unrelated pages and
a deliberately missing path, verifying its `http_status` is 404.

Occasional extreme origin samples shared by unrelated routes point toward fixed request-path work,
which may include a remote call. A timestamp correlation with checkable third-party incident or
application-log evidence strengthens the route, but tier 0 alone cannot see an outbound request.
Without that evidence, the cause is `unknown`; cron, locks, and origin saturation can look alike.

### At tier 1+ (admin / REST)

When Query Monitor is already approved, make an authenticated REST request and inspect `x-qm-*`
headers or the `qm` property returned by `?_envelope`. HTTP API timing and destination evidence can
confirm the category. Do not install or enable production diagnostics without approval.

### At tier 2+ (WP-CLI / SSH)

First require `wp cli has-command profile` to exit 0; the command is not assumed available. Use
`wp profile stage --url="$SLOW_URL"` and `wp profile hook --url="$SLOW_URL"`, then inspect application
or APM evidence for the named outbound request and duration. `wp profile eval` can target a known
code path under a safe, controlled test. Do not infer a destination from public HTML.

The public routing signal is stack-independent.

## Attribute

Attribute the delay when a named outbound call's duration accounts for the slow origin sample and
removing it from the synchronous path removes the delay. Disprove it when no outbound call occurs
during the slow request or profiling assigns the time to cron, database, or local PHP work.

## Fix

### The change

> **Backend hand-off:** Use the [`wp-performance` skill in WordPress/agent-skills](https://github.com/WordPress/agent-skills)
> for profiling and repair. It uses `wp profile stage`, `wp profile hook`, `wp profile eval`, and
> Query Monitor's authenticated REST evidence before addressing timeout, caching, or async design.

This entry provides only the public-to-backend routing decision.

### Host constraints

| Host class | Permitted | Path |
|---|---|---|
| `unknown` | Read-only routing only | Identify outbound-network and diagnostic restrictions first. |
| `wpengine` | Provider-dependent | Use approved profiling, APM, and outbound-network paths. |
| `kinsta` | Provider-dependent | Use approved profiling, APM, and outbound-network paths. |
| `siteground` | Provider-dependent | Use approved profiling, APM, and outbound-network paths. |
| `godaddy` | Provider-dependent | Use approved profiling, APM, and outbound-network paths. |
| `cloudways` | Provider-dependent | Use approved profiling, APM, and outbound-network paths. |
| `flywheel` | Provider-dependent | Use approved profiling, APM, and outbound-network paths. |
| `pressable` | Provider-dependent | Use approved profiling, APM, and outbound-network paths. |
| `rocket-net` | Provider-dependent | Use approved profiling, APM, and outbound-network paths. |
| `hostinger` | Provider-dependent | Use approved profiling, APM, and outbound-network paths. |
| `bluehost` | Provider-dependent | Use approved profiling, APM, and outbound-network paths. |
| `pantheon` | Provider-dependent | Use approved profiling, APM, and outbound-network paths. |
| `wpcom` | Provider-dependent | Use approved profiling, APM, and outbound-network paths. |
| `wpvip` | Provider-dependent | Use approved profiling, APM, and outbound-network paths. |
| `shared-cpanel` | Provider-dependent | Confirm outbound-network and diagnostic controls first. |
| `self-managed` | With operator approval | Follow upstream profiling and retain the prior code/configuration. |
| `other` | Provider-dependent | Confirm outbound request, APM, and plugin policy with the host. |

### Risk

Shorter timeouts or cached responses can surface stale data or change failure behavior; moving work
asynchronously can change when users observe completion.

## Verify

Warm relevant caches, reproduce both normal and failure-path conditions, and rerun the same sample
set. Use `python3 skills/wp-perf-audit/scripts/perf-probe.py --diff baseline.json after.json`; require bounded origin samples and verify
the feature's success, timeout, and fallback behavior.

## Rollback

Restore the exact prior code, timeout, cache, and scheduling configuration. Capture that revision
and any affected cached-data contract before the change.

## Gotchas

- A third-party asset fetched by the browser is not a server-side WordPress HTTP API call.
- A fast median can hide rare timeout-sized delays.
- Correlation with an outage is useful evidence but does not replace request-level attribution.
