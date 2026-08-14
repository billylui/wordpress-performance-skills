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

**A count in the How column is a floor, and floors only ever go up.** A self-test that reports fewer
cases than the row says has had cases deleted, which is the thing worth catching. Raise the number in
the same change that adds cases. These two had already drifted before anyone noticed — WP-DOC-03 read
`16/16` while the checker had been at `24/24` for some time — and a row whose expected value is wrong
is a row nobody is really checking. Prefer WP-GATE-02's shape where you can: it names no count, so it
cannot go stale.

## 1. Always-on rows

Run on EVERY release regardless of diff. All are automated and all run in CI — a row is not
"checked" because CI is green in general, but because this gate ran it and recorded the output.

| ID | Class | Check | How | Budget |
|---|---|---|---|---|
| WP-SMOKE-01 | smoke | A tier-0 audit of a real public site completes and reports origin-vs-edge separately | `perf-probe.py --site <URL> --quick --repeats 1` | 2m |
| WP-GATE-01 | safety | The change-plan validator still refuses every fail-open shape | `validate_plan.py --selftest` → ≥ 36/36 | 1m |
| WP-GATE-02 | safety | The independently-authored adversarial suite passes | `tools/adversarial_gate_tests.py` | 2m |
| WP-DOC-01 | contract | Links resolve, references are one level deep, no time-sensitive claims, no blanket host permission | `tools/check_skill_docs.py` | 1m |
| WP-DOC-02 | contract | The report template still satisfies the report contract | `tools/check_report.py --template …` | 1m |
| WP-DOC-03 | contract | The report checker's own refusals still fire | `check_report.py --selftest` → ≥ 30/30 | 1m |
| WP-EGRESS-01 | promise | No third-party host literal anywhere in the shipped scripts | `tools/check_no_egress.py` | 1m |
| WP-PKG-01 | install | Manifests and the documented install command agree | `tools/check_plugin_manifest.py` | 1m |
| WP-HOST-02 | safety | The host policy table and its human document still agree | `tools/check_host_policy.py` | 1m |
| WP-OBJ-01 | contract | The measurement objectives constant and its human table still agree | `tools/check_measurement_objectives.py` | 1m |
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
| WP-MEAS-04 | measurement | The capability gap list never blocks a run, and never turns "not confirmable from here" into a claim of absence | `capabilities.py` with no provider present exits 0; every gap whose provider cannot be confirmed locally carries `operator_can_supply: "unknown"`, not `true` | 2m |
| WP-WRITE-01 | write-gate | Every fail-open shape is still refused, and the CONTROL plan is still accepted | `validate_plan.py --selftest` plus the adversarial pairs | 2m |
| WP-WRITE-02 | write-gate | A prohibited host policy still refuses the whole plan, not just the change | Adversarial suite | 1m |
| WP-WRITE-03 | write-gate | A code change carries staging or stated compensating controls; a queued plan states its ordering | Adversarial suite | 1m |
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
| WP-ESC-07 | 2026-08-13 | The host-constraint gate never read the host constraints. `validate_plan.py` refused a change whose `risk_lane` the plan had already labelled `prohibited` — and the agent wrote that label — so a plan declaring `host_class: wpengine` while activating WP Rocket, which WP Engine's own disallowed list forbids, passed with zero problems | A documented refusal with no script behind it: enforcement rested on the agent having read a reference correctly earlier in the run | Asking of each documented hard gate "which script enforces this?" — three of seven had no answer. The cure is the one `validate_risk_lane` already names: derive the requirement from the environment, never from the plan's assertion | `references/host-policy.json` + `validate_host_policy()`; 11 adversarial cases incl. three positive controls; `tools/check_host_policy.py` fails the build if the table and the prose drift |
| WP-ESC-08 | 2026-08-13 | The fingerprint turned absence of evidence into a negative claim: no public markers yielded `woocommerce: false`, `multilingual: none` and `is_wordpress: false` at medium confidence, contradicting the invariant the repo calls its most important. A false WooCommerce verdict leads to brochure-site caching advice, which the project's own catalog warns can expose private cart or order state | An invariant enforced in one direction only — every reviewer checked that a positive claim carried evidence; nobody checked that a negative one did | Running every detector against a marker-free page and asking which invent a verdict. Three of eleven did; the rest already returned `unknown`, so the correct pattern was in the same file | `tools/adversarial_gate_tests.py` §"absence of evidence must not become a negative claim" — 8 cases incl. three positive controls that real markers still yield a definite answer |
| WP-ESC-09 | 2026-08-13 | Three documented claims outran their evidence: "every hit is a genuine miss" (a query-string cache-buster does not prove PHP ran), tier 3 reported at `high` confidence from a configured-but-unexercised git remote, and six catalog entries plus the entry template asserting "No host-specific restriction applies" | Prose reviewed for accuracy but never against the code that produces it, and a TEMPLATE that regenerated the third one on every new entry | Asking of each confident sentence "what would have to be true, and did we check it?" For the third, fixing the template rather than the six copies — otherwise entry seven reintroduces it | `tools/check_skill_docs.py` refuses the retired blanket-permission sentence; `access-tiers.md` and `capabilities.py` now agree on `medium`; `cache_status` named as the evidence in place of the cache-buster |
| WP-ESC-10 | 2026-08-13 | Staging existence was never checked anywhere — not detected, not in the schema, not in the validator — while `SKILL.md` said to "say so and stop" without it. Both halves were wrong: nothing enforced the rule, and the rule itself would have made the skill unusable on the majority of WordPress sites, which have no staging | A documented refusal with no script behind it, AND a rule written for the ideal environment rather than the common one — a gate that refuses the normal case gets argued around, not obeyed | Asking not just "which script enforces this?" but "what happens on a site that does not have it?" The second question is what turned a blocker into a capability | `tools/adversarial_gate_tests.py` §"staging changes the process" — 6 cases incl. three positive controls; `validate_staging()` refuses a code change with neither staging nor stated compensating controls |
| WP-ESC-11 | 2026-08-13 | Four gates could be bypassed or were unenforced: the host-policy gate matched only a bare plugin slug, so `wp-rocket/wp-rocket.php` — the canonical WordPress plugin identifier — sailed past it; `staging.url` accepted any string including the production URL; the circuit breaker never covered stylesheet DISCOVERY, the exact path that caused the stall it was built for; and the whole adversarial suite had never run in CI while `docs/TESTING.md` declared it always-on | A guard tested only with the input its author had in mind, and a release contract asserting coverage nobody verified | Asking of each new guard "what is the most ORDINARY way to write this input?" — not the most exotic. And running the release contract's own always-on list against the CI file | `tools/adversarial_gate_tests.py` §host-policy identifier forms, §staging.url validation, §breaker covers discovery; the suite now runs in CI |

| WP-ESC-12 | 2026-08-14 | The host-policy gate was scoped by `target.kind`, so the identical real change — turning a page cache's crawler off on a GoDaddy site — was REFUSED as `plugin-setting` and PASSED as `wp-option`, and `wp-option`/`active_plugins`, the option WordPress stores activation in, passed too. The relabel is what the operator actually used | A guard scoped by the **type of the thing being changed** rather than by the **operation being performed on it**. The schema had no way to say which, so the gate keyed on the nearest available field and got it wrong in both directions at once: refusing the safest change available (a page-cache policy governs adding a cache and cannot be violated by removing one) while a rename walked the same change past it | Asking of a gate not only "what is the most ORDINARY way to write this input?" — WP-ESC-11's question, asked of the identifier and never of the kind — but also **"what happens when this change runs in the opposite direction?"** A refusal that reads the same for `install` and `disable` is not reasoning about the risk it names | `target.operation` in the change-plan schema; `validate_host_policy` gates on operation and exempts `disable`/`deactivate`/`remove`; `tools/adversarial_gate_tests.py` §A and §B, each with the positive control that adding is still refused |
| WP-ESC-13 | 2026-08-14 | `approval.granted: true` was a bare boolean the plan asserted about itself, and the execution-readiness gate obeyed it. The never-act-autonomously hard gate had no script behind it at all for installs, activations, removals and updates | **A fail-open shape fixed at the site that was reported and not at its siblings.** WP-ESC-01 found and locked `approval.required: false` — "a plan must not switch off the check inspecting it" — and `approval.granted: true` is the same shape one field over, in the same object, left untouched. The repo already had the right pattern in the same file: `is_valid_host_confirmation`, "the field carries EVIDENCE, never a verdict" | Enumerating every field a plan can assert about its own compliance the first time one is found, instead of fixing the cited one. Then asking of each documented hard gate "which script enforces this?" — WP-ESC-07's question — and re-asking it after every change to the gate list, since two of the seven had quietly become unenforced | `approval.evidence` required at execution readiness; `validate_operation` requires a high-consequence operation to be named in `approval.evidence.scope`; `tools/adversarial_gate_tests.py` §C and §D with controls on both sides |
| WP-ESC-14 | 2026-08-14 | `cross_check_stack` demanded the plan's `cache_layers_present` exactly equal the layers the fingerprint found. At tier 3 on managed hosting the truth was `{edge, server, object}` and the public probe saw `{edge}`, so declaring the truth was refused and declaring the probe's view left the layer that actually held the stale copy unpurgeable. **There was no honest plan** | A consistency rule between two documents where **one of them structurally cannot know what the other asserts.** `fingerprint.py` reads public HTTP by design; a managed host's gateway and a Redis object cache are invisible to it. Equality was the right relation between two views of the same world and the wrong one between a partial view and a fuller one — which is WP-ESC-10's lesson again (a rule written for the ideal environment refuses the common case and gets argued around) reaching a second, unrelated gate | Asking of every cross-document consistency check **"what can each side actually see?"** before choosing the relation between them. Where one side is a strict subset by construction, equality is a bug and "does not contradict" is the rule | `operator_confirmed` on the stack profile's cache layers; `cross_check_stack` treats a tier-0 `unknown` as not-contradicted only when that entry carries operator evidence; `tools/adversarial_gate_tests.py` §E, whose control is that contradicting a positive public finding is still refused; `evals/scenarios/fix-gate-accepts-operator-confirmed-cache-layers.json` |
| WP-ESC-15 | 2026-08-14 | The first real audit report attributed WP-CLI facts to `fingerprint.py` and printed `high` confidence on two cache-layer cells the script had rated `unknown`. `check_report.py` passed it with zero problems | **A contract that governs one section of a document and leaves the rest ungoverned.** The report contract is thorough about the scorecard — required rows, closed rating vocabulary, a `lab`/`field` declaration the checker enforces — and says nothing about any other section's cells. So the same defect the scorecard rules exist to prevent, a number wearing a word nobody measured, reappeared one section down where nothing was looking | Asking of a contract "which parts of this document does it actually bind?" rather than "is this document under contract?" The scorecard was covered, so the report counted as covered | `report-contract.md` §"A confidence in the Stack section needs a source"; `check_report.py` refuses a Stack table carrying a `Confidence` column without a non-empty `Source` on every row |

| WP-ESC-16 | 2026-08-14 | A tier-3 audit ended with its second-ranked finding — where the origin time actually went — unattributed because `wp profile` was not installed, and with field data missing for want of a PageSpeed key. Both were one message to the operator. Neither message was sent, and the report said `unmeasured` for both | **A boundary reported honestly, with no next step attached.** Every rule in this repo pushed toward stating the limit accurately and none toward asking whether the limit could move, so the skill did the honest half and stopped. A grep for any instruction to ask the operator anything returned nothing across both `SKILL.md` files: the audit had no operator loop at all, and its one reference on the subject sat a level down where a long run never re-reads it | Asking of each `unmeasured` row not only "is this reason accurate?" but **"could the operator have changed this, and did anyone tell them?"** The second question is what turns a boundary into a decision — and it has to live in the procedure, not in a reference, because `SKILL.md` is loaded once | `cannot_measure` entries carry `unlock` and `operator_can_supply`; `SKILL.md` steps 2 and 4b ask once and proceed either way; `report-contract.md` records a declined gap distinctly from an unexamined one; `evals/scenarios/audit-asks-once-for-supplyable-capability.json` pins that it never blocks, never re-asks, and never estimates the metric instead |

| WP-ESC-17 | 2026-08-14 | `tools/adversarial_gate_tests.py` and `tools/check_measurement_objectives.py` both loaded the code under test with `spec_from_file_location` + `exec_module`, which consults the bytecode cache. During a mutation test the mutation was reverted on disk while the checker kept reporting it — the checker was reading a stale `.pyc`, and would equally have reported a clean run against code nobody could see | **A verification tool that reads something other than the artifact it is verifying.** The cache is validated on the source's `(mtime, size)`, and both can match a genuinely changed file: reordering two entries leaves the byte count identical, and a write in the same clock second leaves the mtime identical. Nothing about the checkers looked wrong, because the defect was in an assumption underneath them. **CI could never catch it** — a fresh checkout has no `__pycache__` — so the only machine that can hit it is the developer's, which is exactly where the pre-push gate is supposed to be trustworthy | Mutation-testing the checkers themselves, not just the code they check. The tell was a restore that did not take: the file on disk was right and the tool disagreed with it. Asking "what is this tool actually reading?" rather than trusting that a green run read the working tree | Both loaders now `compile()` and `exec()` the source directly, registering in `sys.modules` first so `@dataclass` can still resolve its annotations; verified by a same-byte-length mutation reverted inside one clock second, which reported the failure before the fix and passes after it |

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
| Execution on a browser-capable non-Claude-Code session | A tier-0 audit has been completed end to end on a second harness (Codex), including the report contract, but that session had no browser — so the Core Web Vitals path is unproven anywhere but here | Run an audit on another harness with a browser tool available, and confirm the rated rows carry a value and a `lab`/`field` source |

## 9. Hotfix lane

A hotfix is a correction to a **wrong claim already shipped** — an incorrect permissive statement
about a host's policy, a catalog entry recommending a change that damages a site, or a gate that
refuses to refuse. Nothing else qualifies; a new feature under time pressure is not a hotfix.

Lane = WP-GATE-01, WP-GATE-02, WP-DOC-01, WP-EGRESS-01, plus the surface rows for the touched
surface. Roughly 8 minutes. Everything else runs the full selection.

**WP-CAT-01 and WP-HOST-01 are never skipped, including in the hotfix lane** — a hotfix to a host
claim is precisely the change most likely to introduce another one.
