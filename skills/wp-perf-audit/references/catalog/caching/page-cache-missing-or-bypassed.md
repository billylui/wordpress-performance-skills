<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Page cache missing or bypassed

Anonymous HTML reaches PHP because the effective full-page cache is absent, cold, or bypassed by a request property.

## Contents

- [Symptom](#symptom)
- [Detect](#detect)
  - [At tier 0 (public URL only)](#at-tier-0-public-url-only)
  - [At tier 1+ (admin / REST)](#at-tier-1-admin--rest)
  - [At tier 2+ (WP-CLI / SSH)](#at-tier-2-wp-cli--ssh)
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

Anonymous navigation has high or variable TTFB even though the page is eligible for full-page
caching. A warm visitor request may repeatedly report `MISS`, `BYPASS`, `DYNAMIC`, or
`unknown`; a cache-status header alone is not proof unless its owning layer is identified.

This defect primarily moves TTFB and can indirectly delay LCP. It does not reduce transferred
bytes, and it does not explain a slow origin when a warm full-page edge response is already fast
for visitors.

## Detect

### At tier 0 (public URL only)

Start with the repository probe, preserving the separate medians and raw samples:

```sh
python3 skills/wp-perf-audit/scripts/perf-probe.py \
  --site "$SITE_URL" --repeats 3 --quick --json cache-baseline.json
```

`origin_ttfb_ms` uses a unique `_wp_perf_probe` query value for every sample. The script excludes
an origin sample that reports `HIT` and records that the cache-buster may have been ignored.
`edge_ttfb_ms` is the bare, visitor-facing URL. Interpret the pair before naming a fault:

| Evidence in `cache-baseline.json` | Interpretation | Next check |
|---|---|---|
| Fast warm `edge_ttfb_ms`, slow `origin_ttfb_ms` | A visitor-facing cache is doing useful work; the uncached render remains expensive | Identify `cache_header` and the owning `edge`, `server`, or `page-plugin` layer |
| Both medians slow and the bare URL remains `MISS` or `BYPASS` | No effective warm HTML response is demonstrated | Repeat the bare URL with no cookies, then test one bypass dimension at a time |
| First edge sample is slow and later edge samples are fast | The page was cold and warmed during the run | Confirm the last response is `HIT`; investigate warming only if important URLs repeatedly go cold |
| Both medians similar and fast | Page caching is not the demonstrated bottleneck | Stop; do not add another cache |
| `cache_status: unknown` | No recognized status token was exposed | Inspect all response headers; at tier 1+ inspect cache controls, and otherwise report `unknown` |

Capture the complete headers for the same canonical URL. Keep cookies out of the clean control:

```sh
/usr/bin/curl --silent --show-error --dump-header - --output /dev/null \
  --cookie '' "$SITE_URL/"
```

Then isolate the common bypass causes:

| Cause | Checkable evidence | Result that supports the cause |
|---|---|---|
| Session or cart cookie | Compare the clean control with the same URL carrying the exact cookie copied from a fresh anonymous browser request; record the request `Cookie` header and response cache-status header | Clean request becomes `HIT`, while the cookie-bearing request is consistently `BYPASS`, `DYNAMIC`, or `MISS`; common WordPress/WooCommerce names include `wordpress_logged_in_*`, `woocommerce_items_in_cart`, and `woocommerce_cart_hash`, but a different cookie remains `unknown` until traced to its setter |
| Logged-in bypass leaking to anonymous traffic | Use a fresh browser profile and verify the request has no `wordpress_logged_in_*` cookie; inspect whether the anonymous response sets or receives a cookie/rule intended only for authenticated users | The cookie-free request follows a rule identified as logged-in-only; compare with an authenticated request only at tier 1+ using the operator's existing authorized session |
| Query string defeats the cache key | Request the bare URL twice, then the same stable harmless query URL twice; record `cache-status`, `age`, and TTFB for every response | Bare URL warms to `HIT`, while repeated identical query requests remain `MISS`/`BYPASS`, or every distinct query creates a separate cold object |
| Cache enabled but never warmed | Compare `edge_ttfb_samples_ms` in order and repeat after the configured TTL without purging | First request is a slow `MISS`, later requests are fast `HIT`, and important URLs repeatedly return to that cold pattern |

Never send a fabricated cart or login cookie to production. Use an observed cookie and redact its
value from notes. If header evidence cannot identify the answering layer, the layer is `unknown`.

### At tier 1+ (admin / REST)

In the active cache product or host panel, capture these checkable fields before changing them:

- page-cache enabled/disabled state;
- exclusions for URL paths, query strings, cookies, roles, and logged-in users;
- cache lifespan/TTL and preloading or crawler status;
- the last purge time or purge log, if the product exposes one;
- whether WooCommerce cart, checkout, account, and authenticated pages are excluded without
  excluding unrelated anonymous pages.

With the operator's existing authorized session, compare the authenticated response with a fresh
anonymous response to confirm that logged-in bypass remains scoped to authenticated traffic. Do
not copy authentication cookies into audit artifacts or create a login during a read-only audit.

A plugin shown as installed or active is not evidence that an anonymous response was served from
its cache. Pair the setting with a clean public `HIT`, a rising `Age`, a vendor-specific header,
or a cache artifact at tier 2.

### At tier 2+ (WP-CLI / SSH)

List active cache components and drop-ins without assuming that one owns the response:

```sh
wp plugin list --status=active --format=table
wp plugin list --status=dropin --format=table
```

For the candidate plugin, `wp plugin is-active <plugin-slug>` must exit successfully. Inspect the
named cache path below, if that stack uses one, and compare its file modification time with a
warm request. A present but stale directory is not proof of a live hit. Server-owned caches may
have no readable WordPress cache directory; use their response header or control plane instead.

### By stack

Each identifier below is from `cache_layers[].value`. The public signal proves only what it
actually exposes; missing comments or stripped headers leave the state `unknown`.

#### `wp-rocket`

- Component evidence: `wp plugin is-active wp-rocket` exits 0.
- Serving evidence: the response contains WP Rocket's generated cache comment, or
  `wp-content/cache/wp-rocket/` contains a matching fresh page artifact and a repeat bare request
  becomes faster.
- Bypass check: inspect WP Rocket's cookie, URL, query, user-role, lifespan, and preload settings.
  An active plugin without a serving signal is medium confidence at most.

#### `litespeed-cache`

- Component evidence: `wp plugin is-active litespeed-cache` exits 0 and the server is
  `litespeed` or `openlitespeed`, or QUIC.cloud is intentionally providing the cache service.
- Serving evidence: `x-litespeed-cache: hit` on the HTML response. `miss` followed by `hit` proves
  warming; repeated `miss` or `bypass` names the state, not the cause.
- If the plugin is active on a stack without a compatible cache engine and no `x-litespeed-cache`
  signal appears, full-page cache operation is `unknown`; confirm in the plugin status screen.

#### `w3-total-cache`

- Component evidence: `wp plugin is-active w3-total-cache` exits 0.
- Serving evidence: the generated HTML comment names W3 Total Cache, or a matching fresh artifact
  exists under `wp-content/cache/page_enhanced/` and the clean bare URL warms.
- Inspect Page Cache method, rejected cookies, rejected query strings, rejected user agents, and
  page-cache preload. Other W3 Total Cache modules do not prove its page cache is active.

#### `wp-super-cache`

- Component evidence: `wp plugin is-active wp-super-cache` exits 0.
- Serving evidence: the generated HTML cache comment names WP-Super-Cache, or a matching fresh
  file exists under `wp-content/cache/supercache/` and the public URL warms.
- Check whether caching is enabled, delivery mode is functional, known users are excluded, and
  garbage collection is not removing objects before they are reused.

#### `wp-fastest-cache`

- Component evidence: `wp plugin is-active wp-fastest-cache` exits 0.
- Serving evidence: the generated HTML comment names WP Fastest Cache, or a matching fresh
  artifact under `wp-content/cache/` corresponds to the URL and a clean repeat request warms.
- Check exclusions, logged-in/mobile rules, timeout, and preload. Do not infer a hit from minified
  asset URLs; those are a different cache function.

#### `sg-optimizer`

- Component evidence: `wp plugin is-active sg-cachepress` exits 0.
- Serving evidence: a SiteGround cache header such as `x-proxy-cache` changes from `MISS` to `HIT`
  on the HTML response, corroborated by the Dynamic Cache state in the SiteGround controls.
- `sg-optimizer` is normally the WordPress control surface for a server cache, so do not layer a
  second page-cache plugin merely because there is no local HTML cache directory.

#### `breeze`

- Component evidence: `wp plugin is-active breeze` exits 0.
- Serving evidence: a matching artifact under `wp-content/cache/breeze/`, or a platform Varnish
  header plus the configured Breeze/Varnish integration, corroborates the warm public response.
- Determine whether Breeze page cache, platform `varnish`, or both are enabled before purging or
  changing exclusions; plugin presence alone does not identify the owner.

#### `surge`

- Component evidence: `wp plugin is-active surge` exits 0.
- Serving evidence: a repeat cookie-free bare URL changes from the cold timing/status to a stable
  warm response while Surge is the only page-cache component shown by WP-CLI.
- If no vendor header or inspectable artifact is available, ownership remains medium confidence;
  confirm through Surge's own diagnostics rather than assigning an unrelated `x-cache` header.

#### `cache-enabler`

- Component evidence: `wp plugin is-active cache-enabler` exits 0.
- Serving evidence: the generated HTML comment names Cache Enabler, or a matching fresh file under
  `wp-content/cache/cache-enabler/` corresponds to the requested URL.
- Check cache expiry, exclusions, query strings, and whether WebP/mobile variants divide the cache
  key. A generated static asset is not proof that page HTML was served from this cache.

#### Server-level only (`page-plugin: none`)

This is a valid and often required configuration. Evidence is `page-plugin: none` together with
a server layer such as `litespeed`, `nginx-fastcgi`, `varnish`, or `batcache`, plus a header or
control-panel status that proves the visitor response came from that layer. Do not install a
page-cache plugin to make the WordPress plugin list look complete.

If both `server` and `page-plugin` are `unknown`, escalate to the host dashboard or support. Do
not guess from a fast TTFB alone.

## Attribute

Attribute high TTFB to a missing or bypassed page cache only when the same anonymous, cacheable
URL demonstrates all of the following:

1. the warm visitor path is slow or repeatedly non-`HIT`;
2. a specific response property or configuration explains the miss/bypass, or no full-page cache
   exists where host policy permits one;
3. removing only that property in a safe control, or warming the same object, produces a reusable
   fast response at the identified layer.

Disprove this attribution if a clean warm anonymous request is already a stable `HIT` with fast
`edge_ttfb_ms`. Slow authenticated, cart, checkout, search, preview, or personalized responses
may be deliberately uncacheable. Slow origin renders behind a fast visitor cache are a backend
issue that has been hidden from most visitors, not a page-cache failure; use the official
[`wp-performance` skill](https://github.com/WordPress/agent-skills) for deep PHP, database,
autoload, cron, and object-cache profiling.

## Fix

### The change

First establish which layer is allowed to own anonymous HTML. Then make the smallest matching
change:

1. remove or narrow the unintended cookie, role, URL, or query-string bypass;
2. correct the cache key so genuinely personalized responses stay separate;
3. enable or repair warming for the important canonical URLs;
4. enable one permitted full-page cache only when no effective platform cache exists.

Never cache cart, checkout, account, preview, admin, nonce-bearing, or user-specific HTML as a
shortcut. Never install a cache plugin until the host constraint is confirmed.

### Host constraints

Managed-host plugin policies and plan capabilities can change. “Confirm with the host” means
check the current official disallowed-plugin policy or obtain written support approval before
activation; absence from an old list is not permission.

| Host class | Permitted | Path |
|---|---|---|
| `wpengine` | Use the platform page cache. Do not install or activate a page-cache plugin unless WP Engine explicitly confirms it is permitted for this environment. | Confirm the current disallowed-plugin policy with the host; use the WP Engine cache controls/support purge path. A disallowed cache plugin can trigger platform enforcement, including removal of the plugin. |
| `kinsta` | Use the platform page cache. Add no competing page-cache plugin without explicit host confirmation. | Confirm with the host; use the Kinsta cache controls or support-approved purge path. |
| `siteground` | Prefer the host-integrated `sg-optimizer` path when Dynamic Cache is available; do not run a competing full-page cache without confirmation. | Confirm with the host for the specific plan; configure and purge through SiteGround controls and `sg-optimizer`. |
| `godaddy` | Treat the managed WordPress cache as the candidate owner; plugin allowance varies by product. | Confirm with the host for the exact plan, then use its platform flush path or one explicitly approved plugin. |
| `cloudways` | Coordinate `breeze` with platform `varnish`; do not enable two independent HTML owners. | Confirm the application's current platform configuration with the host; use the Cloudways/Breeze purge controls selected for that application. |
| `flywheel` | Treat the platform page cache as the candidate owner; do not add a competing page-cache plugin without explicit approval. | Confirm with the host for the environment and use its supported cache controls/purge path. |
| `pressable` | Treat platform caching as the candidate owner; plugin allowance and controls must be verified for the site. | Confirm with the host; use the supported platform purge path or an explicitly approved plugin. |
| `rocket-net` | Treat the managed platform and edge as the candidate HTML owners; do not add another owner by default. | Confirm with the host and document which platform control purges each enabled layer. |
| `hostinger` | Server cache availability and page-cache plugin policy depend on the plan and server. | Confirm with the host; choose the host-integrated path or one explicitly approved page-cache plugin. |
| `bluehost` | Managed/platform cache availability and plugin policy depend on the product. | Confirm with the host for the exact plan, then use its platform flush path or one explicitly approved plugin. |
| `pantheon` | Use the platform's `varnish`/`batcache` path; do not add a page-cache plugin without explicit approval. | Confirm with the host; use the Pantheon-supported cache clearing and deployment workflow. |
| `wpcom` | Platform caching owns delivery; plugin installation and cache controls depend on the site plan. | Confirm with the host for the site and plan; use WordPress.com-supported controls rather than adding a generic page-cache plugin. |
| `wpvip` | Platform caching owns delivery and changes require platform-compatible operations. | Confirm with the host/VIP support and use the approved purge path; do not introduce a page-cache plugin independently. |
| `shared-cpanel` | One page-cache mechanism may be appropriate, but server features and provider rules are unknown until checked. | Confirm with the host. If the server is `litespeed` or `openlitespeed`, evaluate `litespeed-cache`; otherwise choose one compatible plugin and keep other page caches disabled. |
| `self-managed` | One intentional page-cache owner is permitted. A plugin is unnecessary when `nginx-fastcgi`, `varnish`, or another server layer already owns HTML. | Document the selected owner and purge command, disable overlapping page caches, then warm and verify anonymous HTML. |
| `other` | Cache ownership and plugin policy are `unknown` until the provider and server controls are identified. | Confirm with the host; document the permitted owner and purge path before installing or enabling a page-cache plugin. |
| `unknown` | No page-cache plugin change is permitted until the host and existing cache owner are identified. | Resolve the provider/server through account records or support; keep policy `unknown` and make no cache installation in the meantime. |

### Risk

An over-broad cache rule can expose one visitor's cart, account state, locale, currency, nonce, or
preview to another. A second page cache can serve stale content, double-transform responses, or
break purges. On hosts with prohibited-plugin policies, activation can also trigger platform
enforcement. The first people to notice are editors, authenticated users, shoppers, multilingual
visitors, and support staff handling stale pages.

## Verify

Capture a before document, apply the one approved change, purge the owning layer, warm each test
URL, and capture an after document:

```sh
python3 skills/wp-perf-audit/scripts/perf-probe.py \
  --site "$SITE_URL" --repeats 3 --quick --label before --json before.json
python3 skills/wp-perf-audit/scripts/perf-probe.py \
  --site "$SITE_URL" --repeats 3 --quick --label after --json after.json
python3 skills/wp-perf-audit/scripts/perf-probe.py --diff before.json after.json
```

Verification passes only when the cookie-free canonical URL is a stable warm response from the
intended layer, `edge_ttfb_ms` improves or remains acceptably fast, and personalized/excluded
URLs remain bypassed. Also repeat with the observed guest cookie, logged-in session, cart, query,
and locale variants that apply to the site.

Re-measure warm. The probe report explicitly warns that measurements immediately after a cache
flush are transient and not comparable.

## Rollback

Before changing anything, export or screenshot the cache settings, exclusions, TTL, warming list,
host controls, and the exact purge path. To roll back, restore those values, remove only the new
rule or newly activated plugin, restore the former single owner, purge every layer affected by
the attempted change, warm the test URLs, and repeat the control requests. If the previous host
configuration cannot be exported, record its values manually before the change.

## Gotchas

- `edge_ttfb_ms` names the visitor-facing path, not necessarily a CDN. A `server` or
  `page-plugin` layer may have answered it.
- A query-busting origin request is intentionally cold. It does not show the warm visitor
  experience, and a reported `HIT` means the cache may be ignoring the buster.
- A cache comment can be stripped and a header can be hidden. Missing evidence means `unknown`,
  not “cache disabled.”
- A session plugin that sets a cookie for every anonymous visitor can disable full-page caching
  site-wide even when no personalization is visible.
- Warm only representative canonical URLs; warming endless faceted or query-string variants can
  evict useful objects.
- “Install WP Rocket” is unsafe generic advice. The current host policy and existing server cache
  decide whether any page-cache plugin is permitted.
