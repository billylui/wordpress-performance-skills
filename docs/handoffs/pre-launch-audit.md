<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Handoff — what a pre-launch claim audit found

**Status:** OPEN · **Opened:** 2026-08-13 · **Owner:** maintainer

An independent review was asked one question: does the documentation honestly describe what this
repository does? It read every capability claim and looked for the code behind it. Its verdict was
that some of the strongest safety claims are not backed, and that this should block a public launch.

The findings below were **re-verified here against the running code** before being written down.
Where the review was wrong, that is recorded too.

## 1. The host-constraint gate does not know any host's constraints — CONFIRMED, blocking

This is the serious one, because it is the promise the fix skill is built around.

**What the documentation says.** `README.md`: "It refuses a plan whose change the host prohibits."
`docs/CONTRACTS.md`: "a script checks the intent against the host's constraints."
`wp-perf-fix/SKILL.md`: preflight checks "no prohibited change for this host."

**What actually happens.** `validate_plan.py` never reads `host-constraints.md`. It refuses a change
whose `risk_lane` is **already labelled** `prohibited`. The label is written by the agent.

**Reproduced.** A plan declaring `host_class: wpengine` whose change activates WP Rocket — a page
cache that `host-constraints.md` marks PROHIBITED for WP Engine, citing their first-party disallowed
list — passes preflight with `Problems: 0`. Relabel the same change `risk_lane: prohibited` and it is
correctly refused, which confirms the mechanism works exactly as built and only as far as the label.

**Why it matters more than a wording bug.** The safety property rests entirely on the agent having
read a reference file and drawn the right conclusion, at the moment it wrote the plan. That is the
same assumption the report contract was built to remove: a `SKILL.md` is loaded once and never
re-read, so guidance that must hold late in a run cannot rest on a paragraph read early in it. The
report contract answered that with a script. This gate has not been given one, and the cost of it
being wrong is higher — several managed hosts *remove* a disallowed plugin from a live site.

**Two honest ways to close it.** Either encode the policy so the validator can check it — a
machine-readable table keyed by `host_class` and `target.kind`, fail-closed on anything unlisted —
or correct every claim to say precisely what is enforced: that the validator refuses a change the
plan itself labels prohibited, and that identifying prohibition is the agent's job. The first is the
fix; the second is the minimum. Shipping neither is what should block launch.

## 2. `unmeasured` discipline is not applied to the fingerprint's negative claims — CONFIRMED

`docs/CONTRACTS.md` invariant 3 is "`unknown` is a first-class value; never guess", and it calls
itself "the single most important rule in the repo." The fingerprint does not follow it in one
direction: an absence of public markers becomes `woocommerce: false`, `multilingual: none`, or
`is_wordpress: false`, rather than `unknown`.

The repository already knows this is wrong. Its own catalog entry for WooCommerce says a false result
"does not prove that no store exists", and warns that brochure-site caching advice applied to a store
can expose private state. A negative claim at tier 0 is precisely the case the invariant exists for.

## 3. Tier 3 is reported at high confidence without exercising a deploy — CONFIRMED

`docs/CONTRACTS.md` says a tier is confirmed only when "a capability was actually exercised, not
merely configured." `capabilities.py` reports tier 3 at `high` when a checkout is writable, is a git
worktree, and has any remote configured — none of which proves a deploy would land.
`references/access-tiers.md` already admits the remote was not exercised, so the two documents
disagree with each other.

## 4. "Every hit is a genuine miss" is stronger than the probe can prove — CONFIRMED

The cache-buster defeats a cache that varies on the query string. It does not prove an inner page or
object cache also missed, nor that PHP ran. The claim should say what the technique actually
achieves: it defeats query-varying caches, and the `cache_status` field reports what the layer said.

## 5. Uncited permissive host claims in the catalog — CONFIRMED, needs judgement

Six catalog entries state "No host-specific restriction applies", and
`docs/catalog-entry-template.md` instructs authors to write exactly that. Two entries go further and
say specific changes "are permitted" on named managed hosts, without citation.

This also falsifies a claim in [pre-publication.md](pre-publication.md), which says every per-host
claim is either cited or marked for confirmation.

Whether each is *wrong* is a judgement call — no host plausibly forbids removing an unused font
preload — but "permitted on WP Engine" is exactly the shape of claim this project says is the most
damaging error it can make, and the template should not be generating it by default.

## 6. Numbers with no artifact behind them — CONFIRMED, lower severity

The case study's campaign figures, and the CHANGELOG's "verified" entries, have no raw
`perf-probe` JSON, Lighthouse report, or walkthrough report in the repository. They are true and were
measured, but a reader cannot check them. Either land the artifacts or mark them as recorded
observations rather than reproducible evidence.

## Where the review was wrong

It reported the SPDX invariant as violated by 17 files including both `SKILL.md` files. Those two
carry YAML frontmatter that the Agent Skills specification defines, and an SPDX comment above it
would break the parse; `LICENSE` and `.gitignore` are also legitimate exceptions. The invariant's
wording should be narrowed to the file types it means, rather than the files being changed.

It also read `docs/TESTING.md` commands as unrunnable because the scripts are not on `PATH`. They are
shorthand for rows a human executes, and CI invokes them by full path. Worth making explicit, not a
defect.

## Re-verify before acting

```bash
python3 tools/adversarial_gate_tests.py          # 47/47, 1 skipped
python3 skills/wp-perf-fix/scripts/validate_plan.py --selftest   # 11/11
```

Then reproduce finding 1 directly: build a plan with `host_class: wpengine` whose change activates a
page-cache plugin, and run `validate_plan.py --preflight` against it. It should be refused. Today it
is not.
