<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Hero media on the critical path

A large hero image or autoplaying background video competes with the LCP element for bandwidth and decode time during the critical load.

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

Mobile LCP is slow while a hero video, hero background, or oversized first-slide image starts early.
The Network panel shows that media transferring beside the LCP resource, and the performance trace
shows image decode, video demux/decode, or a late first video frame on the critical path.

Total page bytes can be misleading. On an anonymized production campaign, deferring a hero video's
start moved mobile LCP from 10.7 s to 3.5 s while total page bytes fell by only about 5%. The gain was
**when it loaded, not how much it weighed**.

Do not flag a media library by its stored size. A gallery containing about 225 MB of raw `.mov` files transferred only about 144 KB initially with `preload="metadata"`. It imposed a bandwidth cost on
viewers who chose to play the files, but it was not an initial-load problem. Measure transferred bytes
and request timing before calling large media a page-load defect.

## Detect

### At tier 0 (public URL only)

1. Run `fingerprint.py URL --json fingerprint.json`. Use the exact `profile.builder`,
   `profile.theme_type`, `profile.cdn`, and `cache_layers` signals to select the relevant rendering and
   purge paths. Leave an unconfirmed value as `unknown`.
2. In a real browser, identify the LCP element in a performance trace. Record whether it is the poster,
   an `<img>`, a CSS `background-image`, a video frame, or text covered by the hero. A visually dominant
   element is not automatically the recorded LCP element.
3. Inspect the hero markup for `<video>` attributes: `autoplay`, `muted`, `playsinline`, `preload`,
   `poster`, `src`, and nested `<source>` elements. For a CSS background, record the exact rule and the
   stylesheet or inline style that supplies its URL.
4. Reload with cache disabled under the target mobile profile. Record each media request's start time,
   priority, transferred bytes, status, and initiator. Distinguish the encoded file's stored size from
   the bytes actually transferred during the measured load.
5. Test `preload="metadata"` and `preload="auto"` as observed behavior, not promises. `metadata` is a
   hint to fetch duration, dimensions, and related metadata with limited media data; `auto` permits the
   browser to fetch the whole resource. Browser policy, data-saving mode, and server range support can
   change the actual transfer, so the Network panel is the evidence.
6. For MP4, inspect the ISO Base Media File Format box order with a media/container inspector. A
   fast-start file has the `moov` metadata box before the large `mdat` media-data box. If the tool cannot
   show box order, report fast-start as `unknown`; the next check is a container inspector or a known
   `ffmpeg -movflags +faststart` remux followed by a byte-range playback comparison.

`perf-probe.py --site URL --json baseline.json` discovers `<video src>`, nested sources, and poster
images present in static HTML and attempts to size them. It does not execute JavaScript, select sources
as a browser does, or prove how many media bytes transfer during playback. Use its `other_kb`, `img_kb`,
`unsized_resources`, and per-URL `errors` as a floor and cross-check them with the browser waterfall.

### At tier 1+ (admin / REST)

Open the page and every global template that can supply its hero. Record the configured desktop and
mobile media, poster, autoplay, loop, lazy-load, and background-video settings without changing them.
Check whether a responsive control hides the desktop video only with CSS; a hidden element can still
have its `src` discovered and fetched.

Media Library metadata can establish the attachment file and derivatives, but it does not establish
the URL selected by a builder, CDN transformation, `<source media>`, or JavaScript. The final DOM and
Network panel settle that ambiguity.

### At tier 2+ (WP-CLI / SSH)

Use `wp post get POST_ID --field=post_content` to find video blocks, cover blocks, shortcodes, or builder
document references. The raw output should contain a checkable media URL, attachment ID, block comment,
or shortcode attribute. Then read the active template or builder integration to find when it assigns
`src`, creates `<source>`, or calls `play()`.

On a local copy of the source MP4, create a lossless fast-start candidate without re-encoding:

```bash
ffmpeg -i hero-original.mp4 -c copy -movflags +faststart hero-faststart.mp4
```

The expected evidence is an `ffmpeg` message that moves the `moov` atom to the beginning, followed by
container inspection showing `moov` before `mdat`. Preserve the original file; this command does not
prove that the deployed URL serves the remuxed artifact.

### By stack

Identifiers in this table are the closed `builder` vocabulary.

| Stack | Signal | Confidence | Notes |
|---|---|---|---|
| `classic-none` | `<video>`, `<img>`, or a hero `background-image` appears directly in a theme template; the Network initiator points to that template's HTML or stylesheet | high | Source confirmation is required. Prefer semantic markup over a CSS-only background when the hero must expose a poster or responsive source. |
| `block-editor` | A video, cover, image, or gallery block comment in raw post content matches final media markup and URL | high | A block's `preload`, poster, and loading behavior may be filtered by the theme or plugin; verify the rendered element. |
| `site-editor` | The media originates in an assigned template part and the final DOM contains its URL | high | Fix the template part once, then verify every template that reuses it. |
| `elementor` | An Elementor section/container background or video widget creates the request; DOM classes and the Network initiator agree | high | Responsive “hide” controls do not by themselves prove that the media is not fetched. Test the mobile DOM and waterfall. |
| `divi` | A section background video, video module, or slider module maps to `et_*` markup and the measured request | high | Check the first slide and responsive alternatives; a non-visible slide can still be discovered early. |
| `wpbakery` | A video background or media shortcode in `[vc_...]` content maps to the final request | medium | Check theme overrides next. Theme-bundled elements may emit literal mid-template media markup outside WPBakery's core shortcode. |
| `bricks` | A Bricks background/video element and its `brxe-*` wrapper map to the request | high | Confirm whether the source URL exists at initial HTML parse or is assigned by the frontend script. |

## Attribute

Attribute the LCP delay to hero media only when a controlled trace shows that its early transfer or
decode delays the recorded LCP element. Useful proof includes:

- the hero media and LCP resource share the constrained network interval, and deferring only the hero
  lets the LCP request start or finish earlier;
- the video itself is LCP and a poster paints substantially before the first decoded frame;
- a main-thread decode or media task ends immediately before LCP;
- the same URL without early media loading improves LCP while TTFB and the LCP asset remain stable.

Attribution is disproved when the video transfers only metadata, starts after LCP, or is absent from the
critical interval. It is also disproved when the real bottleneck remains TTFB, a render-blocking asset,
a font, or a visibility gate. A 200 MB file with a 100 KB initial range is not a 200 MB initial load.

## Fix

### The change

Choose the smallest intervention supported by the trace:

1. Give a video hero a properly sized, compressed `poster` image so the hero can paint without waiting
   for the first video frame. If the poster is the LCP resource, do not lazy-load it; make its discovery
   early and verify its browser priority.
2. Stop the video from competing with the critical path. The strongest form keeps media URLs out of
   `src` and `<source src>` until after the critical load, then assigns them and calls `load()`/`play()`.
   A lighter form uses `preload="metadata"` and starts playback after the `load` event, an idle window,
   or an intentional intersection threshold. Choose by measurement, not by a universal delay value.
3. Keep `muted` and `playsinline` when muted inline autoplay is part of the intended mobile experience,
   and handle a rejected `play()` promise by leaving the poster and a usable play control visible.
   Mobile autoplay is policy-controlled; these attributes improve eligibility but do not guarantee it.
4. For MP4, move the `moov` atom before `mdat` with a lossless fast-start remux. This allows playback to
   begin before the file is fully buffered; it changes container layout, not visual quality or bitrate.
5. Re-encode or resize only when the quality/transfer tradeoff warrants it. In an anonymized campaign,
   the operator deliberately kept the full 1080p hero after comparison: at matched file size, 1080p at a higher CRF looked better than a downscaled 1600×900 encode at a lower CRF. “Keep the heavy hero,
   load it later” was the measured optimum, not a failure to optimize.

For a click-to-play video, preserve keyboard access, an accessible name, visible focus, captions or
transcript access, and a no-script fallback appropriate to the site.

### Host constraints

No host-specific restriction applies.

The media change may still require purging an `edge` or `server` cache layer and any transformed-media
derivative. Do not assume that replacing the WordPress attachment invalidates a CDN URL with a different
cache key.

### Risk

Deferring `src` can break builder controls that expect media metadata during initialization. A poster
with the wrong crop causes a visible jump when video begins. Fast-start remuxing can replace metadata
or fail if the output is deployed incompletely. Mobile policy may reject scripted autoplay even when
desktop accepts it, leaving a static hero unless the failure path is designed.

The first observers are mobile visual checks, keyboard-only users, reduced-data or reduced-motion
users, and monitoring that records media or console errors.

## Verify

Purge the changed attachment, generated derivative, `page-plugin`, `server`, and `edge` cache layers as
applicable. Warm the page before comparison; do not compare an immediate post-purge miss with a warm
baseline.

In a real visible browser at the target mobile viewport and network profile, verify:

- the poster paints promptly and is the intended crop;
- the video request starts at the intended event, not during the original critical interval;
- transferred bytes before LCP fall or move later, even if total bytes after playback remain similar;
- LCP improves across repeated comparable traces;
- playback starts, pauses, loops, and exposes controls as intended on representative mobile and desktop
  browsers;
- the Network panel shows range requests and the deployed fast-start file, when used;
- rejected autoplay leaves a functional poster and play control rather than a blank hero.

Use `perf-probe.py --diff baseline.json after.json` to compare statically discovered payloads, while
remembering that the important improvement may be request timing rather than total weight. If LCP does
not move and the video was already outside the critical interval, treat further encoding work as media
quality/bandwidth work, not an LCP fix.

## Rollback

Before changing the hero, retain the original media file, poster, attachment URL, markup or builder
setting export, and the exact trigger logic. A CDN-cached original is not an adequate backup.

Rollback means restoring the original source assignment and playback timing, restoring the prior poster
and preload value, redeploying the original media when it was replaced, purging every affected cache or
transformation layer, warming the page, and checking that the original behavior has returned.

## Gotchas

- An in-app or headless browser may not advance media while its pane or tab is hidden. `play()` can
  resolve while `currentTime` remains `0`. Verify video behavior with a real visible browser measurement
  or by eye, not only by scripted playback.
- `preload="metadata"` is a browser hint, not a byte guarantee. The measured transfer is authoritative.
- A CSS-hidden video may still download because the parser discovered its source before responsive CSS
  hid it. Remove or defer the source when mobile should not fetch it.
- Fast-start improves when playback can begin; it does not reduce encoded bytes and cannot repair a
  video that still starts too early for the page's critical path.
- The first video frame is not a substitute for a `poster`: it still requires media transfer and decode.
- `autoplay`, `muted`, and `playsinline` behavior varies with browser policy, user settings, power mode,
  and data-saving preferences. A tested fallback is part of the fix.
- A video may cease to be LCP when a poster is added. Verify the newly recorded LCP element rather than
  assuming the metric still represents the same node.
