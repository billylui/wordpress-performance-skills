---
gate_id: fafe639
date: 2026-08-14
git_sha: fafe639
verdict: NOT-READY
---

<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
# Release gate — fafe639

First gate ever run for this repository; `docs/walkthroughs/` did not exist before it, so "since
last ship" is the whole delta from `b5557a1` — 14 commits, 21 files.

**Verdict: NOT-READY — one failing row and one open review finding.** (An earlier revision of this
line said "two rows", which overstated it: only WP-SCHEMA-01 fails as a row.)

`fafe639` was reviewed after this report was first written, on the operator's instruction rather
than by waiver. It came back with **three P2 findings**, two of which are siblings of earlier
fixes — the second non-convergence signal in this shipment. The review loop is stopped, and the
remaining findings are handed off rather than patched.

1. **WP-SCHEMA-01 FAILS.** `capabilities.py` emits an undocumented `kind` field. See the row below.
   This report originally marked it PASS; that was wrong, and how it was wrong is instructive — the
   row was checked against the commits I was thinking about rather than against every schema change
   in the diff.
2. **Capability-gap guidance is still structurally misleading with no `--target`.** The previous
   round's fix prepended the missing URL to `blocked_by` and left `kind` and `unlock` untouched, so
   the structured fields still say *supply a provider* for a metric no provider can unlock without a
   URL. Fixing the prose and not the structure is what makes this a sibling rather than a new
   finding.

Both are in the capability-gap work. Tracked in
[handoffs/capability-gap-followups.md](../handoffs/capability-gap-followups.md).

`review: ran — 3 findings, 2 siblings; loop stopped for non-convergence, findings handed off.`

## Review record

| Round | Base | Status | Findings |
|---|---|---|---|
| Pre-ship | `b5557a1` | ran | 5, all P2, all fixed in `4ff25f0` |
| Blast-radius | `2187aab` | ran | 3 — two fixed in `fafe639`, one a sibling → handed off |
| `fafe639` | `4ff25f0` | ran | 3 — 2 siblings → loop stopped, handed off; 1 falsehood fixed |

## Always-on rows

| ID | Verdict | Evidence |
|---|---|---|
| WP-SMOKE-01 | PASS | `perf-probe.py --site https://wordpress.org --quick --repeats 1` → exit 0, HTTP 200, origin 1,144.3 ms / edge 815.6 ms reported separately |
| WP-GATE-01 | PASS | `validate_plan.py --selftest` → PASS (36/36), floor is ≥36 |
| WP-GATE-02 | PASS | `tools/adversarial_gate_tests.py` → 138/138 passed, 1 declared skip (no-egress end-to-end) |
| WP-DOC-01 | PASS | `check_skill_docs.py` → OK, 2 skills, 35 markdown files |
| WP-DOC-02 | PASS | `check_report.py --template …` → CONFORMANT, 0 problems |
| WP-DOC-03 | PASS | `check_report.py --selftest` → PASS (30/30), floor is ≥30 |
| WP-EGRESS-01 | PASS | `check_no_egress.py` → OK, 8 files scanned, no disallowed host literals |
| WP-PKG-01 | PASS | `check_plugin_manifest.py` → OK, install command matches manifests |
| WP-HOST-02 | PASS | `check_host_policy.py` → OK, 17 hosts, verdicts agree with the prose |
| WP-OBJ-01 | PASS | `check_measurement_objectives.py` → OK, 8 objectives agree with the table |
| WP-SPEC-01 | PASS | `npx skills-ref@latest validate` → "Valid skill" for both |
| WP-SPEC-02 | PASS | bodies 304 and 273 lines, budget 500 |
| WP-PY-01 | PASS | compiles on 3.13.5 locally; the 3.9 leg ran green in CI on the pushed branch (run 31774457518) |

## Surface rows

Surfaces hit: measurement · write-gate · procedure · report · host-policy · schema · install.
Catalog rows are correctly **not selected** — no catalog entry changed.

| ID | Verdict | Evidence |
|---|---|---|
| WP-MEAS-01 | PASS | live JSON carries `origin_ttfb_ms` and `edge_ttfb_ms` as separate keys; no blended field exists |
| WP-MEAS-02 | PASS ¹ | adversarial: "a resource on a cut-off host is unsized, never zero" (`size_bytes=None`); live run `total_kb=None`, never `0`; `unsized_resources` present |
| WP-MEAS-03 | PASS | `asset_cap_applied` present in the document; per-URL `errors` array present; a `--quick` run reports `unknown`, not a number |
| WP-MEAS-04 | PASS | no-provider run exits 0; the only unconfirmable provider yields `operator_can_supply: "unknown"`, not `true`; every gap carries a `kind` |
| WP-WRITE-01 | PASS | `--selftest` 36/36 plus the suite's adversarial pairs |
| WP-WRITE-02 | PASS | suite §host-policy: prohibited host refuses the whole plan, with controls |
| WP-WRITE-03 | PASS | suite §staging, §sequence |
| WP-PROC-01 | PASS | `check_skill_docs.py` — every referenced file exists and is linked |
| WP-PROC-02 | PASS | `check_skill_docs.py` — no repository-root-relative script path |
| WP-REPORT-01 | PASS | `check_report.py --selftest` 30/30 and `--template` CONFORMANT |
| WP-HOST-01 | PASS | **manual, read the diff.** No permissive verdict introduced. `godaddy` nets `unconfirmable → unconfirmable` with a first-party citation **added**. The only uncited permissive entry is `self-managed`, which is the documented self-authority exemption |
| WP-SCHEMA-01 | **FAIL** | **Corrected after this report was first written.** `capabilities.py` emits a new `cannot_measure[].kind` field (`provider` \| `access`) in 5 places; `docs/CONTRACTS.md` does not define it — the only `kind` in the contract is the unrelated `target.kind`. The contract must change *before* its consumers, and here it did not change at all. The earlier changes in this shipment did satisfy the row (`7d972c4` before `9f57d61`; `3f4f159` before `2187aab`), and passing it on that basis is exactly the error: the row was checked against the commits I had in mind rather than against every schema change in the diff |
| WP-INSTALL-01 | PASS | `check_plugin_manifest.py` OK |

¹ WP-MEAS-02's evidence is the unit-level breaker case plus the live document, not the full payload
walk against a page with an unsizeable asset that the row suggests. The property the row asserts —
nothing unmeasured counted as zero — is directly evidenced; the method differs. Recorded rather than
smoothed over.

## Lesson-promotion audit

Six escaped-bug rows were added this shipment (WP-ESC-12…17). Each has a lock, a taxonomy row
naming its miss-class, and — for the three that generalise — a memory entry. The defects found by
review this session did not reach a real run, so they earn no taxonomy rows.

One correction: **WP-ESC-15's lock claim was overstated when written.** It said `check_report.py`
refuses a Stack table with a `Confidence` column and no `Source`, which was false for
`**Confidence**` until `4ff25f0`. It is true now.

## Quarantine

No quarantined rows.

## What this gate did not cover

- **The two open findings above are unfixed**, by decision rather than oversight — see the handoff.
- **No live `wp-perf-fix` write has ever been performed against a production host.** Unchanged by
  this shipment and tracked in `docs/handoffs/pre-publication.md`.
