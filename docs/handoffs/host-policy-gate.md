<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Scope — make the documented hard gates real

**Status:** DONE · **Opened:** 2026-08-13 · **Owner:** maintainer

**All three are shipped.** The host gate reads a cited policy table for all 17 host classes and
cannot be talked past by the plan. Staging became a capability rather than a precondition — its
absence raises the evidence required, never blocks the work — after the operator corrected an
earlier draft that would have refused prod-only sites. The queue reading is settled as serial, with
a required `sequence_rationale` when a plan carries more than one change.

The scope below is kept because its reasoning is what a future gate should follow, and because the
`unconfirmable` escape hatch and the fail-closed rules are still the design in force.

## The problem in one test

```
plan: host_class = wpengine, change = activate WP Rocket (a page-cache plugin)
host-constraints.md:69 → wpengine: PROHIBITED; listed page caches are disallowed
                          (cited to WP Engine's own disallowed-plugin list)

validate_plan.py --preflight  →  Change plan VALID · Problems: 0
```

`validate_plan.py` never reads `host-constraints.md`. It refuses a change whose `risk_lane` is
already labelled `prohibited` — and the agent writes that label. The gate enforces a label, not a
policy, while three documents say otherwise.

The existing rule states the principle this one must inherit. `validate_risk_lane`'s docstring:
*"Derive the minimum lane from target.kind, never from plan assertions."* The host gate does the
opposite today: it believes the plan.

## It is not one gate, it is a class

Scoping the host gate surfaced siblings. `wp-perf-fix/SKILL.md` lists seven "hard gates … refusals,
not preferences". Each was checked against what a script actually enforces:

| Hard gate | Enforced by a script? |
|---|---|
| 2. No change without a verified snapshot | **Yes** — the artifact must exist on disk |
| 3. No change without per-change approval | **Yes** — `approval.granted` must be exactly `true` |
| 5. Staging-first *lane* for code targets | **Yes** — derived from `target.kind`, not read from the plan |
| 1. Host-constraint gate | **No** — verified above |
| 5. Staging-first *means staging exists* | **No** — see below |
| 6. One change at a time | **No** — see below |

**Staging existence is never checked, and the documented response to its absence is wrong.**
`capabilities.py` has no staging detection, the change-plan schema has no staging field, and
`validate_plan.py` mentions staging only as a lane name. Separately, `SKILL.md` hard gate 5 says
that if no staging exists, *"say so and stop rather than downgrading the lane."*

Stopping is the wrong answer. Most WordPress sites have no staging, and a skill that refuses to work
on them is not a safer skill — it is an unused one, or one whose gate gets talked around. The repo
already solved this exact shape on the audit side and should not solve it differently here:
`access-tiers.md` states that *"Tier 0 (a public URL, no credentials) is a complete audit of the
frontend and cache layers — not a degraded mode."* **Staging is a capability, not a precondition.**
See the design below.

**"One change at a time" is unreconciled rather than simply unenforced.** A plan carrying two changes
passes preflight (verified: exit 0). The loop diagram and hard gate 6 read as one-change-per-plan;
the schema's `changes` array and its "the whole plan is refused" language read as a queue executed
serially. Both are defensible and the documents do not say which is meant — so the first thing this
needs is a decision, not code.

**The shared shape**, and the reason to fix them together: *a documented refusal whose enforcement
depends on the agent having read a reference correctly earlier in the run.* The cure is the one
`validate_risk_lane` already names in its own docstring — derive the requirement from the
environment, never from the plan's assertion — and the one the report contract applied to the
deliverable. These are the same lesson, at the layer where being wrong changes a production site.

Everything below scopes the host gate, which is the largest of the three. Staging detection and the
one-change decision are sized at the end.

## What the host gate must decide

Given `host_class`, `target.kind`, and (for plugins) an identifier, return one of:

| Verdict | Meaning |
|---|---|
| `permitted` | The host documents this as supported. Still needs approval, snapshot, purge, verification. |
| `permitted-with-conditions` | Documented, but conditioned — e.g. only one cache plugin may be active. |
| `staging-first` | Allowed, but not directly against production. |
| `prohibited` | The host forbids it. Refuse the plan. |
| `unconfirmable` | No first-party documentation settles it. **Treated as `prohibited` until confirmed.** |

`unconfirmable` is the common case and the reason this is not a one-line fix — see the escape hatch
below, without which the gate would brick every audit on GoDaddy, `other`, or `unknown`.

## Data model

A `host-policy.json` beside the reference, keyed by `host_class`, each entry carrying a default
verdict per `target.kind`, plus the narrow exceptions the prose already records:

```json
{
  "schema_version": "1.0",
  "hosts": {
    "wpengine": {
      "summary": "prohibited",
      "by_target_kind": {
        "plugin-setting": "unconfirmable",
        "theme-file": "staging-first",
        "server-config": "prohibited"
      },
      "page_cache_plugins": { "permitted": [], "note": "first-party disallowed list" },
      "protected_paths": ["wp-config.php", "wp-content/object-cache.php"],
      "citations": ["https://wpengine.com/support/disallowed-plugins/"]
    }
  }
}
```

Three things make this authorable rather than a research project:

- **The research is already done.** Every verdict exists in `host-constraints.md` today, cited. This
  is transcription into structure, not new investigation — which is also why it is dangerous: a
  transcription slip in a *permissive* direction is the most damaging error this project can make.
- **`.json` is not scanned by `check_no_egress.py`** (`SCAN_SUFFIXES` is `.py .sh .mjs .js .yml
  .yaml`), so citation URLs can live in the data file next to the verdict they support.
- **Defaults collapse the matrix.** 17 hosts × 9 target kinds is 153 cells, but most hosts need a
  summary verdict plus two or three overrides.

## The escape hatch, without which the gate is unusable

`UNCONFIRMABLE` means *prohibited until the host confirms* — not *never*. An operator who has
obtained confirmation must be able to proceed, or the gate blocks legitimate work on the majority of
real sites and gets disabled in practice, which is worse than not having it.

Add an optional per-change `host_confirmation`:

```json
"host_confirmation": {
  "verdict": "permitted",
  "source": "GoDaddy support ticket 1234567, 2026-08-13",
  "scope": "Managed WordPress, WP Rocket activation on this account"
}
```

Rules, each one there to stop the hatch becoming a bypass:

- It only ever upgrades `unconfirmable`. It can **never** override a documented `prohibited` — that
  is the host's published policy, not a gap in ours.
- It is required to carry a `source` naming a human-checkable artifact. A bare `true` is refused.
- Presence of the field is not consent: per-change approval is still required separately.
- `host-constraints.md` already demands this ("Record the first-party documentation or support
  response used for the decision in the change plan"). Today nothing checks it.

## Fail-closed rules

The failure mode to design against is the fail-open class this validator already shipped once, where
a plan could set `approval.required: false` and exempt itself.

1. Unknown `host_class`, unknown `target.kind`, or a host missing from the policy file → `prohibited`.
2. A malformed or unreadable policy file → refuse the run. Never "no policy, no problem".
3. The plan cannot declare its own verdict. `host_confirmation` supplies evidence; the *verdict* is
   always computed from the table.
4. The existing `risk_lane: prohibited` refusal stays. An operator who knows more than the table
   must still be able to stop a change the table would permit.
5. **Permission is not suitability.** The gate says "not forbidden", never "safe" — the reference
   already carries this as its own section and the message wording must not blur it.

## Keeping the two files honest

Two files stating the same policy will drift, and a drifted permissive claim is the worst outcome
here. A `tools/check_host_policy.py` in CI asserts:

- Every `host_class` in the `docs/CONTRACTS.md` vocabulary appears in both the JSON and the summary
  table in `host-constraints.md` — no host silently missing, which would otherwise fail *open* into
  `unconfirmable` and look deliberate.
- The JSON's `summary` verdict matches the keyword in that host's summary-table row.
- Every `permitted` or `permitted-with-conditions` entry carries at least one citation. Permissive
  claims are exactly the ones that must be evidenced.

## Work, in delegatable units

| # | Unit | Depends on | Rough size |
|---|---|---|---|
| 1 | `host-policy.json` for all 17 hosts, transcribed from the prose with citations | — | Largest. Splits cleanly by host group |
| 2 | `validate_host_policy()` rule + `host_confirmation` handling in `validate_plan.py` | schema agreed | Moderate; mirrors `validate_risk_lane` |
| 3 | `tools/check_host_policy.py` consistency check + CI wiring | 1 | Small |
| 4 | Adversarial pairs — a prohibited change refused, and a **positive control** that a permitted one is still accepted | 1, 2 | Moderate |
| 5 | Doc corrections: `README.md`, `docs/CONTRACTS.md` (change-plan schema gains `host_confirmation`), `wp-perf-fix/SKILL.md`, a `TESTING.md` taxonomy row | 2 | Small |

Unit 4 is not optional. Without the positive control, every negative case would also pass against a
gate that simply refused everything — the vacuous-pass failure this repo has already paid for twice.

## The two siblings, sized

**Staging as a capability, not a precondition.** Staging must be *declared*, not inferred, for the
same reason `host_class` and `--local-root` are: nothing observable from outside proves a given URL
is this site's staging environment, and guessing wrong points a write at the wrong installation. But
its absence changes the *process*, not whether the work may proceed.

| | Staging declared | No staging |
|---|---|---|
| Code change (`theme-file`, `plugin-file`, `mu-plugin`) | Apply on staging, verify there, then promote | Permitted **with compensating controls**, below |
| Everything else | Unchanged | Unchanged |

The compensating controls exist because the risk being managed is a PHP fatal taking the site down.
Each is grounded rather than invented:

1. **Prefer the most reversible mechanism available.** A change that can be reverted without
   filesystem access is safer than one that cannot. `functions.php` is the worst of the three
   options — theme updates overwrite it, and a theme rollback does *not* restore the edit, so
   recovery needs a backup. Where the same effect can be had from a plugin or setting, take it.
2. **Syntax-check before writing**, where PHP is reachable (`php -l`). It catches the parse-error
   class outright, which is the largest share of edit-induced fatals.
3. **Verify what a visitor receives immediately after the write**, and roll back on a 5xx or on
   WordPress's critical-error page — the loop already requires this; here it becomes the trigger for
   an automatic revert rather than a reporting step.
4. **Check the safety net before relying on it.** WordPress 5.2+ Recovery Mode catches a fatal from a
   plugin or theme on a normal page load, pauses the offending component *for the admin session*, and
   emails a recovery link. Two documented limits matter: the **frontend still shows the critical-error
   page to visitors** meanwhile, and the recovery email can silently fail — WordPress's own
   documentation notes that when a fatal happens before a mail plugin loads, mail goes out through
   the web server and "might never reach the admin's inbox." It also does not cover cron or
   background tasks. So confirm the admin address can actually receive mail before treating Recovery
   Mode as the fallback, and never present it as making an edit safe.
5. **Say plainly, in the report, that the change went to production untested**, and record it under
   the deliberate-decisions section rather than leaving the reader to infer it.

Sources: [Recovery Mode](https://wordpress.org/documentation/article/recovery-mode/) ·
[Fatal error recovery in 5.2](https://make.wordpress.org/core/2019/04/16/fatal-error-recovery-mode-in-5-2/).

**This loosens a documented rule, deliberately.** Hard gate 5's "stop" becomes "proceed under
compensating controls, and say so." The gate that remains absolute is the host-policy one: a host
that forbids a change still forbids it, with or without staging.

**Worth noting for the managed hosts this skill targets:** WP Engine, Kinsta and Cloudways all
document one-click staging. On those, "no staging" is often "staging available and unused", so the
skill should say that the site's own host provides one rather than treating its absence as fixed.

**One change at a time.** Decide the intended reading first. If one-per-plan: cap `changes` at one
and the rule is three lines. If a serial queue: say so in `SKILL.md` and `CONTRACTS.md`, and the
enforcement belongs at execution instead. Either is fine; leaving both readings live is not.

## Decisions needed before unit 1 starts

1. **Scope of the first cut.** All 17 hosts, or the page-cache gate only across all hosts? The
   page-cache gate is where the documented harm is concentrated and it is the one the summary table
   already answers for every host.
2. **What happens to the prose file.** It stays authoritative for nuance and citations either way.
   The alternative — generating it from the JSON — would remove drift entirely but flatten writing
   that is doing real work.
3. **The one-change reading**, above — a documentation decision that gates a small code change.

## Re-verify before acting

```bash
python3 tools/adversarial_gate_tests.py                        # 47/47, 1 skipped
python3 skills/wp-perf-fix/scripts/validate_plan.py --selftest  # 11/11
```

Then reproduce the hole: a plan with `host_class: wpengine` activating a page-cache plugin must be
refused. Today it passes.
