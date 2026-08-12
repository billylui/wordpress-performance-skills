<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Render-blocking CSS and JavaScript

Stylesheets and synchronous scripts in `<head>` delay first paint until CSS is ready and scripts have executed.

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

The page has usable HTML and an acceptable TTFB, but the browser shows a blank or partly unstyled
viewport while it downloads CSS or executes JavaScript from `<head>`. A browser trace shows a later
First Contentful Paint (FCP) or Largest Contentful Paint (LCP), with stylesheet requests or script
tasks on the critical path.

Do not report every stylesheet as a defect. CSS that is small, cached, and required for the initial
viewport may be the cheapest correct way to render the page. Likewise, a synchronous script is not
worth changing when a before/after trace shows no measurable paint delay. Payload size alone does
not establish render blocking.

## Detect

### At tier 0 (public URL only)

1. Run `fingerprint.py URL --json fingerprint.json` and use the exact `profile.builder`,
   `profile.theme_type`, `profile.host_class`, and `cache_layers` values to select the applicable
   stack row below. If a value is `unknown`, keep it `unknown` until the named follow-up check settles it.
2. In the response HTML, inventory every `<link rel="stylesheet" href="...">` in `<head>` and every
   external `<script src="...">` there that lacks `defer`, `async`, or `type="module"`. Record the
   element's `id`, URL, position, and attributes. A WordPress-generated `id` ending in `-css` or
   `-js` often exposes the registered handle, but confirm it against source or the runtime queue.
3. In a browser Network panel, reload with cache disabled and inspect the Initiator and Priority
   columns. In a performance trace, confirm that parsing or first paint waits for the request or its
   execution. A `<link>` with a non-matching `media` query, a disabled stylesheet, or a script already
   outside the critical path is not evidence of this defect.
4. Compare a page that uses the component with one that does not. The same builder or plugin asset on
   both pages is evidence of global enqueueing; a vendor path alone does not prove the asset is unused.

`perf-probe.py --site URL --json baseline.json` can quantify measured CSS and JavaScript transfer,
but it does not execute a browser or prove that a resource blocks paint. Treat `css_kb` and `js_kb`
as supporting evidence only.

### At tier 1+ (admin / REST)

Open the page in its actual editor and list the blocks, widgets, modules, template parts, popups, and
global headers or footers used on that route. Compare that inventory with the asset basename and the
DOM selectors found in its CSS. Inspect the builder's performance settings without changing them;
record each current value separately so a later one-toggle test has a reliable baseline.

The REST-rendered post body may omit a theme template, global builder template, shortcode expansion,
or dynamically injected asset. Absence from REST content therefore leaves attribution `unknown`;
the next check is the final HTML plus the active template or builder document.

### At tier 2+ (WP-CLI / SSH)

Use `wp post get POST_ID --field=post_content` to expose block comments, shortcodes, and builder markers.
The output is the raw content string; match a required component such as `<!-- wp:... -->`,
`[vc_...]`, or a builder-specific document reference to the handle under review.

Read the theme, child theme, and implicated plugin source for `wp_enqueue_style()`,
`wp_enqueue_script()`, `wp_register_style()`, and `wp_register_script()`. Record the exact handle,
dependencies, hook, and conditional around the call. Do not dequeue a handle solely because its
basename looks unrelated: dependencies and runtime-generated templates may still require it.

For database, query, autoload, object-cache, cron, and PHP profiling, use the official
[`wp-performance` skill](https://github.com/WordPress/agent-skills) rather than extending this
browser-visible diagnosis into backend profiling.

### By stack

Identifiers in this table are the closed `builder` vocabulary returned by `fingerprint.py`.

| Stack | Signal | Confidence | What conditional loading offers |
|---|---|---|---|
| `classic-none` | A theme stylesheet such as `/wp-content/themes/THEME/style.css` and theme scripts appear on every route; source shows unconditional enqueueing | high | The theme author can register once and enqueue only inside route, template, shortcode, or rendered-component conditions. Move independent scripts to the footer or give them a safe loading strategy. |
| `block-editor` | HTML contains `wp-block-*` classes and only the style handles for rendered blocks; `profile.theme_type` may still be `classic` or `hybrid` | medium | Confirm `theme_type` before applying a theme-specific path. When WordPress's block-asset-on-demand decision is true, registered block styles load when their block renders. |
| `site-editor` | A `wp-site-blocks` wrapper or `wp-container-*` layout classes accompany per-block or inline global styles, and the active theme is a block theme | high | A block theme with no custom external stylesheet can have essentially no external render-blocking CSS: `theme.json` global rules and rendered block styles may be inline. The proof is the absence of blocking `<link>` elements, not the theme label. |
| `elementor` | Base Elementor assets occur on a page with no corresponding Elementor widget, while widget-specific selectors or handlers are absent from the DOM | medium | A global template can disprove the finding. Elementor provides improved asset loading for native widget handlers and selected libraries; third-party add-ons may still enqueue globally. |
| `divi` | `/themes/Divi/` or builder asset paths and `et_*` markup map to a global stylesheet or script on a route without the relevant module | medium | Check the active template. Divi exposes separate dynamic CSS, dynamic JavaScript library, critical CSS, and stylesheet options; test one at a time. |
| `wpbakery` | `vc_*` or `wpb_*` assets occur without matching shortcode output; theme integration source enqueues them on every front-end request | high | WPBakery's asset API supports enqueueing from an element only when that element is used. There is no safe assumption that a theme-bundled integration follows it. |
| `bricks` | `bricks-frontend` and `bricks-scripts` are documented base handles; an additional library appears without a matching element | medium | The base-handle identity is high-confidence, but component need still requires DOM mapping. Bricks conditionally loads many additional libraries and offers a lighter generated-CSS path. |

The WordPress mechanism is checkable in
[`wp_should_load_block_assets_on_demand()`](https://developer.wordpress.org/reference/functions/wp_should_load_block_assets_on_demand/).
Builder mechanisms are documented by
[`elementor`](https://elementor.com/help/optimized-assets-loading/),
[`divi`](https://help.elegantthemes.com/en/articles/5502417-divi-dynamic-css-frontend-performance-feature),
[`wpbakery`](https://kb.wpbakery.com/docs/developers-how-tos/asset-management/), and
[`bricks`](https://academy.bricksbuilder.io/developer/guides/asset-loading/). Documentation describes
capability, not the site's active setting; the emitted handles remain the evidence.

## Attribute

Attribute the delay only when a browser waterfall or trace places the resource before FCP or LCP and
shows the browser waiting for its transfer, CSS processing, or script execution. Then run a controlled
comparison that changes only that handle or one builder setting.

Attribution is disproved when any of the following is true:

- the resource finishes well before the paint bottleneck;
- the stylesheet is required for above-the-fold layout and replacing it with critical CSS leaves the
  same FCP or LCP;
- the script is already deferred or executes after the relevant paint;
- the apparent unused builder asset belongs to a global header, footer, popup, or responsive state;
- TTFB, the LCP resource itself, font discovery, or a visibility gate remains the longer critical path.

Record “cleanup, not a performance fix” when the controlled comparison removes bytes or requests but
does not materially move the paint trace.

## Fix

### The change

Prefer the smallest change in this order:

1. Stop enqueueing a handle on routes where its component cannot render. Keep registration and
   dependency metadata intact; put the condition around enqueueing.
2. For a required independent script, use WordPress's supported `defer` or `async` strategy through
   `wp_enqueue_script()`. Use `defer` when execution order or the parsed DOM matters. Use `async` only
   when the script is independent because asynchronous scripts do not preserve document order.
   WordPress evaluates the dependency tree and may choose a safer eligible strategy.
3. For required CSS, inline only the rules needed to paint the initial viewport and load the remaining
   stylesheet outside the critical path. Generate critical CSS per materially different template and
   responsive layout; one homepage fragment is not universal critical CSS.
4. Use the builder's native conditional or generated-asset mode when it covers the observed handle.
   For third-party widgets or a theme-bundled builder, fix the integration's enqueue condition.

Do not enable minification, combination, delay-JavaScript, remove-unused-CSS, and critical-CSS toggles
as a batch. Aggressive CSS/JS optimization toggles in a `page-plugin` cache layer frequently break builder layouts by changing execution order or removing required rules. Measure and visually inspect
after each toggle individually.

### Host constraints

| Host class | Permitted | Path |
|---|---|---|
| `wpengine` | Theme or builder enqueue changes are permitted through the site's normal deployment path; do not introduce a page-caching plugin for this fix | Use source conditions or existing builder controls. Confirm platform policy before changing the `page-plugin` cache layer. |
| `unknown` | Unknown until the host is identified | Make only the scoped theme/builder change; check host policy before adding or replacing any caching plugin. |
| `other` | Scoped theme/builder changes are normally independent of hosting | Use the existing deployment and cache-purge path. A new caching plugin is not required for this mechanism. |

### Risk

Deferring a dependency can make its consumer run first. `async` can reorder scripts. Incorrect critical
CSS produces a flash of unstyled content, breakpoint-specific layout shifts, or missing hover, menu,
popup, and logged-in states. Conditional dequeueing can break a global template that is not visible in
post content. Builder-generated CSS may become stale until its documented regeneration step and all
applicable caches are cleared.

The first observers are usually visual-regression checks at mobile breakpoints, navigation and form
tests, browser console errors, and editors viewing a page whose generated CSS was not refreshed.

## Verify

Capture a before and after browser waterfall and performance trace with the same device, viewport,
network, URL, consent state, and logged-out state. Confirm all of the following:

- the targeted handle is absent where unused, or no longer blocks the relevant paint where required;
- dependency order is intact and the console has no new errors;
- FCP or LCP improves in the trace, not merely a synthetic audit opportunity score;
- desktop and mobile layouts, menus, forms, popups, sliders, and global templates still work;
- a page that genuinely uses the component still receives the asset.

Purge the changed builder-generated assets and every applicable `page-plugin`, `server`, and `edge`
cache layer. Then warm the URL before comparing it. A reading immediately after purge is transient.
Use `perf-probe.py --diff baseline.json after.json` only as supporting transfer evidence; it does not
replace the browser trace.

If bytes fall but paint timing does not, retain the change only if the maintenance and regression risk
are justified, and label it cleanup rather than a performance fix.

## Rollback

Before changing anything, export or screenshot every relevant builder and caching setting and save the
exact original enqueue code plus the list of emitted handles for representative pages.

Rollback means restoring that code or each setting individually, regenerating the builder's CSS/data if
the changed mode requires it, purging the same cache layers, warming the affected URLs, and confirming
the original handles and layout have returned. Do not “rollback” by enabling a different optimization
bundle; that creates a second uncontrolled experiment.

## Gotchas

- A stylesheet is render-blocking by default only in a matching rendering context. `media="print"` is
  not equivalent to a normal screen stylesheet.
- `defer` and `async` solve execution scheduling, not long execution. A deferred script can still harm
  interactivity; see [INP and main-thread work](inp-and-main-thread.md).
- Inline CSS removes a request but enlarges HTML and cannot be cached independently. It is beneficial
  only when the inlined rules are genuinely critical and small.
- A block-theme label does not prove a zero-CSS page. Plugin blocks, classic compatibility styles,
  custom stylesheets, and third-party widgets can all add blocking CSS.
- A builder page that appears to use none of the builder may inherit a builder-made header, footer,
  popup, or archive template. Check the final DOM and template assignment before dequeueing.
- Combining files can increase the critical payload on pages that previously needed only one small
  handle. Request count is not the goal; paint timing is.
