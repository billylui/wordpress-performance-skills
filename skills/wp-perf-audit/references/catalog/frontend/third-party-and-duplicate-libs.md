<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Third-party scripts and duplicate libraries

Duplicate libraries and third-party tags add transfers, connections, parsing, and execution that may not contribute to the page's primary task.

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

The Network panel shows the same library more than once, or it shows marketing, analytics, video,
map, social, chat, review, and advertising origins transferring and executing before their feature is
used. Common evidence includes WordPress's bundled jQuery plus a CDN copy of a different jQuery
version, literal mid-body `<script>` tags in a theme template, and an iframe that pulls a large player
runtime merely to display a play button.

The cost can move transferred bytes, request count, connection setup, Total Blocking Time (TBT), and
Interaction to Next Paint (INP). It can also move nothing measurable. In an anonymized production
campaign, duplicate jQuery plus two CDN-hosted libraries totaled roughly 60 KB and two extra connection handshakes on a site whose TBT was already near zero. The finding was recorded as **cleanup, not a performance fix**. Making it a headline issue would teach the wrong priority.

## Detect

### At tier 0 (public URL only)

1. Run `fingerprint.py URL --json fingerprint.json` and record the exact `profile.builder`,
   `profile.theme_type`, `profile.cdn`, and `cache_layers` values. A site CDN and a third-party library
   CDN are different roles; do not rewrite the stack `cdn` signal because an external script URL exists.
2. Save the final HTML and inventory every external `<script src>`, iframe, and stylesheet by full URL,
   DOM position, element `id`, attributes, and surrounding markup. Specifically record literal script
   tags between body content nodes: their position and missing WordPress handle are checkable evidence
   of template injection.
3. In a clean browser Network panel, reload with cache disabled and group by domain and Initiator. Tag
   each request as parser-discovered, WordPress-enqueued, tag-manager-injected, iframe descendant, or
   script-injected. A hostname alone does not identify which plugin or owner added it.
4. Detect duplicate jQuery from two separate response URLs or bodies: a WordPress path such as
   `/wp-includes/js/jquery/jquery.min.js` plus another file whose header/source identifies jQuery. A
   final `window.jQuery.fn.jquery` value proves only which version currently owns the global; it does
   not prove that only one version loaded.
5. Record transferred bytes, connection timing, parse/compile tasks, long tasks, and whether the feature
   was visible or used. For a tag-manager child request, keep the parent initiator chain as evidence.
6. For embeds, measure the page before interaction. A video iframe can pull several hundred KB of
   JavaScript simply to render a branded play button. The exact Network request list and transferred
   total—not the reputation of the provider—establish the cost.

Run `perf-probe.py --site URL --json baseline.json` for a static payload walk. It prefers `HEAD` sizing
and falls back to a compressed `GET`. A third-party asset may reject both requests from a non-browser
client, sometimes with HTTP 400, even though a browser can load it. In that case the resource appears in
`unsized_resources` and the per-URL `errors`; the measured total is a floor.

### At tier 1+ (admin / REST)

Inventory active analytics, tag-manager, consent, chat, embed, social, map, review, advertising, and
builder integrations. Record which plugin, theme panel, builder widget, or tag container owns each
measured URL. A tag configured in both a plugin and a tag manager is a checkable duplicate injection
path even when its child request URLs differ.

Inspect the affected page plus global headers, footers, popups, templates, reusable blocks, and custom
HTML widgets. REST content can expose literal tags in post content but may omit theme templates and
scripts injected during rendering. When ownership remains ambiguous, report `unknown`; the next check
is the final DOM's initiator chain plus source inspection.

### At tier 2+ (WP-CLI / SSH)

Run:

```bash
wp plugin list --status=active --fields=name,status --format=table
wp theme list --status=active --fields=name,status --format=table
```

The output tables identify active slugs. They narrow the source search but do not prove front-end
injection. Read the active theme, child theme, and implicated plugins for literal `<script>`, `<iframe>`,
`wp_enqueue_script()`, `wp_register_script()`, `wp_head`, and `wp_footer` output. Record the exact file,
hook or template location, handle, URL, and condition.

For jQuery, trace dependencies before changing anything. WordPress handles can cause the bundled copy
to be legitimately enqueued even when a template separately emits a CDN copy. The defect is the second
injection path; deregistering the dependency that plugins expect is usually the riskier fix.

For database, autoload, object-cache, cron, and PHP attribution, use the official
[`wp-performance` skill](https://github.com/WordPress/agent-skills) rather than expanding a browser asset
finding into backend profiling.

### By stack

Identifiers in this table are the closed `builder` vocabulary.

| Stack | Signal | Confidence | Notes |
|---|---|---|---|
| `classic-none` | Source confirms that a literal third-party tag sits in `header.php`, `footer.php`, or another active template, or that a theme handle owns it | high | Replace literal library tags with WordPress registration/enqueueing so dependency and route conditions are explicit. |
| `block-editor` | A Custom HTML or embed block in raw post content maps to the final request and its initiator | high | Reusable patterns and plugin blocks can inject the same provider elsewhere; check duplicate ownership. |
| `site-editor` | An assigned template part or navigation/footer pattern supplies the tag across routes and the final DOM contains it | high | Removing it from page content will not remove the template-part copy. |
| `elementor` | An HTML widget, embed widget, global template, or add-on creates the request; Elementor DOM and initiator agree | high | Native conditional assets do not govern arbitrary code pasted into HTML widgets or third-party add-ons. |
| `divi` | A Code module, integration field, global module, or theme option supplies the tag | high | Check both module content and theme integration settings before deciding there is one owner. |
| `wpbakery` | Source confirms that a Raw HTML/JS element, shortcode template, or bundled-theme template emits the tag | high | Mid-body literal tags are common in custom shortcode templates and bypass WordPress dependency handling. |
| `bricks` | A Code element, embed, global component, or third-party Bricks element owns the request | high | Separate Bricks' expected base handles from external libraries added by the element. |

## Attribute

Attribute a performance defect only when the duplicate or third-party resource occupies a measured
bottleneck:

- its transfer or connection setup delays an LCP or other critical request on the constrained network;
- its execution creates long tasks or blocks the named interaction;
- the embed's descendants materially increase initial transfer before the user expresses intent;
- removing only one duplicate injection path preserves behavior and improves the target trace.

Disprove attribution when the resource starts after the relevant paint, executes without meaningful
main-thread blocking, or disappears without moving the target metric. Also disprove it when a supposed
duplicate is actually two different modules with distinct consumers, or when an iframe is already
facaded and loads only after activation.

If TBT is near zero and the measured cost is roughly tens of kilobytes plus a small number of
connections, label the work cleanup unless a constrained-network trace shows a user-visible delay.
Security, privacy, consent, resilience, or maintainability can still justify removal, but those are
different findings.

## Fix

### The change

Use the smallest fix for the proven mechanism:

1. For duplicate jQuery, remove the literal or separately registered CDN copy and keep WordPress's
   dependency-managed handle when active plugins depend on it. If a tested application truly requires
   isolation, use an explicit no-conflict design rather than allowing two versions to race for globals.
2. Replace mid-body literal library tags with one `wp_register_script()` definition and conditional
   `wp_enqueue_script()` calls. Declare dependencies and a safe loading strategy. Enqueue only on routes
   or components that use the library.
3. Remove duplicate marketing/analytics ownership. Choose one injection path—plugin, theme integration,
   or tag manager—and confirm consent and event coverage before disabling the others.
4. Delay chat, maps, social widgets, and other optional third parties until consent, intent, or proximity
   to the viewport, provided the first interaction does not inherit all initialization work.
5. Replace a heavy embed with a facade: render a local static thumbnail and accessible play/open button,
   then create the real iframe only on click or another explicit activation. Preserve the title,
   accessible name, keyboard behavior, focus transition, consent behavior, and a usable fallback.
6. Self-host a library only when licensing, update ownership, cache behavior, security response, and
   functional testing are all understood. Self-hosting changes the connection path; it does not remove
   parse or execution cost.

### Host constraints

No host-specific restriction applies.

The change may live outside WordPress when a tag-manager or vendor account owns it. That is an access
constraint, not a hosting restriction. If cache or script-optimization settings are also changed, check
the identified `host_class` policy before modifying the `page-plugin` layer.

### Risk

Removing one jQuery copy can reveal code written for the removed version or code that relied on the
second copy resetting `$`. Tag consolidation can drop conversions, consent state, ecommerce events, or
debugging signals. A facade can break deep links, captions, fullscreen, provider cookies, or keyboard
focus. Delayed chat can violate support expectations. Self-hosted libraries can become stale.

The first observers are browser console monitoring, analytics/tag debuggers, consent tests, conversion
and form monitoring, iframe accessibility checks, and owners of the third-party service.

## Verify

Purge applicable `page-plugin`, `server`, and `edge` cache layers, then warm the URL. Use the same
consent state, viewport, account state, browser profile, and network profile for before/after tests.

Verify all of the following:

- the Network panel shows one intended library copy and the removed URL is absent;
- no second plugin, template, tag container, or iframe reinjects it later;
- console, menu, form, cart, gallery, and builder interactions have no regression;
- analytics and marketing events fire exactly once under each required consent state;
- a facade transfers only its thumbnail and local behavior before activation, then loads the iframe and
  transfers provider assets after activation;
- TBT, interaction traces, LCP, and transferred bytes are reported separately so cleanup is not promoted
  to a performance win without evidence;
- `unsized_resources` is zero or every unmeasured URL remains explicitly listed. Never compare an
  unmeasured resource as though it weighed zero.

Use `perf-probe.py --diff baseline.json after.json` for the static payload comparison and a real browser
trace for execution and iframe descendants. If the only outcome is roughly 60 KB and two connections
removed from an already near-zero-TBT page, report the result as cleanup.

## Rollback

Before changing anything, save the original theme or plugin source, tag-manager/container export,
builder template export, script handles and dependency order, consent configuration, and a network log
of expected requests and events.

Rollback means restoring the removed injection path or embed, restoring the original tag/container
revision and consent rules, purging and warming the same caches, and confirming the original URLs and
events return exactly once. Restore one path—not every historical duplicate—unless the captured baseline
proves that duplication was required.

## Gotchas

- A third-party asset can refuse both `HEAD` and `GET` from a non-browser client, including with HTTP
  400. Report it as unmeasured, not zero. A resource that could not be measured is not weightless.
- `window.jQuery.fn.jquery` shows the surviving global version, not the number of jQuery files that
  downloaded or executed.
- Tag managers and consent tools inject descendants after initial HTML parse. Saved source alone is an
  incomplete inventory; use the final Network initiator chain.
- An iframe has its own request tree. Counting only the iframe HTML request can miss most of the embed.
- DNS-prefetch or preconnect can reduce connection latency but may contact a third party before consent.
  Treat privacy behavior and performance behavior separately.
- Removing a CDN copy can increase same-origin bytes while still removing a connection handshake. Judge
  the measured critical path, not one isolated counter.
- A facade improves initial load only if the real iframe URL is absent until activation. A hidden or
  transparent iframe behind the thumbnail is not a facade.
- Duplicate libraries are often maintainability or security cleanup. Say so plainly when the user-facing
  metric does not move.
