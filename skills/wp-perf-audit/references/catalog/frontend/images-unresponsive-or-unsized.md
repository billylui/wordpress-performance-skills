<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Images unresponsive or unsized

Image markup makes the browser fetch an oversized or inappropriate source, reserves no stable
layout box, or deprioritizes an above-the-fold image that is likely to become LCP.

## Contents

- [Symptom](#symptom)
- [Detect](#detect)
- [Attribute](#attribute)
- [Fix](#fix)
- [Verify](#verify)
- [Rollback](#rollback)
- [Gotchas](#gotchas)

## Symptom

Mobile transfers remain image-heavy because `srcset` is missing, its candidates are wrong, or
`sizes` overstates the rendered slot. The browser downloads a full-size original into a small
card, or a photographic asset is stored as PNG when a photographic codec would be much smaller.
Images without intrinsic `width` and `height` contribute layout movement. An above-the-fold hero
starts late because it is marked `loading="lazy"` instead of being eagerly discoverable and, when
appropriate, carrying `fetchpriority="high"`.

The defects move different numbers: source and codec errors move transferred bytes and may move
LCP; missing dimensions move CLS; lazy loading the LCP image moves LCP. In an anonymized campaign
on a multilingual site on managed hosting, two photographic PNGs remained 2.8 MB each even though
test JPEG/WebP exports were about 250 KB. On another listing template, repairing one theme-side
thumbnail choke point reduced payload by 66%, which is the reusable lesson: find the function
that emits the markup rather than editing cards one by one.

## Detect

Use `fingerprint.py URL --pages N` to identify the builder and cache layers, then inspect the
rendered response in a browser. `perf-probe.py --site URL --repeats N --json PATH` provides a
public payload walk and `img_kb`, but browser evidence is required to know which `srcset` candidate
was actually selected and whether an image was LCP.

### At tier 0 (public URL only)

For each large image request, record these checkable signals from the live `<img>` or `<picture>`:

| Defect | Evidence | Disambiguating check |
|---|---|---|
| Missing responsive source | No `srcset`, or every candidate URL resolves to the same full-size file | Compare `currentSrc`, `naturalWidth`, and the element’s rendered `getBoundingClientRect().width` at mobile and desktop viewports. |
| Wrong `sizes` | The evaluated `sizes` slot is materially wider than the rendered CSS slot | Record the matched `sizes` condition, device-pixel ratio, selected `currentSrc`, candidate width descriptor, and rendered width. |
| Full original in a small slot | `currentSrc` is an original upload whose intrinsic width greatly exceeds the required CSS-pixel width × device-pixel ratio | Confirm the media URL and response bytes; filename alone is not sufficient because a CDN may transform it. |
| Wrong codec | A photographic image response has `Content-Type: image/png` and large transfer size | Visually inspect transparency needs and compare controlled JPEG/WebP exports at acceptable quality. Do not infer from extension alone. |
| Missing dimensions | The rendered `<img>` lacks usable `width` and `height`, and no CSS `aspect-ratio` reserves the correct box | In a Performance trace, link a Layout Shift entry to that image’s late size change. Missing attributes without a shift are a risk, not proven CLS attribution. |
| Lazy above the fold | The LCP event names the image and its markup has `loading="lazy"`, a placeholder `src`, or real URL only in `data-src` / `data-srcset` | Network Initiator and Priority show delayed discovery; forcing eager native markup advances request start. |
| Missing priority hint | The LCP `<img>` is early in HTML but begins at lower priority among competing images | Test `fetchpriority="high"` on that one image and verify request priority/start plus repeated LCP. Do not apply it to every image. |

Test the same URL at representative viewport widths and device-pixel ratios. The browser is
allowed to choose a candidate larger than the CSS slot; candidate spacing and pixel density make
an exact match uncommon. Report a defect only when markup gives the browser a meaningfully better
choice or declares the slot incorrectly.

### At tier 1+ (admin / REST)

Map `currentSrc` to its Media Library attachment. Record the original dimensions, generated
intermediate sizes, file type, and which builder/module/template setting selected “full” or a
named size. Confirm translated pages use the same attachment or repeat the mapping per language.

If the original upload is the only generated size, do not guess why. Check whether WordPress
reports an image-processing error and whether the intended registered size exists. A media
optimization plugin being active does not prove it generated or served the candidate.

### At tier 2+ (WP-CLI / SSH)

Use read-only commands to compare registered sizes and attachment metadata:

```text
wp media image-size
wp post meta get ATTACHMENT_ID _wp_attachment_metadata --format=json
```

The first output is a table of registered size names and dimensions. The second should contain
the attachment’s original `width`, `height`, `file`, and a `sizes` object of generated filenames
and dimensions. A missing expected entry is checkable evidence that the markup cannot select it.
Do not regenerate media during detection.

At tier 3, search the active theme/plugin for the exact wrapper class, template partial, or
function that emitted the defective tag. Record the file path and the call returning a raw URL
instead of responsive attachment markup. For deep backend image-processing, database, cron, or
PHP profiling, use the official
[`WordPress/agent-skills` wp-performance skill](https://github.com/WordPress/agent-skills)
rather than duplicating that workflow.

### By stack

Only list stack-specific ownership signals; the browser checks above apply to every row. The
identifiers match the `builder` vocabulary exactly.

| Stack | Signal | Confidence | Notes |
|---|---|---|---|
| `elementor` | The selected LCP/card node maps to an Elementor widget whose Image Size, lazy-load, or background setting emits the defective public markup | high | Record the widget ID and rendered tag; a page-level Elementor marker alone is insufficient. |
| `divi` | The selected image maps to the exact Divi module or background setting and its output supplies the observed `srcset`, `sizes`, loading, and priority attributes | high | Inspect module and template output at each responsive breakpoint. |
| `wpbakery` | The selected node maps to a WPBakery element or add-on wrapper that requests the full source or replaces native attachment markup | high | Record the element/add-on name and its rendered wrapper class. |
| `bricks` | The selected node maps to a Bricks image/background element and its size/loading controls produce the observed request | high | Confirm the element ID and `currentSrc`, especially when an image CDN rewrites URLs. |
| `beaver-builder` | The selected node maps to a Beaver Builder row, column, or module whose photo source and size controls emit the tag | high | Distinguish a module image from a theme-owned featured-image card. |
| `block-editor` | A core or plugin block emits the exact defective tag instead of native responsive attachment markup | medium | Record the block class and plugin asset path; the editor alone does not identify ownership. |
| `site-editor` | A template block or block-theme function emits the exact hero/card markup | high | One template-part fix may cover many routes; verify all assigned templates. |
| `classic-none` | A theme template or helper emits a raw attachment URL or hard-coded `<img>` at the defective node | high | Record the PHP file/function at tier 3; at tier 0, leave code ownership `unknown`. |

## Attribute

Separate the mechanisms so one image does not generate four unproven findings:

1. Save a baseline browser trace, Network log, CLS entries, LCP node, `currentSrc`, rendered size,
   and `perf-probe.py` JSON.
2. Override only `srcset`/`sizes` and confirm the browser selects a smaller adequate candidate.
3. Restore markup, then substitute only a controlled photographic export to measure codec impact.
4. Restore again, add only intrinsic dimensions/aspect ratio, and confirm the linked layout shift
   disappears.
5. For an image LCP, restore again, remove only lazy loading and add `fetchpriority="high"` only
   if the waterfall shows priority is limiting it; compare request start and repeated LCP.

Responsive-source attribution is disproved if `currentSrc` and transferred bytes do not change.
CLS attribution is disproved if no Layout Shift entry involves the image. Loading-priority
attribution is disproved if the image was already eagerly discovered at high priority or repeated
LCP does not move.

## Fix

### The change

Fix the narrowest shared markup emitter:

- Pass an attachment ID and an appropriate registered size through
  `wp_get_attachment_image()` so WordPress can emit `srcset`, `sizes`, intrinsic `width`/`height`,
  and loading attributes. Use `wp_get_attachment_image_attributes` or the responsive-image
  filters when a shared component needs a precise slot declaration.
- Generate candidates around real rendered slots and keep the original out of small cards.
- Write `sizes` from layout truth. `sizes="100vw"` is correct for a genuinely full-bleed banner;
  it is not automatically a bug. The browser can still conservatively choose a larger available
  candidate than the device strictly needs. In the measured layout where the post-767 px slot
  was explicitly 1920 CSS pixels, tightening the declaration to
  `sizes="(max-width: 767px) 100vw, 1920px"` recovered that difference. Do not transplant that
  value: when the slot follows the viewport until a 1920 px cap, declare that behavior, for
  example `sizes="(max-width: 1920px) 100vw, 1920px"`.
- Convert photographic PNGs that do not need PNG characteristics to a tested JPEG/WebP output.
  Preserve the original for rollback and visually compare quality, color, and transparency.
- Emit correct intrinsic `width` and `height` matching the source aspect ratio, or reserve that
  ratio in CSS when markup cannot carry dimensions.
- Make the actual above-the-fold LCP `<img>` eager and directly discoverable. Apply
  `fetchpriority="high"` to the single critical image when browser evidence supports it. Keep
  below-the-fold images lazy.

Repair a repeated card/listing defect in its one theme helper, block render callback, module
template, or attachment-attribute filter. Do not hand-edit every template instance when they all
call the same choke point.

### Host constraints

No host-specific restriction applies.

If a `cdn` such as `cloudflare`, `cloudflare-apo`, `bunny`, `fastly`, `akamai`, or
`aws-cloudfront` rewrites images, purge its `edge` cache as well as active `server` and
`page-plugin` layers reported by `fingerprint.py`. Do not install a cache or image-optimization
plugin solely to implement markup that WordPress can already emit.

### Risk

Wrong crops can remove focal content. Incorrect `sizes` can make desktop images soft or keep
mobile downloads large. Re-encoding can damage text, transparency, or color. Hard-coded
dimensions with the wrong aspect ratio can distort the image. Eager/high-priority hints applied
broadly compete with the real LCP resource. A shared choke-point change can affect archives,
languages, and components not represented by the first page; editors and visual QA notice crop
and quality regressions first.

## Verify

Purge relevant caches, warm every tested URL until visitor-facing cache status is stable, then
repeat browser measurements under the baseline viewport, device-pixel ratio, and throttling.
Verify:

- `currentSrc` is an adequate candidate close to the required rendered pixels at each viewport;
- Network transferred bytes fall and the response `Content-Type` matches the intended codec;
- `srcset` candidates all resolve and the evaluated `sizes` condition matches the actual slot;
- intrinsic dimensions or `aspect-ratio` reserve the correct box and linked CLS disappears;
- the image LCP is eagerly discovered, receives the intended priority, and repeated median LCP
  improves without starving other critical resources; and
- below-the-fold images remain lazy and do not enter the initial critical waterfall.

Run a matching `perf-probe.py --site URL --repeats N --json after.json`, then
`perf-probe.py --diff before.json after.json` to compare broad payload and TTFB. Treat `img_kb` as
a referenced-resource walk, not proof of the browser-selected candidate; the Network log is the
transfer authority. For a shared listing fix, sample every template family and verify the expected
payload reduction rather than assuming the first card represents all output.

## Rollback

Before editing, save the original attachment IDs/files, generated metadata, markup, template or
helper code, builder settings, crop/focal-point choices, and baseline browser/perf-probe artifacts.
Roll back by restoring the single shared emitter and original media references, purge the same
cache layers, warm the pages, and confirm the prior `currentSrc`, dimensions, and loading behavior
return.

Never delete original uploads until the new codec and crops have passed visual and multilingual
review. A source asset is the rollback artifact for future sizes and formats.

## Gotchas

- `sizes="100vw"` is correct for a genuinely full-bleed image. Call it wrong only when the
  declared slot differs from the measured layout or a more explicit breakpoint cap gives the
  browser a better truthful choice.
- Browsers may choose a candidate larger than the CSS slot because of device-pixel ratio and the
  candidates available. “Larger than viewport” is not sufficient evidence of a bug.
- `srcset` URLs may legitimately contain commas. A Cloudflare image-resizing candidate such as
  `/cdn-cgi/image/f=auto,w=1120/photo.webp 1120w` contains a comma inside the URL. A parser or
  regex that splits on every comma shatters it. The candidate URL runs to the next whitespace,
  not the next comma; `perf-probe.py` follows this rule.
- A CDN-rewritten URL can serve a transformed response even when its path resembles the original.
  Use `currentSrc`, response headers, intrinsic dimensions, and transferred bytes as evidence.
- Missing `width`/`height` does not prove CLS. Link the image to an actual Layout Shift entry, and
  recognize that correct CSS `aspect-ratio` may already reserve space.
- `fetchpriority="high"` is a hint, not a guarantee, and applying it to many images destroys its
  prioritization value.
- CSS background images do not use `<img srcset>` semantics. Fix their discovery and responsive
  selection in the owning CSS/template rather than adding irrelevant `<img>` attributes.
- One shared thumbnail function can dominate a whole listing payload. Search for the emitter
  before editing templates one by one.
