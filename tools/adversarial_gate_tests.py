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
FINGERPRINT = REPO / "skills/wp-perf-audit/scripts/fingerprint.py"

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
def write_plan(tmp: pathlib.Path, *, site="https://example.com", tier=3,
               host_class="self-managed", **over) -> pathlib.Path:
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
        "host_class": host_class,
        "tier": tier,
        "baseline_metrics": "b.json",
        "cache_layers_present": ["page-plugin"],
        "changes": [change],
    }
    plan.update(over)
    path = tmp / "plan.json"
    path.write_text(json.dumps(plan))
    return path


def write_stack(tmp: pathlib.Path, target: str, host="self-managed",
                host_confidence="high") -> pathlib.Path:
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
            "host_class": {
                "value": host,
                "confidence": host_confidence,
                "evidence": [] if host == "unknown" else ["header: x"],
            }
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
    path = tmp / f"stack-{abs(hash((target, host, host_confidence)))}.json"
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


def capabilities_for(cwd: pathlib.Path, target: str, local_root: pathlib.Path = None) -> dict:
    argv = [PY, str(CAPS), "--target", target, "--quiet", "--json", "-"]
    if local_root is not None:
        argv += ["--local-root", str(local_root)]
    out = subprocess.run(argv, capture_output=True, text=True, cwd=str(cwd))
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

        print("\n=== validate_plan.py — the host's own policy, not the plan's label ===")
        # Until this gate existed, the refusal the whole skill advertises was a LABEL check: a
        # change was refused only when the plan had already written risk_lane 'prohibited'. A plan
        # declaring host_class wpengine while activating WP Rocket — a page cache WP Engine's own
        # disallowed list forbids — passed with zero problems. Taxonomy row WP-ESC-07.
        def cache_plan(host: str, plugin: str, **extra) -> pathlib.Path:
            change = {"target": {"kind": "plugin-setting", "identifier": plugin},
                      "risk_lane": "direct",
                      "catalog_entry": "caching/page-cache-missing-or-bypassed.md"}
            change.update(extra)
            return write_plan(tmp, tier=2, host_class=host, change=change)

        # CONTROLS FIRST. Without these, every refusal below would also pass against a gate that
        # simply rejected all page-cache changes, which would be useless rather than safe.
        expect_exit("CONTROL: sg-optimizer on siteground is its documented path",
                    [VALIDATE, cache_plan("siteground", "sg-optimizer"), "--preflight", "--quiet"], 0)
        expect_exit("CONTROL: breeze on cloudways is documented",
                    [VALIDATE, cache_plan("cloudways", "breeze"), "--preflight", "--quiet"], 0)
        expect_exit("CONTROL: a plugin that is not a page cache is not gated",
                    [VALIDATE, cache_plan("wpengine", "some-unrelated-plugin"), "--preflight", "--quiet"], 0)

        expect_exit("a page cache on wpengine is refused (first-party disallowed list)",
                    [VALIDATE, cache_plan("wpengine", "wp-rocket"), "--preflight", "--quiet"], 1)
        expect_exit("a page cache on kinsta is refused (banned list)",
                    [VALIDATE, cache_plan("kinsta", "wp-rocket"), "--preflight", "--quiet"], 1)
        expect_exit("a page cache siteground does not document is refused",
                    [VALIDATE, cache_plan("siteground", "wp-rocket"), "--preflight", "--quiet"], 1)
        expect_exit("an unconfirmable host refuses a page cache by default",
                    [VALIDATE, cache_plan("godaddy", "wp-rocket"), "--preflight", "--quiet"], 1)

        # The escape hatch, and its two limits. Without the hatch the gate would brick every audit
        # on the hosts that need it most; without the limits it would be a bypass.
        confirmed = {"source": "GoDaddy support ticket 1234567",
                     "scope": "Managed WordPress, WP Rocket activation on this account"}
        expect_exit("operator confirmation unblocks an UNCONFIRMABLE host",
                    [VALIDATE, cache_plan("godaddy", "wp-rocket", host_confirmation=confirmed),
                     "--preflight", "--quiet"], 0)
        expect_exit("confirmation CANNOT override a published prohibition",
                    [VALIDATE, cache_plan("wpengine", "wp-rocket", host_confirmation=confirmed),
                     "--preflight", "--quiet"], 1)
        expect_exit("a confirmation with no checkable source is refused",
                    [VALIDATE, cache_plan("godaddy", "wp-rocket",
                                          host_confirmation={"source": "", "scope": ""}),
                     "--preflight", "--quiet"], 1)
        expect_exit("host_confirmation: true is not a confirmation",
                    [VALIDATE, cache_plan("godaddy", "wp-rocket", host_confirmation=True),
                     "--preflight", "--quiet"], 1)

        print("\n=== validate_plan.py — a fingerprint must belong to the plan's installation ===")
        expect_exit("CONTROL: matching stack profile is accepted",
                    [VALIDATE, write_plan(tmp), "--stack", write_stack(tmp, "https://example.com/"), "--quiet"], 0)
        # A fingerprint of a SUBPAGE is refused, by design. Containment was abandoned because a
        # parent installation at `/` appears to contain a separate one at `/shop/`; the accepted
        # cost is that a fingerprint must be taken against the site root the plan names.
        expect_exit("a fingerprint of a subpage is refused, not assumed to be the root",
                    [VALIDATE, write_plan(tmp), "--stack", write_stack(tmp, "https://example.com/some-page/"), "--quiet"], 1)
        expect_exit("stack profile from a different host",
                    [VALIDATE, write_plan(tmp), "--stack", write_stack(tmp, "https://someone-else.example.org/"), "--quiet"], 1)
        expect_exit("stack profile from a SIBLING install on the same origin",
                    [VALIDATE, write_plan(tmp, site="https://example.com/site-a"),
                     "--stack", write_stack(tmp, "https://example.com/site-b/"), "--quiet"], 1)

        # The plan's host_class is the operator's declaration; the fingerprint is a
        # contradiction check. Gating on the fingerprint's CONFIDENCE instead deadlocked real
        # sites — GoDaddy is detected at medium by design, so no GoDaddy site could be fixed —
        # while leaving genuine contradictions unexamined, because the helper bailed out before
        # the comparison ran.
        expect_exit("CONTROL: a medium-confidence host that AGREES is accepted",
                    [VALIDATE, write_plan(tmp, host_class="godaddy"), "--stack",
                     write_stack(tmp, "https://example.com/", host="godaddy",
                                 host_confidence="medium"), "--quiet"], 0)
        expect_exit("a host that CONTRADICTS the plan is refused, even at medium confidence",
                    [VALIDATE, write_plan(tmp, host_class="godaddy"), "--stack",
                     write_stack(tmp, "https://example.com/", host="wpengine",
                                 host_confidence="medium"), "--quiet"], 1)
        expect_exit("a high-confidence contradiction is refused",
                    [VALIDATE, write_plan(tmp, host_class="godaddy"), "--stack",
                     write_stack(tmp, "https://example.com/", host="kinsta",
                                 host_confidence="high"), "--quiet"], 1)
        expect_exit("an unknown host leaves the operator's declaration standing",
                    [VALIDATE, write_plan(tmp, host_class="godaddy"), "--stack",
                     write_stack(tmp, "https://example.com/", host="unknown",
                                 host_confidence="none"), "--quiet"], 0)

    print("\n=== capabilities.py — local evidence must belong to the audited installation ===")
    # The loopback fixture answers 200 on every path, so /site-a/ and /site-b/ are both reachable
    # and the only thing distinguishing them is the binding under test.
    base, server = start_fixture()
    try:
        with tempfile.TemporaryDirectory() as d:
            tmp = pathlib.Path(d)
            # Binding is now an explicit operator declaration rather than a URL inference, so
            # these cases no longer depend on WP-CLI being installed and cannot go vacuous.
            checkout = make_wordpress_checkout(tmp / "checkout", base)

            doc = capabilities_for(checkout, base + "/", local_root=checkout)
            bound = doc["access"].get("deploy_path") or doc["access"].get("wp_cli")
            record(bool(bound), "CONTROL: a checkout declared with --local-root DOES bind",
                   f"tier={doc['tier']['value']} deploy_path={doc['access'].get('deploy_path')}")

            # The flag's main case: running from somewhere else entirely. An earlier version
            # discovered the checkout only from the working directory, so --local-root silently
            # did nothing unless you were already standing inside the checkout.
            outside = tmp / "unrelated-working-dir"
            outside.mkdir()
            doc = capabilities_for(outside, base + "/", local_root=checkout)
            bound = doc["access"].get("deploy_path") or doc["access"].get("wp_cli")
            record(bool(bound), "CONTROL: --local-root works from a DIFFERENT working directory",
                   f"tier={doc['tier']['value']} deploy_path={doc['access'].get('deploy_path')}")

            doc = capabilities_for(checkout, base + "/")
            unbound = not doc["access"].get("deploy_path") and not doc["access"].get("wp_cli")
            record(unbound, "the same checkout WITHOUT --local-root does not bind",
                   f"tier={doc['tier']['value']} deploy_path={doc['access'].get('deploy_path')}")

            # Under explicit declaration, whatever the operator names IS the binding — so
            # "--local-root points somewhere else" is no longer a meaningful negative; it is the
            # operator changing their mind. The guard that still matters is that a declared path
            # which is not a WordPress checkout binds nothing.
            not_wordpress = tmp / "just-a-folder"
            not_wordpress.mkdir()
            doc = capabilities_for(checkout, base + "/", local_root=not_wordpress)
            unbound = not doc["access"].get("deploy_path") and not doc["access"].get("wp_cli")
            record(unbound, "--local-root naming a non-WordPress directory binds nothing",
                   f"tier={doc['tier']['value']} deploy_path={doc['access'].get('deploy_path')}")
    finally:
        server.shutdown()

    print("\n=== installation identity is exact, and ambiguity is refused ===")
    validate = load_module("validate_plan", VALIDATE)
    for label, site, probed, want in [
        ("identical URLs are the same install", "https://example.com", "https://example.com", True),
        ("trailing slash is not a difference", "https://example.com", "https://example.com/", True),
        ("subdirectory install matches itself", "https://example.com/blog", "https://example.com/blog/", True),
        ("SIBLING install is refused", "https://example.com/site-a", "https://example.com/site-b/", False),
        ("NESTED install is refused", "https://example.com", "https://example.com/shop/", False),
        ("a subpage is not the site root", "https://example.com", "https://example.com/a-page/", False),
        ("dot-segment traversal is refused, not normalized",
         "https://example.com/site-a", "https://example.com/site-a/../site-b/", None),
        ("encoded separator is refused",
         "https://example.com/site-a", "https://example.com/site-a%2f..%2fsite-b/", None),
    ]:
        got = validate.identifies_same_installation(site, probed)
        record(got is want, f"identity: {label}", f"got {got}, want {want}")

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

    print("\n=== fingerprint.py — absence of evidence must not become a negative claim ===")
    fingerprint_mod = load_module("fingerprint", FINGERPRINT)
    # The repo calls "`unknown` is a first-class value; never guess" the single most important rule
    # it has, and the fingerprint broke it in one direction: finding no marker produced
    # `woocommerce: false`, `multilingual: none`, `is_wordpress: false` at medium confidence. The
    # WooCommerce case has a documented harm path — this project's own catalog says a false result
    # "does not prove that no store exists" and warns that brochure-site caching advice on a store
    # can expose private cart or order state. Taxonomy row WP-ESC-08.
    def fingerprint_signals(html: str):
        pages = [fingerprint_mod.FetchedPage(
            requested_url="https://e.invalid/", final_url="https://e.invalid/", status=200,
            headers={}, cookies=[], html=html, truncated=False, error="", redirect_notes=[])] * 3
        parsers = []
        for page in pages:
            parser = fingerprint_mod.PageParser()
            parser.feed(page.html)
            parsers.append(parser)
        wordpress, _version = fingerprint_mod.detect_wordpress(pages, parsers)
        multilingual, _notes = fingerprint_mod.detect_multilingual(pages, parsers, [])
        return {
            "is_wordpress": wordpress,
            "multilingual": multilingual,
            "woocommerce": fingerprint_mod.detect_woocommerce(pages, parsers),
        }

    # CONTROL FIRST: with markers present these must still be definite, or a fingerprint that
    # answered "unknown" to everything would pass every case below while detecting nothing.
    present = fingerprint_signals(
        '<html><body class="woocommerce">'
        '<a href="/wp-content/plugins/woocommerce/x.js"></a>'
        '<link href="/wp-content/plugins/sitepress-multilingual-cms/y.css">'
        '<script src="/wp-includes/js/z.js"></script></body></html>'
    )
    record(present["is_wordpress"]["value"] is True,
           "CONTROL: real WordPress markers still yield a definite true",
           f"got {present['is_wordpress']['value']!r}")
    record(present["woocommerce"]["value"] is True,
           "CONTROL: real WooCommerce markers still yield a definite true",
           f"got {present['woocommerce']['value']!r}")
    record(present["multilingual"]["value"] == "wpml",
           "CONTROL: a real multilingual product is still named",
           f"got {present['multilingual']['value']!r}")

    absent = fingerprint_signals("<html><body><p>nothing identifying here</p></body></html>")
    for field in ("is_wordpress", "woocommerce", "multilingual"):
        signal = absent[field]
        record(signal["value"] == "unknown",
               f"no marker yields unknown, not a negative claim: {field}",
               f"got {signal['value']!r} @ {signal['confidence']!r}")
    record(absent["woocommerce"]["confidence"] == "none",
           "an unknown carries confidence 'none', per the signal contract",
           f"got {absent['woocommerce']['confidence']!r}")
    # The observation itself must survive — "we looked and saw none" is useful; concluding false
    # from it is not. An unknown with no evidence would hide that the check ran at all.
    record(bool(absent["woocommerce"]["evidence"]),
           "the absence observation is still reported as evidence",
           f"evidence entries: {len(absent['woocommerce']['evidence'])}")

    print("\n=== the probe must not identify as a bot and measure a challenge page ===")
    # An escaped defect with no lock until now: an honest bot User-Agent is the intuitive choice
    # and was the original one, but security plugins, host WAFs and CDN bot rules answer it with a
    # challenge or a 403 — so the probe faithfully times an error page and reports it as the site's
    # performance. A fabricated measurement is worse than no measurement.
    #
    # Nothing asserted this, so a refactor could have reverted the default and every test would
    # still have passed. Taxonomy row PERF-04 in docs/TESTING.md.
    record(probe.DEFAULT_USER_AGENT.startswith("Mozilla/5.0"),
           "perf-probe's default User-Agent is a browser string",
           f"starts {probe.DEFAULT_USER_AGENT[:24]!r}")
    record(fingerprint_mod.USER_AGENT.startswith("Mozilla/5.0"),
           "fingerprint's User-Agent is a browser string",
           f"starts {fingerprint_mod.USER_AGENT[:24]!r}")
    # The two scripts must agree, or on a bot-protected site they describe different pages.
    record(probe.DEFAULT_USER_AGENT == fingerprint_mod.USER_AGENT,
           "both scripts send the SAME User-Agent, so they see the same page",
           "probe and fingerprint agree" if probe.DEFAULT_USER_AGENT == fingerprint_mod.USER_AGENT
           else "they differ, so a bot-protected site answers them differently")
    # CONTROL: the override still works, or a site needing a specific string has no way through.
    saved_ua = probe.USER_AGENT
    try:
        probe.apply_user_agent("wp-perf-probe/0.1")
        record(probe.USER_AGENT == "wp-perf-probe/0.1",
               "CONTROL: --user-agent still overrides the browser default",
               f"got {probe.USER_AGENT!r}")
    finally:
        probe.USER_AGENT = saved_ua

    print("\n=== perf-probe.py — one dead host must not consume the whole payload walk ===")
    # The real stall this guards against: font CSS pointed at a staging domain that resolved but
    # never answered, so every request burned the full timeout. --max-assets caps the count, which
    # bounds the symptom; only the breaker stops one host eating the budget.
    #
    # Driven against the breaker itself rather than over the network, because reproducing it end
    # to end needs a host that accepts connections and never replies — which is either a
    # third-party endpoint (undeclared egress) or a fixture that must hang for a full timeout.
    probe.BREAKER.reset()
    dead, alive = "dead.invalid", "alive.invalid"

    # Positive control: a host under the limit stays in service. Without this, every negative
    # case below would also pass against a breaker that simply refused everything.
    for _ in range(probe.HOST_TIMEOUT_CIRCUIT_LIMIT - 1):
        probe.BREAKER.record_outcome(dead, True)
    record(not probe.BREAKER.is_open(dead),
           "CONTROL: a host below the timeout limit is still requested",
           f"open after {probe.HOST_TIMEOUT_CIRCUIT_LIMIT - 1} of {probe.HOST_TIMEOUT_CIRCUIT_LIMIT}")

    probe.BREAKER.record_outcome(dead, True)
    record(probe.BREAKER.is_open(dead),
           "a host is cut off after the limit of consecutive timeouts",
           f"still open={probe.BREAKER.is_open(dead)} after {probe.HOST_TIMEOUT_CIRCUIT_LIMIT}")

    record(not probe.BREAKER.is_open(alive),
           "cutting one host off does not cut off any other",
           f"unrelated host open={probe.BREAKER.is_open(alive)}")

    # A merely slow host must recover, or an intermittently loaded CDN gets written off for the
    # rest of the run and its bytes silently leave the total.
    probe.BREAKER.reset()
    for _ in range(probe.HOST_TIMEOUT_CIRCUIT_LIMIT - 1):
        probe.BREAKER.record_outcome(alive, True)
    probe.BREAKER.record_outcome(alive, False)
    for _ in range(probe.HOST_TIMEOUT_CIRCUIT_LIMIT - 1):
        probe.BREAKER.record_outcome(alive, True)
    record(not probe.BREAKER.is_open(alive),
           "one answered request resets the run of timeouts",
           f"open={probe.BREAKER.is_open(alive)} after an answer broke the streak")

    # Only timeouts may trip it. A refused or unresolvable host fails in milliseconds and is
    # self-limiting; counting those would cut off hosts that cost the walk nothing.
    probe.BREAKER.reset()
    for _ in range(probe.HOST_TIMEOUT_CIRCUIT_LIMIT * 2):
        probe.BREAKER.record_outcome(dead, False)
    record(not probe.BREAKER.is_open(dead),
           "fast failures do not trip the breaker; only timeouts do",
           f"open={probe.BREAKER.is_open(dead)} after non-timeout failures")

    record(probe.CURL_TIMEOUT_CODE in probe.UNREACHABLE_CURL_CODES,
           "the code the breaker counts is curl's timeout code",
           f"CURL_TIMEOUT_CODE={probe.CURL_TIMEOUT_CODE}")

    # Nothing skipped may be counted as zero bytes — that would turn a dead host into a quietly
    # smaller page, which is the exact failure the payload totals rule exists to prevent.
    probe.BREAKER.reset()
    for _ in range(probe.HOST_TIMEOUT_CIRCUIT_LIMIT):
        probe.BREAKER.record_outcome(dead, True)
    skipped_result = probe.head_size("/nonexistent-curl", f"https://{dead}/font.woff2", "font")
    record(skipped_result["size_bytes"] is None and skipped_result.get("circuit_skipped") is True,
           "a resource on a cut-off host is unsized, never zero",
           f"size_bytes={skipped_result['size_bytes']}, marked={skipped_result.get('circuit_skipped')}")
    probe.BREAKER.reset()

    failed = [r for r in results if not r[0]]
    print(f"\n=== {len(results) - len(failed)}/{len(results)} passed, {len(skipped)} skipped ===")
    for _ok, name, detail in failed:
        print(f"  FAILED: {name} — {detail}")
    for note in skipped:
        print(f"  SKIPPED: {note}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
