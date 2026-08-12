<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Verify a production change reached visitors

A successful command is not proof of a successful change. Read back the public representation an
anonymous visitor receives, verify every affected variant, warm the caches, and record the
evidence. Admin UI state, files on disk, and logged-in previews are supporting evidence only.

## Contents

- [Build the verification set before changing anything](#build-the-verification-set-before-changing-anything)
- [Fetch the anonymous public response](#fetch-the-anonymous-public-response)
- [Prove the cache copy is fresh](#prove-the-cache-copy-is-fresh)
- [Check failures across affected URLs](#check-failures-across-affected-urls)
- [Multilingual gate: verify every language](#multilingual-gate-verify-every-language)
- [Verify every affected template](#verify-every-affected-template)
- [Re-measure warm against the baseline](#re-measure-warm-against-the-baseline)
- [When verification fails](#when-verification-fails)
- [Record evidence](#record-evidence)
- [Copyable checklist](#copyable-checklist)

## Build the verification set before changing anything

Before the approved change, record a representative URL matrix. Include every template, language,
hostname, and cache-key variant the change could affect. Capture the pre-change response for those
same URLs so the after-state has something concrete to differ from.

At minimum, consider:

- the exact changed URL and its canonical public URL;
- each template that executes the changed theme/plugin code or embeds the changed global content;
- archive, search, product/cart/account, error, and API routes when the change can reach them;
- every language URL and translated duplicate;
- mobile/device, currency, cookie, query, and hostname variants when cache rules distinguish them;
- the direct public URL of every changed CSS, JavaScript, font, image, or other asset.

Do not add an unsafe checkout or account action merely for verification. Use representative public
GETs and the site's approved non-mutating health checks.

## Fetch the anonymous public response

Use the normal public hostname, no authentication, no logged-in cookies, and no cache-busting query
string. A logged-in WordPress session frequently bypasses page caching and can show the new origin
output while anonymous visitors still receive stale HTML.

One reproducible fetch pattern is:

```sh
/usr/bin/curl --silent --show-error --location --compressed \
  --cookie '' --dump-header response.headers --output response.body \
  "$PUBLIC_URL"
```

For each response, confirm the changed artifact in what was actually served:

| Change | Public read-back proof |
|---|---|
| Markup or content | An unmistakable new marker or expected absence is present in `response.body` |
| Header or redirect | Final status, final URL, and exact response header match the approved change |
| CSS/JavaScript/font/image | The asset's final public URL returns success and its bytes/hash match the changed artifact |
| Option or plugin setting | The visitor-visible behavior or output derived from the value changed; the admin form value alone is insufficient |

Capture redirects and headers for the final response, not only the first hop. Do not use the source
file on disk as delivery proof: a different release, generated asset, server, or stale cache may
still answer the public request.

## Prove the cache copy is fresh

Follow the documented [cache purge matrix](cache-purge-matrix.md) in inner-to-outer order. For the
normal anonymous URL, record before, first-after-purge, and warm responses with:

- status and final URL;
- the changed body marker or asset hash;
- `age`, `etag`, and `last-modified` where present;
- every attributable cache-status/header name and value;
- the response time as context, not as freshness proof.

A typical shared-cache sequence is a stale `HIT`, then a post-purge `MISS`/refill with reset or
absent `Age`, then a warm `HIT` containing the new representation. Products use different words
and some expose no status header, so confirm semantics for the detected owner. An ambiguous
`x-cache`, a missing header, or a command result is not enough.

An outer cache may replay inner-layer headers stored with the response. Prove freshness with the
changed body/asset hash plus the attributable outer status and, when authorized, an approved
origin or layer-bypass comparison. Do not invent a bypass header or query parameter.

## Check failures across affected URLs

Request every URL in the verification set and fail verification on any unexpected redirect,
authentication challenge, blank/truncated response, `5xx`, or visitor-visible PHP fatal, parse
error, warning, or notice. Capture the status and a bounded response excerpt. Check authorized PHP,
web-server, host, and application logs for the same request window when access exists; production
error display may be disabled, so clean HTML alone cannot rule out logged warnings.

Checking only the homepage is insufficient. A template-specific PHP path might execute only on a
single post, taxonomy archive, search result, product, cart, account route, translated page, or
not-found response. The homepage can remain healthy while the changed template returns a fatal
elsewhere.

For dynamic or personalized routes, verify the approved anonymous behavior without placing an
order, changing user data, or exposing private content. Confirm that pages which must bypass shared
cache still report the expected bypass behavior.

## Multilingual gate: verify every language

**A multilingual change is not verified until every language is checked.** Build the URL list from
the site's language switcher, canonical/alternate links, sitemap, and the confirmed multilingual
configuration. Read the audit guidance in
[multilingual architectures](../../wp-perf-audit/references/catalog/platform/multilingual.md)
before deciding which records and cache variants share a source.

In a duplicate-post architecture, each language can have separate post content, builder data,
metadata, generated CSS, and cache keys. Applying a fix to the default-language record can leave
every translation untouched. The site then looks fixed to anyone testing only the default
language.

For every affected language:

1. fetch the language's own canonical public URL anonymously;
2. confirm the changed markup, behavior, header, or asset in that response;
3. confirm the cache status and body are fresh for that language key;
4. check the applicable templates and failures, not just the language homepage;
5. record the language identifier, URL, status, marker/hash, and cache evidence separately.

If a translation is missing, intentionally falls back, or is managed remotely, record that fact
as `unknown` until the configured architecture proves the expected behavior. Do not infer that a
shared visual layout means shared content storage.

## Verify every affected template

Map the changed mechanism to templates before testing. Use one or more real public URLs for every
affected row:

| Change surface | Representative templates to consider |
|---|---|
| Global header, footer, navigation, design token, or enqueued asset | Front page, singular, archive, search, not-found, and commerce/account templates that render it |
| Singular template or reusable builder component | Each post type and each language that uses the template/component |
| Archive/query code | Home/posts archive, taxonomy, author, date, search, pagination, and empty-result states that execute it |
| Commerce code or setting | Shop/product plus safe cart/account states; never mutate orders merely to test |
| Media or attachment output | Pages embedding the media, attachment template if public, responsive variants, and the direct asset URLs |
| Redirect, header, or server rule | Matching path, a non-matching control path, trailing-slash/query variants, and affected hostnames |

Include a negative control: a URL the change should not affect. It helps detect an over-broad
redirect, cache rule, asset replacement, or template regression.

## Re-measure warm against the baseline

Do not measure immediately after a purge. The first requests pay to rebuild `object`,
`page-plugin`, `server`, and `edge` entries, so cold TTFB is transient. Warm every URL in the same
verification set with anonymous public requests until the intended cache owner reports stable
fresh behavior, then capture the after measurement with the same URL set and measurement mode as
the pre-change baseline.

Using the real `perf-probe.py` flags:

```sh
python3 skills/wp-perf-audit/scripts/perf-probe.py \
  --site "$SITE_URL" --repeats 3 --label after --json after.json
python3 skills/wp-perf-audit/scripts/perf-probe.py \
  --diff before.json after.json
```

Use the existing pre-change JSON path in place of `before.json`. Keep `--site`, selected URLs,
`--repeats`, and full versus `--quick` mode comparable to the baseline. `perf-probe.py` measures
origin TTFB with unique cache-busting queries and edge TTFB on the bare visitor URL; do not merge
those two metrics when explaining the result.

Record the `--diff` output even when the expected metric did not move. A null result is valid
evidence. If the warm after-run regresses, do not explain it away with the cold-cache effect once
the cache status is stable.

## When verification fails

**Roll back first, diagnose second.** Follow the captured [rollback procedure](rollback.md), purge
the restored representation through the same affected layers in inner-to-outer order, and verify
service restoration from the public visitor path.

Stop the change when any required URL, template, or language is stale or broken; when a `5xx` or
PHP fatal appears; when the intended cache owner cannot be identified; or when evidence conflicts.
Do not stack another speculative fix onto an unverified production state. Preserve the failed
response, timestamps, logs, purge results, and measurement files for diagnosis after service is
restored.

## Record evidence

The report must cite observations, not assert success. Store enough evidence for another operator
to reproduce the conclusion:

| Field | Record |
|---|---|
| Change | Change-plan ID and approved summary |
| Request | Timestamp, anonymous method, requested URL, final URL, and language/template/variant |
| Response | Status, changed marker or asset hash, bounded relevant excerpt, and validators |
| Cache | Detected layer/value, purge action and scope, cache headers before/after/warm, and `Age` |
| Health | URLs checked, unexpected redirects, PHP errors/warnings, `5xx`, and relevant log result |
| Measurement | Baseline JSON, after JSON, warm-up evidence, `--diff` output, and expected metric result |
| Rollback | Verified snapshot artifact and the restoration path if verification fails |

Do not record credentials, session cookies, authorization headers, private customer content, or
unbounded production logs. A concise body marker or cryptographic asset hash is usually enough.

## Copyable checklist

- [ ] Anonymous public fetch contains the changed markup, header, behavior, or asset bytes.
- [ ] Cache header/status plus body/hash proves a fresh copy, then stable warm delivery.
- [ ] No unexpected redirect, PHP fatal/warning, blank response, or `5xx` appears on affected URLs.
- [ ] Every affected template has a representative public URL checked, including a negative control.
- [ ] Every affected language is fetched, purged as needed, and verified separately.
- [ ] Every measured URL is warm before the after-run; `perf-probe.py --diff` compares like with like.
- [ ] URLs, statuses, markers/hashes, cache headers, health checks, and measurement evidence are recorded.
- [ ] On any failure, rollback happens before diagnosis and the restored public state is verified.
