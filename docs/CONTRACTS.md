<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Shared contracts — wp-perf-skills

Every script in `skills/*/scripts/` codes against this document. It is the single home for the
JSON schemas, the shared invariants, and the CLI conventions. Change it here first, then change
the scripts.

## Contents

- [Shared invariants](#shared-invariants) — binding on every script
- [CLI conventions](#cli-conventions)
- [The signal object](#the-signal-object) — the shape every claim takes
- [Schema: stack profile](#schema-stack-profile) (`fingerprint.py`)
- [Schema: metrics](#schema-metrics) (`perf-probe.py`)
- [Schema: capability profile](#schema-capabilities) (`capabilities.py`)
- [Vocabularies](#vocabularies) — the closed value sets

---

## Shared invariants

These hold for **every** script in this repo. A unit that violates one is wrong even if it
works.

1. **Python 3.9+, standard library only.** No `pip install`, no third-party imports, no
   vendored dependencies. Operators run these on unknown machines — often the same shared
   hosting boxes we are auditing. `curl` may be shelled out to; nothing else may be assumed.
2. **No network egress except the operator's target.** Requests go to the URL the operator
   passed and to hosts reachable from that page's own markup. No analytics, no telemetry, no
   version checks, no third-party APIs — with one exception: an explicitly operator-supplied
   API endpoint (e.g. a PageSpeed Insights key passed by flag or env). Hardcoded hostnames of
   any kind are a build failure; CI greps for them.
3. **`unknown` is a first-class value; never guess.** Every schema admits `"unknown"`. A wrong
   confident answer about someone's production stack is worse than no answer. This is the
   single most important rule in the repo.
4. **Every claim carries evidence.** No bare values in output — see
   [the signal object](#the-signal-object). If a script cannot say *why* it believes something,
   it does not get to believe it.
5. **Read-only.** Nothing in Phase 1 writes to, authenticates against, or mutates a target
   site. These scripts are safe to run against production by design, with no credentials.
6. **No magic constants.** Every threshold, timeout, and retry count is a module-level named
   constant with a comment explaining the value. `TIMEOUT = 47` with no rationale is rejected.
7. **Scripts solve, they don't defer.** Handle errors in the script with a useful message; do
   not emit a traceback and leave the agent to interpret it.
8. **Forward slashes everywhere.** No Windows-style paths, in code or docs.
9. **Deterministic output ordering.** Sort keys and lists so two runs diff cleanly. The whole
   point is comparing a before to an after.
10. **SPDX header on every file:** `# SPDX-License-Identifier: GPL-2.0-or-later`.

## CLI conventions

Every script supports:

| Flag | Meaning |
|---|---|
| `--json PATH` | Write the machine-readable document to PATH. `-` means stdout. |
| `--quiet` | Suppress the human-readable report; JSON only. |
| `-h`, `--help` | Usage, from the module docstring. |

Default behaviour with no `--json`: print the human-readable report to stdout only.

**Exit codes** — identical across all scripts:

| Code | Meaning |
|---|---|
| 0 | Ran to completion. (Findings of "unknown" are still a successful run.) |
| 2 | Usage error — bad flags, missing required argument. |
| 3 | Target unreachable — DNS failure, connection refused, total timeout. |
| 4 | Target reachable but not usable — e.g. non-HTML response where HTML was required. |

A partial result is **not** an error: if six of ten URLs respond, exit 0 and record the
failures in the per-URL `errors` array.

## The signal object

Every non-trivial claim in every schema uses this shape. This is what enforces invariant 4.

```json
{
  "value": "elementor",
  "confidence": "high",
  "evidence": [
    "html: 21 elements matching class prefix 'elementor-'",
    "html: stylesheet /wp-content/plugins/elementor/assets/css/frontend.min.css"
  ]
}
```

- `value` — a member of the field's vocabulary, or `"unknown"`. Never `null`, never `""`.
- `confidence` — `"high"` | `"medium"` | `"low"` | `"none"`. Use `"none"` only with
  `value: "unknown"`.
- `evidence` — array of short human-readable strings, each prefixed with its source:
  `html:`, `header:`, `dns:`, `url:`, `cookie:`, `probe:`. **Empty only when
  `value` is `"unknown"`.**

Confidence rubric — apply consistently:

| Confidence | Standard |
|---|---|
| `high` | A signal that is definitive for this value and effectively cannot be produced by anything else (a vendor-specific response header, a vendor-namespaced asset path). |
| `medium` | Two or more corroborating circumstantial signals, or one strong signal that a different product could in principle also emit. |
| `low` | A single circumstantial signal. Report it, but the agent must treat it as a hypothesis to confirm at a higher tier. |
| `none` | Nothing found. Pairs only with `"unknown"`. |

## Schema: stack profile

Produced by `fingerprint.py`. Consumed by both skills to decide which catalog sections apply.

```json
{
  "schema_version": "1.0",
  "tool": "fingerprint",
  "tool_version": "0.1.0",
  "generated_at": "2026-08-12T04:15:00Z",
  "target": "https://example.com/",
  "pages_probed": ["https://example.com/", "https://example.com/sample-page/"],
  "profile": {
    "is_wordpress":  { "value": true,               "confidence": "high",   "evidence": ["..."] },
    "wp_version":    { "value": "unknown",          "confidence": "none",   "evidence": [] },
    "builder":       { "value": "elementor",        "confidence": "high",   "evidence": ["..."] },
    "theme_slug":    { "value": "hello-elementor",  "confidence": "medium", "evidence": ["..."] },
    "theme_type":    { "value": "classic",          "confidence": "medium", "evidence": ["..."] },
    "server":        { "value": "nginx",            "confidence": "high",   "evidence": ["..."] },
    "php_version":   { "value": "unknown",          "confidence": "none",   "evidence": [] },
    "host_class":    { "value": "wpengine",         "confidence": "high",   "evidence": ["..."] },
    "cdn":           { "value": "cloudflare",       "confidence": "high",   "evidence": ["..."] },
    "multilingual":  { "value": "none",             "confidence": "medium", "evidence": ["..."] },
    "woocommerce":   { "value": false,              "confidence": "medium", "evidence": ["..."] },
    "multisite":     { "value": "unknown",          "confidence": "none",   "evidence": [] }
  },
  "cache_layers": [
    { "layer": "edge",        "value": "cloudflare-apo", "confidence": "high",
      "evidence": ["header: cf-cache-status: HIT", "header: cf-apo-via: tcache"] },
    { "layer": "page-plugin", "value": "unknown",        "confidence": "none", "evidence": [] }
  ],
  "notes": [
    "Host strips X-Powered-By; PHP version is not determinable at tier 0."
  ]
}
```

Rules:

- `profile` keys are **fixed** — always all present, `"unknown"` when not determined. Consumers
  index by key and must never have to check for absence.
- `cache_layers` is an array with **exactly one entry per layer** in the fixed order
  `edge`, `server`, `page-plugin`, `object` — `"unknown"` where undetermined. Fixed cardinality
  makes two profiles diffable.
- `is_wordpress`, `woocommerce` carry booleans or the string `"unknown"`; everything else is a
  string.
- `notes` explains *why* something is unknown when the reason is itself informative. This is
  what lets the agent say "the host strips this header" instead of silently omitting it.

## Schema: metrics

Produced by `perf-probe.py`. The before/after comparison document.

```json
{
  "schema_version": "1.0",
  "tool": "perf-probe",
  "tool_version": "0.1.0",
  "generated_at": "2026-08-12T04:15:00Z",
  "label": "baseline",
  "site": "https://example.com",
  "repeats": 3,
  "quick": false,
  "urls": [
    {
      "url": "https://example.com/",
      "http_status": 200,
      "origin_ttfb_ms": 1180.4,
      "edge_ttfb_ms": 210.7,
      "origin_ttfb_samples_ms": [1204.1, 1150.2, 1186.9],
      "edge_ttfb_samples_ms": [215.0, 208.3, 208.8],
      "cache_status": "HIT",
      "cache_header": "cf-cache-status",
      "requests": 84,
      "html_kb": 122.4,
      "css_kb": 310.8,
      "js_kb": 402.1,
      "img_kb": 1840.5,
      "font_kb": 96.0,
      "other_kb": 12.2,
      "total_kb": 2784.0,
      "unsized_resources": 1,
      "discovery_incomplete": false,
      "errors": []
    }
  ],
  "totals": {
    "url_count": 10,
    "all_urls_total_kb": 27840.0,
    "all_urls_requests": 840,
    "all_urls_unsized_resources": 3
  }
}
```

Rules:

- **`origin_ttfb_ms` and `edge_ttfb_ms` are never merged.** Origin is measured with a unique
  cache-buster per request so every hit is a genuine miss; edge is the bare URL as a visitor
  gets it. A blended number hides which problem the site has. This separation is the reason
  this script exists.
- Reported TTFB is the **median** of `repeats` samples; the raw samples ship alongside so an
  outlier is visible rather than averaged away.
- `*_kb` are the transferred kilobytes that were **actually measured** — `content-length` when
  the server provides it, otherwise the byte count of a compressed GET. Sizing falls back to GET
  because servers that compress text on the fly omit `content-length`, and some CDNs answer HEAD
  with a 4xx while serving GET normally.
- **Nothing unmeasured is ever counted as zero.** Resources that could not be sized are excluded
  from the sums and counted in `unsized_resources`; each one also appears in `errors`. A total is
  therefore a floor, not a guess, and `unsized_resources: 0` means it is complete.
  <details>
  <summary>Old pattern: strict null propagation (removed)</summary>

  An earlier revision nulled the entire bucket, and with it `total_kb`, as soon as one resource
  resisted sizing. On a live site a single third-party widget answering 400 to both HEAD and GET
  erased an 11 MB image total. Since both a before and an after run would null out the same way,
  it defeated the comparison the tool exists to make.
  </details>
- `discovery_incomplete` is `true` when a stylesheet could not be read, so resources it
  references are unknown **in number**, not merely in size. Distinct from `unsized_resources`,
  which counts resources that were found but could not be measured.
- `cache_status` is normalised to `HIT` | `MISS` | `BYPASS` | `DYNAMIC` | `unknown`, with the
  raw header name preserved in `cache_header` so the operator can see which layer answered.
- `errors` is per-URL and non-fatal. Failing URLs stay in the array with their error recorded.

`--diff A.json B.json` prints a comparison and exits 0. It must refuse (exit 2) when the two
documents have different `schema_version` values.

## Schema: capabilities

Produced by `capabilities.py`. Decides the access tier and which measurement paths are open.

```json
{
  "schema_version": "1.0",
  "tool": "capabilities",
  "tool_version": "0.1.0",
  "generated_at": "2026-08-12T04:15:00Z",
  "target": "https://example.com/",
  "tier": { "value": 0, "name": "public", "confidence": "high", "evidence": ["..."] },
  "access": {
    "public_url": true, "rest_api": true, "wp_admin": false,
    "wp_cli": false, "ssh": false, "deploy_path": false
  },
  "tools": {
    "curl":                 { "present": true,  "version": "8.7.1" },
    "python3":              { "present": true,  "version": "3.13.5" },
    "lighthouse_cli":       { "present": false, "version": null },
    "chrome_devtools_mcp":  { "present": false, "version": null },
    "psi_api_key":          { "present": false, "version": null },
    "wp_cli":               { "present": false, "version": null }
  },
  "can_measure":    ["origin-vs-edge TTFB", "payload weight", "render-blocking resources"],
  "cannot_measure": ["autoloaded option size", "slow queries", "cron spikes"],
  "notes": ["No browser-capable tool found; Core Web Vitals cannot be measured in this session."]
}
```

Rules:

- `tier.value` is the **highest fully-confirmed** tier, never an aspirational one. Confirmation
  means a capability was actually exercised, not merely configured. When no tier can be
  confirmed at all — for example a run with no target supplied — both `tier.value` and
  `tier.name` are the string `"unknown"` with `confidence: "none"`, per invariant 3. Consumers
  must handle a non-integer `tier.value`.
- An unauthenticated REST index proves the site is WordPress, **not** that the operator has
  admin access. It never on its own raises the tier above 0.
- `can_measure` / `cannot_measure` are human-readable and mutually exclusive. Together they are
  what the agent reports to the operator as the honest boundary of the audit.
- Detection is **presence-only and local** — no credential is used, no login attempted, no
  request authenticated. Establishing that `/wp-json/` returns an index is a public GET.

## Schema: change plan

Produced by `wp-perf-fix` **before it touches anything**, validated by
`skills/wp-perf-fix/scripts/validate_plan.py`, and only then executed. This is the
plan-validate-execute pattern: the agent writes down what it intends to do, a script checks the
intent against the host's constraints and this project's safety rules, and a failed validation
stops the run. A plan is cheap to reject; a half-applied change to production is not.

```json
{
  "schema_version": "1.0",
  "tool": "change-plan",
  "tool_version": "0.1.0",
  "generated_at": "2026-08-12T04:15:00Z",
  "site": "https://example.com",
  "host_class": "wpengine",
  "tier": 2,
  "baseline_metrics": "baselines/before.json",
  "cache_layers_present": ["edge", "page-plugin"],
  "changes": [
    {
      "id": "c1",
      "summary": "Remove the preload for a font family no rule references",
      "catalog_entry": "frontend/fonts-preloaded-unused.md",
      "risk_lane": "direct",
      "target": { "kind": "theme-file", "identifier": "functions.php" },
      "snapshot": { "required": true, "artifact": "snapshots/c1-functions.php.bak" },
      "approval": { "required": true, "granted": false },
      "purge_layers": ["page-plugin", "edge"],
      "expected_effect": { "metric": "total_kb", "url": "https://example.com/", "direction": "decrease" },
      "rollback": "Restore snapshots/c1-functions.php.bak and purge page-plugin then edge."
    }
  ]
}
```

Rules — each exists because violating it has a specific real-world cost:

- **`risk_lane`** is `direct` | `staging-first` | `prohibited`. A change is `prohibited` when the
  host forbids it; the validator rejects the whole plan rather than skipping the change, because
  a plan containing a prohibited action was built on a wrong understanding of the environment.
- **`snapshot.artifact` must exist on disk before execution.** `required: true` with a missing
  artifact fails validation. A change you cannot reverse is not a change you may make.
- **`approval.granted` must be `true` at execution time**, per change. Approval for one change is
  never approval for the next, and is never inferred from a general go-ahead.
- **`purge_layers` must be non-empty** whenever any cache layer is present, and every entry must
  be a layer the fingerprint actually found. A change purged on the wrong layer is a change that
  never shipped.
- **`expected_effect` is mandatory.** Stating the target metric *before* the change is what makes
  the after-measurement meaningful; without it, any result can be rationalized as success.
- **`catalog_entry`** is a path relative to `skills/wp-perf-audit/references/catalog/` and must
  resolve. It ties the change to the documented Fix, Verify and Rollback procedure.
- **`tier` must be sufficient for every `target.kind`** in the plan — a `theme-file` change needs
  tier 3, a `wp-option` change needs tier 2, and so on. Planning a change the access level cannot
  perform wastes an approval round-trip at best.

`target.kind` vocabulary: `theme-file` · `plugin-file` · `mu-plugin` · `wp-option` ·
`plugin-setting` · `builder-content` · `media` · `server-config` · `dns-or-cdn-setting`

## Vocabularies

Closed sets. `"unknown"` is always additionally valid. Extending a vocabulary means editing this
section in the same change.

**`builder`** — `elementor` · `divi` · `wpbakery` · `bricks` · `beaver-builder` · `oxygen` ·
`breakdance` · `brizy` · `thrive` · `block-editor` · `site-editor` · `classic-none`

**`theme_type`** — `classic` · `block` · `hybrid`

**`server`** — `nginx` · `apache` · `litespeed` · `openlitespeed` · `cloudflare` · `other`

**`host_class`** — `wpengine` · `kinsta` · `siteground` · `godaddy` · `cloudways` · `flywheel` ·
`pressable` · `rocket-net` · `hostinger` · `bluehost` · `pantheon` · `wpcom` · `wpvip` ·
`shared-cpanel` · `self-managed` · `other`

**`cdn`** — `cloudflare` · `cloudflare-apo` · `quic-cloud` · `bunny` · `keycdn` · `fastly` ·
`akamai` · `stackpath` · `aws-cloudfront` · `none` · `other`

**`cache_layers[].layer`** — `edge` · `server` · `page-plugin` · `object` *(fixed set, fixed order)*

**`cache_layers[].value`** — edge: any `cdn` value · server: `litespeed` · `nginx-fastcgi` ·
`varnish` · `batcache` · page-plugin: `wp-rocket` · `litespeed-cache` · `w3-total-cache` ·
`wp-super-cache` · `wp-fastest-cache` · `sg-optimizer` · `breeze` · `surge` · `cache-enabler` ·
object: `redis` · `memcached` · `apcu` · `object-cache-pro` · plus `none` for any layer

**`multilingual`** — `wpml` · `polylang` · `translatepress` · `weglot` · `gtranslate` ·
`multilingualpress` · `none`

**`tier.name`** — `public` (0) · `admin` (1) · `cli` (2) · `code` (3)
