<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Changelog

Notable changes to this project. Versions follow [semantic versioning](https://semver.org/);
until 1.0.0, minor versions may change the JSON schemas in `docs/CONTRACTS.md`.

## [Unreleased]

Everything here came out of pointing the skills at real WordPress sites and at the Agent Skills
specification. Almost every entry is a defect that only appeared under real use.

### Added

- `perf-probe --max-assets N` caps the payload walk. A real audit abandoned the walk after ten
  minutes and lost its byte breakdown; the same page capped at 60 finishes in 80 seconds.
  Resources are chosen in rotation across kinds so a capped breakdown still reflects the page,
  and `asset_cap_applied` marks the total as a floor over a sample.
- **`perf-probe` stops requesting a host after three consecutive timeouts.** `--max-assets`
  caps how many resources are sized, which bounds the symptom; it does not stop one unreachable
  host from consuming the whole budget. On a real audit, font CSS pointed at a staging domain
  that resolved but never answered, and every font request burned the full timeout. Only
  timeouts trip it — a refused or unresolvable host fails in milliseconds and is self-limiting —
  and the counter resets on any answered request, so a merely slow host recovers. Resources on a
  cut-off host are counted in `unsized_resources` with the reason, never as zero.
- `perf-probe --delay SECONDS` sets a minimum interval between requests, enforced across all
  workers, for sites that rate-limit sustained probing.
- `perf-probe --user-agent STRING` overrides the request identity.
- `capabilities --local-root PATH` declares that a local checkout is the site being audited.
- `validate_plan --preflight` checks everything knowable before approval and snapshot exist, so
  the documented fix loop can pass its own gate.
- `skills/wp-perf-audit/references/measurement-objectives.md` — for every number the audit
  reports: the objective, the capability required, known providers in preference order, and the
  honest answer when a harness has none.
- **`skills/wp-perf-audit/references/report-contract.md`** — the human deliverable is now under
  contract, as the JSON always was. Mandatory sections in a fixed order, opening with a scorecard
  whose ten rows are always present. The first real audit produced good content in an ad hoc
  shape, and the metrics a reader looks for first were not visible anywhere in it.
- **`check_report.py` validates a draft report before it is published** — sections present and in
  order, every scorecard row present, each row either a value with a rating from the published
  table or an explicit `unmeasured` with a reason, and no rating on a metric that has no value.
  A template is advice; a checker is a contract. It ships inside the skill, so the agent can run
  it on its own draft on any harness, with a `tools/` shim for use from a repository checkout.
- `wp-perf-fix` step 9 re-emits that same scorecard before and after with a delta column, reusing
  the audit's contract rather than defining a second one. A fixed before/after table is what makes
  a null result legible.
- `license` and `compatibility` frontmatter, so a conforming client can read the runtime
  requirements before executing anything.
- `tools/adversarial_gate_tests.py`, `tools/check_plugin_manifest.py`, and the specification's
  own `skills-ref` validator in CI.
- **`docs/TESTING.md`** — the release contract, plus an escaped-bug taxonomy with one row per
  defect that reached a real run before a test caught it. Each row names the **miss-class**
  rather than the bug, because a miss-class predicts the next defect and a bug only records the
  last one. Writing it immediately earned its place: the bot-User-Agent fix had shipped with no
  regression lock at all, so a refactor could have reverted the default and every check would
  still have passed. Four cases now assert it, including that `fingerprint.py` and
  `perf-probe.py` send the *same* string — on a bot-protected site, disagreement makes the two
  scripts describe different pages.
- **The host-constraint gate now reads the host's constraints.** `validate_plan.py` previously
  refused a change whose `risk_lane` the plan had *already labelled* `prohibited` — and the agent
  wrote that label — so a plan declaring `host_class: wpengine` while activating WP Rocket, a page
  cache WP Engine's own disallowed list forbids, passed with zero problems. The page-cache verdict
  for all 17 host classes now comes from `references/host-policy.json`, transcribed from
  `host-constraints.md` with its first-party citation, and is computed from `host_class` plus the
  change's own target. A plan cannot assert its way past it. An unmapped host is refused rather
  than exempt, and a missing policy file stops the run instead of waving it through.
- `host_confirmation` on a change carries **evidence, never a verdict** — a `source` a human could
  check and a `scope` saying what was confirmed. It unblocks a host whose policy is merely
  *unconfirmed*, which is most of them and without which the gate would block legitimate work on
  real sites. It can never override a published prohibition.
- `tools/check_host_policy.py` fails the build if the policy table and its human document drift,
  if a host is missing from either, or if a permissive verdict cites nothing.
- **Absence of a public marker is now `unknown`, not a negative claim.** `fingerprint.py`
  reported `woocommerce: false`, `multilingual: none` and `is_wordpress: false` at medium
  confidence when it found nothing — contradicting the invariant this project calls its most
  important. A CDN, an optimizer or a headless front end strips markers from sites that
  unmistakably have the thing, and a crawl of a few pages never reaches most of a site. The
  WooCommerce case had the clearest harm path: the catalog already warned that a false result
  "does not prove that no store exists", and that brochure-site caching advice applied to a store
  can expose private cart or order state. The observation survives as evidence — what was searched
  for, across how many pages — because "we looked and saw none" is useful; concluding `false` from
  it was not.
- **Three claims that outran their evidence, corrected.** A unique cache-buster defeats caches
  keyed on the query string; it does not prove PHP executed, so "every hit is a genuine miss"
  became a statement of what the technique actually achieves, with `cache_status` named as the
  evidence for how a request was served. `capabilities.py` reported tier 3 at `high` confidence
  from a writable git checkout with *some* remote configured — which proves neither reachability,
  nor credentials, nor that the remote owns production — and now reports `medium` and says what was
  not exercised; `access-tiers.md` had documented that gap while the code contradicted it.
- **Six catalog entries claimed "No host-specific restriction applies", and the entry template
  instructed authors to write it.** A defect class can be host-neutral, but the change *mechanism*
  is not: a WP Engine GitPush reverts direct edits to tracked files, Pantheon's Live code is
  read-only, and several platforms own the cache drop-ins. The template was fixed first, since it
  regenerates the claim on every new entry, and `check_skill_docs.py` now refuses the retired
  sentence. Two uncited "are permitted" claims about named managed hosts became conditions to
  confirm.
- **Staging is a capability, not a precondition.** It was never checked anywhere — not detected,
  not in the schema, not in the validator — while the skill said to "say so and stop" without it.
  Both halves were wrong: nothing enforced the rule, and the rule would have made the skill
  unusable on the majority of WordPress sites, which have no staging. `capabilities.py` gains
  `--staging-url` (declared, never inferred), and `validate_plan.py` refuses a **code** change that
  has neither staging nor stated `compensating_controls` — not for lacking staging, but for having
  no answer to how a PHP fatal would be survived. Database-backed changes are exempt: the snapshot
  already holds the prior value.
- **Staging proves safety, not speed**, and the difference is now written down. Managed staging
  commonly runs with page cache and OPcache disabled, so a before/after measured there is not
  evidence about production; the scorecard measurement always happens on production, warm.
  Promotion also depends on where a change lives — files are pushed, database changes are
  **re-applied**, because a database push discards everything written to the live site since the
  staging copy, including orders. `references/staging.md` carries this with its sources.
- **`changes` is a serial queue, and says why it is in that order.** A plan may carry several —
  performance work has real dependencies — but they execute strictly one at a time, and a plan with
  more than one now states `sequence_rationale`. Previously a two-change plan passed with no
  ordering stated at all, and the documents supported two different readings of what that meant.
- **Four gates that could be bypassed, or were never enforced.** An independent review of the
  whole session found them; each was reproduced before being fixed. The host-policy gate matched
  only a bare plugin slug, so `wp-rocket/wp-rocket.php` — the identifier WordPress itself stores in
  `active_plugins` — passed straight through it on a host that bans page caches. `staging.url`
  accepted any non-empty string, including the production URL, which would let a "staging-first"
  change run against production while appearing staged. The circuit breaker never covered
  stylesheet **discovery**, which is serial and runs before sizing — the exact path that caused the
  stall it was built for. And the adversarial suite had **never run in CI**, while `docs/TESTING.md`
  declared it an always-on row: every lock in it was unenforced.
- Code of conduct, issue templates, and a pull-request template.

### Verified

- **A second harness now runs the audit end to end.** Both skills were installed to another
  agent's skills directory, validated in place, and `wp-perf-audit` completed a tier-0 audit of a
  live production WordPress site there — a different harness on a different vendor's model, given
  only a plain-language request naming the skill and told nothing about how to run it. It
  resolved the skill directory through the documented discovery loop, ran the scripts in order,
  reported origin and edge TTFB separately, produced every mandatory report section in order, and
  ran the report checker on its own draft. All ten scorecard rows were present; the six the
  session could not measure each carried their own reason rather than one blanket line, and no
  rating was invented for any of them.
- The same run in that agent's default sandbox, which has no outbound DNS, reported the
  environment as the blocker instead of labelling the site unreachable, and fabricated no
  metrics — the behaviour the `compatibility` field exists to produce, observed for the first
  time.

### Changed

- **`host_class` is the operator's declaration; the fingerprint is a contradiction check.**
  Requiring high-confidence detection before any write meant a GoDaddy site could never be
  fixed, because GoDaddy is detected at medium by design.
- **Installation identity is exact canonical equality.** Containment treated a parent site at `/`
  as containing a separate installation at `/shop/`, and a dot-segment path as inside its own
  sibling. Ambiguous paths are now refused rather than normalized.
- **A local checkout no longer raises the access tier on its own.** Nothing about a directory on
  disk proves it is the site at a given address.
- `perf-probe` sends a browser User-Agent by default, matching `fingerprint`. A bot string is
  answered with a challenge or a 403 by many WAFs, so the probe was liable to time an error page
  and report it as the site's performance.
- Skills locate their own scripts instead of assuming a repository-relative path, and the
  fallback list leads with the cross-agent `.agents/skills/` convention rather than Claude Code's.
- Payload totals report measured bytes plus an explicit `unsized_resources` count. Strict null
  propagation let one unsizeable third-party asset erase an 11 MB image total.
- **An unmeasured metric now occupies a labelled row with a reason instead of vanishing.** A
  reader cannot tell a metric nobody measured from a healthy one when both look like silence, and
  the report format is what decides which of those a reader sees.
- The report format is stated as a standing instruction backed by a script, not as one numbered
  step. A skill's `SKILL.md` is loaded once and not re-read, so guidance that must hold at the end
  of a long audit cannot rest on a paragraph read at the start of it.
- The two browser traps that cost a real audit its paint numbers — a hidden pane recording no
  paint timing, and a load-only pass being unable to produce INP — moved from a reference file
  into the audit skill's body. Both look like an unsupported browser when they are not, and an
  agent that never loads the reference never learns to tell the difference.

### Fixed

- **The Mermaid diagrams rendered as run-together text on GitHub.** Every multi-line node label
  used `<br/>`, which only breaks a line where the renderer has `htmlLabels` enabled; GitHub
  sanitises Mermaid labels, so the tag was stripped and "Fingerprint" ran into "what stack is
  this?". Sixteen labels across four diagrams no longer depend on HTML at all — each is a single
  line, which renders the same on GitHub, in an editor preview and in any static generator.
- **The README claimed each skill directory was self-contained. It was not.** `wp-perf-fix` reaches
  into the audit skill in four places — `perf-probe.py` to measure before and after, and
  `check_report.py` plus the report contract to write the result. Both installers place the two as
  siblings so behaviour was always correct, but anyone following that sentence for a manual install
  would have ended up with a fix skill that could not measure or report.

- GoDaddy Managed WordPress is detected from its `x-gateway-*` headers; it previously reported
  `unknown`, which routed a real managed host to the most restrictive constraint lane.
- `theme_type` no longer claims `block` from `global-styles-inline-css` alone — WordPress emits
  that for classic themes too, and a live classic-theme site was misreported.
- `srcset` parsing follows the HTML rule that a candidate runs to whitespace, not to a comma.
  Splitting on every comma shattered Cloudflare image-resizing URLs, so every such image went
  unsized.
- REST detection no longer requires `routes` to be a JSON object. PHP encodes an empty array as
  `[]`, so hardened sites were misread as not WordPress.
- `perf-probe --quick` derives usability from HTTP status and content type rather than network
  reachability, so a 5xx or non-HTML response is no longer reported as a successful measurement.
- An HTTP-error stylesheet is treated as incomplete discovery instead of being parsed as CSS.
- `fingerprint --json` returns the usage exit code for an unwritable path, rather than the code
  reserved for an unusable target.
- The security policy's "report a vulnerability" link pointed at the pre-rename repository and
  returned 404.

### Security

- **The change-plan validator no longer lets a plan switch off the checks inspecting it.** A plan
  could set `approval.required: false` or `snapshot.required: false` and skip those gates
  entirely, and a code-file change could declare the `direct` lane and bypass staging-first.
  Safety requirements are now derived from the contract and the change's own target kind.
- A `--stack` fingerprint must belong to the site named in the plan, so evidence from one
  installation cannot authorize a change to another.

## 0.1.0 — first release

The initial cut: two skills, a defect catalog, three measurement scripts, and an evaluation
harness.

### Skills

- **`wp-perf-audit`** — read-only, safe against production. Fingerprints the stack, establishes
  the access tier, measures, attributes findings to defect classes, and reports what it could
  *not* check alongside what it found.
- **`wp-perf-fix`** — the guarded write loop. One change at a time, each with explicit approval, a
  rollback snapshot captured and verified first, a purge on the layer that actually holds the
  stale copy, and verification of what a visitor received.

### Catalog

20 defect classes across frontend, caching, backend, platform and plugins. Each entry is
self-contained, with per-stack detection and per-host fix guidance inline, and each says when the
defect is **not** worth fixing. Backend entries deliberately route to
[`WordPress/agent-skills`](https://github.com/WordPress/agent-skills) rather than duplicating its
profiling depth.

### Scripts

- `fingerprint.py` — builder, theme, cache layers, CDN, host class, multilingual plugin,
  WooCommerce and multisite, from public signals. Every claim carries evidence and a confidence.
- `perf-probe.py` — origin TTFB and edge TTFB kept strictly separate, plus a payload walk and
  before/after diffing.
- `capabilities.py` — the access tier, and an explicit list of what cannot be measured.
- `validate_plan.py` — a fail-closed gate over a change plan. Non-zero exit stops the run.

### Guarantees

- **No telemetry.** No analytics, no phone-home, no version checks. Enforced by
  `tools/check_no_egress.py` in CI, not merely promised.
- **Standard library only, Python 3.9+.** PHP 7.4 and MySQL 5.7 are first-class targets; a large
  share of real WordPress sites still run them.
- **`unknown` is a first-class value.** A confidently wrong claim about someone's production
  stack is worse than no claim.

### Known limits

- Core Web Vitals require a browser-capable tool in the session. Without one they are reported as
  unmeasured, never estimated.
- The stack matrix in `evals/fixtures/` is not yet exercised across every builder and cache
  combination, so stacks nobody has pointed it at may be misread. Reports of a misidentified
  stack are the most useful contribution.
- `wp-perf-fix` has been exercised against local fixtures, not a broad range of production hosts.
