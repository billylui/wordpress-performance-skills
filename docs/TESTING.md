---
# Release contract — parsed by the /release-gate skill.
gate_id_cmd: "git rev-parse --short HEAD"
report_dir: docs/walkthroughs
stacks: []
---

<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Release Contract — wordpress-performance-skills

Every release runs this contract and writes a report to `docs/walkthroughs/<gate-id>.md`.

**What "ship" means here.** This repository has no deploy and no store build. What it ships is
*instructions an agent will follow against someone else's production WordPress site*, so the failure
mode is not a crash — it is a confident wrong claim, or advice that damages a live site. A release is
a merge to `main` that changes a `SKILL.md`, a catalog entry, a script, or a schema.

Rules: no PASS without evidence; no silent SKIP; quarantined rows stay visible in every report.

## 1. Always-on rows

Run on EVERY release regardless of diff. All are automated and all run in CI — a row is not
"checked" because CI is green in general, but because this gate ran it and recorded the output.

| ID | Class | Check | How | Budget |
|---|---|---|---|---|
| WP-SMOKE-01 | smoke | A tier-0 audit of a real public site completes and reports origin-vs-edge separately | `perf-probe.py --site <URL> --quick --repeats 1` | 2m |
| WP-GATE-01 | safety | The change-plan validator still refuses every fail-open shape | `validate_plan.py --selftest` → 11/11 | 1m |
| WP-GATE-02 | safety | The independently-authored adversarial suite passes | `tools/adversarial_gate_tests.py` | 2m |
| WP-DOC-01 | contract | Links resolve, references are one level deep, no time-sensitive claims | `tools/check_skill_docs.py` | 1m |
| WP-DOC-02 | contract | The report template still satisfies the report contract | `tools/check_report.py --template …` | 1m |
| WP-DOC-03 | contract | The report checker's own refusals still fire | `check_report.py --selftest` → 16/16 | 1m |
| WP-EGRESS-01 | promise | No third-party host literal anywhere in the shipped scripts | `tools/check_no_egress.py` | 1m |
| WP-PKG-01 | install | Manifests and the documented install command agree | `tools/check_plugin_manifest.py` | 1m |
| WP-SPEC-01 | conformance | Both skills validate against the Agent Skills reference implementation | `npx -y skills-ref@latest validate ./skills/*` | 2m |
| WP-SPEC-02 | conformance | `SKILL.md` bodies stay under 500 lines | CI step | 1m |
| WP-PY-01 | portability | Everything compiles on the 3.9 floor and a current release | CI matrix | 1m |

## 2. Surface map

Path globs → surface tags. Drives diff-based row selection.

| Glob | Surface |
|---|---|
| `skills/wp-perf-audit/scripts/**` | measurement |
| `skills/wp-perf-fix/scripts/**` | write-gate |
| `skills/*/SKILL.md` | procedure |
| `skills/wp-perf-audit/references/catalog/**` | catalog |
| `skills/wp-perf-audit/references/report-contract.md` | report |
| `skills/wp-perf-audit/references/findings-report-template.md` | report |
| `skills/wp-perf-fix/references/host-constraints.md` | host-policy |
| `docs/CONTRACTS.md` | schema |
| `.claude-plugin/**`, `README.md` | install |

## 3. Surface rows

Run when the diff touches that surface.

| ID | Surface | Check | How | Budget |
|---|---|---|---|---|
| WP-MEAS-01 | measurement | Origin and edge TTFB are still reported separately, never blended | Read the JSON from a live `--quick` run | 2m |
| WP-MEAS-02 | measurement | Nothing unmeasured is counted as zero; `unsized_resources` accounts for every gap | Full walk against a page with an unsizeable asset | 3m |
| WP-MEAS-03 | measurement | A capped or circuit-broken run is labelled a floor, not a page weight | Check `asset_cap_applied` and the `errors` array | 2m |
| WP-WRITE-01 | write-gate | Every fail-open shape is still refused, and the CONTROL plan is still accepted | `validate_plan.py --selftest` plus the adversarial pairs | 2m |
| WP-WRITE-02 | write-gate | A prohibited host policy still refuses the whole plan, not just the change | Adversarial suite | 1m |
| WP-PROC-01 | procedure | Every referenced file exists and is linked from `SKILL.md` | `check_skill_docs.py` | 1m |
| WP-PROC-02 | procedure | No script is invoked by a repository-root-relative path | `check_skill_docs.py` | 1m |
| WP-CAT-01 | catalog | Every per-host claim is cited to first-party documentation, or marked "confirm with the host" | Read the diff; an uncited permissive claim fails | 5m |
| WP-CAT-02 | catalog | The entry says when the defect is **not** worth fixing | Read the diff | 2m |
| WP-REPORT-01 | report | Contract, template and checker still agree | `check_report.py --selftest` and `--template` | 1m |
| WP-HOST-01 | host-policy | No permissive claim about a host's policy without a first-party citation | Read the diff | 5m |
| WP-SCHEMA-01 | schema | `docs/CONTRACTS.md` changed **before** the scripts, and every consumer still parses | Read the diff; run both skills' scripts | 3m |
| WP-INSTALL-01 | install | The documented install command matches the manifests | `check_plugin_manifest.py` | 1m |

**WP-CAT-01 and WP-HOST-01 are the two rows that cannot be automated and must not be skipped.** An
incorrect permissive claim about a host's policy is the most damaging error this project can make:
several managed hosts *remove* disallowed plugins from a site, so recommending one is a real-world
harm rather than a stylistic error. The fail-closed default exists because of this.

## 4. Escaped-bug taxonomy

One row per defect that reached a real run without a test catching it first. Every fix PR adds its
row. The locks stop each specific bug returning; **this table is what turns a one-off fix into
coverage, because it names the missing check rather than the missing line.**

| ID | Date | Bug (one line) | Miss-class | What would have caught it | Lock |
|---|---|---|---|---|---|
| WP-ESC-01 | 2026-08-12 | The change-plan validator failed open three ways: a plan could set `approval.required: false` or `snapshot.required: false` to exempt itself, and a code-file change could declare the `direct` lane and bypass staging-first | Self-test written by the implementer — it passed the whole time | A suite authored from the *contract* by someone who did not write the code, testing what the document must refuse rather than what the function does | `tools/adversarial_gate_tests.py` §"must not switch off the check inspecting it"; `validate_plan.py --selftest` cases 6–8 |
| WP-ESC-02 | 2026-08-12 | The probe identified as a bot, so WAFs and CDN bot rules answered with a challenge or a 403 and the probe timed an error page and reported it as the site's performance | No assertion on a default whose effect appears only against a live protected site | An invariant on the default itself — plus a check that `fingerprint.py` and `perf-probe.py` send the *same* string, since disagreement makes them describe different pages | `tools/adversarial_gate_tests.py` §"must not identify as a bot" (4 cases) — **added when this table was written; the fix had shipped with no lock at all** |
| WP-ESC-03 | 2026-08-12 | Skills invoked their scripts by a repository-root-relative path, so the first command of the audit was "No such file" once installed to `~/.claude/skills/` | Tested only from a checkout, never from an install location | A grep that fails the build on `python3 skills/*/scripts/…` appearing in any skill document | `tools/check_skill_docs.py:59` `REPO_RELATIVE_SCRIPT_RE` |
| WP-ESC-04 | 2026-08-13 | Requiring a high-confidence fingerprint before any write deadlocked real sites — GoDaddy is detected at `medium` by design — while leaving genuine contradictions unexamined, because the helper bailed out before the comparison ran | No test for the *interaction* of two rules; each looked correct alone | A pair: a medium-confidence agreeing fingerprint must be ACCEPTED, and a contradicting one REFUSED at the same confidence | `tools/adversarial_gate_tests.py` §"a fingerprint must belong to the plan's installation" (4 host_class cases incl. the medium-confidence control) |
| WP-ESC-05 | 2026-08-13 | A payload walk could not finish: ~130 resources on a page, and font CSS pointing at a staging domain that resolved but never answered, so every request burned the full timeout. The audit lost its byte breakdown entirely | No bound on wall-clock for an unbounded external dependency | A cap on the work, and a breaker on any single host that stops answering — the cap alone bounds the symptom, not the cause | `--max-assets`; `tools/adversarial_gate_tests.py` §"one dead host must not consume the whole payload walk" (7 cases incl. a positive control) |
| WP-ESC-06 | 2026-08-13 | The audit report had no fixed shape, so each run invented one. LCP, INP and CLS were not visible anywhere in the first real audit — an unmeasured metric vanished instead of appearing with a reason | The machine output was under contract; the human deliverable was not, and nothing checked it | A contract for the report plus a checker the agent runs on its own draft — the format cannot rest on an instruction read at the start of a long audit, because `SKILL.md` is loaded once and never re-read | `skills/wp-perf-audit/scripts/check_report.py` (16 self-test cases); CI validates the shipped template against the contract |

### How to add a row

Name the **miss-class**, not the bug. "Off-by-one in the loop" is not a miss-class; "no test for the
interaction of two rules" is, because it predicts the next bug. If the honest answer to "what would
have caught it" is "nothing here", say so and open the gap as its own row rather than writing a lock
that does not exist. Writing WP-ESC-02 above is what revealed that its fix had shipped with no lock.

## 5. Personas

This project has no user accounts. Its equivalent is **the stack a site is actually running**, since
every finding is only correct against the stack it was found on.

| Persona | Shape it exhibits | How to use |
|---|---|---|
| Seeded fixture site | Known defects, deterministic | `evals/fixtures/docker-compose.yml`, then `evals/fixtures/seed/seed.sh` |
| Elementor + Cloudflare + WPML | Builder bloat, edge-cached HTML, multilingual tax | The scenario JSONs under `evals/scenarios/` |
| Managed host with a disallowed-plugin policy | The fail-closed constraint gate | A plan declaring `host_class` for a host in `host-constraints.md` |
| No browser in the session | Core Web Vitals unmeasurable | Run the audit with no browser tool; every CWV row must say `unmeasured` with a reason |

**The last one is a required persona, not an edge case.** It is the most common real session, and it
is the one the report contract exists to make honest.

## 6. Tours

| Tour | Focus | Budget | When |
|---|---|---|---|
| Measurement | Origin vs edge stays separate; nothing unmeasured becomes zero | 5m | every release touching `scripts/` |
| Honesty | Every unmeasured metric has a reason; both honesty sections are non-empty | 3m | every release |
| Refusal | Each hard gate still refuses, and each CONTROL still passes | 5m | every release touching the write path |
| Install | Fresh install on a non-Claude-Code agent, then a tier-0 audit | 10m | before any release that changes packaging or `SKILL.md` structure |

## 7. Walkthrough procedure

1. `git rev-parse --short HEAD` for the gate id.
2. Run every always-on row, capturing the command and its actual output — not a summary of it.
3. `git diff --name-only main...HEAD`, map through §2, run the selected surface rows.
4. For non-automatable rows (WP-CAT-01, WP-HOST-01, WP-SCHEMA-01), read the diff and record the
   specific citation or contradiction found. "Looks fine" is not evidence.
5. Write `docs/walkthroughs/<gate-id>.md` with one line per row: ID, PASS/FAIL/SKIP, and the
   evidence. Reproduce §8 in full in every report.
6. Any FAIL blocks the release. A SKIP must name why and what would unblock it.

## 8. Quarantine

Checks this gate does NOT run, each with its unblock condition. Listed in every report so the gap
stays visible rather than being forgotten.

| Check | Why quarantined | Unblock condition |
|---|---|---|
| End-to-end non-HTML refusal (`perf-probe` exit 4) | Needs an HTTPS endpoint serving non-HTML; defaulting to a third-party host would break this project's own no-egress promise. The predicate is covered in-process; only the CLI path is unproven | Operator sets `WP_PERF_TEST_NONHTML_URL` |
| `wp-perf-fix` against a production host | Never executed against a real managed host. Purge paths and host-constraint tables are documentation-derived, not execution-verified | One low-risk change run end-to-end on a site the maintainer controls, ideally on a host with a published disallowed-plugin policy |
| Full builder × cache eval matrix | Only a subset of `evals/fixtures/` combinations has been run, so stacks nobody has pointed the audit at may be misread | Run {Elementor, Block/FSE, Divi, classic} × {page-cache plugin, server cache, none} and record coverage |
| Execution on a non-Claude-Code agent | Format conformance is proven — `skills-ref` passes and the cross-agent CLI lists both skills — but installation and execution have only been exercised on Claude Code | Install on one other agent and complete a tier-0 audit |

## 9. Hotfix lane

A hotfix is a correction to a **wrong claim already shipped** — an incorrect permissive statement
about a host's policy, a catalog entry recommending a change that damages a site, or a gate that
refuses to refuse. Nothing else qualifies; a new feature under time pressure is not a hotfix.

Lane = WP-GATE-01, WP-GATE-02, WP-DOC-01, WP-EGRESS-01, plus the surface rows for the touched
surface. Roughly 8 minutes. Everything else runs the full selection.

**WP-CAT-01 and WP-HOST-01 are never skipped, including in the hotfix lane** — a hotfix to a host
claim is precisely the change most likely to introduce another one.
