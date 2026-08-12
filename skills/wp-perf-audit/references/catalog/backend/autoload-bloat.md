<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Autoload bloat

Large autoloaded options add retrieval, copying, and deserialization work to every WordPress request, with database transfer on a cache miss or when no persistent object cache serves `alloptions`.

## Contents

- [Symptom](#symptom)
- [Detect](#detect)
- [Attribute](#attribute)
- [Fix](#fix)
- [Verify](#verify)
- [Rollback](#rollback)
- [Gotchas](#gotchas)

## Symptom

Uncached TTFB is slow across unrelated public URLs, including simple pages, while payload and
browser rendering may be ordinary. A warm edge response can remain fast because it avoids the
WordPress render; misses, uncached routes, and logged-in requests still pay the origin cost.

## Detect

### At tier 0 (public URL only)

Run `python3 skills/wp-perf-audit/scripts/perf-probe.py --site "$SITE_URL" --repeats 7 --quick --json baseline.json` against a mix of
unrelated URLs. Add `--url` once per target, including a real page and a deliberately missing
path, then verify that the missing path's `http_status` is genuinely 404 rather than a soft 200.

The routing signal is uniformly high `origin_ttfb_ms`; similar raw
`origin_ttfb_samples_ms` across the real page and 404 point to fixed per-request overhead. That
is consistent with autoload bloat, bootstrap work, always-on plugins, or a request-path HTTP call.
Tier 0 cannot distinguish those causes, so report autoload bloat as `unknown`, not confirmed.

This is the opposite of [slow queries](slow-queries.md): strong TTFB differences by template
point toward template-dependent query or rendering work, not uniformly loaded options.

### At tier 1+ (admin / REST)

Admin access can inventory active plugins and expose an approved diagnostic plugin, but it does
not by itself measure autoload bytes. Keep the cause `unknown` unless checkable output names the
autoloaded options and their sizes.

### At tier 2+ (WP-CLI / SSH)

First require `wp cli has-command doctor` to exit 0; optional packages are not assumed installable.
Confirm with `wp doctor check`, `wp option list --autoload=on --format=total_bytes`, and `wp option list --autoload=on --fields=option_name,size_bytes`. Their output must show the total
and the named options responsible; uniform public TTFB alone is not confirmation.

The signal is stack-independent; no builder-specific table is useful.

## Attribute

Attribute the cost only when tier-2 output shows a large autoload payload and the same request
becomes faster after an approved autoload change. A much slower archive or search template, a
normal 404 cost, or a `wp profile stage` result dominated by template work disproves this route.

## Fix

### The change

> **Backend hand-off:** Use the [`wp-performance` skill in WordPress/agent-skills](https://github.com/WordPress/agent-skills)
> for profiling and the actual fix. It uses `wp doctor check` and the two `wp option list`
> commands above to identify candidates before changing or removing anything.

This entry stops at routing; it does not duplicate the upstream skill's option-level procedure.

### Host constraints

| Host class | Permitted | Path |
|---|---|---|
| `unknown` | Read-only routing only | Identify the host and approved database-change path first. |
| Managed hosting — `wpengine`, `kinsta`, `siteground`, `godaddy`, `cloudways`, `flywheel`, `pressable`, `rocket-net`, `hostinger`, `bluehost`, `pantheon`, `wpcom`, `wpvip` | Provider-dependent | Use the provider-approved WP-CLI and database-change path. |
| `shared-cpanel` | Provider-dependent | Confirm backup and database-write controls before changes. |
| `self-managed` | With operator approval | Take a database backup, then follow the upstream skill. |
| `other` | Provider-dependent | Confirm backup, database-write, and diagnostic-plugin policy with the host. |

### Risk

Changing or deleting an option still used by a plugin or theme can break configuration or site
behavior. The owning component and a restorable database artifact must be known first.

## Verify

Warm every relevant cache layer, repeat the identical URL set and sample count, then run
`python3 skills/wp-perf-audit/scripts/perf-probe.py --diff baseline.json after.json`. Require lower `origin_ttfb_ms` without HTTP or
functional regressions; an immediate post-purge miss is not comparable.

## Rollback

Restore each option's exact prior value and autoload state, or restore the pre-change database
backup. Capture both before the upstream skill makes any write.

## Gotchas

- A uniformly slow 404 localizes fixed overhead but does not name autoload as the cause.
- A fast edge HIT can hide expensive origin work.
- An object cache may reduce database reads without removing deserialization or memory cost.
