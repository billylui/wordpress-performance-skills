<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Slow queries

Template-dependent database work can multiply queries or make individual queries expensive during rendering.

## Contents

- [Symptom](#symptom)
- [Detect](#detect)
- [Attribute](#attribute)
- [Fix](#fix)
- [Verify](#verify)
- [Rollback](#rollback)
- [Gotchas](#gotchas)

## Symptom

Uncached TTFB is much worse on a particular template class, such as search, an archive, or a
listing, than on a simple page. Browser rendering and transferred bytes need not explain the gap.

## Detect

### At tier 0 (public URL only)

Run `python3 skills/wp-perf-audit/scripts/perf-probe.py --site "$SITE_URL" --repeats 7 --quick --json baseline.json` with repeated
`--url` values for a simple page, the suspect archive or search page, and a deliberately missing
path. Confirm the latter row has `http_status: 404`, then compare `origin_ttfb_ms` and the raw
`origin_ttfb_samples_ms` between templates.

Strong, repeatable origin TTFB variation by template routes toward query or template work. It is
not proof of N+1 queries, expensive meta queries, or missing indexes; tier 0 cannot see query
count, SQL text, call stacks, or query plans, so the backend cause remains `unknown`.

This explicitly contrasts with [autoload bloat](autoload-bloat.md): similar slow origin TTFB on
unrelated pages and a bare 404 points to fixed per-request overhead, not template-dependent SQL.

### At tier 1+ (admin / REST)

If Query Monitor is already approved and active, an authenticated REST `_envelope` response can
expose `x-qm-*` headers and a `qm` property. Those are checkable evidence; plugin presence alone
is not. Do not install or enable production diagnostics without approval.

### At tier 2+ (WP-CLI / SSH)

First require `wp cli has-command profile` to exit 0; do not assume the optional command is
installed or may be installed. Run `wp profile stage --url="$SLOW_URL"`, then
`wp profile hook --url="$SLOW_URL"` and, where justified, `wp db query`. Confirmation requires
query counts/timings or an explain plan tied to the slow template, not merely a large database.

The public routing signal is stack-independent; no builder-specific table is useful.

## Attribute

Attribute the delay when profiling ties it to database time and a specific query pattern on the
slow template. Disprove it when `wp profile stage` places the time outside database work, the
simple page and 404 are equally slow, or the template gap disappears across repeated samples.

## Fix

### The change

> **Backend hand-off:** Use the [`wp-performance` skill in WordPress/agent-skills](https://github.com/WordPress/agent-skills)
> for profiling and repair. It directs the operator through `wp profile stage`, `wp profile hook`,
> Query Monitor's authenticated REST evidence, and targeted `wp db query` inspection.

This entry identifies the route only; N+1 repair, query redesign, and index decisions stay upstream.

### Host constraints

| Host class | Permitted | Path |
|---|---|---|
| `unknown` | Read-only routing only | Identify the host and its query-profiling policy first. |
| Managed hosting — `wpengine`, `kinsta`, `siteground`, `godaddy`, `cloudways`, `flywheel`, `pressable`, `rocket-net`, `hostinger`, `bluehost`, `pantheon`, `wpcom`, `wpvip` | Provider-dependent | Use provider-approved query profiling and database changes. |
| `shared-cpanel` | Provider-dependent | Confirm backup and database-change controls before writes. |
| `self-managed` | With operator approval | Snapshot the database and schema before any query or index change. |
| `other` | Provider-dependent | Use provider-approved diagnostics and database-change workflow. |

### Risk

Query rewrites can change result sets; indexes and schema changes can lock tables or increase
write cost. Production profiling tools can add overhead.

## Verify

Repeat the same URLs and sample count after warming caches, then use
`python3 skills/wp-perf-audit/scripts/perf-probe.py --diff baseline.json after.json`. Require a lower origin TTFB on the affected
template, unchanged output, and no regression on the simple page or 404.

## Rollback

Revert the exact code or query change and restore any schema change from captured DDL or the
pre-change database backup. Record both the code revision and database state beforehand.

## Gotchas

- A slow archive can be PHP rendering work rather than SQL; only profiling settles it.
- One cache-warm request can conceal an N+1 pattern, so compare multiple raw samples.
- A large database is not evidence of a slow query.
