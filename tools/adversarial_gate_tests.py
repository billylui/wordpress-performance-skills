#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Adversarial tests for the safety gates, written from review findings rather than from the code.

A self-test written by whoever wrote the implementation can only check the cases its author
thought of. An adversarial review of this project once found the change-plan validator failing
open in three ways *while its own self-test passed* — a plan could set `approval.required: false`
or `snapshot.required: false` and skip those checks entirely.

So these cases are derived from what the review said was wrong, by a different author, and are
deliberately not shaped like the validator's internal tests. Each asserts a REFUSAL, plus one
control asserting that a legitimate plan is still accepted — because "fix fail-open by refusing
everything" is not a fix.

Not wired into CI: the perf-probe cases need network access, which makes them flaky in a runner.
The offline half of this ground is covered there by `validate_plan.py --selftest`. Run this
manually after touching any gate:

    python3 tools/adversarial_gate_tests.py

Exit codes: 0 all passed · 1 at least one gate failed to refuse
"""
import json, os, subprocess, sys, tempfile, pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
PY = "/usr/bin/python3"
VALIDATE = REPO / "skills/wp-perf-fix/scripts/validate_plan.py"
CAPS = REPO / "skills/wp-perf-audit/scripts/capabilities.py"
PROBE = REPO / "skills/wp-perf-audit/scripts/perf-probe.py"

results = []
def check(name, got, want):
    ok = got == want
    results.append((ok, name, f"got {got}, want {want}"))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  (exit {got}, expected {want})")

def run(args):
    return subprocess.run([PY, *map(str, args)], capture_output=True, text=True).returncode

def base_plan(tmp, **over):
    snap = tmp / "snap.bak"
    snap.write_text("original\n")
    plan = {
        "schema_version": "1.0", "tool": "change-plan", "tool_version": "0.1.0",
        "generated_at": "2026-08-12T00:00:00Z", "site": "https://example.com",
        "host_class": "self-managed", "tier": 3, "baseline_metrics": "b.json",
        "cache_layers_present": ["page-plugin"],
        "changes": [{
            "id": "c1", "summary": "drop unused font preload",
            "catalog_entry": "frontend/fonts-preloaded-unused.md",
            "risk_lane": "staging-first",
            "target": {"kind": "theme-file", "identifier": "functions.php"},
            "snapshot": {"required": True, "artifact": str(snap)},
            "approval": {"required": True, "granted": True},
            "purge_layers": ["page-plugin"],
            "expected_effect": {"metric": "total_kb", "url": "https://example.com/", "direction": "decrease"},
            "rollback": "restore snap.bak",
        }],
    }
    for k, v in over.items():
        if k == "change":
            plan["changes"][0].update(v)
        else:
            plan[k] = v
    p = tmp / "plan.json"
    p.write_text(json.dumps(plan))
    return p

print("=== validate_plan.py — the fail-open class the review named ===")
with tempfile.TemporaryDirectory() as d:
    tmp = pathlib.Path(d)
    # Control: a legitimate plan must STILL pass. Fixing fail-open by refusing everything is
    # not a fix.
    check("control: a legitimate plan is accepted", run([VALIDATE, base_plan(tmp), "--quiet"]), 0)

    # P1: plan declares it needs no approval
    check("plan sets approval.required=false to exempt itself",
          run([VALIDATE, base_plan(tmp, change={"approval": {"required": False, "granted": False}}), "--quiet"]), 1)

    # P1: plan declares it needs no snapshot
    check("plan sets snapshot.required=false to exempt itself",
          run([VALIDATE, base_plan(tmp, change={"snapshot": {"required": False, "artifact": None}}), "--quiet"]), 1)

    # P1: code target on the direct lane (a PHP fatal takes the site down)
    check("theme-file change declares risk_lane=direct",
          run([VALIDATE, base_plan(tmp, change={"risk_lane": "direct"}), "--quiet"]), 1)

    # P2: raw option change below the tier the contract requires
    check("wp-option change at tier 1",
          run([VALIDATE, base_plan(tmp, tier=1, change={"target": {"kind": "wp-option", "identifier": "x"},
                                                        "risk_lane": "direct"}), "--quiet"]), 1)

    # P1: stack profile from a DIFFERENT site authorising this plan
    stack = tmp / "stack.json"
    stack.write_text(json.dumps({
        "schema_version": "1.0", "tool": "fingerprint", "tool_version": "0.1.0",
        "generated_at": "2026-08-12T00:00:00Z", "target": "https://someone-elses-site.example.org/",
        "pages_probed": [], "notes": [],
        "profile": {"host_class": {"value": "self-managed", "confidence": "high", "evidence": ["x"]}},
        "cache_layers": [{"layer": "page-plugin", "value": "wp-rocket", "confidence": "high", "evidence": ["x"]}],
    }))
    check("--stack profile belongs to a different site",
          run([VALIDATE, base_plan(tmp), "--stack", stack, "--quiet"]), 1)

    # The two-gate split: preflight accepts what execution readiness must refuse.
    pending = base_plan(tmp, change={"approval": {"required": True, "granted": False},
                                     "snapshot": {"required": True, "artifact": str(tmp / "not-written-yet.bak")}})
    check("preflight accepts a plan pending approval+snapshot",
          run([VALIDATE, pending, "--preflight", "--quiet"]), 0)
    check("execution mode refuses that same plan",
          run([VALIDATE, pending, "--quiet"]), 1)

print("\n=== capabilities.py — local checkout must not raise a remote target's tier ===")
with tempfile.TemporaryDirectory() as d:
    fake_wp = pathlib.Path(d) / "some-other-wordpress"
    fake_wp.mkdir()
    (fake_wp / "wp-load.php").write_text("<?php\n")
    (fake_wp / "wp-config.php").write_text(
        "<?php\ndefine('WP_HOME','https://a-totally-different-site.example.net');\n"
        "define('WP_SITEURL','https://a-totally-different-site.example.net');\n")
    (fake_wp / "wp-includes").mkdir()
    out = subprocess.run([PY, str(CAPS), "--target", "https://example.com/", "--quiet", "--json", "-"],
                         capture_output=True, text=True, cwd=str(fake_wp))
    try:
        doc = json.loads(out.stdout)
        tier = doc["tier"]["value"]
        acc = doc["access"]
        ok = (tier in (0, "unknown")) and not acc.get("wp_cli") and not acc.get("deploy_path")
        results.append((ok, "unrelated local WP checkout does not raise remote tier",
                        f"tier={tier} wp_cli={acc.get('wp_cli')} deploy={acc.get('deploy_path')}"))
        print(f"  [{'PASS' if ok else 'FAIL'}] unrelated local WP checkout does not raise remote tier "
              f"(tier={tier}, wp_cli={acc.get('wp_cli')}, deploy_path={acc.get('deploy_path')})")
    except Exception as e:
        results.append((False, "capabilities returned parseable JSON", str(e)))
        print(f"  [FAIL] capabilities JSON unparseable: {e}\n  stdout: {out.stdout[:200]}")

print("\n=== perf-probe.py — quick mode must not call an unusable response usable ===")
check("quick mode against a non-HTML 200 (JSON API)",
      run([PROBE, "--site", "https://api.github.com", "--quick", "--repeats", "1", "--quiet",
           "--json", "/dev/null"]), 4)
check("quick mode against a normal HTML site still succeeds",
      run([PROBE, "--site", "https://example.com", "--quick", "--repeats", "1", "--quiet",
           "--json", "/dev/null"]), 0)
check("unreachable host is still exit 3, not 4",
      run([PROBE, "--site", "https://nope-xyz-nores.invalid", "--quick", "--repeats", "1", "--quiet"]), 3)

failed = [r for r in results if not r[0]]
print(f"\n=== {len(results)-len(failed)}/{len(results)} passed ===")
for ok, name, detail in failed:
    print(f"  FAILED: {name} — {detail}")
sys.exit(1 if failed else 0)
