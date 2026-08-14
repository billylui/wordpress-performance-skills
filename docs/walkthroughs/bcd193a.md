---
gate_id: bcd193a
date: 2026-08-14
git_sha: bcd193a
verdict: READY
---

<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Release gate — bcd193a

Re-run after `fafe639` came back NOT-READY. Supersedes
[fafe639.md](fafe639.md), which stays for the record because it documents a row
it originally passed in error.

**Verdict: READY.** All 26 selected rows pass, including the two that blocked last time.

## What changed since the NOT-READY gate

| Blocker at `fafe639` | Now |
|---|---|
| WP-SCHEMA-01 FAIL — `kind` emitted, undocumented | **PASS.** The capability schema defines `kind`, its closed vocabulary, and the rule that `unlock` is defined *by* `kind` |
| No-target gaps structurally unactionable | **Fixed in the structure** — `kind`, `capability`, `unlock` and `operator_can_supply` all re-keyed, not just the human string |

**How WP-SCHEMA-01 was checked differs from last time, and that matters more than the result.** It
was passed at `fafe639` by verifying the schema changes I remembered making, which missed one
entirely. This run enumerates every field the script actually emits and matches each against the
contract: `blocked_by`, `capability`, `kind`, `metric`, `objective`, `operator_can_supply`,
`unlock` — none missing. A check that depends on recall is not a check.

## Review record — five rounds, 17 findings

| Round | Base | Status | Findings |
|---|---|---|---|
| Pre-ship | `b5557a1` | ran | 5 — all fixed |
| Blast-radius | `2187aab` | ran | 3 — 2 fixed, 1 sibling → handed off |
| `fafe639` | `4ff25f0` | ran | 3 — 2 siblings, loop stopped, ship held |
| Fixes | `0e709cc` | ran | 3 — 2 fixed, 1 third-attempt → handed off |
| Docs | `247788a` | ran | 3 — **contract clean**, all three in the handoff prose; fixed |

Every finding was P2 or lower. None was a safety defect. The two that stopped the loop were
siblings of earlier fixes — the signal that mattered was never the count but that a previous fix
had been shallower than claimed.

## Always-on rows

| ID | Verdict | Evidence |
|---|---|---|
| WP-SMOKE-01 | PASS | `perf-probe.py --site https://wordpress.org --quick --repeats 1` → exit 0, HTTP 200, origin 1,118.7 ms / edge 790.3 ms reported separately |
| WP-GATE-01 | PASS | `validate_plan.py --selftest` → PASS (36/36) |
| WP-GATE-02 | PASS | `adversarial_gate_tests.py` → **145/145**, 1 declared skip (was 83 before this shipment) |
| WP-DOC-01 | PASS | `check_skill_docs.py` → OK, 2 skills, 35 markdown files |
| WP-DOC-02 | PASS | `check_report.py --template …` → CONFORMANT |
| WP-DOC-03 | PASS | `check_report.py --selftest` → PASS (30/30) |
| WP-EGRESS-01 | PASS | `check_no_egress.py` → OK, no disallowed host literals |
| WP-PKG-01 | PASS | `check_plugin_manifest.py` → OK |
| WP-HOST-02 | PASS | `check_host_policy.py` → OK, 17 hosts agree with the prose |
| WP-OBJ-01 | PASS | `check_measurement_objectives.py` → OK, 8 objectives agree |
| WP-SPEC-01 | PASS | `npx skills-ref@latest validate` → "Valid skill" for both |
| WP-SPEC-02 | PASS | bodies 304 and 273 lines, budget 500 |
| WP-PY-01 | PASS | compiles on 3.13.5 locally; 3.9 leg green in CI on the pushed branch |

## Surface rows

Surfaces: measurement · write-gate · procedure · report · host-policy · schema · install.
Catalog rows correctly not selected — no catalog entry changed.

| ID | Verdict | Evidence |
|---|---|---|
| WP-MEAS-01 | PASS | live JSON: `origin_ttfb_ms` and `edge_ttfb_ms` separate keys, no blended field |
| WP-MEAS-02 | PASS ¹ | adversarial "unsized, never zero"; live `total_kb=None` |
| WP-MEAS-03 | PASS | `asset_cap_applied` present; per-URL `errors` present; `--quick` reports unknown |
| WP-MEAS-04 | PASS | no-provider run exits 0; unconfirmable provider yields `"unknown"`; every gap carries `kind` |
| WP-WRITE-01/02/03 | PASS | selftest 36/36 plus the suite's adversarial pairs and controls |
| WP-PROC-01/02 | PASS | `check_skill_docs.py` |
| WP-REPORT-01 | PASS | selftest 30/30 and `--template` CONFORMANT |
| WP-HOST-01 | PASS | **manual.** No permissive verdict introduced across the whole diff; every permissive verdict cited except `self-managed`, the documented self-authority exemption |
| WP-SCHEMA-01 | PASS | every emitted gap field enumerated and matched against the contract; contract precedes consumers at `7d972c4`→`9f57d61` and `3f4f159`→`2187aab` |
| WP-INSTALL-01 | PASS | `check_plugin_manifest.py` |

¹ Evidence is the unit-level breaker case plus the live document, not the full payload walk the row
suggests. The property is directly evidenced; the method differs.

## Shipping with known open work

Two handoffs are OPEN by decision, both documented with acceptance criteria:

- **`godaddy-product-granularity.md`** — GoDaddy publishes a blocklist this project cannot safely
  act on, because the host class covers several products and cannot tell them apart. The verdict
  sits at `unconfirmable`, which is the fail-closed default and the pre-session state. Two attempts
  at a stricter verdict were reverted.
- **`no-target-gap-routing.md`** — a tier-0 gap renders as "ask at step 4b", a checkpoint that
  follows the measurement the missing URL is blocking. Wording only, and only on the bare
  invocation the documented flow never uses.

## What this gate did not cover

- **The final handoff-prose corrections are unreviewed.** They change no code and no contract; the
  round-5 review found the contract clean and its findings were confined to that document.
- **No live `wp-perf-fix` write has been performed against a production host.** Its read-only half
  now has — see `pre-publication.md`, narrowed this shipment.
- The full payload walk behind WP-MEAS-02, noted above.
