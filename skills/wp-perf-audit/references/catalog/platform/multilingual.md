<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Multilingual architecture and per-language work

Multilingual plugins use different storage and delivery architectures, so the same visible language switcher can represent content multiplication, runtime HTML translation, or a proxy/service request path.

> [!WARNING]
> **Never fix only the default-language post. Resolve the full translation set from the multilingual plugin, apply the change to every language, and verify every language URL separately. Never hardcode a single post ID.** Duplicate-post translations can contain separate builder payloads while reusing the same element IDs, making a one-language change look complete when most copies remain broken.

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

One language can have slower origin TTFB, larger HTML, missing optimizations, stale content, or a different LCP/CLS/INP result from the default language. A cache purge or builder edit can appear successful on the default URL while alternate-language URLs still serve the old payload.

The cost model depends on architecture:

| `multilingual` identifier | Architecture | Primary performance cost |
|---|---|---|
| `wpml` | Duplicate posts linked as translations | Multiplied posts, postmeta, builder content, queries, and per-language cache entries. |
| `polylang` | Duplicate posts linked as translations | Multiplied posts, postmeta, builder content, queries, and per-language cache entries. |
| `translatepress` | Translates rendered HTML at request time | Runtime parsing/lookup/replacement work and a separately cached rendered response per language. |
| `weglot` | Proxy/service-based translation delivery | Service/proxy latency, client integration, and cache behavior outside the origin's post model. |
| `gtranslate` | Proxy/service-based translation delivery | Service/proxy or client delivery cost and cache behavior outside duplicate WordPress posts. |
| `multilingualpress` | Multisite-based language sites | Per-site WordPress work plus cross-site relationships; see [WordPress multisite shared-resource contention](./multisite.md). |

## Detect

### At tier 0 (public URL only)

Run the evidence-bearing detector:

```sh
python3 skills/wp-perf-audit/scripts/fingerprint.py https://example.com/ --pages 2 --json fingerprint.json --quiet
```

Read `profile.multilingual.value`, `confidence`, and `evidence` together. Public markers include vendor-namespaced asset paths, class tokens, and cookies for the exact identifiers `wpml`, `polylang`, `translatepress`, `weglot`, `gtranslate`, and `multilingualpress`.

`hreflang` alone does not identify a plugin or architecture. If alternate links exist without a supported product marker, report `unknown` and use tier 1 to inspect the active plugin and translation relationships.

For every language URL, record:

- the canonical URL, `<html lang>`, and every `<link rel="alternate" hreflang="...">` target;
- response cache headers and `Vary`;
- language cookies and redirect behavior in a clean session;
- HTML bytes, requests, origin TTFB, and edge TTFB;
- language-switcher requests, including their URL, initiator, response cache status, and duration.

A language switcher that fetches session-, geography-, or availability-specific state can add uncached per-request work. Static switcher markup does not.

### At tier 1+ (admin / REST)

Confirm the active plugin and use its own translation UI/API to resolve the complete translation set for the target content. Capture language code, URL, post/site identifier, translation status, and source relationship for every member.

For `wpml` and `polylang`, confirm that alternate languages resolve to distinct post IDs. For `translatepress`, confirm that languages render from the same source post rather than assuming duplicate posts. For `multilingualpress`, resolve the language site's `blog_id` and continue with [multisite detection](./multisite.md).

Also inspect the page builder's stored content for every duplicate post. Identical element IDs across language copies are not proof that the content is shared.

### At tier 2+ (WP-CLI / SSH)

Start with inventory evidence:

```sh
wp plugin list --status=active --fields=name,status --format=json
wp post get <resolved-post-id> --fields=ID,post_type,post_status,post_modified_gmt --format=json
```

Run the second command for every post ID returned by the multilingual plugin, not for a guessed ID. Plugin-specific translation APIs or WP-CLI extensions settle relationships; if none is available, use the plugin's documented relationship data through WordPress and report unresolved members as `unknown`.

Use the [official WordPress agent skills](https://github.com/WordPress/agent-skills) `wp-performance` workflow for database/query profiling after the architecture and language segment are known.

### By stack

| Stack | Signal | Confidence | Notes |
|---|---|---|---|
| `wpml` | Vendor marker plus plugin-resolved translation group containing distinct post IDs | high | Builder data can be independently stored on every post. |
| `polylang` | Vendor marker plus plugin-resolved translation map containing distinct post IDs | high | Builder data can be independently stored on every post. |
| `translatepress` | `trp-` or `/plugins/translatepress-multilingual/` evidence plus one source post rendered at alternate URLs | high | Attribute runtime translation work separately from source-post queries. |
| `weglot` | `weglot` public marker plus service/proxy configuration in admin | high | Tier 0 alone may not reveal where translation and caching occur. |
| `gtranslate` | `gtranslate` or `gt_switcher` marker plus service/proxy configuration in admin | high | Deployment modes differ; do not infer cache ownership from the switcher alone. |
| `multilingualpress` | Plugin evidence plus a tier-1/2 mapping from language URL to network `blog_id` | high | Apply both this entry and [multisite](./multisite.md). |

## Attribute

Treat each language URL as a separate measurement segment:

1. Resolve the authoritative language set and URLs.
2. Warm each URL through the same cache path, then compare cache status, origin/edge TTFB, payload, and browser metrics.
3. For `wpml` or `polylang`, compare postmeta/builder payload only across the resolved post IDs. Distinct posts explain duplicated storage but do not by themselves prove runtime delay.
4. For `translatepress`, compare the source-language and translated response at origin with equivalent cache state. Attribute runtime translation only when the translated request adds measured server time or query work.
5. For `weglot` or `gtranslate`, separate origin time from service/proxy/client time using request URLs and initiators.
6. Measure the switcher with and without its dynamic request. Attribute only the delta while preserving required behavior.

Disproof includes equal warm origin/edge results across languages, a static switcher with no request, or a slow translated URL whose delay is entirely an unrelated image, font, or cache miss.

## Fix

### The change

Match the change to the architecture:

- For `wpml` and `polylang`, resolve the full translation set through the plugin, edit every language's stored builder/content payload that contains the defect, and keep translation relationships intact.
- For `translatepress`, optimize the measured rendered-HTML translation path or its cacheability; do not create duplicate posts as a generic performance fix.
- For `weglot` and `gtranslate`, change the measured service/proxy/client integration or its cache configuration through the supported control plane; do not edit WordPress post IDs that do not own the translated output.
- For `multilingualpress`, apply the content change to each resolved language site and follow the per-`blog_id` safeguards in [multisite](./multisite.md).
- Build cache keys from the actual language URL/host and any language-varying cookie or header used by the stack. Purge every language URL, not only the source URL.
- Keep `hreflang` reciprocal and canonical URLs language-correct after URL or content changes.
- Make a switcher static/cacheable only if it does not need visitor-specific state; otherwise reduce its measured request cost without serving the wrong language set.

**Binding rule: resolve the full translation set from the multilingual plugin and apply the change to every language, then verify each language's URL separately. Never hardcode a single post ID.**

### Host constraints

| Host class | Permitted | Path |
|---|---|---|
| `wpengine` | Content edits are permitted; cache-key and purge changes must use the active host/edge controls. | Enumerate and purge every language host/path at both layers. |
| `kinsta` | Content edits are permitted; cache-key and purge changes must use the active host/edge controls. | Enumerate and purge every language host/path at both layers. |
| `pantheon` | Preserve platform cache integration and domain routing. | Validate each language host/path through the supported cache workflow. |
| `wpcom` | Use only exposed plugin, domain, and cache controls. | Escalate unavailable per-language purge or routing controls. |
| `wpvip` | Follow deployment and cache-review workflow for plugin or code changes. | Include the complete language URL matrix in verification. |
| `other` | Restrictions are `unknown` until cache ownership, proxy ownership, and domain routing are checked. | Record which operator controls origin, `edge`, and translation service caches. |

### Risk

A partial fix leaves languages behaviorally inconsistent. A bad cache key can serve one language at another URL; a partial purge leaves stale translations; incorrect canonical or `hreflang` edits can misstate language relationships; changing a proxy/service integration can make translated URLs unavailable. Editors, localized support teams, and search monitoring notice first.

## Verify

Build a matrix with one row per resolved language and verify each URL separately after purging every applicable `page-plugin`, `server`, and `edge` layer, plus any translation-service cache. Warm each row before comparison.

For every language, confirm:

- the intended content or builder change is present;
- the defect is absent even where element IDs match another language;
- canonical, `<html lang>`, and reciprocal `hreflang` values are correct;
- switcher links reach the correct resolved URLs without loops;
- cache headers show the intended isolated entry and never another language's HTML;
- the measured TTFB, payload, LCP, CLS, or INP change matches the attributed mechanism.

Save equivalent `perf-probe.py` runs per language URL and compare like-for-like documents with `--diff A.json B.json`. A default-language pass is not sufficient evidence.

## Rollback

Before change, export the plugin's translation map, every affected post/site identifier, builder payload or content revision, language URLs, canonical/`hreflang` markup, switcher settings, and cache configuration.

Rollback means restoring every member of the translation set, not only the source post; restoring the prior proxy/service or switcher configuration; and purging all language-specific cache entries again. Re-run the full language matrix after restoration.

## Gotchas

### Critical: duplicate builder content can make a partial fix look complete

With a duplicate-post architecture, a page builder stores content separately for each translated post. A homepage hero can therefore exist once per active language while those copies share the same element IDs. Editing the default-language post changes only that copy; testing only its URL silently misses the rest.

**Resolve the full translation set from the multilingual plugin and apply the change to every language, then verify each language's URL separately. Never hardcode a single post ID.**

Other gotchas:

- Shared element IDs identify builder elements, not shared storage across translated posts.
- `hreflang` proves alternate declarations exist; it does not identify `wpml`, `polylang`, `translatepress`, `weglot`, `gtranslate`, or `multilingualpress`.
- Purging one URL does not prove that another language's host/path, `edge` entry, or translation-service cache was purged.
- Language negotiation by cookie or header must be represented in the cache key or redirected to stable language URLs.
- A language switcher can be the only uncached dynamic request on an otherwise cached page; measure it rather than assuming it is free.
