<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Cache purge matrix

There is no common purge interface across WordPress hosting. A cache action is usable only after
its owner, scope, control surface, required access, and observable result have been confirmed for
this site. A change purged on the wrong layer is a change that never shipped.

## Contents

- [Stop gate: establish the path first](#stop-gate-establish-the-path-first)
- [Purge order: innermost outward](#purge-order-innermost-outward)
- [Map a change target to purge layers](#map-a-change-target-to-purge-layers)
- [Layer matrix](#layer-matrix)
  - [`edge`](#edge)
  - [`server`](#server)
  - [`page-plugin`](#page-plugin)
  - [`object`](#object)
- [Managed host control surfaces](#managed-host-control-surfaces)
- [Prove the purge reached visitors](#prove-the-purge-reached-visitors)
- [Gotchas](#gotchas)

## Stop gate: establish the path first

Before applying the approved change, build a purge record for every affected layer:

| Required fact | Evidence to capture before the change |
|---|---|
| Layer and owner | Exact `cache_layers[].layer` and `cache_layers[].value` from the stack profile, corroborated in the site's control plane when possible |
| Control surface | The host dashboard, provider dashboard, WordPress screen, API operation, or operator runbook that owns the purge |
| Access | An authorized operator can reach the control and select the intended site/environment |
| Scope | Exact URL, tag/group, site, environment, network, or global; choose the narrowest sufficient scope |
| Completion signal | Purge log/status plus the public body, validator, `Age`, and cache-status transition expected afterward |
| Failure path | The person or support route that can purge or bypass the layer if the normal control fails |

Do not discover this after applying the change. If the only route is a dashboard button and no
authorized operator can use it, stop. If a host or product policy cannot be confirmed from that
owner's documentation, record it as `unknown`, treat the proposed operation as prohibited, and
[confirm with the host](host-constraints.md). A button label, API success, or plugin notice does
not prove the cached representation was removed.

## Purge order: innermost outward

Purge only the layers that store the affected representation, in this order:

```text
object → page-plugin → server → edge
```

The order is load-bearing. An outer cache refills from the next inner layer. Purging `edge` before
stale `server` or `page-plugin` HTML has been invalidated lets the edge immediately store that
stale HTML again. Likewise, rebuilding page HTML before invalidating a stale `object` can bake the
old value into a new page-cache entry. Finish or verify each inner invalidation before moving
outward; do not fire all purges in parallel.

Omit a layer when it does not store the changed representation. Preserve the relative order of
the layers that remain. The change plan's `purge_layers` must contain only layers confirmed by the
stack profile, using the exact identifiers `edge`, `server`, `page-plugin`, and `object`.

## Map a change target to purge layers

This table maps every change-plan `target.kind` value to the usual dependency path. It is not a
license to flush every listed cache. Select only confirmed layers that store the affected bytes or
derived output, then write them in innermost-to-outermost order in `purge_layers`. If ownership is
`unknown`, stop and identify it rather than guessing.

| `target.kind` | Purge layers to select, in order | Boundary and narrowing rule |
|---|---|---|
| `theme-file` | `page-plugin` → `server` → `edge` when PHP/template output or an asset URL changed; `edge` alone for same-URL CSS, JavaScript, font, or image bytes | A static CSS edit does **not** require an `object` flush. Purge HTML layers only when their stored markup, inline bytes, or versioned URL changed. |
| `plugin-file` | `page-plugin` → `server` → `edge`; add `object` first only when the changed code reads or writes a persistent cached key that remains stale | A code deploy may also require an approved PHP opcode-cache reload; opcode cache is not a change-plan cache-layer value. |
| `mu-plugin` | `page-plugin` → `server` → `edge`; add `object` first only for an identified stale key/group | Treat generated HTML and static assets separately. Do not turn code deployment into a global object flush by default. |
| `wp-option` | `object` → `page-plugin` → `server` → `edge` for an option reflected in public output | WordPress normally invalidates its own option cache on an API-mediated update, but verify that it did. Prefer the exact option/key invalidation over a full `object` flush. |
| `plugin-setting` | `object` → `page-plugin` → `server` → `edge` when the setting affects public output | If the setting only changes an external service or admin screen, remove unrelated layers. If it changes cache configuration itself, follow the product's transition runbook. |
| `builder-content` | `object` → `page-plugin` → `server` → `edge` for affected pages and reusable/global components | Purge every URL/template/language that embeds the changed content, not merely the editor preview URL. Use the builder's own targeted regeneration before a site-wide flush when available. |
| `media` | `edge` for changed same-URL media bytes; `object` → `page-plugin` → `server` → `edge` when attachment metadata or rendered markup changed | Prefer purging the exact asset URL and affected HTML URLs. Browser caches are outside the closed layer set; use a new asset URL when immutable browser caching prevents recall. |
| `server-config` | `server` → `edge` when the change affects cached responses, headers, routing, or cache keys | Do not purge `page-plugin` or `object` unless the specific configuration change invalidates their output. Reloading server configuration is not itself proof that cached responses changed. |
| `dns-or-cdn-setting` | `edge` when cached edge objects or edge behavior changed | Recursive-resolver DNS caches are outside this vocabulary and cannot be globally purged by WordPress. DNS/CDN changes remain explicitly approved operations; verify normal public resolution and delivery. |

For a page that embeds a changed asset, separate two questions: the asset URL may require `edge`,
while cached HTML requires an inner HTML purge only if the markup or asset URL changed. Avoid a
site-wide HTML purge for unchanged markup.

## Layer matrix

The paths below identify the control surface to establish; they do not assert that an account,
plan, plugin build, or host integration exposes it. Confirm the exact action and its scope in the
owner's documentation and in the target account before the change. Never send a guessed `PURGE`,
`BAN`, API request, or WP-CLI command to production.

### `edge`

| `cache_layers[].value` | Purge path to establish before change | Visitor evidence after purge |
|---|---|---|
| `cloudflare` | The zone's documented cache-purge control in the Cloudflare dashboard or API; prefer URL/tag scope over the whole zone | `cf-cache-status` for the requested URL transitions away from the prior stale `HIT`; `Age` resets or disappears; the body/asset marker is new; a later warm request may become `HIT` |
| `cloudflare-apo` | The Cloudflare control explicitly documented to invalidate APO HTML and any connected WordPress integration; do not assume an origin/plugin purge reaches APO | Check `cf-apo-via` and `cf-cache-status` together, then prove the anonymous body is new and a warm response remains new |
| `quic-cloud` | The site's QUIC.cloud dashboard purge control or its confirmed LiteSpeed Cache integration | `x-qc-cache` changes from the stale hit state, `Age`/validators reset where exposed, and the new body persists after warming |
| `bunny` | The affected pull zone's cache-purge control or API operation, scoped to the changed URL when supported | Provider markers such as `cdn-pullzone`/`cdn-uid` still identify the edge; status/`Age` evidence, validators, and new bytes prove invalidation |
| `keycdn` | The affected zone's purge control or API operation; verify whether the documented scope is URL or zone | `x-edge-location` identifies the delivery path but does not alone prove invalidation; require reset status/`Age` where exposed and the new body or asset hash |
| `fastly` | The service's documented URL, surrogate-key, or service purge in its control panel/API | `x-cache`, `x-served-by`, `via`, and `Age` show the miss/refill sequence when exposed; the changed marker must be present on both cold and warm fetches |
| `aws-cloudfront` | A documented invalidation for the exact distribution and path pattern; confirm the distribution before submitting it | `x-amz-cf-*` identifies CloudFront; `x-cache`/`Age` may show miss then hit, but only the new body or asset hash proves the right object changed |
| `akamai` | The property's documented purge/invalidation workflow, using the exact URL or cache tag where available | Akamai-namespaced headers or `akamai-grn` may identify delivery; require the new representation and reset validator/`Age` or provider purge evidence because status headers may be absent |
| `stackpath` | The service/zone's documented purge control; if the account no longer exposes an attributable owner, keep the route `unknown` and stop | `x-sp-cache` or `x-hw` can identify the edge; require a fresh body/hash and status/`Age` transition where exposed |
| `none` | No `edge` purge. Confirm that DNS and response headers really show no intervening edge before omitting it | No edge-specific status or rising shared-cache `Age`; the public response matches the confirmed origin path |
| `other` | Identify the provider and its documented purge interface; no generic edge purge is safe | Record its attributable header/status semantics and prove the new body; an ambiguous `x-cache` is insufficient |
| `unknown` | Stop until account records, DNS/control-plane evidence, or the host identifies the owner and purge route | No header interpretation can substitute for ownership; retain `unknown` |

### `server`

| `cache_layers[].value` | Purge path to establish before change | Visitor evidence after purge |
|---|---|---|
| `litespeed` | The virtual host's documented LiteSpeed cache purge, often surfaced through the host control panel or a confirmed LiteSpeed Cache integration | With `edge` bypassed or known to miss, `x-litespeed-cache` changes from stale `hit` to `miss` and then a warm `hit`; every response contains the new marker |
| `nginx-fastcgi` | The host/server runbook for its configured FastCGI cache: URL purge, zone purge, deployment hook, or dashboard action as actually implemented | With outer caches controlled, `x-fastcgi-cache` or attributable `x-cache-status` shows miss/refill; `Age`/validator resets and the body changes |
| `varnish` | The platform's documented purge or ban path for the correct service/environment; the accepted method and cache key are configuration-specific | With `edge` controlled, attributable `x-cache`, `x-varnish`, `via`, and `Age` evidence supports the transition; the new body proves the selected object changed |
| `batcache` | The WordPress/platform invalidation path documented for the installed Batcache integration; do not equate a generic object-cache flush with a safe page purge | The Batcache HTML marker can identify generated output, but only a new body/validator after the platform invalidation proves freshness |
| `none` | No `server` purge | An approved origin path returns the new representation without a server-cache hit signal |
| `unknown` | Stop until the host/server owner identifies the cache and invalidation path | Ambiguous `server`, `via`, or `x-cache` headers are not enough to choose a purge command |

### `page-plugin`

Use the installed plugin's documented WordPress administration action. A similarly named host
button may purge a different layer. Confirm whether the action targets one URL, all generated
pages, minified assets, or connected `edge` caches.

| `cache_layers[].value` | WordPress control surface to establish | Visitor evidence after purge |
|---|---|---|
| `wp-rocket` | WP Rocket dashboard/admin-bar cache-clear action, with the affected URL scope when the installed product exposes one | With outer layers controlled, the WP Rocket marker/artifact is regenerated and anonymous HTML contains the new marker; a marker alone is not freshness proof |
| `litespeed-cache` | LiteSpeed Cache Toolbox purge control for the narrowest sufficient scope; separately establish whether it also signals QUIC.cloud or server LiteSpeed | `x-litespeed-cache` can represent more than one LiteSpeed-owned layer, so isolate outer/server behavior and prove the body across miss then warm hit |
| `w3-total-cache` | W3 Total Cache Performance dashboard cache-empty control, narrowed to the affected cache type or URL where available | The W3 Total Cache HTML marker/artifact is regenerated and visitor HTML is new after outer layers are controlled |
| `wp-super-cache` | WP Super Cache contents/cache deletion control, scoped to the affected cached pages when available | A fresh file/HTML marker and new anonymous body replace the prior object; repeat after warming |
| `wp-fastest-cache` | WP Fastest Cache cache deletion control; establish separately whether generated CSS/JavaScript also needs deletion | Its HTML/header marker may identify ownership; require the new body/asset hash after controlled outer layers |
| `sg-optimizer` | The `sg-optimizer` caching control in WordPress and the SiteGround platform control that owns Dynamic Cache; determine whether one invokes the other | `x-proxy-cache-info` where exposed plus new body and miss/refill behavior; a WordPress success notice alone is insufficient |
| `breeze` | Breeze cache purge control; establish separately the Cloudways `varnish` and any `edge` controls | `x-breeze-cache` or plugin artifact can identify the layer; new anonymous HTML after the full inner-to-outer sequence proves it changed |
| `surge` | Surge's documented automatic or manual invalidation for the installed site; if no operator control can be confirmed, stop | `x-surge-cache` where exposed plus the new body across cold/warm requests; do not infer freshness from the header name alone |
| `cache-enabler` | Cache Enabler site/page cache-clear control, using the narrowest available scope | `x-cache-enabler` or the plugin marker/artifact identifies ownership; the new public body after warming proves freshness |
| `none` | No `page-plugin` purge | Confirm no active page-cache plugin or page-cache artifact owns anonymous HTML |
| `unknown` | Stop until active-plugin, drop-in, artifact, or control-plane evidence identifies the owner | Do not install a second plugin merely to obtain a purge button |

### `object`

An `object` flush is not free. A full flush on a busy site creates a thundering herd of misses
against the database while keys rebuild. Prefer invalidating the exact key and group, or use the
application's normal update API that already invalidates them. Use a full flush only when the
affected keys cannot be bounded, the operator explicitly approves that scope, and database
capacity and recovery monitoring are in place.

| `cache_layers[].value` | Purge path to establish before change | Proof and narrower alternative |
|---|---|---|
| `redis` | The documented WordPress drop-in/plugin or platform control for the site's Redis namespace; confirm multisite and shared-instance scope | Public headers rarely prove a key deletion. Read back the changed value and regenerated page; prefer deletion of the exact WordPress key/group over flushing the namespace or server |
| `memcached` | The installed drop-in/platform invalidation for the site's namespace; confirm whether a flush affects other sites | Prove the application read and regenerated output; prefer an exact key/group delete because a full flush can cold-start every tenant sharing the service |
| `apcu` | The application's documented invalidation executed in every relevant PHP process/pool; a one-process clear may not reach peers | There is no reliable visitor header. Prefer application-versioned keys or exact-entry invalidation; verify repeated requests across the public pool |
| `object-cache-pro` | Object Cache Pro's documented site/network cache tool for the installed topology, using key/group invalidation where supported | `x-object-cache-pro` may identify the product but does not prove the affected key was removed; use its diagnostics plus public output and prefer the exact key/group |
| `none` | No `object` purge | Confirm WordPress is not using an external object-cache drop-in for the affected data |
| `unknown` | Stop before flushing. Identify the drop-in, backend, namespace, and blast radius | A public page-cache header cannot establish object-cache ownership or safe flush scope |

## Managed host control surfaces

`host_class` routes the operator to a control surface; it is not proof of current host policy or
of what a button clears. For each row, use the host's own documentation for the exact product and
account, confirm the selected site/environment, and record which of `server`, `page-plugin`, and
`edge` the action actually reaches. If the documented path is unavailable, the purge path is
`unknown` and the change stops.

| `host_class` | Dashboard/platform path to locate and verify before change |
|---|---|
| `wpengine` | The environment cache control in the WP Engine portal and any WP Engine WordPress-admin cache control; establish separately any external `edge` purge |
| `kinsta` | The site's cache control in MyKinsta tools and any Kinsta WordPress-admin cache control; identify whether CDN/edge cache is included |
| `siteground` | Site Tools caching controls plus the `sg-optimizer` WordPress controls; prove whether Dynamic Cache and external `edge` are separate actions |
| `godaddy` | The exact Managed WordPress product's dashboard or WordPress-admin managed-cache control; product identity and scope must be confirmed with GoDaddy |
| `cloudways` | The application's platform Varnish control, the `breeze` WordPress control, and any external `edge` control as three candidate owners until proven coordinated |
| `flywheel` | The site's Flywheel dashboard cache control and any WordPress-admin host control; establish the external `edge` path separately |
| `pressable` | The site's MyPressable cache/performance control or host-provided WordPress control documented for that account; establish any external `edge` action |
| `rocket-net` | The site's Rocket.net cache/CDN controls; record whether one action reaches platform HTML, asset, and edge objects or whether scopes differ |
| `hostinger` | The site's hPanel cache manager and any confirmed LiteSpeed/WordPress cache control; determine which owner each action purges |
| `bluehost` | The exact Bluehost product's portal performance/cache control and any provider WordPress plugin control; confirm scope for that plan |
| `pantheon` | The selected site's environment cache-clear control in the Pantheon dashboard or approved platform tooling; verify the environment and `varnish`/`batcache` sequence |
| `wpcom` | The WordPress.com platform or support workflow documented for the site's plan; do not invent a dashboard purge when none is exposed |
| `wpvip` | The approved WordPress VIP operational or support workflow for the application/environment; coordinate the platform purge rather than issuing an unapproved generic request |
| `shared-cpanel` | The account's product-specific cPanel cache manager or host-provided LiteSpeed/plugin control, if present; cPanel itself is not a common purge interface |
| `self-managed` | The operator-owned runbook for each configured cache zone/service; no dashboard or command is implied by this identifier |
| `other` | Identify the provider and obtain its documented control path; treat cache mutation as prohibited until then |
| `unknown` | Stop. Resolve host ownership from account records or host support before planning a purge |

## Prove the purge reached visitors

Use [live verification](verify-live.md) after each layer, not merely after the last button. Fetch
the normal public URL anonymously, without a cache-busting query string, and capture:

1. URL, status, body marker or asset hash, `etag`, `last-modified`, `age`, and all cache-status
   headers before the purge;
2. the same evidence on the first post-purge request;
3. the same evidence after enough anonymous requests to warm the affected URL;
4. the host/provider purge log or completion result, clearly labelled as control-plane evidence,
   not visitor proof.

Expected evidence by layer:

| Layer | What a visitor response can prove |
|---|---|
| `edge` | The attributable edge status leaves the stale `HIT`, `Age` resets or disappears, the new marker/hash is served, and later warm responses remain new |
| `server` | With `edge` bypassed through an approved route or known to miss, the attributable server status moves through miss/refill and the new body remains present |
| `page-plugin` | With outer layers controlled, anonymous HTML changes and any vendor marker/artifact is regenerated; many plugins expose no reliable status header |
| `object` | Usually no public header proves invalidation. The source value, product diagnostics, regenerated HTML, and stable repeated output must agree |

An outer cache can replay headers stored from an inner response. Multiple `HIT` strings in one
response do not prove every layer executed on that request. Pair headers with the changed body or
asset hash and an approved bypass/control-plane observation.

## Gotchas

- **TTFB spikes immediately after a flush are transient.** The first requests pay to rebuild the
  cache. Warm every affected URL and re-measure before reporting a regression. This has produced
  false alarms in real campaigns more than once.
- Purging all languages under one URL does not prove translated URLs changed. Purge and verify
  each language/cache-key variant.
- Query strings, cookies, device variants, currency, and hostnames may create separate objects.
  Purge the variants the changed representation actually affects.
- A successful command, dashboard toast, or API response proves only that an action was accepted.
  It is not proof of what a visitor received.
- Rollback requires the same inner-to-outer purge sequence as the forward change; otherwise the
  restored state can remain hidden behind the changed cached copy.
