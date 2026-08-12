<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Visitor-triggered cron spawning and contention

Visitor-triggered WordPress cron spawning and concurrent due work can add request overhead or resource contention.

## Contents

- [Symptom](#symptom)
- [Detect](#detect)
- [Attribute](#attribute)
- [Fix](#fix)
- [Verify](#verify)
- [Rollback](#rollback)
- [Gotchas](#gotchas)

## Symptom

By default, WordPress uses visitor traffic to spawn due cron work through a loopback request that is
intended to be non-blocking. Some requests can still pay spawn delay, and concurrent jobs can
contend for origin resources; identical uncached requests then show occasional TTFB spikes.
The page, template, and payload are unchanged, so the long tail rather than the median is the clue.

## Detect

### At tier 0 (public URL only)

Run `python3 skills/wp-perf-audit/scripts/perf-probe.py --site "$SITE_URL" --repeats 9 --quick --json baseline.json` for the same URL.
Inspect `origin_ttfb_samples_ms`, not only `origin_ttfb_ms`: the script deliberately ships raw
samples beside the median so occasional spikes remain visible.

Several ordinary samples plus isolated slow samples are consistent with due-now cron work. Tier 0
cannot see the cron queue or prove that a spike ran cron, so the cause remains `unknown`. Network
variance, lock contention, a remote HTTP call, or an overloaded origin can produce the same shape.

When useful, repeat the same comparison on a real page and a genuine 404. Similar intermittent
spikes on both routes support fixed request-path work rather than template-specific rendering.

### At tier 1+ (admin / REST)

Admin access can establish whether a platform or plugin exposes scheduled-task status, but a UI
inventory without timestamps and durations does not attribute a public TTFB spike.

### At tier 2+ (WP-CLI / SSH)

First require `wp cli has-command cron` to exit 0. Confirm spawning health and queue state with
`wp cron test` and `wp cron event list`. Under an approved, controlled procedure,
`wp cron event run --due-now` measures due-event runtime; correlate it with request timestamps and
resource evidence rather than treating it alone as proof of visitor-request causality.

The routing signal is independent of builder and theme.

## Attribute

Attribute the spike only when request and resource evidence, or an approved before/after change,
shows loopback spawn delay or contention with a cron worker. Disprove it when the queue is not due,
the platform does not use visitor-triggered spawning, or another profiler accounts for the delay.

## Fix

### The change

> **Backend hand-off:** Use the [`wp-performance` skill in WordPress/agent-skills](https://github.com/WordPress/agent-skills)
> for diagnosis and the actual cron fix. It uses `wp cron test`, `wp cron event list`, and
> `wp cron event run --due-now`, then covers de-duplication and moving heavy work off-request.

This entry does not restate that queue-level procedure.

### Host constraints

| Host class | Permitted | Path |
|---|---|---|
| `unknown` | Do not change cron mode | Determine whether the host already supplies a platform schedule. |
| `wpengine` | Check platform scheduling first | Use the provider-supported scheduler and WP-CLI path. |
| `kinsta` | Check platform scheduling first | Use the provider-supported scheduler and WP-CLI path. |
| `siteground` | Check platform scheduling first | Use the provider-supported scheduler and WP-CLI path. |
| `godaddy` | Check platform scheduling first | Use the provider-supported scheduler and WP-CLI path. |
| `cloudways` | Check platform scheduling first | Use the provider-supported scheduler and WP-CLI path. |
| `flywheel` | Check platform scheduling first | Use the provider-supported scheduler and WP-CLI path. |
| `pressable` | Check platform scheduling first | Use the provider-supported scheduler and WP-CLI path. |
| `rocket-net` | Check platform scheduling first | Use the provider-supported scheduler and WP-CLI path. |
| `hostinger` | Check platform scheduling first | Use the provider-supported scheduler and WP-CLI path. |
| `bluehost` | Check platform scheduling first | Use the provider-supported scheduler and WP-CLI path. |
| `pantheon` | Check platform scheduling first | Use the provider-supported scheduler and WP-CLI path. |
| `wpcom` | Check platform scheduling first | Use the provider-supported scheduler and WP-CLI path. |
| `wpvip` | Check platform scheduling first | Use the provider-supported scheduler and WP-CLI path. |
| `shared-cpanel` | Check control-panel scheduling first | Coordinate its scheduler with WordPress cron configuration. |
| `self-managed` | With operator approval | Coordinate the system schedule and WordPress configuration as one change. |
| `other` | Provider-dependent | Use the host's supported scheduler and command path. |

### Risk

Disabling visitor-spawned cron without a working replacement stops scheduled publishing,
maintenance, and plugin jobs. Running due events can send messages or mutate external systems.

## Verify

After the upstream change, warm caches and repeat the identical URL and sample count. Use
`python3 skills/wp-perf-audit/scripts/perf-probe.py --diff baseline.json after.json`; require a tighter raw origin sample distribution
and confirm scheduled jobs still run through their intended path.

## Rollback

Restore the prior WordPress cron configuration, platform or system scheduler entry, and changed
event registrations. Capture each exact value and schedule before modification.

## Gotchas

- Some managed hosts run cron on a platform schedule, changing the visitor-request picture entirely.
- The median can look healthy while some requests incur spawn delay or contend with a cron worker.
- A recurring spike pattern is routing evidence, not proof of a particular event.
