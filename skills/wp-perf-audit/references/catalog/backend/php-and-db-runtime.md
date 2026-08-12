<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# PHP and database runtime

An outdated or poorly configured PHP/database runtime can make otherwise ordinary WordPress work expensive.

## Contents

- [Symptom](#symptom)
- [Detect](#detect)
- [Attribute](#attribute)
- [Fix](#fix)
- [Verify](#verify)
- [Rollback](#rollback)
- [Gotchas](#gotchas)

## Symptom

Origin TTFB is broadly slow across simple pages and a real 404, without a matching frontend payload
or rendering explanation. Runtime versions and configuration are unknown until measured; never
assume that a production site uses a modern PHP or MySQL runtime.

## Detect

### At tier 0 (public URL only)

Run `python3 skills/wp-perf-audit/scripts/perf-probe.py --site "$SITE_URL" --repeats 7 --quick --json baseline.json` across unrelated
URLs and a deliberately missing path, then verify the 404 row's `http_status`. Uniformly slow
`origin_ttfb_ms` is consistent with fixed runtime or bootstrap cost, but cannot distinguish the
runtime from autoload bloat, always-on plugins, or a synchronous HTTP call.

Run `python3 skills/wp-perf-audit/scripts/fingerprint.py "$SITE_URL" --json stack.json`. PHP is known only when an explicit
`X-Powered-By` response header publishes it. PHP is usually not determinable at tier 0 because
hosts strip that header; the script then
reports `profile.php_version.value` as `unknown` and notes why tier 0 cannot determine it.

### At tier 1+ (admin / REST)

In WordPress administration, Tools → Site Health → Info provides checkable Server and Database
version fields. Treat opcode-cache status as `unknown` unless the host panel or another approved
diagnostic explicitly reports it.

### At tier 2+ (WP-CLI / SSH)

Record runtime and database versions from the environment and confirm PHP opcode-cache status.
Require `wp cli has-command doctor` and `wp cli has-command profile` to exit 0 before running
`wp doctor check` and `wp profile stage`; optional packages are not assumed available.

The public signal is independent of builder and theme.

## Attribute

Older PHP branches can be markedly slower than newer compatible branches, and enabled opcode
caching matters because otherwise PHP repeatedly compiles code. For database runtime, require
checkable server-resource, storage-latency, connection, configuration, or query-plan evidence.
Template-only slowness or one named application query disproves a general runtime attribution.

## Fix

### The change

> **Backend hand-off:** Use the [`wp-performance` skill in WordPress/agent-skills](https://github.com/WordPress/agent-skills)
> for backend profiling with `wp doctor check`, `wp profile stage`, and targeted `wp db query`
> where database runtime evidence warrants it. Coordinate runtime changes with the host or ops team.

Check every active plugin and theme for compatibility before recommending a PHP upgrade. An upgrade
that white-screens the site is not a performance win.

### Host constraints

| Host class | Permitted | Path |
|---|---|---|
| `unknown` | Do not change the runtime | Identify host controls, supported runtimes, and rollback path. |
| `wpengine` | Provider-controlled | Use the provider runtime process and confirmed rollback path. |
| `kinsta` | Provider-controlled | Use the provider runtime process and confirmed rollback path. |
| `siteground` | Provider-controlled | Use the provider runtime process and confirmed rollback path. |
| `godaddy` | Provider-controlled | Use the provider runtime process and confirmed rollback path. |
| `cloudways` | Provider-controlled | Use the provider runtime process and confirmed rollback path. |
| `flywheel` | Provider-controlled | Use the provider runtime process and confirmed rollback path. |
| `pressable` | Provider-controlled | Use the provider runtime process and confirmed rollback path. |
| `rocket-net` | Provider-controlled | Use the provider runtime process and confirmed rollback path. |
| `hostinger` | Provider-controlled | Use the provider runtime process and confirmed rollback path. |
| `bluehost` | Provider-controlled | Use the provider runtime process and confirmed rollback path. |
| `pantheon` | Provider-controlled | Use the provider runtime process and confirmed rollback path. |
| `wpcom` | Provider-controlled | Use the provider runtime process and confirmed rollback path. |
| `wpvip` | Provider-controlled | Use the provider runtime process and confirmed rollback path. |
| `shared-cpanel` | Control-panel-dependent | Test compatibility and confirm a runtime rollback path. |
| `self-managed` | With operator approval | Test compatibility on staging and preserve packages/configuration for rollback. |
| `other` | Provider-dependent | Use the host's runtime selector or support process and approved database path. |

### Risk

PHP or database changes can expose plugin/theme incompatibilities, missing extensions, SQL-mode
differences, or irreversible data migrations. Opcache changes can alter memory use.

## Verify

Test the site and critical workflows on staging first. After production change and cache warming,
repeat the identical URL set and use `python3 skills/wp-perf-audit/scripts/perf-probe.py --diff baseline.json after.json`; also rerun the
upstream profile and check PHP logs for new errors.

## Rollback

Restore the prior PHP/database runtime, extensions, configuration, and application revision. Capture
the exact runtime versions, configuration, database backup, and a proven host rollback path first.

## Gotchas

- `server` and `php_version` are separate fingerprint fields; one does not imply the other.
- A public `X-Powered-By` value is evidence, but an absent header means `unknown`, not modern PHP.
- A version upgrade without compatibility testing can trade latency for an outage.
