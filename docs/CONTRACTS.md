<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Shared contracts — wordpress-performance-skills

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
11. **Each schema below carries its own `schema_version`, and they move independently.** The stack
    profile, the metrics document, the capability profile and the change plan are produced by
    different tools at different times; a change to one is not a change to the others. A consumer
    validating two documents needs one constant per schema. One shared constant reads as tidy right
    up to the first version that has to move on its own, at which point it silently rejects a
    document that was never wrong — so keep them separate even while the numbers agree.

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
  "schema_version": "1.1",
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
    "multilingual":  { "value": "unknown",          "confidence": "none",   "evidence": ["..."] },
    "woocommerce":   { "value": "unknown",          "confidence": "none",   "evidence": ["..."] },
    "multisite":     { "value": "unknown",          "confidence": "none",   "evidence": [] }
  },
  "cache_layers": [
    { "layer": "edge",        "value": "cloudflare-apo", "confidence": "high",
      "evidence": ["header: cf-cache-status: HIT", "header: cf-apo-via: tcache"] },
    { "layer": "server",      "value": "unknown",        "confidence": "none", "evidence": [],
      "operator_confirmed": { "value": "other", "tier": 2,
        "evidence": ["wp-cli: wp cache-gateway status → enabled"],
        "confirmed_by": "WP-CLI over SSH, 2026-08-13" } },
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
- **`server: "other"` means a server cache is proven to exist but its product is not identifiable.**
  Managed hosts front WordPress with their own gateway cache and announce it under a house header —
  GoDaddy's `x-gateway-cache-status` is one. The header proves the layer; it does not name a product
  in this vocabulary. `other` is how the profile says *there is a cache here and I cannot tell you
  what it is*, which is a different and more useful statement than `unknown`.
- `is_wordpress`, `woocommerce` carry booleans or the string `"unknown"`; everything else is a
  string.
- **A negative verdict needs evidence of absence, not absence of evidence.** Finding no public
  marker yields `"unknown"`, never `false` or `"none"`. A CDN, an optimizer or a headless front end
  strips markers from sites that unmistakably have the thing, and a crawl of a few pages never
  reaches most of a site. This is invariant 3 applied in the direction it is easiest to forget:
  `woocommerce: false` on a real store leads to brochure-site caching advice, which this project's
  own catalog warns can expose private cart or order state. The observation is still reported —
  the evidence string says what was looked for and across how many pages — because *"we looked and
  saw none"* is useful. Concluding `false` from it is not.
- **`operator_confirmed` is where a higher access tier gets to speak, and it never overwrites the
  public reading.** `fingerprint.py` sees only what a public HTTP response reveals. That is the
  right scope for it, but on a great many real sites it is not the whole truth: a managed host's
  server cache may announce itself under a name this script does not recognize, and an object cache
  is entirely server-side and emits nothing at all. Before this field existed there was nowhere to
  put what WP-CLI proved, so the fact landed in report prose wearing an invented confidence, and a
  change plan built on it was refused by `validate_plan.py` for disagreeing with a tier-0 profile
  that had simply not looked. **A layer nobody could see from outside is the common case on managed
  hosting, and a rule that refuses the common case gets argued around rather than obeyed.**

  It is optional, and when present carries `value` (from that layer's vocabulary), `tier` (1–3, the
  access level the evidence came from), `evidence` (non-empty, the commands or readings behind it),
  and `confirmed_by` (something a human could go and check). The sibling `value` / `confidence` /
  `evidence` fields keep reporting what the public probe saw, unchanged — a reader can always tell
  *"the probe could not see this"* from *"the operator proved it"*, which is the whole point.
  Consumers that only understand public signals ignore the field and behave exactly as before.

  It carries **evidence, never a verdict**, for the same reason `host_confirmation` does. And it may
  only ever *fill in* a layer the public probe left `unknown` — it can never contradict a positive
  public finding, because a script that watched the site answer outranks a claim typed into a file.
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
      "asset_cap_applied": false,
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
  cache-buster per request, which defeats any cache keyed on the query string; edge is the bare
  URL as a visitor gets it. **The buster proves the query-varying layers were bypassed, not that
  PHP executed** — an inner page or object cache that ignores the query string can still serve it.
  `cache_status` carries what the answering layer actually reported, and is the evidence for how
  the request was served. A blended number hides which problem the site has. This separation is the reason
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
- `asset_cap_applied` is `true` when `--max-assets` stopped the walk short. **A capped run's
  totals are a floor over a sample, never a page weight**, and the skipped resources are counted
  in `unsized_resources`. Selection is a deterministic round-robin across resource kinds rather
  than a sorted prefix, so a capped breakdown still reflects the page rather than the alphabet.
- **A host that stops answering is dropped from the walk, and its resources stay unsized.** After
  three consecutive timeouts from one host the probe stops requesting it, counts everything
  remaining on that host in `unsized_resources`, and records one line in `errors` naming the host
  and how many resources it covers. Only timeouts trip this: a refused or unresolvable host fails
  in milliseconds and is self-limiting, while one that accepts the connection and never answers
  burns the full timeout every time. The counter resets on any answered request, so a merely slow
  host recovers rather than being written off for the rest of the run. This adds no field — the
  evidence is in `errors`, and the totals stay a floor exactly as they do under `--max-assets`.
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
  "staging":        { "declared": false, "url": "unknown" },
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
- `staging` records an operator declaration via `--staging-url`, never an inference. It is
  reported so the fix skill can choose a process, and its absence is a normal state rather than a
  problem: it is `{"declared": false, "url": "unknown"}` on most sites.
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
  "schema_version": "1.1",
  "tool": "change-plan",
  "tool_version": "0.1.0",
  "generated_at": "2026-08-12T04:15:00Z",
  "site": "https://example.com",
  "host_class": "wpengine",
  "tier": 2,
  "baseline_metrics": "baselines/before.json",
  "cache_layers_present": ["edge", "page-plugin"],
  "staging": { "url": "https://staging.example.com", "confirmed_by": "MyKinsta environment" },
  "sequence_rationale": "Purge configuration first, so the second change is measured warm.",
  "changes": [
    {
      "id": "c1",
      "summary": "Remove the preload for a font family no rule references",
      "catalog_entry": "frontend/fonts-preloaded-unused.md",
      "risk_lane": "direct",
      "target": { "kind": "theme-file", "identifier": "functions.php", "operation": "configure" },
      "snapshot": { "required": true, "artifact": "snapshots/c1-functions.php.bak" },
      "approval": {
        "required": true,
        "granted": true,
        "evidence": {
          "source": "Operator message in session 2026-08-12T04:31Z, quoted in the run record",
          "scope": "Remove the unused Lora preload from functions.php on production. Only this."
        }
      },
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
- **`target.operation` says what is being done to the target, not merely what the target is.** It is
  required on every change. `target.kind` answers *what sort of thing is this* — a file, an option, a
  plugin's settings — and that is what decides tier and risk lane. It cannot answer *what is
  happening to it*, and two of this project's safety rules turn entirely on that: a host's
  disallowed-plugin policy governs **adding** a cache and has nothing to say about removing one, and
  the rule against acting autonomously governs installs, activations and removals rather than
  configuration. Scoping either of those by `kind` gets both wrong in both directions at once —
  refusing safe work and waving through consequential work.
- **The host's page-cache policy is checked against a table, not read from the plan, and it is
  scoped by operation.** `references/host-policy.json` carries each host's verdict, transcribed from
  `host-constraints.md` with its first-party citation, and `validate_plan.py` computes the verdict
  from `host_class` plus the change's own target. A plan cannot assert its way past it, for the same
  reason `approval.required: false` is refused rather than obeyed. An unmapped host is refused, not
  exempt.

  **`disable`, `deactivate` and `remove` are exempt, and every other operation is gated.** A
  disallowed-plugin list exists to stop a cache being *added* to a site the host will then strip it
  from; no such policy can be violated by turning one off. Gating those three refused the safest
  change available while a relabel let the same real change through, which taught the operator to
  route around the gate rather than obey it. The exemption is narrow and the default is to refuse,
  because `configure` on a caching plugin can perfectly well mean switching page caching on.

  Scope is the change's **identifier**, matched across every `kind`. Earlier revisions matched only
  `plugin-setting` and `plugin-file`; `active_plugins` is a `wp-option`, and it is the option
  WordPress stores activation in.
- **`host_confirmation`** is optional, and carries **evidence, never a verdict**:
  `{"source": "…", "scope": "…"}`, both non-empty. It upgrades an `unconfirmable` host — the common
  case, and without it the gate would block legitimate work on most real sites. It can **never**
  override a published prohibition, and it is not approval: per-change approval is still separate.
- **`snapshot.artifact` must exist on disk before execution.** `required: true` with a missing
  artifact fails validation. A change you cannot reverse is not a change you may make.
- **`approval.granted` must be `true` at execution time and must carry `approval.evidence`**, per
  change. Approval for one change is never approval for the next, and is never inferred from a
  general go-ahead. `evidence` is `{"source": "…", "scope": "…"}`, both non-empty, on exactly the
  pattern `host_confirmation` uses: `source` says where the consent is recorded so a human could go
  and read it back, `scope` says what was actually agreed to.

  A validator that reads a file cannot verify that a human consented — that is true and it stays
  true. What it *can* refuse is a bare boolean, which is a document asserting its own compliance and
  is the same shape as the `approval.required: false` this contract already refuses rather than
  obeys. Requiring the plan to write down *whose* approval and *for what* turns a self-assertion into
  a recorded attestation someone can later check, and makes a fabricated one a deliberate act rather
  than a default. **The last gate before a production write is still the agent, and it should be.**
- **Operations with consequences beyond performance need approval that names them.** `install`,
  `activate`, `deactivate`, `remove`, `update` and `replace` reach past the change itself — they can
  take a site down, delete content, or alter what other software on the box does. Each is refused
  unless `approval.evidence.scope` names that operation, so a general approval to "fix the fonts"
  cannot be spent on deactivating a plugin. This is the first mechanical backstop under the
  never-act-autonomously rule; before it, that rule rested entirely on the agent remembering it.
- **`purge_layers` must be non-empty** whenever any cache layer is present, and every entry must be
  a layer the fingerprint found **or that the stack profile records as `operator_confirmed`**. A
  change purged on the wrong layer is a change that never shipped — and on managed hosting the layer
  holding the stale copy is routinely the one no public header names.
- **`cache_layers_present` may not contradict the `--stack` profile, but it may go beyond it.** A
  layer the fingerprint positively found must be listed; a layer it found as `none` must not be. A
  layer it left `unknown` is a layer nobody looked at from outside, and the plan may list it —
  provided the stack profile carries `operator_confirmed` evidence for it. The plan still never gets
  to assert a layer into existence; the evidence lives in the stack document, next to its tier.

  Exact set equality was the earlier rule, and on a managed host it deadlocked: declaring the truth
  was refused for disagreeing with the profile, and declaring only what the profile saw made the
  real cache layer unpurgeable. There was no honest plan.
- **`expected_effect` is mandatory.** Stating the target metric *before* the change is what makes
  the after-measurement meaningful; without it, any result can be rationalized as success.
- **`catalog_entry`** is a path relative to `skills/wp-perf-audit/references/catalog/` and must
  resolve. It ties the change to the documented Fix, Verify and Rollback procedure.
- **A `--stack` fingerprint must name exactly the same site as the plan.** The comparison is
  canonical equality — scheme, host, effective port and path, with a trailing slash ignored — and
  a URL whose path contains a dot segment or an encoded separator is **refused rather than
  normalized**, because this code cannot know how the origin resolved it.

  <details>
  <summary>Old pattern: containment (removed after three review rounds)</summary>

  Earlier revisions tried to infer whether the fingerprint's target lay *inside* the plan's site.
  Comparing origins treated `https://example.com/site-a/` and `/site-b/` as one site. Adding path
  containment then treated a parent installation at `/` as containing a separate one mounted at
  `/shop/`, and `/site-a/../site-b/` resolved server-side to a sibling while still looking
  contained. URL strings cannot prove installation identity, so the contract narrowed instead:
  both documents are produced by this project's own tools and can carry the identical site string
  by construction.

  The accepted cost is that a fingerprint taken against a subpage no longer matches a plan whose
  `site` is the root — re-run `fingerprint.py` against the site root.
  </details>
- **`staging` is declared, never inferred, and is not a gate.** Most WordPress sites have no
  staging environment, and refusing to work on them would make the skill unused rather than safe —
  the same reasoning that makes tier 0 a complete audit rather than a degraded one. Its absence
  changes the evidence required, not whether work proceeds. When present it carries `url` and a
  `confirmed_by` naming something a human could check; nothing observable from outside proves a URL
  is this site's staging environment.
- **A file-backed change needs staging OR stated `compensating_controls`.** `theme-file`,
  `plugin-file` and `mu-plugin` changes can fatal a site, so a plan that has neither is refused —
  not for lacking staging, but for having no answer to how a fatal would be survived.
  `compensating_controls` carries `mechanism`, `verification` and `rollback_trigger`, all non-empty.
  Database-backed kinds are exempt: the snapshot already holds the prior value and rollback is
  setting it back. See [staging.md](../skills/wp-perf-fix/references/staging.md).
- **Staging proves safety, not speed.** Managed staging commonly runs with page cache and OPcache
  disabled, so a before/after measured there is not evidence about production. The scorecard's
  measurement always happens on production, warm.
- **Promotion depends on where the change lives.** File-backed changes are promoted by pushing
  **files only**. Database-backed changes are **re-applied** on production and never promoted by a
  database push, which would discard everything written to the live site since the staging copy —
  comments, sign-ups, orders.
- **`changes` is a serial queue, executed one at a time.** More than one is legitimate, because
  performance work has real dependencies. A plan carrying several must state
  `sequence_rationale`: what each change depends on, and what would be mis-attributed in another
  order. Ids stay unique so a report and a rollback can name one unambiguously.
- **`tier` must be sufficient for every `target.kind`** in the plan — a `theme-file` change needs
  tier 3, a `wp-option` change needs tier 2, and so on. Planning a change the access level cannot
  perform wastes an approval round-trip at best.

`target.kind` vocabulary: `theme-file` · `plugin-file` · `mu-plugin` · `wp-option` ·
`plugin-setting` · `builder-content` · `media` · `server-config` · `dns-or-cdn-setting`

`target.operation` vocabulary: `configure` · `enable` · `disable` · `install` · `activate` ·
`deactivate` · `remove` · `update` · `replace`

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
`varnish` · `batcache` · `other` · page-plugin: `wp-rocket` · `litespeed-cache` · `w3-total-cache` ·
`wp-super-cache` · `wp-fastest-cache` · `sg-optimizer` · `breeze` · `surge` · `cache-enabler` ·
object: `redis` · `memcached` · `apcu` · `object-cache-pro` · plus `none` for any layer

**`multilingual`** — `wpml` · `polylang` · `translatepress` · `weglot` · `gtranslate` ·
`multilingualpress` · `none`

**`tier.name`** — `public` (0) · `admin` (1) · `cli` (2) · `code` (3)
