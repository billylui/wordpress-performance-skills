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
- `perf-probe --delay SECONDS` sets a minimum interval between requests, enforced across all
  workers, for sites that rate-limit sustained probing.
- `perf-probe --user-agent STRING` overrides the request identity.
- `capabilities --local-root PATH` declares that a local checkout is the site being audited.
- `validate_plan --preflight` checks everything knowable before approval and snapshot exist, so
  the documented fix loop can pass its own gate.
- `skills/wp-perf-audit/references/measurement-objectives.md` — for every number the audit
  reports: the objective, the capability required, known providers in preference order, and the
  honest answer when a harness has none.
- `license` and `compatibility` frontmatter, so a conforming client can read the runtime
  requirements before executing anything.
- `tools/adversarial_gate_tests.py`, `tools/check_plugin_manifest.py`, and the specification's
  own `skills-ref` validator in CI.
- Code of conduct, issue templates, and a pull-request template.

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

### Fixed

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
