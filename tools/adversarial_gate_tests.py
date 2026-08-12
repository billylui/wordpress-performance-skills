#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Adversarial tests for the safety gates, written from review findings rather than from the code.

A self-test written by whoever wrote the implementation can only check the cases its author
thought of. An adversarial review of this project once found the change-plan validator failing
open in three ways *while its own self-test passed* — a plan could set `approval.required: false`
or `snapshot.required: false` and skip those checks entirely.

So these cases are derived from what the review said was wrong, by a different author, and are
deliberately not shaped like the validator's internal tests.

**Every guard is tested as a pair: a positive control and a negative case.** A later review found
two cases here passing *vacuously* — the fixtures were malformed, so the refusal came from the
fixture being invalid rather than from the guard under test, and the cases would have passed with
the guard deleted. A positive control makes that impossible to repeat: if a fixture stops being
recognized, the control fails loudly instead of the negative case passing for a free reason.

**No third-party network access.** An earlier version probed a public API, which contradicted the
no-egress guarantee this project makes about itself. Reachable-target cases now use a loopback
server started by this process, and perf-probe's usability rules — which cannot be driven over
loopback because the tool deliberately requires an absolute HTTPS site — are exercised in-process
against the predicate itself.

A case that cannot run here is SKIPPED with its reason and never counted as a pass. Where the
skipped case is a positive control, the summary says that its negative counterparts are weaker
evidence on this machine.

    python3 tools/adversarial_gate_tests.py

Optional, operator-supplied, never defaulted to a third-party host:

    WP_PERF_TEST_NONHTML_URL=https://…  # an HTTPS URL serving non-HTML, for the end-to-end case

Exit codes: 0 all passed · 1 at least one gate failed
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading

REPO = pathlib.Path(__file__).resolve().parent.parent
PY = sys.executable or "python3"
VALIDATE = REPO / "skills/wp-perf-fix/scripts/validate_plan.py"
CAPS = REPO / "skills/wp-perf-audit/scripts/capabilities.py"
PROBE = REPO / "skills/wp-perf-audit/scripts/perf-probe.py"

# The four cache layers the change-plan contract requires a fingerprint to carry, in order. A
# fixture missing any of them is refused for being malformed, which would mask the guard we mean
# to exercise.
CACHE_LAYERS = ("edge", "server", "page-plugin", "object")

def load_module(name: str, path: pathlib.Path):
    """Import a script by path so its predicates can be exercised without the CLI."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


results: list[tuple[bool, str, str]] = []


skipped: list[str] = []


def record(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def skip(name: str, why: str) -> None:
    """Record a case that could not run here.

    A skip is reported, never silently dropped and never counted as a pass. Where a skipped case
    is a positive control, its negative counterparts are correspondingly weaker evidence on this
    machine, and the summary says so.
    """
    skipped.append(f"{name} — {why}")
    print(f"  [SKIP] {name}  ({why})")


def expect_exit(name: str, argv: list, want: int) -> None:
    got = subprocess.run([PY, *map(str, argv)], capture_output=True, text=True).returncode
    record(got == want, name, f"exit {got}, expected {want}")


# --------------------------------------------------------------------------- loopback fixture --
class _Handler(http.server.BaseHTTPRequestHandler):
    """Serves exactly the response shapes the probe's usability rules must distinguish."""

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's required name
        if self.path.startswith("/json"):
            body, ctype, status = b'{"ok":true}', "application/json", 200
        elif self.path.startswith("/error"):
            body, ctype, status = b"upstream is unwell", "text/plain", 503
        else:
            body, ctype, status = b"<html><body><h1>hi</h1></body></html>", "text/html", 200
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def log_message(self, *_args):
        return  # keep the suite's output readable


def start_fixture() -> tuple[str, http.server.HTTPServer]:
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}", server


# ------------------------------------------------------------------------------- plan fixtures --
def write_plan(tmp: pathlib.Path, *, site="https://example.com", tier=3, **over) -> pathlib.Path:
    snap = tmp / "snap.bak"
    snap.write_text("original\n")
    change = {
        "id": "c1",
        "summary": "drop unused font preload",
        "catalog_entry": "frontend/fonts-preloaded-unused.md",
        "risk_lane": "staging-first",
        "target": {"kind": "theme-file", "identifier": "functions.php"},
        "snapshot": {"required": True, "artifact": str(snap)},
        "approval": {"required": True, "granted": True},
        "purge_layers": ["page-plugin"],
        "expected_effect": {
            "metric": "total_kb",
            "url": "https://example.com/",
            "direction": "decrease",
        },
        "rollback": "restore snap.bak",
    }
    change.update(over.pop("change", {}))
    plan = {
        "schema_version": "1.0",
        "tool": "change-plan",
        "tool_version": "0.1.0",
        "generated_at": "2026-08-12T00:00:00Z",
        "site": site,
        "host_class": "self-managed",
        "tier": tier,
        "baseline_metrics": "b.json",
        "cache_layers_present": ["page-plugin"],
        "changes": [change],
    }
    plan.update(over)
    path = tmp / "plan.json"
    path.write_text(json.dumps(plan))
    return path


def write_stack(tmp: pathlib.Path, target: str) -> pathlib.Path:
    """A CONTRACT-VALID fingerprint. Every field but the target matches the plan, so a refusal
    can only come from the target binding under test."""
    stack = {
        "schema_version": "1.0",
        "tool": "fingerprint",
        "tool_version": "0.1.0",
        "generated_at": "2026-08-12T00:00:00Z",
        "target": target,
        "pages_probed": [target],
        "notes": [],
        "profile": {
            "host_class": {"value": "self-managed", "confidence": "high", "evidence": ["header: x"]}
        },
        "cache_layers": [
            {
                "layer": layer,
                "value": "wp-rocket" if layer == "page-plugin" else "none",
                "confidence": "high",
                "evidence": ["header: x"],
            }
            for layer in CACHE_LAYERS
        ],
    }
    path = tmp / f"stack-{abs(hash(target))}.json"
    path.write_text(json.dumps(stack))
    return path


def make_wordpress_checkout(root: pathlib.Path, home: str) -> pathlib.Path:
    """A checkout the detector will actually recognize.

    `find_local_wordpress_root` requires BOTH wp-load.php and wp-includes/version.php. An earlier
    fixture created only the first, so the checkout was never recognized and the binding test
    passed without exercising the binding at all.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "wp-load.php").write_text("<?php\n")
    (root / "wp-includes").mkdir(exist_ok=True)
    (root / "wp-includes" / "version.php").write_text("<?php $wp_version='6.7.1';\n")
    (root / "wp-config.php").write_text(
        f"<?php\ndefine('WP_HOME','{home}');\ndefine('WP_SITEURL','{home}');\n"
    )
    # A deploy path is only confirmed for a git checkout that has a configured PUSH REMOTE, so
    # `git init` alone leaves deploy_path false and the positive control would fail for a reason
    # unrelated to the binding. The remote is a local filesystem path: it satisfies the check
    # without this test process contacting anything over the network.
    subprocess.run(["git", "init", "-q"], cwd=root, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(root.parent / "bare-remote.git")],
                   cwd=root, capture_output=True)
    return root


def capabilities_for(cwd: pathlib.Path, target: str) -> dict:
    out = subprocess.run(
        [PY, str(CAPS), "--target", target, "--quiet", "--json", "-"],
        capture_output=True, text=True, cwd=str(cwd),
    )
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        # Surface this as a readable failure rather than a traceback: it usually means the target
        # was unreachable, which makes the case untestable rather than passing or failing.
        raise AssertionError(
            f"capabilities.py produced no JSON for {target} (exit {out.returncode}): "
            f"{(out.stderr or out.stdout)[:200]}"
        )


# ---------------------------------------------------------------------------------------- run --
def main() -> int:
    print("=== validate_plan.py — a plan must not switch off the check inspecting it ===")
    with tempfile.TemporaryDirectory() as d:
        tmp = pathlib.Path(d)
        expect_exit("CONTROL: a legitimate plan is accepted", [VALIDATE, write_plan(tmp), "--quiet"], 0)
        expect_exit(
            "plan sets approval.required=false to exempt itself",
            [VALIDATE, write_plan(tmp, change={"approval": {"required": False, "granted": False}}), "--quiet"], 1)
        expect_exit(
            "plan sets snapshot.required=false to exempt itself",
            [VALIDATE, write_plan(tmp, change={"snapshot": {"required": False, "artifact": None}}), "--quiet"], 1)
        expect_exit(
            "theme-file change declares risk_lane=direct",
            [VALIDATE, write_plan(tmp, change={"risk_lane": "direct"}), "--quiet"], 1)
        expect_exit(
            "wp-option change at tier 1",
            [VALIDATE, write_plan(tmp, tier=1, change={
                "target": {"kind": "wp-option", "identifier": "x"}, "risk_lane": "direct"}), "--quiet"], 1)

        pending = write_plan(tmp, change={
            "approval": {"required": True, "granted": False},
            "snapshot": {"required": True, "artifact": str(tmp / "not-yet.bak")}})
        expect_exit("preflight accepts a plan pending approval+snapshot", [VALIDATE, pending, "--preflight", "--quiet"], 0)
        expect_exit("execution mode refuses that same plan", [VALIDATE, pending, "--quiet"], 1)

        print("\n=== validate_plan.py — a fingerprint must belong to the plan's installation ===")
        expect_exit("CONTROL: matching stack profile is accepted",
                    [VALIDATE, write_plan(tmp), "--stack", write_stack(tmp, "https://example.com/"), "--quiet"], 0)
        expect_exit("CONTROL: a page inside the site is accepted",
                    [VALIDATE, write_plan(tmp), "--stack", write_stack(tmp, "https://example.com/some-page/"), "--quiet"], 0)
        expect_exit("stack profile from a different host",
                    [VALIDATE, write_plan(tmp), "--stack", write_stack(tmp, "https://someone-else.example.org/"), "--quiet"], 1)
        expect_exit("stack profile from a SIBLING install on the same origin",
                    [VALIDATE, write_plan(tmp, site="https://example.com/site-a"),
                     "--stack", write_stack(tmp, "https://example.com/site-b/"), "--quiet"], 1)

    print("\n=== capabilities.py — local evidence must belong to the audited installation ===")
    # The loopback fixture answers 200 on every path, so /site-a/ and /site-b/ are both reachable
    # and the only thing distinguishing them is the binding under test.
    base, server = start_fixture()
    try:
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            # Binding reads WP_HOME/WP_SITEURL via `wp config get`, so without WP-CLI installed a
            # checkout can never bind — which is fail-closed and correct, but makes the positive
            # control unrunnable. Skipping is honest; passing it here would be meaningless.
            if shutil.which("wp") is None:
                skip("CONTROL: a checkout of the audited site does bind local access",
                     "WP-CLI not installed, so no checkout can bind; the two negative cases below "
                     "are correspondingly weaker evidence on this machine")
            else:
                matching = make_wordpress_checkout(tmp / "matching", base)
                doc = capabilities_for(matching, base + "/")
                bound = doc["access"].get("deploy_path") or doc["access"].get("wp_cli")
                record(bool(bound), "CONTROL: a checkout of the audited site does bind local access",
                       f"deploy_path={doc['access'].get('deploy_path')} wp_cli={doc['access'].get('wp_cli')}")

            other = make_wordpress_checkout(tmp / "other", "https://a-different-site.example.net")
            doc = capabilities_for(other, base + "/")
            unbound = not doc["access"].get("deploy_path") and not doc["access"].get("wp_cli")
            record(unbound, "an unrelated checkout does NOT bind local access",
                   f"tier={doc['tier']['value']} deploy_path={doc['access'].get('deploy_path')}")

            sibling = make_wordpress_checkout(tmp / "sibling", base + "/site-a")
            doc = capabilities_for(sibling, base + "/site-b/")
            unbound = not doc["access"].get("deploy_path") and not doc["access"].get("wp_cli")
            record(unbound, "a SIBLING install on the same origin does NOT bind local access",
                   f"tier={doc['tier']['value']} deploy_path={doc['access'].get('deploy_path')}")
    finally:
        server.shutdown()

    print("\n=== perf-probe.py — quick mode must not call an unusable response usable ===")
    # perf-probe deliberately requires an absolute HTTPS --site, so a plain-HTTP loopback fixture
    # cannot drive it end to end. Rather than reach for a third-party HTTPS endpoint — which is
    # exactly the undeclared egress this suite was criticised for — the predicate the review
    # flagged is exercised directly, in-process.
    probe = load_module("perf_probe", PROBE)
    for ctype, want, label in [
        ("text/html; charset=utf-8", True, "text/html is HTML"),
        ("application/xhtml+xml", True, "xhtml is HTML"),
        ("application/json", False, "JSON is not HTML"),
        ("text/plain", False, "plain text is not HTML"),
        ("", False, "a missing content type is not HTML"),
    ]:
        got = bool(probe.is_html_content_type(ctype))
        record(got == want, f"quick-mode content type: {label}", f"got {got}, want {want}")

    record(probe.HTTP_USABLE_MIN == 200 and probe.HTTP_ERROR_MIN == 400,
           "quick-mode status window excludes 5xx and 4xx",
           f"usable range [{probe.HTTP_USABLE_MIN}, {probe.HTTP_ERROR_MIN})")

    # The end-to-end exit-4 path needs a real HTTPS endpoint, which only the operator can supply.
    endpoint = os.environ.get("WP_PERF_TEST_NONHTML_URL")
    if endpoint:
        expect_exit("end-to-end: operator-supplied non-HTML endpoint is refused",
                    [PROBE, "--site", endpoint, "--quick", "--repeats", "1", "--quiet",
                     "--json", "/dev/null"], 4)
    else:
        skip("end-to-end: non-HTML endpoint is refused",
             "set WP_PERF_TEST_NONHTML_URL to an HTTPS URL serving non-HTML; not defaulted to a "
             "third-party host because this project promises no undeclared egress")

    expect_exit("unreachable host is still exit 3, not 4",
                [PROBE, "--site", "https://nope-xyz-nores.invalid", "--quick", "--repeats", "1", "--quiet"], 3)

    failed = [r for r in results if not r[0]]
    print(f"\n=== {len(results) - len(failed)}/{len(results)} passed, {len(skipped)} skipped ===")
    for _ok, name, detail in failed:
        print(f"  FAILED: {name} — {detail}")
    for note in skipped:
        print(f"  SKIPPED: {note}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
