<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Cache layers conflict or purge independently

Two or more cache owners store the same representation without a coordinated key, TTL, or purge path, so one layer can hide or restore another layer's stale output.

## Contents

- [Symptom](#symptom)
- [Detect](#detect)
  - [At tier 0 (public URL only)](#at-tier-0-public-url-only)
  - [At tier 1+ (admin / REST)](#at-tier-1-admin--rest)
  - [At tier 2+ (WP-CLI / SSH)](#at-tier-2-wp-cli--ssh)
  - [By conflict pattern](#by-conflict-pattern)
- [Attribute](#attribute)
- [Fix](#fix)
  - [The change](#the-change)
  - [Host constraints](#host-constraints)
  - [Risk](#risk)
- [Verify](#verify)
- [Rollback](#rollback)
- [Gotchas](#gotchas)

## Symptom

Editors purge or publish successfully but some visitors still receive old HTML; a stale page
reappears after apparently being fixed; cache-status headers disagree; or TTFB alternates between
fast hits and slow misses after a change. Conflicts can move visitor-facing TTFB, but correctness
is the larger risk: **a change purged on the wrong layer is a change that never shipped.**

The defect does not exist merely because several caches are present. Browser, `edge`, `server`,
`page-plugin`, `object`, and database reuse can coexist when each owns a distinct artifact or their
keys and invalidations are deliberately coordinated.

## Detect

### At tier 0 (public URL only)

First separate uncached-origin render cost from the bare visitor path:

```sh
python3 "$SKILL_DIR/scripts/perf-probe.py" \
  --site "$SITE_URL" --repeats 3 --quick --json conflict-baseline.json
```

`origin_ttfb_ms` is measured with a unique query buster. `edge_ttfb_ms` is the bare URL. The
probe's `cache_header` records one recognized response header, so it cannot by itself enumerate a
multi-layer chain. Capture every final response header for the HTML document:

```sh
/usr/bin/curl --silent --show-error --dump-header - --output /dev/null \
  --cookie '' "$SITE_URL/"
```

Before reading the response, disable the browser cache or use a fresh command-line/private client.
Otherwise a browser memory/disk response may never contact the measured `edge` layer.

Build an evidence inventory. Use only closed identifiers for profile layers:

| Layer | Evidence that can identify it | Evidence that it answered this request |
|---|---|---|
| `edge` | `cf-cache-status`, `x-qc-cache`, an attributable `x-cache` plus corroborating `via`/provider headers, DNS/control-plane configuration | Outer header reports `HIT`, a shared-cache `Age` is present/rising, and the response body/validator matches the edge object |
| `server` | `x-litespeed-cache`, `x-fastcgi-cache`, `x-varnish-cache`, attributable `x-cache-status`, or host control-plane status | Server header reports `HIT` when the outer edge is bypassed or known to be a miss |
| `page-plugin` | Vendor HTML comment, fresh matching artifact under `wp-content/cache/`, and active plugin evidence | Cookie-free canonical URL warms in a way attributable to that plugin after outer layers are bypassed/purged |
| `object` | Not visible at tier 0 | Remains `unknown`; public page-cache headers cannot prove an object-cache hit |

Multiple hit-looking headers in one response do not prove that multiple layers were consulted on
that request. An outer cache can replay the inner cache's headers from the response it stored.
Use changing `Age`, an outer-layer status transition, and a provider/origin bypass to determine
which layer actually answered.

Check for stale disagreement using an existing authorized content change or incident evidence; do
not mutate production merely for detection:

1. record the canonical URL, visible revision marker or body hash, `etag`, `last-modified`, `age`,
   and every cache-status header before the documented purge;
2. record the same evidence through the normal visitor path and the approved origin-bypass path;
3. if origin has the new body while the visitor path has the old body and an outer `HIT`/rising
   `Age`, the outer copy survived;
4. if the outer layer is purged but refills with the old body, test the next inner `server` or
   `page-plugin` layer; it may be repopulating the edge with stale output.

### At tier 1+ (admin / REST)

Inventory every enabled cache control surface and capture:

- the product/layer identifier, enabled state, TTL, key dimensions, and exclusions;
- the exact action triggered by “purge,” “clear cache,” publish, update, deployment, and scheduled
  expiry;
- purge scope: one URL, related URLs, tags, site, network, or all objects;
- last purge request/outcome and integration/webhook errors, if exposed;
- whether an outer provider is connected to the WordPress plugin or host control panel;
- whether edits to posts, menus, widgets, options, products, translations, and templates invalidate
  all pages that embed them.

A successful UI notification is intent evidence, not delivery evidence. Confirm the visitor body
and headers after the action.

### At tier 2+ (WP-CLI / SSH)

List WordPress-owned cache components and drop-ins:

```sh
wp plugin list --status=active --format=table
wp plugin list --status=dropin --format=table
wp eval 'var_export( wp_using_ext_object_cache() ); echo "\n";'
```

Inspect the exact virtual host, platform, or deployment configuration for `nginx-fastcgi`,
`varnish`, `batcache`, or `litespeed`, plus each active `page-plugin`. Record who owns the cache
key and what event invokes its purge. Do not execute a guessed purge command: there is no common
purge interface across products or hosts.

For a conflict involving `object`, inspect the loaded `wp-content/object-cache.php`, the backend
status, and the application event that invalidates the affected key/group. Use the official
[`wp-performance` skill](https://github.com/WordPress/agent-skills) for deep database, autoload,
query, cron, and object-cache profiling instead of duplicating it.

### By conflict pattern

| Layers | Checkable pattern | What would settle it |
|---|---|---|
| `server` + `page-plugin` | Host/server header and an active page-cache plugin both claim or can store anonymous HTML; clearing the plugin leaves a server `HIT` with the old body, or clearing the server allows the plugin's old body to refill it | Use the approved origin/server bypass, inspect the plugin artifact, and execute only the already-documented individual purge paths during an authorized verification |
| `edge` + `server` | Origin/server body is new while edge body is old, or edge refill retrieves a stale server object | Compare body marker/hash and validators through approved edge-bypass and visitor paths; purge inner then outer and verify the refill body |
| `edge` + `page-plugin` | WordPress/plugin purge reports success but the edge `Age` continues and old body remains | Edge purge log plus body/headers proves whether the WordPress hook reached the edge |
| `page-plugin` + `object` | Object data is corrected or flushed but stored page HTML still contains the old value, or page HTML is purged and immediately rebuilt from a stale object | Inspect object key/group invalidation and the generated page artifact; invalidate source object first, then page HTML |
| Any one-layer-only purge | One control surface reports success while another layer retains or refills the old representation | Trace one controlled revision through every enabled layer in request order and record each purge outcome |

## Attribute

Attribute the incident to a cache-layer conflict only when two identified owners can store the
same affected representation and evidence shows one retained or regenerated the stale body after
the other changed. A header list alone is correlation. Strong evidence is a body hash/revision
marker paired with layer-specific status, `Age`, artifact modification time, and purge log.

Disprove the attribution when all layers return the same current body after warm measurement and
only uncached origin TTFB is slow. Also disprove it when the “old” content comes from the database,
application code, a translation source, or a browser/service worker rather than a profiled cache
layer. Keep the owner `unknown` until the next bypass or control-plane check settles it.

## Fix

### The change

Establish the purge path **before** changing content or cache configuration. For each enabled
layer, record its owner, interface, credentials holder, scope, expected completion signal, and
rollback. Then:

1. choose one owner for anonymous full-page HTML wherever the host permits;
2. disable the redundant `page-plugin` when a host-managed `server` cache already owns HTML,
   unless the host explicitly documents a coordinated combination;
3. connect publish/update/deploy events to every layer that stores the affected representation;
4. align cache keys for language, currency, device, cookie, query, hostname, and authentication
   variants without sharing personalized output;
5. invalidate from inner source toward outer delivery—affected `object`, then `page-plugin`, then
   `server`, then `edge`—so an outer refill cannot retrieve a known-stale inner object;
6. version browser-cached assets or correct browser cache directives when the changed artifact is
   not HTML.

Do not add a “purge all” hook to every write as a substitute for understanding dependencies. It
can create continuous cold-cache load and hide the real key/tag defect.

### Host constraints

| Host class | Permitted | Path |
|---|---|---|
| `wpengine` | Platform `server` caching remains the authoritative path unless the host explicitly approves another HTML cache. | Confirm current plugin policy with the host; document platform purge plus any external `edge` purge before changing content. |
| `kinsta` | Platform page caching remains authoritative unless an integration is explicitly supported. | Confirm with the host; connect or sequence the platform and external `edge` purge paths. |
| `siteground` | Use the supported Dynamic Cache/`sg-optimizer` combination; avoid an independent competing page cache. | Confirm with the host; document SiteGround, plugin, and external `edge` purge behavior. |
| `godaddy` | The platform cache and plugin allowance depend on the managed product. | Confirm with the host for the exact plan; identify its flush action before adding another cache owner. |
| `cloudways` | Coordinate `breeze`, platform `varnish`, and any `edge`; do not assume one button clears all three. | Confirm the application topology with the host and record each enabled purge path. |
| `flywheel` | Treat the platform `server` cache as a candidate owner and avoid an unapproved competing page cache. | Confirm with the host; document platform and external `edge` purge paths. |
| `pressable` | Treat platform caching as a candidate owner; supported integrations must be verified. | Confirm with the host and record every enabled purge path before changing configuration. |
| `rocket-net` | Treat managed platform/edge caching as candidate owners rather than adding another HTML cache. | Confirm with the host; identify which control purges each stored representation. |
| `hostinger` | Server and plugin cache topology depends on the plan and server. | Confirm with the host; retain one intended HTML owner and document any external `edge` purge. |
| `bluehost` | Platform cache topology and plugin policy depend on the product. | Confirm with the host for the exact plan and identify every enabled purge action. |
| `pantheon` | Use the platform `varnish`/`batcache` workflow and supported invalidation model. | Confirm with the host; do not layer an unmanaged page-cache plugin. |
| `wpcom` | Platform delivery controls cache ownership and available integrations. | Confirm with the host for the site/plan; use only supported purge controls. |
| `wpvip` | Cache and purge changes require platform-compatible operations. | Coordinate with VIP support and document the approved purge sequence. |
| `shared-cpanel` | One page-cache owner may be used, but a hidden provider/server cache is possible. | Confirm with the host, inventory server features, and disable redundant plugins only after the remaining owner is proven. |
| `self-managed` | Multiple layers are permitted when ownership, keys, observability, and purge fan-out are explicit. | Maintain a layer diagram and inner-to-outer purge runbook; keep an approved bypass for each layer. |
| `other` | Cache ownership and purge interfaces are `unknown` until the provider and server controls are identified. | Confirm with the host; inventory all layers and establish each purge path before changing content or configuration. |
| `unknown` | No cache mutation is safe until host ownership is identified. | Identify the provider/server from account records or support, then apply its row; keep every policy claim `unknown` in the meantime. |

### Risk

Disabling the wrong layer can expose the origin to load. Broad purge fan-out can cause a thundering
herd. Incorrect keys can leak personalized account, cart, locale, currency, preview, or nonce data.
Purging outer-to-inner can let the edge immediately refill from a stale origin cache. Editors and
shoppers notice stale correctness first; operations notices the cold-origin load afterward.

## Verify

Use a low-risk controlled revision with an unmistakable marker on a representative cacheable URL.
Follow the documented inner-to-outer purge path, then:

1. confirm the approved origin-bypass path returns the new marker;
2. request the normal visitor path once to warm it, then repeat until status and `Age` stabilize;
3. confirm every response contains the new marker/body hash and expected validators;
4. confirm exactly the intended layer owns warm HTML and personalized routes still bypass;
5. capture the after probe and compare both origin and edge medians.

```sh
python3 "$SKILL_DIR/scripts/perf-probe.py" \
  --site "$SITE_URL" --repeats 3 --quick --label after --json conflict-after.json
python3 "$SKILL_DIR/scripts/perf-probe.py" \
  --diff conflict-baseline.json conflict-after.json
```

TTFB immediately after a flush is cold and transient. Warm every measured URL before reporting a
regression; the probe's report legend gives the same instruction.

## Rollback

Before changing anything, export or record every enabled cache's settings, rules, key dimensions,
TTLs, integration/webhook configuration, purge scope, plugin state, host controls, and DNS/proxy
state. Preserve the previous plugin artifact/configuration when removal is part of the approved
change.

To roll back, restore the former configuration and owner only where host policy permits it,
restore purge integrations, invalidate affected objects inner-to-outer, warm the former visitor
path, and verify the prior body and status behavior. If a removed plugin is prohibited by the
host, do not reactivate it as rollback; escalate to the host-approved configuration captured
beforehand.

## Gotchas

- **TTFB spikes immediately after a cache flush are transient.** This has been reproduced in real
  campaigns: re-measure warm before reporting a regression or chasing a number that fixes itself.
  `perf-probe.py` states the same warning in its report legend.
- **There is no common purge interface.** WP Engine, Kinsta, SiteGround, Cloudflare, LiteSpeed,
  Nginx Helper, Varnish, and Redis each purge differently; some paths exist only in a dashboard,
  while others are a plugin action, API, host command, or support operation. Establish and test
  the purge path before making a change, not after.
- An outer cache can replay an inner cache's `HIT` header. Multiple `HIT` strings do not prove
  multiple layers executed for the current request.
- Purging only WordPress does not clear a disconnected `edge`; purging only the edge can refill it
  from stale `server` or `page-plugin` content.
- A successful purge toast or API response proves request acceptance, not that every object,
  variant, or point of presence is current.
- A change purged on the wrong layer is a change that never shipped.
