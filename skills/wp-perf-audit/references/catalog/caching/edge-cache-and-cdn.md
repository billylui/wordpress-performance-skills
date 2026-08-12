<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Edge cache and CDN not serving the intended content

The configured edge either does not cache page HTML, bypasses eligible requests, expires them too quickly, or retains content after the origin changes.

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

Visitor-facing TTFB remains close to the uncached origin cost, HTML never becomes a demonstrated
edge `HIT`, or visitors continue receiving an old representation after the origin was updated.
The primary metric is TTFB; stale delivery can be functionally wrong even when it is fast.

An asset CDN can lower image, CSS, font, or JavaScript transfer latency without moving HTML TTFB.
Do not report that as a failed CDN. The defect exists only when full-page HTML caching was intended
or when the configured edge mishandles the content it is meant to cache.

## Detect

### At tier 0 (public URL only)

Run the visitor-path/origin comparison and keep the JSON evidence:

```sh
python3 skills/wp-perf-audit/scripts/perf-probe.py \
  --site "$SITE_URL" --repeats 3 --quick --json edge-baseline.json
```

The probe gives each origin sample a unique query buster and requests the bare URL for each edge
sample. It reports median `origin_ttfb_ms` and `edge_ttfb_ms`, the raw samples, normalized
`cache_status`, and the raw `cache_header` selected from the final response.

| Origin versus visitor path | Cache evidence | Attribution |
|---|---|---|
| Large `origin_ttfb_ms` minus `edge_ttfb_ms` gap | Identified edge header reports `HIT` on HTML | The edge is doing real work. Visitors benefit, but origin cost is deprioritized, not solved. |
| Small gap and both are slow | Edge header is `MISS`, `BYPASS`, `DYNAMIC`, or absent | Full-page HTML is not demonstrated at the edge; check whether the product is asset-only or the request is bypassed. |
| Small gap and both are fast | Any | No visitor-facing TTFB defect is demonstrated. Do not add HTML caching solely to create a gap. |
| Fast edge with `cache_status: unknown` | No identifiable owner | A visitor-path cache may exist, but its layer is `unknown`; inspect all headers and confirm in the edge control plane. |
| Slow first edge sample, fast later samples | Final response becomes an identified edge `HIT` | Cold object warmed during the run; investigate TTL or purge frequency rather than absence. |

Capture the final HTML headers, not an asset response:

```sh
/usr/bin/curl --silent --show-error --dump-header - --output /dev/null \
  --cookie '' "$SITE_URL/"
```

Read these fields together:

| Header | Checkable meaning | Limitation |
|---|---|---|
| `cf-cache-status` | Cloudflare's disposition such as `HIT`, `MISS`, `BYPASS`, or `DYNAMIC` | A Cloudflare asset `HIT` does not prove HTML is cached; check the document response |
| `x-litespeed-cache` | LiteSpeed/QUIC.cloud cache disposition when exposed | Can describe a server or service cache; corroborate with `x-qc-cache`, DNS, or the control plane |
| `x-qc-cache` | QUIC.cloud cache disposition when exposed | Missing may mean stripped or disabled, so absence remains `unknown` |
| `x-cache` | A cache result emitted by several products | Ambiguous by itself; use the value plus `via`, `x-served-by`, `x-amz-cf-pop`, DNS, or provider configuration |
| `age` | Seconds the current stored response has resided in a shared cache | Missing does not prove a miss; a rising value on identical requests is stronger evidence |
| `cache-control` | Browser/shared-cache directives and TTLs such as `max-age`, `s-maxage`, `private`, or `no-store` | The edge can override origin directives; confirm effective policy in its control plane |
| `vary` | Request fields included in representation selection | `Vary: Cookie` can fragment or defeat caching; a hidden edge cache key can add more dimensions |

Test the common edge failures one dimension at a time:

- **Cookie-driven bypass:** compare a no-cookie control with the same URL carrying the exact
  observed anonymous cookie. Record request `Cookie`, `cf-cache-status`/`x-qc-cache`/other owning
  status, and `Age`. A clean `HIT` versus cookie-bearing `BYPASS` supports the cause.
- **Short or missing TTL:** issue identical requests over an observation period. A low
  `s-maxage`/effective edge TTL, `Age` repeatedly resetting, and recurring `MISS` after short idle
  periods support premature expiry. Do not infer an effective TTL from `cache-control` alone when
  the edge has an override.
- **Purge never fires:** after an authorized controlled content change and the documented purge,
  compare body hash or visible marker, `etag`/`last-modified`, `Age`, and cache status at origin
  and edge. New origin content plus an old edge body whose `Age` continues rising proves the wrong
  layer retained the object.

### At tier 1+ (admin / REST)

Capture the CDN/edge settings that can settle public ambiguity:

- whether the HTML document hostname actually passes through the edge;
- whether a full-page/dynamic HTML feature is enabled, rather than only asset delivery;
- cache rules for document paths, methods, status codes, cookies, query strings, and response
  headers;
- effective edge TTL, stale-serving behavior, and cache-key dimensions;
- the WordPress integration or webhook responsible for purge, its scope, and its last outcome;
- exclusions for authenticated, cart, checkout, account, preview, API, and personalized routes.

A dashboard toggle is configuration evidence, not serving evidence. Pair it with the final HTML
response from tier 0.

### At tier 2+ (WP-CLI / SSH)

Identify the origin-side integration and any competing full-page cache:

```sh
wp plugin list --status=active --format=table
wp plugin list --status=dropin --format=table
```

Inspect the web server or host configuration only for the exact hostname in scope. Capture the
rule that sets `cache-control`, bypasses cookies/query strings, or calls the provider purge API.
If credentials or the edge control plane are unavailable, purge delivery remains `unknown`; do
not treat an installed WordPress integration as proof that its webhook succeeds.

### By stack

Identifiers are the closed `cdn` vocabulary. “Full-page capable” still requires an enabled rule
and a demonstrated HTML `HIT` for this site.

#### `cloudflare`

`cloudflare` proves the request traverses Cloudflare, not that HTML is cached. Common static
assets may show `cf-cache-status: HIT` while the HTML document shows `DYNAMIC` or `BYPASS`.
Full-page HTML requires an intentional cache rule or equivalent configuration. Capture the HTML
`cf-cache-status`, `age`, `cache-control`, and the matching rule. Without those, HTML caching is
`unknown` or not demonstrated.

#### `cloudflare-apo`

Automatic Platform Optimization is the WordPress-aware full-page HTML mode. Evidence is an HTML
`cf-cache-status: HIT` corroborated by an APO-specific response signal such as `cf-apo-via` and
the enabled WordPress integration. Its value is full-page delivery plus coordinated purging, but
the integration can still fail or a cookie can still bypass. If only `cf-cache-status` is visible,
distinguish generic `cloudflare` rules from `cloudflare-apo` in the control plane.

#### `quic-cloud`

QUIC.cloud is designed to cache static and dynamic WordPress content. Check the HTML response for
`x-qc-cache` and, where exposed, `x-litespeed-cache`; then corroborate the domain and LiteSpeed
Cache integration. A static asset hit does not prove dynamic HTML caching. Confirm the crawler,
TTL, purge queue, and vary groups when the first request is repeatedly cold.

#### `bunny`

Treat `bunny` as an asset CDN, not a full-page WordPress HTML cache. It normally needs a separate
`server` or `page-plugin` owner for HTML. Prove this by checking whether the document hostname and
HTML response pass through Bunny; a Bunny-served asset hostname is only asset evidence. A custom
edge arrangement changes the answer only when its explicit HTML rule and response signal are
captured.

#### `keycdn`

Treat a normal WordPress `keycdn` integration as asset delivery unless the HTML hostname and an
explicit cache policy prove otherwise. `x-cache` can be emitted on KeyCDN responses but is
ambiguous alone; corroborate with the responding hostname, `via`, DNS/profile evidence, and the
zone configuration. Do not map an origin `x-cache` to `keycdn` merely because KeyCDN assets exist.

#### `fastly`

Fastly can cache full-page HTML when its service/VCL permits it. Evidence is an HTML `x-cache`
value such as a hit, corroborated by `x-served-by`, `via`, `age`, and the matching service rule.
Because `x-cache` is shared by other products, that header alone has medium confidence at most.
Inspect cookie shielding, TTL, surrogate keys, and purge results.

#### `aws-cloudfront`

CloudFront can cache HTML or only selected/static behaviors. Evidence for HTML is the document
response `x-cache` value containing CloudFront context, corroborated by `via` or `x-amz-cf-pop`,
plus the distribution behavior matching that path. Check cache policy fields forwarded for
cookies, query strings, and headers; forwarding too many values can create a near-zero hit rate.

#### `akamai`

Akamai can cache HTML when the property configuration permits it. Debug cache headers may be
hidden, so `x-cache`/`age` evidence must be corroborated with the active property and hostname.
If public headers cannot identify the property or outcome, report HTML cache status `unknown` and
confirm it in the Akamai control plane. Do not infer from Akamai-hosted assets.

#### `stackpath`

Treat `stackpath` as the exact fingerprint value only when vendor-specific DNS, headers, or the
site's control plane identifies it. `x-cache` alone is ambiguous and does not prove HTML caching.
Check the document hostname, explicit HTML policy, effective TTL, cache key, and purge result; if
the control plane is no longer available, HTML behavior and purge ownership remain `unknown`.

#### `none`

`cdn: none` means no CDN was identified; it does not mean no cache exists. The bare visitor path
can still be served by `litespeed`, `nginx-fastcgi`, `varnish`, `batcache`, or a `page-plugin`.
Use their headers and the stack profile. If a CDN may be intentionally hiding its headers, keep
the value `unknown` until DNS or the control plane settles it.

#### `other`

`cdn: other` means evidence identified an edge outside the named vocabulary but not its supported
adapter. Preserve the evidence, inspect the HTML response and provider control plane, and apply
the generic origin-versus-visitor, cache-key, TTL, and purge checks. Do not translate an ambiguous
`x-cache` value into a named CDN.

## Attribute

Attribute slow visitor TTFB to the edge only when full-page HTML was intended and the final HTML
response proves one of these mechanisms: no edge traversal, repeated eligible `MISS`, explicit
`BYPASS` tied to a request property, TTL expiry before reuse, or stale content surviving an
authorized purge.

Disprove the attribution when an identified edge consistently serves warm HTML `HIT`s with fast
`edge_ttfb_ms`. A slow `origin_ttfb_ms` behind that edge remains real but is not the immediate
visitor-path defect. For its backend cause, cross-link to the official
[`wp-performance` skill](https://github.com/WordPress/agent-skills) rather than duplicating PHP,
database, autoload, cron, and object-cache profiling here.

Also disprove an “edge cache failure” when the configured product is asset-only and assets are
served correctly. In that case, investigate the actual HTML owner in
[page cache missing or bypassed](page-cache-missing-or-bypassed.md).

## Fix

### The change

Make the smallest change at the proven owner:

1. enable full-page HTML only if it is intended and safe for this site;
2. narrow the cookie, query, header, or path bypass without caching personalized routes;
3. set an effective edge TTL long enough for reuse and short enough for the site's purge
   guarantees;
4. repair the WordPress-to-edge purge hook and map it to every stored variant;
5. for an asset-only CDN, leave it asset-only and ensure one separate layer owns HTML.

Establish the purge path before making the change. Record whether it is a WordPress action,
provider dashboard operation, API call, host support action, or deployment hook.

### Host constraints

| Host class | Permitted | Path |
|---|---|---|
| `wpengine` | External edge changes must preserve the platform cache and its purge behavior. | Confirm with the host before putting a second full-page edge in front; document whether platform and edge purges are linked. |
| `kinsta` | External edge changes must coordinate with the platform page cache/CDN offering. | Confirm with the host for the environment; use the supported integration and purge path. |
| `siteground` | CDN/edge settings must coordinate with SiteGround Dynamic Cache and `sg-optimizer`. | Confirm with the host; avoid an independent HTML rule whose purge is not connected to the origin cache. |
| `godaddy` | CDN/edge behavior must coordinate with the cache provided by the exact managed product. | Confirm with the host for the plan; document both platform and external `edge` purge paths. |
| `cloudways` | Edge configuration must coordinate with `breeze` and platform `varnish`. | Confirm the application topology with the host and test both purge paths. |
| `flywheel` | External edge behavior must coordinate with the platform page cache. | Confirm with the host; document whether a platform purge reaches the external `edge`. |
| `pressable` | External edge behavior must coordinate with platform caching and supported integrations. | Confirm with the host before adding full-page HTML caching; record both purge paths. |
| `rocket-net` | Treat the managed platform/edge as the candidate delivery owner. | Confirm with the host; avoid adding an independent HTML edge whose purge is disconnected. |
| `hostinger` | CDN and server-cache topology depends on the plan and server. | Confirm with the host; identify the HTML owner and every enabled purge path. |
| `bluehost` | CDN and platform-cache topology depends on the product. | Confirm with the host for the exact plan and record both platform and external edge controls. |
| `pantheon` | Edge behavior must follow the platform `varnish`/`batcache` workflow. | Confirm with the host and use its supported cache tags/purge operation. |
| `wpcom` | Platform delivery controls what external proxying and purge integration are supported. | Confirm with the host for the site and plan before adding or changing an edge. |
| `wpvip` | Edge and purge changes require platform-compatible operations. | Coordinate with VIP support; use the approved purge and deployment path. |
| `shared-cpanel` | An external CDN may be used if the provider and DNS configuration permit it. | Confirm with the host, retain origin access, and document both origin and CDN purge paths. |
| `self-managed` | Edge caching is permitted when its cache key, exclusions, and purge integration are owned and tested. | Keep an origin bypass for diagnosis, one documented HTML owner, and a recoverable DNS/proxy rollback. |
| `other` | Edge and platform restrictions are `unknown` until the provider and origin topology are identified. | Confirm with the host; document the permitted proxy, cache owner, and purge sequence. |
| `unknown` | No edge mutation is safe until hosting and delivery ownership are identified. | Resolve the host and DNS/control-plane owner; keep policy and purge behavior `unknown` meanwhile. |

### Risk

An unsafe edge rule can leak account, cart, locale, currency, preview, or nonce-bearing HTML across
visitors. Over-forwarding cookies or query strings can destroy the hit rate; under-forwarding
them can mix representations. A broken purge makes correct origin content appear unpublished.
Editors and shoppers usually notice first, while monitoring may continue to report fast TTFB.

## Verify

After changing and purging the intended layer, warm the canonical URL before measuring. Capture
an after document and compare it:

```sh
python3 skills/wp-perf-audit/scripts/perf-probe.py \
  --site "$SITE_URL" --repeats 3 --quick --label after --json edge-after.json
python3 skills/wp-perf-audit/scripts/perf-probe.py \
  --diff edge-baseline.json edge-after.json
```

Pass criteria are an identified HTML edge `HIT`, stable warm `edge_ttfb_ms`, the expected
origin/edge gap, and continued bypass for every personalized route. Verify a controlled content
change reaches both origin and edge by comparing a body marker or hash and ensuring `Age` resets.
Check the applicable cookie, query, language, currency, mobile, and hostname variants.

Re-measure warm: readings immediately after purge are transient and not comparable.

## Rollback

Before the change, export the edge rule set, cache policy, DNS/proxy state, TTLs, cache-key fields,
purge integration, and host cache settings. Roll back the exact changed rule or integration,
restore the prior routing/configuration, purge every layer that received the bad representation,
warm the previous safe path, and repeat the anonymous and personalized controls. DNS changes need
the previously recorded values and an operator-approved restoration plan.

## Gotchas

- “Uses a CDN” and “caches HTML at the edge” are different claims. Test the document response.
- `cloudflare` is not `cloudflare-apo`; a static asset `HIT` does not upgrade the identifier.
- `x-cache` alone is ambiguous because multiple products emit it. Preserve its full value and
  collect corroborating headers or control-plane evidence.
- A large origin/edge gap is good for visitors, but it hides rather than fixes origin work.
- Cookie exclusions that match any cookie can bypass nearly every real browser while clean curl
  tests keep hitting.
- A purge that succeeds at the origin but not the edge leaves a fast, stale site. Verify content,
  not merely a successful purge notification.
