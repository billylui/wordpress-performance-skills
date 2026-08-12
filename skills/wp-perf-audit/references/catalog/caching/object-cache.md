<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Persistent object cache ineffective or unhealthy

WordPress repeatedly recomputes or refetches reusable objects because the persistent object-cache drop-in is absent, inactive, cold, poorly keyed, or backed by an unhealthy store.

## Contents

- [Symptom](#symptom)
- [Detect](#detect)
  - [At tier 0 (public URL only)](#at-tier-0-public-url-only)
  - [At tier 1+ (admin / REST)](#at-tier-1-admin--rest)
  - [At tier 2+ (WP-CLI / SSH)](#at-tier-2-wp-cli--ssh)
  - [At tier 3 (code)](#at-tier-3-code)
  - [By stack](#by-stack)
- [Attribute](#attribute)
- [Fix](#fix)
  - [The change](#the-change)
  - [Host constraints](#host-constraints)
  - [Risk](#risk)
- [Verify](#verify)
- [Rollback](#rollback)
- [Gotchas](#gotchas)

## Symptom

Uncached or deliberately uncacheable WordPress requests have high or variable TTFB, repeated
database work, or large latency spikes after an object-cache flush. This entry primarily concerns
origin TTFB. A full-page `edge`, `server`, or `page-plugin` hit may hide it from anonymous
visitors; authenticated, cart, API, cron, and cache-miss traffic still reach the object cache.

Installing a Redis or Memcached management plugin without an active `object-cache.php` drop-in
moves nothing measurable. A low hit rate is also not automatically a defect: unique or correctly
non-cacheable lookups should miss.

## Detect

### At tier 0 (public URL only)

Tier 0 cannot see whether `wp-content/object-cache.php` is loaded, whether Redis/Memcached/APCu is
connected, what groups are used, or the object-cache hit rate. Public cache-status headers such as
`cf-cache-status`, `x-litespeed-cache`, `x-qc-cache`, and `x-cache` describe page/edge layers, not
the WordPress object cache.

The repository probe can identify when origin work deserves escalation:

```sh
python3 "$SKILL_DIR/scripts/perf-probe.py" \
  --site "$SITE_URL" --repeats 3 --quick --json object-cache-baseline.json
```

Its unique query buster is intended to make `origin_ttfb_ms` a full-page-cache miss, but it does
**not** flush or bypass the object cache. If a cache reports `HIT` for a busted request, the script
excludes that origin sample and warns that the buster may have been ignored. A slow origin median
supports deeper investigation; it cannot attribute that cost to `object`. A fast edge and slow
origin mean visitors are protected while origin work remains. At tier 0, the object-cache value
must remain `unknown`.

### At tier 1+ (admin / REST)

WordPress Site Health and an object-cache product's own status screen can provide:

- whether WordPress reports a persistent object cache;
- backend connection state and last error, if exposed;
- hit/miss counters, memory use, evictions, and cache size, if exposed;
- configured prefix/database, timeout, and serializer/compression state;
- whether a flush or disconnect occurred near the observed regression.

Capture the exact status text and counter values. “Plugin active” is only component evidence. Tier
1 cannot independently inspect the drop-in file, daemon scope, server-wide counter contamination,
network latency, or the code's cache keys/groups unless the product exposes those facts. Report
them `unknown` rather than inferring them from Site Health.

### At tier 2+ (WP-CLI / SSH)

This is the first tier that can directly establish the core state. Run:

```sh
wp plugin list --status=dropin --format=table
wp eval 'var_export( wp_using_ext_object_cache() ); echo "\n";'
wp eval 'global $wp_object_cache; echo is_object( $wp_object_cache ) ? get_class( $wp_object_cache ) : "unknown"; echo "\n";'
wp eval 'echo WP_CONTENT_DIR . "/object-cache.php\n";'
```

Required evidence for an active persistent cache is:

1. `wp-content/object-cache.php` exists and appears in the drop-in list;
2. `wp_using_ext_object_cache()` prints `true` in the same WordPress runtime;
3. the drop-in identifies the expected backend and reports a healthy connection;
4. backend counters change for the site's own namespace while controlled requests run.

Items 1–2 prove that WP-CLI loaded an external object-cache drop-in. Items 3–4 prove that the
expected persistent backend is functional and being used; keep health `unknown` if those checks
are unavailable. WP-CLI can boot different code, configuration, or PHP SAPI from web requests, so
reconcile `ABSPATH`, `WP_CONTENT_DIR`, environment variables, and web-serving diagnostics before
applying its result to PHP-FPM or another web runtime.

The installed conventional plugin list is insufficient: a connector plugin can be active while
the drop-in is missing, disabled, replaced, or unable to connect.

Measure hit rate over a representative warm interval from the product dashboard or authorized
backend statistics. Record the starting and ending hit/miss counters, the namespace/database, and
the requests issued. Compute `hits / (hits + misses)` only when both counters cover this site and
interval. A server-wide rate shared by other sites is `unknown` for this site.

Do not flush a live cache merely to test cold behavior. If an operational flush already occurred,
record its time and compare the first requests with the same routes after warming. Cold-cache
spikes that decay are transient; persistent slowness after counters stabilize needs attribution.

For `alloptions` interaction, capture only the size evidence needed to decide whether to escalate:

```sh
wp option list --autoload=on --fields=option_name,size_bytes --format=table
```

WordPress loads autoloaded options into the `alloptions` object in the `options` group. A
persistent backend avoids rebuilding it on every request, but an oversized object still incurs
serialization, transfer, memory, invalidation, and cold-fill cost. Use the official
[`wp-performance` skill](https://github.com/WordPress/agent-skills) for the deeper autoload,
database-query, cron, and backend profiling workflow rather than reproducing it here.

### At tier 3 (code)

When counters show poor reuse but do not explain it, instrument a bounded staging run or a short,
approved production window around `wp_cache_get()`, `wp_cache_set()`, and invalidation calls.
Record the key pattern, group, hit/miss result, call site, and request type without logging values
or personal data.

Check for these concrete code signals:

- high-cardinality keys containing timestamps, nonces, random values, or per-request IDs;
- the same logical object written under inconsistent keys or groups;
- a group declared non-persistent even though reuse is intended;
- missing site/blog context in shared multisite keys, or unnecessary per-user context in public
  keys;
- broad invalidation or `wp_cache_flush()` during routine writes;
- one large `alloptions` object repeatedly invalidated by frequently updated autoloaded options.

Remove instrumentation after the observation window. If code access is unavailable, the key/group
cause stays `unknown`.

### By stack

Each heading is a closed `cache_layers[].value` identifier.

#### `redis`

- Active evidence: the drop-in exists, `wp_using_ext_object_cache()` is `true`, and its status
  identifies a connected Redis backend for the site's configured namespace/database.
- If the installed integration registers WP-CLI commands, run `wp help redis` before using them;
  a successful product status command is corroboration, not a substitute for the core checks.
- With authorized backend access, `redis-cli INFO stats` exposes `keyspace_hits`,
  `keyspace_misses`, and eviction-related counters. Prove the selected Redis database/namespace
  belongs to the site before assigning server-wide numbers to it.
- Repeated connection errors, timeouts, evictions, or counters that never change during controlled
  requests disprove healthy reuse.

#### `memcached`

- Active evidence: the drop-in identifies Memcached, `wp_using_ext_object_cache()` is `true`, and
  the configured servers are reachable from the PHP runtime.
- Authorized Memcached `stats` output provides `get_hits`, `get_misses`, `evictions`,
  `curr_items`, and memory counters. Record the exact server pool and interval.
- A plugin that only supplies configuration, with no active drop-in, is not a persistent object
  cache. Pool-wide counters shared by unrelated applications do not establish this site's rate.

#### `apcu`

- Active evidence: the drop-in identifies APCu and `wp_using_ext_object_cache()` is `true`; PHP
  runtime status confirms APCu is enabled in the same SAPI serving the site.
- Authorized `apcu_cache_info()` and `apcu_sma_info()` output can expose hits, misses, entry count,
  and memory state. CLI APCu state may differ from the web-serving SAPI, so a CLI-only result is
  not enough.
- APCu is local to a PHP process pool/host rather than a shared network cache. On multiple web
  nodes, each node can be cold or inconsistent; identify the node before interpreting counters.

#### `object-cache-pro`

- Active evidence: `wp-content/object-cache.php` identifies Object Cache Pro,
  `wp_using_ext_object_cache()` is `true`, and its diagnostics report a connected Redis backend.
- Use its own status/analytics surface for request-scoped hit rate, latency, errors, and evictions
  when available. Preserve the exact output rather than translating a colored “healthy” badge.
- A conventional plugin entry without the Object Cache Pro drop-in is not active. A Redis daemon
  being reachable does not prove Object Cache Pro is the loaded client.

#### `none`

High-confidence `object: none` requires both no `wp-content/object-cache.php` drop-in and
`wp_using_ext_object_cache()` printing `false`. WordPress's default in-process object cache still
exists for one request, but it is not persistent across requests. If a host injects a drop-in
outside the inspected deployment or WP-CLI boots different code from web traffic, report
`unknown` until the runtime paths are reconciled.

## Attribute

Attribute origin cost to the object cache only when a controlled warm workload shows a concrete
object-layer mechanism and a matching performance effect. Examples are a missing/inactive drop-in
where host policy supports one, connection failures followed by database fallbacks, a high miss
or eviction delta for reusable groups, or bounded instrumentation showing unstable keys or broad
invalidations.

Disprove the attribution when the drop-in is active and healthy, the site's own warm counters show
expected reuse, and origin TTFB remains slow. The remaining cause may be uncached queries, remote
APIs, PHP work, cron, autoload, or deliberately dynamic code; use the official
[`wp-performance` skill](https://github.com/WordPress/agent-skills) to profile it.

A TTFB spike immediately after a known flush is not a persistent regression. Warm the same routes
and repeat before attributing it.

## Fix

### The change

Choose the smallest fix for the proven mechanism:

1. restore the expected drop-in and connection when the backend is present but inactive;
2. correct the site namespace/database, credentials source, timeout, or server pool through the
   supported host/product configuration;
3. reduce evictions by removing accidental key cardinality or sizing the approved backend;
4. stabilize keys/groups and narrow invalidation in the owning code;
5. reduce frequently invalidated autoloaded data through the official backend workflow;
6. leave `object: none` unchanged when the host does not support a persistent cache or measured
   reuse would not justify one.

Do not install a generic Redis/Memcached plugin and assume activation creates a working drop-in.
Do not flush production as a repair unless the incident specifically requires invalidating bad
objects and the purge impact is accepted.

### Host constraints

Persistent object-cache availability, credentials, and supported drop-ins are platform-specific.
Where the table says confirm, use current host documentation or support for the exact environment.

| Host class | Permitted | Path |
|---|---|---|
| `wpengine` | Use only a host-supported persistent object-cache service/drop-in. | Confirm with the host; enable, disable, and flush through the supported control or support path. |
| `kinsta` | Use only the persistent object-cache option and drop-in supported for the environment. | Confirm with the host; do not replace a platform-managed drop-in. |
| `siteground` | Use only the object-cache service/integration exposed for the plan. | Confirm with the host and use its supported activation and flush controls. |
| `godaddy` | Object-cache availability and plugin policy depend on the product. | Confirm with the host before installing a daemon client or drop-in. |
| `cloudways` | Coordinate the application-level object cache with the platform's configured service. | Confirm with the host; use the application/server controls and one supported drop-in. |
| `flywheel` | Use only a persistent object-cache service and drop-in supported for the environment. | Confirm with the host; do not replace a platform-managed drop-in independently. |
| `pressable` | Object-cache availability and supported integrations must be verified for the site. | Confirm with the host; use only its approved activation and flush path. |
| `rocket-net` | Persistent object-cache ownership and access are platform-specific. | Confirm with the host; do not install an unmanaged backend client or drop-in. |
| `hostinger` | Persistent service availability and isolation depend on the plan/server. | Confirm with the host; use a documented namespace and supported drop-in only. |
| `bluehost` | Object-cache availability and plugin policy depend on the product. | Confirm with the host before installing a daemon client or drop-in. |
| `pantheon` | Platform cache architecture and supported persistent stores control the permitted path. | Confirm with the host; do not add an unmanaged drop-in to production. |
| `wpcom` | Platform caching and plan capabilities control object-cache access. | Confirm with the host; do not assume daemon or drop-in access. |
| `wpvip` | Object-cache changes must follow platform guidance. | Coordinate with VIP support and use the approved runtime, diagnostics, and flush path. |
| `shared-cpanel` | A persistent service may be unavailable or shared; daemon access is not implied by cPanel. | Confirm with the host. Use a supported service/drop-in only when the site gets an isolated or documented namespace. |
| `self-managed` | A persistent cache is permitted when the team owns availability, isolation, monitoring, and rollback. | Provision one backend, one drop-in, a unique prefix/database, bounded timeouts, monitoring, and a documented disable/flush path. |
| `other` | Persistent object-cache support and ownership are `unknown` until the provider is identified. | Confirm with the host; use only a supported backend, isolated namespace, and documented flush path. |
| `unknown` | No object-cache mutation is safe until hosting and runtime ownership are identified. | Resolve the provider/runtime through account records or support; keep support and health `unknown` meanwhile. |

### Risk

Wrong prefixes or multisite keys can leak or overwrite cached data across sites. A replacement
drop-in can make the site fatal before WordPress loads. Flushes can create database and PHP load
spikes; an undersized cache can thrash; long network timeouts can make backend failure slower than
no cache. Editors, authenticated users, checkout flows, cron, and APIs are likely to notice first.

## Verify

Verify at the object layer and the request layer:

1. confirm the expected `object-cache.php` is the loaded drop-in and
   `wp_using_ext_object_cache()` prints `true`;
2. record healthy connection diagnostics with no new errors/timeouts;
3. capture start/end site-scoped hits, misses, evictions, and memory over the same representative
   warm requests;
4. re-run the probe and compare origin TTFB without merging it with edge TTFB;
5. exercise authenticated/dynamic routes that actually depend on object reuse.

```sh
python3 "$SKILL_DIR/scripts/perf-probe.py" \
  --site "$SITE_URL" --repeats 3 --quick --label after --json object-cache-after.json
python3 "$SKILL_DIR/scripts/perf-probe.py" \
  --diff object-cache-baseline.json object-cache-after.json
```

Warm before comparing. The probe's own legend says measurements immediately after a cache flush
are transient and not comparable.

## Rollback

Before the change, preserve the existing `wp-content/object-cache.php`, plugin/product settings,
backend endpoint and non-secret configuration, prefix/database, serializer/compression settings,
timeouts, memory policy, and health counters. Keep secrets in their existing secret store, not in
the audit artifact.

To roll back, restore the prior supported drop-in and configuration, remove only the new
integration, restart/reload only if the platform's approved procedure requires it, invalidate
objects through the documented path, warm representative routes, and confirm the former status.
If rollback is “return to `object: none`,” remove the drop-in through the product's supported
deactivation path rather than deleting it while traffic is executing.

## Gotchas

- `perf-probe.py` bypasses full-page cache, not object cache. Its origin number can still be a warm
  object-cache render.
- “Redis plugin active,” “external drop-in loaded,” and “persistent backend healthy” are three
  different claims. The drop-in plus runtime flag settle only the second; connection diagnostics
  and site-scoped activity settle the third.
- Hit rate without a site namespace, interval, and representative requests is not actionable.
- A flush makes the object cache cold and can temporarily raise origin TTFB and database load.
- `alloptions` bloat can remain costly with a persistent cache because the large object must still
  be moved, decoded, and invalidated.
- APCu CLI counters may describe a different process cache from PHP-FPM/web traffic.
- Never log cached values while instrumenting keys/groups; they may contain secrets or personal
  data.
