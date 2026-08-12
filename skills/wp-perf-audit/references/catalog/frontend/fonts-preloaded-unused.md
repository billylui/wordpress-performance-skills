<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Fonts preloaded but unused

A `<link rel="preload" as="font">` forces an early high-priority transfer for a face that no
rendered element uses, consuming critical-path bandwidth without contributing a paint.

## Contents

- [Symptom](#symptom)
- [Detect](#detect)
- [Attribute](#attribute)
- [Fix](#fix)
- [Verify](#verify)
- [Rollback](#rollback)
- [Gotchas](#gotchas)

## Symptom

The Network waterfall starts a large font request from a preload tag or `Link` response header,
but the browser’s rendered-font inspection never maps that face to an element. The request
competes with stylesheets, scripts, the LCP image, or the font actually needed for a text LCP.

An anonymized campaign on a multilingual site on managed hosting removed 1,506 KB of transferred
font weight per page by deleting one unused preload. On one template, mobile LCP moved from
46.8 s to 7.1 s. The font file was large, but its decisive property was configuration: nothing
referenced its family, so file-size analysis alone could not identify why the browser fetched it.

For a font that is genuinely used by the LCP text, `font-display: swap` matters for a different
reason. It permits fallback text during the font’s block period rather than holding text invisible
until the web font is ready. A preload does not repair a face whose `font-display` policy delays
text paint, and `swap` does not make an unused preload useful.

## Detect

Run `capabilities.py --target URL` to record whether a browser can measure LCP. Run
`fingerprint.py URL --pages N` to choose the applicable builder source below. Neither script
proves that a preloaded face is unused; that requires matching browser and CSS evidence.

### At tier 0 (public URL only)

For each font preload, capture all of the following:

1. The exact `<link rel="preload" as="font" href="…">` in response HTML, or the raw `Link`
   response header. Record `href`, `type`, and `crossorigin`.
2. The Network request’s Initiator and Priority. Reload with cache disabled so a memory-cache hit
   does not hide the transfer.
3. The `@font-face` rule whose `src` URL resolves to that request. Record its `font-family`,
   `font-style`, `font-weight`, and `font-display` descriptors.
4. The Computed panel’s rendered-font result for the LCP node and representative text nodes in
   every language and template under test.
5. Every matched `font-family` declaration for those nodes. The decisive signal is that the
   preloaded face’s family never appears in a matched declaration, not merely that another face
   rendered during one sample.

Use CSS Coverage and a DOM-wide computed-style inventory as supporting evidence, not as sole
proof. Pseudo-elements, consent dialogs, menu states, and translated glyph ranges can be missed
by a static page state. If one tested state matches the family, classify site-wide unused status
as `unknown` and narrow the preload to the templates or states that need it.

### At tier 1+ (admin / REST)

Map the preload URL and family name back to its configured source:

- In a builder font manager, record the custom-font family, uploaded file, weights, and any global
  preload switch. Compare the setting to the rendered asset path and `@font-face` family.
- In theme options, record the typography or performance option that emits the preload. Save the
  option value and confirm it produces the exact URL in a preview response.
- In a custom-fonts plugin, record the active plugin slug from the plugin screen and the font
  record that owns the URL. A plugin merely being active is not attribution.

Repeat the mapping for every language. A family unused in one language may supply glyphs in
another, and a multilingual plugin identifier such as `wpml`, `polylang`, `translatepress`,
`weglot`, `gtranslate`, or `multilingualpress` does not by itself reveal font use.

### At tier 2+ (WP-CLI / SSH)

Use read-only inventory commands to settle ambiguous ownership:

```text
wp plugin list --status=active --fields=name,status --format=table
wp theme mod list
wp option list --search=font --fields=option_name --format=table
```

The checkable evidence is an active plugin slug, a theme-mod key/value, or an option name that can
be tied to the exact family or file URL. These commands locate candidates; they do not prove use.
Inspect the selected option with `wp option get OPTION_NAME` and preserve its output before any
change. If the URL cannot be tied to a setting, report the source as `unknown` and continue at
tier 3 rather than guessing.

### At tier 3 (code / deploy path)

Search the active theme and plugins for the exact font filename, family, or preload URL. A
hand-written `functions.php` enqueue is proven by a file path and the hook that registers the
font stylesheet or emits its preload, commonly `wp_enqueue_scripts` together with a `wp_head`
callback or `wp_resource_hints` filter. Also check for a direct `<link>` in a template. Record both
the registration path and the condition controlling which templates receive it.

For deep PHP, database, autoload, query, cron, and object-cache analysis, use the official
[`WordPress/agent-skills` wp-performance skill](https://github.com/WordPress/agent-skills)
instead of expanding this browser-visible source-attribution check.

### By stack

The identifiers in this table match the `builder` vocabulary exactly. Builder ownership remains
`unknown` until its setting produces the exact public URL or family.

| Stack | Signal | Confidence | Notes |
|---|---|---|---|
| `elementor` | A custom-font record maps the family and file to an Elementor-generated `@font-face` asset and the same manager or generated markup emits the preload | high | Check global typography and translated templates before removing the record or preload. |
| `divi` | A Divi typography/performance setting or generated theme asset maps to the exact family URL and emits the preload | high | A `/themes/Divi/` path alone is not proof that the configured face is unused. |
| `wpbakery` | The exact preload is emitted by the active theme, an element add-on, or a custom-font integration used with WPBakery | medium | WPBakery markup alone does not identify ownership; require the setting, plugin path, or code hook. |
| `bricks` | A Bricks font record or generated CSS asset maps the exact family/file and the page output carries its preload | high | Confirm whether the font is global or template-scoped. |
| `beaver-builder` | A Beaver Builder module/theme setting or add-on asset maps to the exact family/file and preload | medium | Require the namespaced asset path or saved setting; a generic custom font may be theme-owned. |
| `block-editor` | A block plugin, theme typography setting, or `theme.json`-related asset emits the exact family and preload | medium | The block editor is not proof of ownership; record the plugin or theme path. |
| `site-editor` | A block theme or plugin font setting maps the exact family/file to the emitted preload | high | Inspect global styles and template-specific output across language variants. |
| `classic-none` | Theme options, a custom-fonts plugin, or hand-written theme code emits the exact preload | high | Attribute with the option key, active plugin path, or source file/hook; otherwise use `unknown`. |

## Attribute

Establish causality with a one-variable browser experiment:

1. Save a cold-load Network log and Performance trace with cache disabled.
2. Remove only the preload through a local response override. Leave the `@font-face` declaration,
   font file, other preloads, and page CSS unchanged.
3. Reload several times under fixed mobile throttling. Confirm the unused font request disappears
   rather than merely changes priority, and compare median LCP plus the critical waterfall.
4. Restore only the preload and confirm the request and regression return.

Attribution is disproved if the font is fetched later because a matched declaration uses it, if
removing the preload causes a visible font failure, or if repeated traces show no transferred-byte
or critical-path change. In that case retain or scope the preload and investigate the actual LCP
dependency.

## Fix

### The change

Remove the narrowest configuration that emits the unused preload. Preserve the `@font-face` rule
when the font may be needed on another template or interaction; an unused face declaration does
not itself force a browser transfer. If the face is unused everywhere and removal is separately
proven, delete the font record and generated CSS in a distinct, reversible cleanup.

For a face used by text LCP:

- set `font-display: swap` unless the design has a documented reason for a different policy;
- preload only the exact style/weight needed above the fold;
- ensure the preload URL exactly matches the `@font-face` URL after redirects and CDN rewriting;
- include correct `type` and cross-origin handling; and
- subset only after verifying every required language and glyph range.

Do not replace one unconditional preload with a JavaScript-injected preload. The browser discovers
that later, and it does not solve the ownership or usage error.

### Host constraints

No host-specific restriction applies.

After changing builder, theme, plugin, or code output, purge every active `edge`, `server`, and
`page-plugin` cache layer reported by `fingerprint.py`. Do not install a cache or font plugin as
part of this fix.

### Risk

Removing a preload that is used only in an untested language, route, modal, or interaction can
introduce late font loading, fallback glyphs, layout movement, or a flash of unstyled text. Editing
generated CSS can be overwritten by the builder. Removing the face rather than only its preload
can break pages outside the sample. Content editors and visitors using non-default languages
notice glyph and typography regressions first.

## Verify

Purge relevant caches, warm each URL until visitor-facing cache status is stable, then make fresh
browser navigations with cache disabled for transfer comparison. A valid pass shows:

- the preload tag or `Link` header is absent on templates that do not use the face;
- the unused font request is absent from the Network log, not merely served from cache;
- transferred bytes fall by the font request’s actual encoded transfer size;
- median LCP is stable or improved under the same profile;
- the intended rendered fonts, weights, and glyphs remain correct in every tested language; and
- text LCP can paint in fallback while a used web font loads when `font-display: swap` applies.

Keep the browser HAR or Network export as primary proof. `perf-probe.py --site URL --repeats N
--json PATH` remains useful for a broad before/after payload walk, but its `font_kb` is referenced
font sources discovered in CSS, not a browser’s actual request log.

## Rollback

Before editing, export the font-manager/plugin setting, theme options, relevant generated CSS,
and the exact original preload tag or header code. Roll back by restoring the single source that
emitted the preload, regenerating builder/theme CSS when applicable, purging the same cache
layers, warming the page, and confirming the original request initiator returns.

If glyphs or typography regress, restore immediately and narrow the next test by template,
language, font style, and weight rather than applying a global removal.

## Gotchas

- **Referenced-byte totals may not move after a correct fix.** Removing only the preload leaves
  the `@font-face` source declared in CSS by design. A payload walker that sums referenced URLs
  will still count that font. Judge this fix by transferred weight in a browser measurement and
  the Network request’s disappearance, not by the referenced-bytes total. `perf-probe.py` states
  the same limitation in its report legend.
- A warm memory or disk cache can make an unnecessary preload appear free. Disable cache for the
  diagnostic transfer comparison, then perform warm comparable LCP verification separately.
- “Downloaded but not rendered on the heading” is not enough. The face may serve another element,
  pseudo-element, weight, language, or interaction.
- A family named in an unmatched CSS rule is not used. Require a matched `font-family`
  declaration or a rendered-font record on an exercised state.
- A preload URL that differs from the `@font-face` URL by query string, CDN rewrite, format, or
  redirect can cause two transfers even when the face is needed.
- `font-display: swap` helps a used text face paint with fallback; it does not excuse preloading a
  face that nothing references.
- Multilingual coverage is a correctness boundary. Never remove or subset a font globally after
  testing only the default language.
