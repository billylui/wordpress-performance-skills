<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Case study: the campaign this project generalizes

An anonymized account of the production engagement these skills were built from. The site is not
named and never will be — what generalizes is the defect shapes, the measurement discipline, and
the mistakes.

**The site:** a multilingual brochure site on managed WordPress hosting. Classic child theme
driven by a page builder, three active languages, a long-lived edge cache in front of the origin,
a media-heavy homepage. Roughly 2,000 media attachments across a few hundred pages. An ordinary
site of a very common shape.

**The complaint:** "a bit slow."

## Contents

- [Result](#result)
- [What actually caused it](#what-actually-caused-it)
- [The measurement discipline](#the-measurement-discipline)
- [What did not work](#what-did-not-work)
- [Deliberate decisions that look like oversights](#deliberate-decisions-that-look-like-oversights)
- [Gotchas worth carrying forward](#gotchas-worth-carrying-forward)
- [What this says about the tooling](#what-this-says-about-the-tooling)

## Result

Lab measurements on bare URLs — what a visitor actually receives.

| Page | Score | LCP | Page weight |
|---|---|---|---|
| Home, mobile | 63 → **77** | 16.3 s → **3.5 s** | 16.4 → **3.7 MB** |
| Home, desktop | 72 → **91** | 3.6 s → **1.2 s** | 16.7 → **6.9 MB** |
| Listing, mobile | 69 → **75** | 46.8 s → **5.1 s** | 13.2 → **0.9 MB** |
| Listing, desktop | 76 → **93** | 2.9 s → **1.7 s** | 13.2 → **2.1 MB** |

Payload fell 67% on the listing template, 70% on detail pages, 54% on the gallery, and 46–67% on
the secondary-language equivalents. Across the measured fleet, excluding one video gallery left
deliberately untouched: **−38.6%**. CLS stayed between 0.000 and 0.013 throughout. Both desktop
pages moved inside the 2.5 s LCP threshold.

## What actually caused it

> **The two biggest wins were configuration, not assets** — a 1.5 MB font that nothing
> referenced, and an entrance animation holding the LCP text invisible. Neither would be found by
> looking at file sizes.

That sentence is the reason this project exists.

**A preloaded font nothing used.** The theme preloaded a font family that no matched
`font-family` declaration referenced. It cost 1,506 KB per page on the critical path, and
removing the preload took the listing template's mobile LCP from 46.8 s to 7.1 s in one change.
No image optimizer, minifier or CDN would have found it, because nothing about the file was
wrong — it simply should not have been requested.

**An entrance animation gating LCP.** The builder's entrance-animation class held the largest
text element at zero opacity until its JavaScript bundle executed and a configured delay elapsed.
The browser records no paint until that moment, so LCP was pinned to the bundle, not to the
content. Removing the gate on that one element moved home mobile LCP from 10.7 s to 3.5 s. There
were 21 elements still carrying the class on that page; only the two gating the LCP text needed
touching.

**Responsive images at a choke point.** The theme emitted thumbnails through a single helper
function. Fixing `srcset`/`sizes` there — one function, not dozens of templates — cut the listing
template's payload by 66%.

**Hero video timing, not size.** The homepage hero video got `faststart`, a poster image, and a
deferred start. Total page bytes fell only about 5%. The gain was **when** it loaded, not how much
it weighed.

## The measurement discipline

**Origin and edge were never blended.** The site served most visitors from a long edge cache.
Origin TTFB ran 1.0–1.4 s while edge-cached visitors saw ~0.2 s. Those are two different problems
with two different fixes, and a single averaged number would have hidden which one the site had.
Every measurement separated them, using a unique cache-buster per request so origin samples were
genuine misses. That separation is now `perf-probe.py`.

**A baseline was captured before anything changed**, and re-measured after every phase, warm.

**Field data was unavailable.** The site fell below the traffic threshold for real-user data, so
lab measurement was the entire basis. That was stated explicitly rather than papered over — a
site with no field data is the normal case for small businesses, not an error condition.

## What did not work

The engagement set a target of zero failing responsive-image assertions on the listing template
at a 375 px viewport. **It did not reach it.** Four of 25 images still failed, against a baseline
of 15 of 15.

The attribution matters more than the number:

- **Three were the header logo**, an 800 px natural image rendered into an 80 px slot — a 10×
  overshoot. Its `sizes` attribute was the page builder's own generated header markup, outside
  the scope of the work, and pre-existing.
- **One was mine.** The listing banner took a 1280 px candidate for a 750 device-pixel need — a
  3.4× overshoot, down from 7.4× at baseline. Its `sizes="100vw"` was *correct*, because the
  banner is genuinely full-bleed; the browser was simply rounding up conservatively. Tightening
  to an explicit `(max-width: 767px) 100vw, 1920px` would likely have pulled it to a 768 w
  candidate. That was a ~60 KB win needing a deploy and purge cycle, and it was deliberately left
  undone at wrap time.

Also left open, and recorded as such: two 2.8 MB PNGs of photographs that belonged in a lossy
format; a duplicate jQuery plus two CDN-hosted libraries totalling ~60 KB; and a home-mobile
Speed Index still at 9.3 s despite LCP at 3.5 s, because the deferred video and lazy images fill
in late by design.

The duplicate-library finding is worth dwelling on. Total blocking time on that site was 0–31 ms.
**It was recorded as cleanup, not a performance fix.** An audit that promotes it to a headline
finding is teaching bad prioritization.

## Deliberate decisions that look like oversights

- **The hero video stayed at full 1080p.** The operator chose quality, and measurement backed the
  choice: at matched file size, 1080p at a higher CRF beat a downscaled encode at a lower one.
  Homepage payload therefore fell only ~5%. "Keep the heavy hero, load it later" was the correct
  outcome, not a failure to optimize.
- **Mobile background video playback stayed enabled**, because the video is the signature
  experience of the brand.
- **Four of six hero animations were kept.** Only the two gating the LCP text were cleared.

A report that omits these reads as though the auditor missed them. Recording the reasoning is
what stops the next audit re-litigating settled decisions.

## Gotchas worth carrying forward

Each of these cost real time, and each is now encoded in a catalog entry.

1. **A multilingual site duplicates builder content per language.** The homepage hero existed
   three times, once per active language, with the copies sharing element IDs. A fix applied to
   the default-language copy alone silently missed two thirds of the site — and looked complete
   to anyone testing the default language. This bit once; every later change resolved the full
   translation set from the plugin instead of hardcoding an ID.
2. **A referenced-bytes payload total will not drop when you remove an unused font preload**,
   because the `@font-face` sources are still declared by design. Judge that fix by transferred
   weight in a browser, not by the referenced total. A correct fix reads as a failed one otherwise.
3. **TTFB spikes immediately after a cache flush are transient.** Verified twice. Re-measure warm
   before reporting a regression.
4. **A filter that short-circuits an option must not return `false`.** WordPress treats `false` as
   "no filter ran". Returning `'0'` is the fix. This shipped once and was caught by post-change
   verification — which is the argument for post-change verification.
5. **A hidden browser pane may not advance media.** `play()` resolves while `currentTime` stays 0.
   Verify video by a real measurement or by eye, not by scripting playback.

## What this says about the tooling

Reading back over the engagement, four things did the work, and each became a component here:

| What mattered | Where it lives now |
|---|---|
| Knowing the stack before advising on it | `fingerprint.py` |
| Origin and edge as separate numbers | `perf-probe.py` |
| Configuration defects that file-size analysis cannot see | the frontend catalog |
| A snapshot and a purge for every change | `wp-perf-fix` and its validator |

And one thing that was not a tool at all: **the report recorded a target it did not meet, and
attributed the shortfall honestly between pre-existing conditions and its own work.** That is why
the report template makes "What could not be checked" and "What did not work" mandatory sections.
An audit containing only wins is a sales document.
