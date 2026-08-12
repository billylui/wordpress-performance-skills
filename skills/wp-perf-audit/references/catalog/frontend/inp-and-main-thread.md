<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# INP and main-thread work

Long tasks, hydration, and expensive event handlers keep the main thread from presenting the next paint after a real user interaction.

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

A menu, filter, accordion, form, cart control, search overlay, or editor-built interaction responds
late even though the pointer or key event arrived. Field data reports poor Interaction to Next Paint
(INP), or an interaction trace shows a long delay before the next frame.

Builder-heavy and plugin-heavy pages are exposed because each feature can register handlers, observe
the DOM, hydrate a front-end component, or execute a large bundle on the same main thread. A
feature-rich multipurpose theme with a bundled builder can add a very large JavaScript bundle to every
page, including routes that use little of the builder. That is a hypothesis until the request initiator,
execution tasks, and emitted handles tie the bundle to the interaction delay.

Do not inflate script weight into an interactivity finding. A site can have a poor Speed Index or heavy
total JavaScript and still show near-zero Total Blocking Time (TBT). If comparable lab runs show TBT of
0–31 ms and the interaction trace contains no blocking task, reducing script bytes is **cleanup, not a performance fix**.

## Detect

### At tier 0 (public URL only)

Start with `capabilities.py --target URL --json capabilities.json`. If neither an interactive browser
path nor field data is available, state that INP cannot be measured in this session. Do not turn an
absent measurement into a zero.

INP requires a real interaction. A passive lab navigation produces LCP, CLS, and loading diagnostics,
but it does not produce INP in the way it produces LCP. A site below the traffic threshold for the field-data source has no INP data available; report “field INP unavailable” and reason from TBT plus
long-task interaction traces instead.

With a real browser:

1. Run `fingerprint.py URL --json fingerprint.json` and record the exact `profile.builder`,
   `profile.theme_type`, and `theme_slug` signals. A `theme_slug` is evidence only when its asset path
   appears in the measured trace.
2. Record a performance trace while carrying out a named, repeatable interaction: for example, open
   the mobile menu, select a product filter, submit a valid form, or advance a builder slider. Mark the
   input event and the first paint that presents its result.
3. Break the interval into input delay, event-handler processing, and presentation delay. Record the
   exact long task, script URL, function name when available, and initiator. A task longer than 50 ms is
   a useful long-task signal; the portion beyond 50 ms contributes to lab TBT only inside that metric's
   measurement window.
4. Inspect Event Listeners, the call tree, bottom-up view, and main-thread flame chart. Evidence is a
   handler or task attributable to a URL and call frame, not “the page feels slow.”
5. Check whether a hydration or mount task scans or recreates a large DOM subtree before the control is
   usable. Record the root node, script, task duration, and mutations. Do not call ordinary WordPress
   markup “hydration” without a client-side framework attaching behavior to server-rendered output.

Use the trace-based workflow in
[`../../references/chrome-devtools-mcp.md`](../../chrome-devtools-mcp.md). `perf-probe.py` measures TTFB and
statically discovered payload; it does not execute handlers and does not report INP or TBT.

### At tier 1+ (admin / REST)

Inventory active builder features, front-end plugins, tag integrations, template-wide effects, and
the exact widgets on the affected route. Check global headers, footers, popups, product templates, and
consent tools, because they can register handlers without appearing in the post body.

Compare a minimal route with the affected route under the same theme. A bundle common to both routes
is evidence of global loading, but not yet of delay. Match its executed functions to the traced
interaction. Admin screens and REST content can identify configuration; only final front-end execution
establishes main-thread cost.

### At tier 2+ (WP-CLI / SSH)

Use `wp plugin list --status=active --fields=name,status --format=table` and `wp theme list
--status=active --fields=name,status --format=table`. The evidence is a table whose rows identify the
active plugin and theme slugs; it does not prove that their JavaScript executes on the affected page.

Read registrations and enqueue calls for the traced handle. Record its dependency chain, whether it is
global, and the route or component condition. Search the implicated source for the traced event name,
listener, hydration root, timer, observer, or DOM scan. A minified call frame may remain `unknown`; the
next check is the matching source map or an unminified staging build with the same behavior.

Deep PHP, database, autoload, object-cache, cron, and server-side profiling belongs to the official
[`wp-performance` skill](https://github.com/WordPress/agent-skills). Use it when the interaction calls a
slow server endpoint; do not infer backend cause from a browser wait alone.

### By stack

Identifiers in this table are the closed `builder` vocabulary.

| Stack | Signal | Confidence | Notes |
|---|---|---|---|
| `classic-none` | A theme or plugin handle owns the traced listener or long task; source shows it enqueued on the affected route | high | Conditional enqueueing and handler-level work reduction are usually clearer than introducing a general “delay JS” layer. |
| `block-editor` | A front-end interactive block mounts or hydrates from a `wp-block-*` root and its bundle owns the task; call frames and root agree | high | Static blocks do not need hydration. Attribute only the interactive block or plugin that attaches client-side behavior. |
| `site-editor` | The handler originates in an assigned reusable template part, navigation block, or interactive block present across templates | high | Fix and verify every template reusing the part; the page's post content may not contain it. |
| `elementor` | An Elementor or add-on handler appears in the interaction call tree, with matching widget markup | high | Base runtime presence is not enough. Separate native widget handlers from third-party add-on bundles and test the affected widget state. |
| `divi` | A Divi module, motion effect, sticky behavior, or theme bundle owns the long task; module markup and call frames agree | high | Compare dynamic-library settings one at a time; a bundled theme script can be large without blocking the tested interaction. |
| `wpbakery` | Source confirms that a theme-bundled WPBakery element or its add-on owns the handler; the same bundle appears on pages without the shortcode | high | Theme integrations often matter more than the builder label. Condition the actual handle, not every `vc_*` asset. |
| `bricks` | `bricks-scripts` or an element-specific library owns the listener or task and a matching `brxe-*` element exists | high | The base script is expected. Attribute additional work to the exact element or library before changing asset loading. |

## Attribute

INP field data and lab TBT answer different questions:

- INP observes responsiveness to real interactions over page visits. It includes input delay,
  processing, and the delay until the next paint.
- TBT is a navigation-lab diagnostic. It sums the blocking portions of long main-thread tasks within
  its measurement window, whether or not a user interacted.
- High TBT can warn that the main thread is often unavailable and therefore raises INP risk. It cannot
  predict which field interaction is slow.
- Low TBT does not disprove a poor handler that runs only after a click, because a passive navigation
  may never trigger it.

Attribute a defect only when the named interaction repeatedly overlaps a specific handler, long task,
or presentation bottleneck and a controlled removal or reduction shortens that interval. Keep network
wait and main-thread work separate: an event can wait on an API response without consuming CPU.

Attribution is disproved when the trace shows the main thread idle during the delay, the slow work
belongs to a different interaction, or removing the suspected bundle does not change the interaction.
It is also disproved when TBT is 0–31 ms, no interaction trace shows blocking, and the only evidence is
large `js_kb`. Record that as cleanup.

## Fix

### The change

Make the smallest change that shortens the attributed interaction interval:

1. Stop loading a feature's handle on routes where the feature cannot render. Preserve dependencies and
   test global templates before dequeueing.
2. Split a large synchronous handler into bounded work. Perform the visual state change first, then
   schedule non-visible bookkeeping after the next paint or in small tasks. Avoid replacing one long
   task with a chain that still blocks every frame.
3. Reduce DOM queries, layout reads/writes, serialization, and repeated listener registration inside
   the traced handler. Delegate repeated-item events where appropriate and remove duplicate listeners.
4. Hydrate only the interactive island that needs behavior. Do not mount a client framework over an
   entire builder-rendered page when a menu, filter, or form is the only interactive component.
5. Lazy-initialize below-the-fold sliders, maps, galleries, and embeds near visibility or on intent.
   Keep the first interaction usable: moving all initialization onto the first click can worsen INP.
6. If a third-party handler is responsible, use its consent, facade, or delayed-init path, or remove it
   from routes where it has no purpose. See
   [third-party and duplicate libraries](third-party-and-duplicate-libs.md).

Do not apply a blanket script-delay setting as the first fix. It can postpone menus, consent, analytics,
forms, builder layout, and accessibility behavior to the first interaction—the exact moment INP is
measured.

### Host constraints

No host-specific restriction applies.

If the change is delivered through a caching or script-optimization plugin, first check the identified
`host_class` policy and the existing `page-plugin` layer. The mechanism does not require installing a
new caching plugin.

### Risk

Work splitting can expose intermediate state, reorder side effects, or cause duplicate requests.
Conditional loading can omit code from a global template. Lazy initialization can make the first click
do more work, create focus-management failures, or leave keyboard users with an inert control.
Changing a theme-bundled builder file can be overwritten by an update; use a supported child-theme,
plugin, or deployment override.

The first observers are interaction traces, keyboard and screen-reader tests, form/cart monitoring,
console errors, and real-user error telemetry.

## Verify

Purge applicable `page-plugin`, `server`, and `edge` cache layers, then warm the URL before measuring.
Use the same device profile, viewport, account/consent state, data, and exact interaction sequence.

Verify all of the following:

- the attributed handler or long task is shorter or absent in the new trace;
- the next paint occurs sooner after the same input;
- no equivalent work moved onto the first interaction or a later frame;
- lab TBT does not regress across comparable navigation runs;
- menus, forms, filters, carts, popups, focus order, keyboard activation, and responsive states still
  work;
- routes that need the conditionally loaded feature still receive it.

Field INP cannot validate instantly: field datasets require real eligible visits and may be unavailable
for low-traffic sites. Report the immediate trace and TBT evidence separately from later field data.
If TBT remains 0–31 ms and interaction traces were already clean, call any byte reduction cleanup, not
a performance fix.

## Rollback

Before changing code or settings, save the original handles, dependency order, builder or optimizer
settings, source artifact, and a trace of the named interaction.

Rollback means restoring the original enqueue condition and handler or hydration behavior, restoring
each setting individually, rebuilding generated assets if applicable, purging and warming the same
cache layers, then replaying the exact interaction. Confirm that both functionality and the original
trace shape return; do not mask a failed rollback with a different script-delay rule.

## Gotchas

- A Lighthouse-style navigation does not manufacture INP without interaction. TBT is a diagnostic, not
  a synthetic INP value.
- “Not enough field data” means unavailable, not good and not zero.
- Near-zero navigation TBT can coexist with a slow click handler that the navigation never exercised.
- Heavy JavaScript can hurt transfer or Speed Index while leaving main-thread blocking negligible.
  Optimize the metric and user journey the evidence identifies.
- A long task immediately after a click may belong to a browser extension or development tool. Confirm
  the script URL and repeat in a clean profile.
- Delaying every script until interaction can make that first interaction dramatically worse.
- A minified filename or builder namespace is attribution evidence only when the call tree and DOM
  component agree. Otherwise the owner remains `unknown`.
- Warm-cache verification still matters: cache misses can change script arrival and task ordering even
  when the JavaScript itself is unchanged.
