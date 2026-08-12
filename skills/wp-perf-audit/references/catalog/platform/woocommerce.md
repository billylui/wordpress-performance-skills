<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# WooCommerce workload and cacheability

A WooCommerce store mixes cacheable catalog traffic with personalized sessions, write-heavy order activity, and deliberately uncacheable customer flows.

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

A store may show high origin TTFB, repeated `admin-ajax.php` or `?wc-ajax=` traffic, low page-cache HIT rates, or large product-page HTML and JavaScript payloads. Cart, checkout, and account requests can remain slow even when catalog pages are fast because those customer-specific pages must bypass a shared page cache.

If the store sets a WooCommerce session or cart cookie for every anonymous visitor and the cache bypasses on that cookie, shared page caching is defeated for every visitor, including people who never add a product.

High-Performance Order Storage (HPOS) moves orders out of the posts and postmeta model into dedicated WooCommerce order tables. If HPOS compatibility mode remains enabled, WooCommerce also synchronizes order data with the legacy posts tables. That synchronization is an ongoing write cost, not merely a migration step.

**A store has a fundamentally different cacheability profile from a content site. Advice written for a brochure site can cache private cart or account state, discard cart updates, or force every visitor to bypass cache. Do not apply it unchanged to a store.**

## Detect

### At tier 0 (public URL only)

Run the public stack detector and retain its evidence-bearing output:

```sh
python3 skills/wp-perf-audit/scripts/fingerprint.py https://example.com/ --pages 2 --json fingerprint.json --quiet
```

`profile.woocommerce.value: true` is supported by exact public evidence such as `woocommerce*` class tokens, a `/plugins/woocommerce/` asset path, or a `wc-ajax` endpoint reference. A false or `unknown` result from a small public crawl does not prove that no store exists; probe a known product URL or confirm at tier 1.

In browser Network evidence, check for:

- `?wc-ajax=get_refreshed_fragments`, commonly triggered to refresh a mini-cart;
- `/wp-admin/admin-ajax.php`; inspect the request method and `action` field instead of attributing every `admin-ajax.php` request to WooCommerce;
- cart and session cookies named `woocommerce_items_in_cart`, `woocommerce_cart_hash`, or `wp_woocommerce_session_*`;
- `data-product_variations` markup or `?wc-ajax=get_variation` requests on variation-heavy products;
- cache headers on a catalog page, cart, checkout, and account URL. Record the raw header and value, such as `cf-cache-status: HIT` or `x-cache: BYPASS`.

The cart, checkout, and account routes are functional roles, not reliable literal slugs: an operator can rename endpoints. At tier 0, treat their identity as `unknown` until navigation, form actions, or admin configuration settles it.

### At tier 1+ (admin / REST)

In WooCommerce settings and status tools, capture:

- whether HPOS is enabled;
- whether compatibility mode / legacy-table synchronization is enabled;
- whether synchronization has pending work before compatibility mode is changed;
- the configured cart, checkout, and account pages and endpoint slugs;
- active page-cache exclusions and cookie-bypass rules;
- scheduled actions whose failed or overdue rows correlate with slow order processing.

An active plugin list settles whether WooCommerce is installed; it does not prove WooCommerce caused a measured delay.

### At tier 2+ (WP-CLI / SSH)

Use exact option output to distinguish HPOS from compatibility mode:

```sh
wp option get woocommerce_custom_orders_table_enabled
wp option get woocommerce_custom_orders_table_data_sync_enabled
```

Record the literal output and the site URL against which WP-CLI ran. Do not infer a boolean from a missing option. Confirm the dedicated tables for that installation's database prefix and check WooCommerce's synchronization status before disabling compatibility mode.

For database query, autoload, object-cache, cron, and scheduled-action depth, use the [official WordPress agent skills](https://github.com/WordPress/agent-skills) `wp-performance` workflow rather than reproducing backend profiling here.

### By stack

| Stack | Signal | Confidence | Notes |
|---|---|---|---|
| `page-plugin` | The configured exclusions contain the actual cart, checkout, and account URLs, and session/cart cookies produce BYPASS rather than HIT | high | Match the detected `cache_layers[].value` before editing configuration. |
| `edge` | A personalized route returns an edge HIT or a shared cached response | high | The edge can be wrong even when the origin page cache is configured correctly. |
| `object` | Repeated catalog or variation lookups improve on a warm object cache while HTML remains uncached | medium | This correlates with query cost; tier-2 profiling must prove attribution. |

## Attribute

Separate mechanisms before recommending a change:

1. Compare a logged-out catalog URL with cart, checkout, and account URLs. A healthy shared page cache may HIT the catalog and deliberately BYPASS personalized routes.
2. Repeat an anonymous catalog request without cart cookies, then with the observed WooCommerce cookies. If every URL changes from HIT to BYPASS, the cookie-bypass scope is too broad or the test client is carrying a session.
3. In Network, block only the cart-fragments request for a controlled reload. Attribute its request bytes and server time only if the mini-cart still meets the site's requirements.
4. Compare a simple product with a variation-heavy product. Attribute variation cost only when the latter adds measurable HTML, JavaScript, requests, or origin time.
5. Correlate order-write latency with HPOS settings and synchronization activity. Compatibility mode existing is not proof of a meaningful bottleneck.

Disproof includes stable origin TTFB with and without the suspected request, a cache BYPASS limited to personalized routes, or a product payload whose variations add no measurable transferred bytes or work.

## Fix

### The change

Apply the smallest mechanism-specific change:

- Exclude the configured cart, checkout, account, order-pay, order-received, and other customer-specific endpoints from every shared page-cache layer. Include the relevant WooCommerce session/cart cookies in the bypass logic without bypassing anonymous catalog traffic.
- Remove or conditionally suppress cart-fragments refresh only when the mini-cart is absent or can update through the site's chosen cart interaction. Do not break add-to-cart state to save one request.
- Identify each `admin-ajax.php` action and change its caller, frequency, or cacheable data path; never block the endpoint globally.
- Keep HPOS enabled after a completed migration when compatible with the store's extensions. Once synchronization is complete and every required extension is HPOS-compatible, disable compatibility mode so orders are not written continually to both storage models.
- Reduce variation payloads by using the store's supported deferred variation lookup or by splitting an unusably large product model, while preserving purchasable combinations, pricing, stock, and accessibility.
- Optimize catalog filters and queries only after tier-2 evidence identifies the expensive query path.

### Host constraints

| Host class | Permitted | Path |
|---|---|---|
| `wpengine` | Use the existing host cache and its exclusion or support path; do not add a second page cache merely to express WooCommerce exclusions. | Confirm exclusions at both host and `edge` layers. |
| `kinsta` | Use the existing host cache and its exclusion or support path; avoid overlapping page-cache ownership. | Confirm exclusions at both host and `edge` layers. |
| `pantheon` | Preserve the platform cache integration and express personalized-route bypasses through its supported configuration. | Verify cookie and route behavior at `edge` and origin separately. |
| `wpcom` | Change only controls available to the site's plan and operating model. | Escalate unavailable cache or HPOS controls to platform support. |
| `wpvip` | Follow the platform's deployment and cache-review path. | Validate exclusions in a non-production environment, then deploy through the approved workflow. |
| `other` | The restriction is `unknown` until the host's current prohibited-plugin and cache policy is checked. | Record the policy source before changing cache ownership. |

### Risk

Incorrect cache exclusions can expose one customer's cart or account state to another, reject valid checkout changes, or erase useful cache coverage. Disabling HPOS compatibility mode before all extensions and integrations are ready can stop order consumers from seeing current data. Variation changes can make valid combinations impossible to buy. Customers and support staff notice first.

## Verify

Purge every affected layer in the detected `cache_layers` array, then warm and re-measure. A measurement immediately after purge is transient.

Verify separately that:

- anonymous catalog URLs return the intended cache status on repeated requests;
- cart, checkout, account, order-pay, and order-received routes never return another session's state;
- add-to-cart updates the mini-cart and persists through checkout;
- each remaining `admin-ajax.php` request has an identified action and expected frequency;
- order creation, payment, refund, email, fulfillment, and integrations work after any HPOS change;
- the legacy synchronization option is disabled only after synchronization is complete;
- simple and variation-heavy product pages retain correct price, stock, and purchasable combinations.

Use `perf-probe.py` before and after against the same warm public URL, repeats, and cache state; compare saved documents with `--diff A.json B.json`.

## Rollback

Before changing anything, export the WooCommerce settings/status evidence, cache configuration, relevant option values, and a list of affected URLs and integrations.

Rollback means restoring the previous cache exclusions and cookie rules, restoring the original cart-fragments or AJAX behavior, or re-enabling compatibility synchronization if an order consumer fails. Purge all affected cache layers after restoration and repeat the customer journey that exposed the regression.

## Gotchas

- A logged-in browser or a browser carrying `wp_woocommerce_session_*` can make a correctly cacheable catalog look globally uncacheable. Retest in a clean session.
- A page-cache HIT on checkout is a failure signal, not a performance win.
- HPOS enabled and HPOS compatibility mode enabled are different states. The latter keeps paying the legacy synchronization write cost.
- Cache exclusions at `page-plugin` do not automatically configure `edge`, and the reverse is also true.
- `admin-ajax.php` is a transport shared by many plugins and themes. Attribute the `action`, not the filename.
- Product count alone does not establish catalog query cost; filters, taxonomy joins, stock/meta lookups, and variations change the workload.
