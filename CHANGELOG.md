<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Changelog

Notable changes to this project. Versions follow [semantic versioning](https://semver.org/);
until 1.0.0, minor versions may change the JSON schemas in `docs/CONTRACTS.md`.

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
