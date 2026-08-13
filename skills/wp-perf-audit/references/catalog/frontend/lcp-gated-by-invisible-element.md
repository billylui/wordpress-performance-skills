<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# LCP gated by an invisible element

The largest element starts at `opacity: 0` or `visibility: hidden` and becomes paintable only
after JavaScript and an animation delay, pinning LCP to that gate rather than to asset delivery.

## Contents

- [Symptom](#symptom)
- [Detect](#detect)
- [Attribute](#attribute)
- [Fix](#fix)
- [Verify](#verify)
- [Rollback](#rollback)
- [Gotchas](#gotchas)

## Symptom

The hero text or image appears late even though its HTML, fonts, and images arrived earlier. A
browser trace shows a long render delay after the LCP resource is available, followed by LCP at
the same moment a class or inline style changes. The delayed element begins with computed
`opacity: 0`, `visibility: hidden`, or an equivalent non-painted state.

This is a configuration defect, not an asset-size defect. The browser cannot record the hidden
element as a paint candidate, so compressing its image, preloading its font, or reducing its CSS
does not move the gate. In an anonymized campaign on a multilingual site on managed hosting,
removing the gate alone moved mobile LCP from 10.7 s to 3.5 s. One affected page still had 21
elements carrying the animation-hidden class, but only the LCP element needed immediate repair.

## Detect

Run `capabilities.py --target URL` first. If its `cannot_measure` list contains `Largest
Contentful Paint (LCP)`, report that LCP attribution is `unknown` until a browser-capable tool is
available. `fingerprint.py URL --pages N` can select the relevant builder row below; it does not
detect the visibility gate itself.

### At tier 0 (public URL only)

Use a browser Performance recording with a mobile viewport and cache disabled for diagnosis:

1. Select the LCP event and record its DOM node. Do not infer the node from visual size alone.
2. Inspect that node and every ancestor at navigation start. Record the class attribute and
   computed `opacity`, `visibility`, `display`, `animation-delay`, and `transition-delay`.
3. In the Elements panel, add a DOM attribute modification breakpoint to the hidden wrapper.
   Reload and record the script stack that removes the class or changes the style. Pausing alters
   timing, so use this only for source attribution, not the final LCP number.
4. In a second unpaused trace, compare the LCP timestamp with the class/style mutation and the
   animation start. A matching timestamp is checkable evidence of the gate.

View source as well as the live DOM. A class present in source but absent by the time DevTools is
opened is still relevant. Conversely, a token such as `animated` without a computed non-painted
state is not enough; report `unknown` and inspect the CSS rule that supplies the initial state.

### At tier 1+ (admin / REST)

Open the page or template in the detected builder and inspect the exact widget, module, or
wrapper selected by the LCP event. Record the animation name and configured delay. Check every
responsive breakpoint and language variant: an animation can be disabled on desktop but active
on mobile, or present only in a translated template.

Admin configuration raises confidence only when it maps to the same rendered DOM node. A page
setting named “hero animation” that emits no hidden state is not evidence of this defect.

### At tier 2+ (WP-CLI / SSH)

Use `wp post meta get POST_ID META_KEY` only after the builder has identified its storage key.
For example, an `elementor` page normally exposes its widget configuration through the
`_elementor_data` post meta value. The checkable output is serialized or JSON-like widget data
containing the selected element identifier plus its animation setting and delay. Do not edit the
value in place.

If the browser signal points to theme or plugin code instead, search the deployed CSS and
JavaScript for the exact class token and selector found in the DOM. The evidence is the file path,
the initial hidden declaration, and the code path that removes it. For deep database, cron,
object-cache, or PHP profiling, use the official
[`WordPress/agent-skills` wp-performance skill](https://github.com/WordPress/agent-skills)
rather than reproducing that backend workflow here.

### By stack

The identifiers in this table match the `builder` vocabulary exactly.

| Stack | Signal | Confidence | Notes |
|---|---|---|---|
| `elementor` | `.elementor-invisible` is on the LCP widget or an ancestor, its rule produces the initial non-painted state, and the class disappears when the entrance animation runs | high | Inspect the widget’s per-device Entrance Animation and delay; count all `.elementor-invisible` nodes to establish scope, but fix the LCP path first. |
| `divi` | The LCP module carries Divi animation tokens such as `.et_animated` / `et_pb_animation_*`, has a zero-opacity start, and becomes painted when the module animation begins | high | Confirm Design → Animation on that section, row, or module; a Divi class without the computed hidden state is only a hypothesis. |
| `wpbakery` | The LCP wrapper has `.wpb_animate_when_almost_visible` and later receives `.wpb_start_animation` while its computed opacity changes | high | Attribute the setting to the exact WPBakery element or animation wrapper, including any add-on wrapper. |
| `bricks` | A `brx-animate-*` class or Bricks interaction on the LCP wrapper supplies the initial hidden style and the interaction changes it | high | Inspect the rendered class and Interactions configuration; if only a generic custom class is present, trace its stylesheet before naming Bricks as the source. |
| `beaver-builder` | `.fl-animation` plus `data-animation-delay` / `data-animation-duration` is on the LCP row, column, or module and `.fl-animated` appears at reveal | high | The configured delay is explicit evidence; verify the wrapper is the LCP node or its ancestor. |
| `block-editor` | The LCP block is hidden by a plugin class, theme selector, or inline style and a script later changes that exact state | medium | The editor itself does not identify the animation source. Record the plugin asset path or theme file; otherwise source remains `unknown`. |
| `site-editor` | The LCP template block is hidden by a plugin class, theme selector, or inline style and a script later changes that exact state | medium | Inspect the template part as well as page content. Do not attribute a generic animation to the site editor without a namespaced asset or setting. |
| `classic-none` | An AOS, WOW.js, GSAP ScrollTrigger, or custom wrapper starts non-painted and is revealed by its corresponding class/style mutation | high | Check for tokens such as `data-aos`, `wow`, or the exact `.loaded` selector and record the responsible script path. A library name alone is insufficient. |

## Attribute

Prove that the visibility gate causes the number rather than merely co-occurs with it:

1. Save a baseline Performance trace and filmstrip under fixed mobile throttling.
2. With a local browser override, make only the recorded LCP node visible from the first frame;
   leave its assets, markup, and other animations unchanged.
3. Repeat several cold navigations and compare median LCP. Keep the trace showing the same LCP
   node now paints before the animation bundle or delay completes.
4. Restore the gate and confirm the late LCP returns.

The attribution is disproved if the element is visible before the first paint, the browser names
a different LCP node, or forcing it visible does not move repeated LCP measurements. In those
cases inspect [render-blocking CSS/JS](render-blocking-css-js.md), font rendering, or the actual
LCP image instead of reporting this defect.

## Fix

### The change

The clean fix is to set the LCP element’s entrance animation to none and emit it visible in the
initial HTML/CSS. Keep animations on non-LCP hero elements if they preserve the design. In the
anonymized campaign, four of six hero animations were deliberately retained; removing one gate
did not require flattening the whole page.

If the design owner will not remove the reveal, the commonly used workaround is:

```css
.lcp-reveal {
  opacity: 0.01;
}

.lcp-reveal.is-ready {
  opacity: 1;
}
```

Add `is-ready` from a synchronous inline script placed immediately after the element, scheduling
the change inside `requestAnimationFrame` rather than waiting for `DOMContentLoaded` or a
deferred builder bundle:

```html
<script>
requestAnimationFrame(function () {
  document.querySelector('.lcp-reveal')?.classList.add('is-ready');
});
</script>
```

This is a metric workaround: the element is technically painted at very low opacity before a
human can usefully see it. It must not be represented as equivalent to making meaningful content
visible. Do not use `visibility: hidden`, `display: none`, or exact `opacity: 0` in the workaround,
because those recreate the gate. Respect reduced-motion preferences and preserve readable
content when JavaScript fails. Simply not animating the LCP element is cleaner.

### Host constraints

No host prohibits this fix class itself. The host's normal constraints on the change mechanism
still apply — see `wp-perf-fix/references/host-constraints.md` before editing theme files,
builder templates or plugin settings, because the deploy path that owns production varies by
host and a later platform push can revert a direct edit.

Purge every active `edge`, `server`, and `page-plugin` cache layer reported by `fingerprint.py`
after the configuration or asset change. Do not install or replace a caching plugin as part of
this fix.

### Risk

Removing the animation can change the approved visual sequence. A low-opacity workaround can
produce a flash, reduce contrast for a frame, behave differently when JavaScript is blocked, or
conflict with the builder’s own classes. The design owner notices sequence changes first; users
on slow devices notice no-JavaScript and timing failures first. Limit overrides to the exact LCP
selector and test all languages and responsive breakpoints.

## Verify

After purging relevant caches, warm each tested URL and language until the visitor-facing cache
status is stable. Then record repeated browser runs under the same mobile profile used for the
baseline. A valid pass shows:

- the same intended LCP content is painted without waiting for the animation bundle or delay;
- median LCP improves and the improvement persists on warm comparable runs;
- the element is visible and readable with JavaScript disabled;
- remaining hero animations still run as designed;
- no new CLS or console error appears; and
- reduced-motion mode exposes the content immediately.

`perf-probe.py --site URL --repeats N --json PATH` can confirm that origin/edge TTFB and payload
did not silently change, but it does not measure LCP. Keep the browser trace as the primary proof.

## Rollback

Before editing, export the page/template or capture the exact animation name, delay, responsive
conditions, selector, stylesheet rule, and inline script. Roll back by restoring that saved
configuration or reverting the narrowly scoped CSS/script deployment, purge the same cache
layers, warm the page, and confirm the original class transition and visual sequence return.

Do not roll back by adding a new site-wide animation rule; that cannot reproduce per-widget
settings and may gate unrelated content.

## Gotchas

- A fast image and font do not help while their container remains non-painted. Configuration can
  dominate asset work.
- Very low non-zero opacity may make the element eligible for paint timing, but it is a metric
  workaround, not proof that a person saw usable content.
- Opening DevTools after load often misses the initial class. Preserve a navigation trace or use
  view source and a mutation breakpoint.
- A DOM breakpoint pauses JavaScript and changes timing. Use its stack for attribution only.
- An animation class on a descendant is irrelevant if an ancestor remains at `opacity: 0` or
  `visibility: hidden`; inspect the entire ancestor chain.
- Count all gated elements to understand scope, but do not turn a targeted LCP repair into an
  unnecessary removal of every page animation.
- Builder configuration can differ by device and translated template. A desktop-only check can
  falsely clear a mobile or language-specific gate.
