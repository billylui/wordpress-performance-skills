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
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import types

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

# These are the only operations exempt from the page-cache host-policy gate: they remove or turn
# off a cache rather than adding one.
PAGE_CACHE_REMOVAL_OPERATIONS = ("disable", "deactivate", "remove")

# These ordinary add/turn-on operations are paired with the removal cases so deleting the entire
# page-cache gate cannot make the operation-scope tests pass vacuously.
PAGE_CACHE_ADDITION_OPERATIONS = ("enable", "activate", "install")

# The change-plan contract requires approval scope to name each of these operations because their
# consequences reach beyond performance configuration.
HIGH_CONSEQUENCE_OPERATIONS = (
    "install", "activate", "deactivate", "remove", "update", "replace",
)


def load_module(name: str, path: pathlib.Path):
    """Execute a script from its SOURCE so its predicates can be exercised without the CLI.

    Deliberately not `spec_from_file_location` + `exec_module`, which consults the bytecode cache.
    That cache is validated on the source's (mtime, size), and both can match a file that has
    changed: editing a line to reorder two entries leaves the byte count identical, and a write
    landing in the same clock second leaves the mtime identical too. Python then serves the stale
    `.pyc`, and this suite reports on code that is not on disk.

    That is not hypothetical — it happened while mutation-testing this repo's own checkers, and it
    is the worst possible failure for a verification tool: a green run proving something about
    bytecode nobody can read. CI hides it behind a fresh checkout with no `__pycache__`, so the
    machine that would catch it is the one that never sees it.
    """

    source = path.read_text(encoding="utf-8")
    module = types.ModuleType(name)
    module.__file__ = str(path)
    # Register before executing. `@dataclass` resolves its annotations through
    # `sys.modules[cls.__module__]`, so a module absent from that table raises while the class body
    # is still being built — which is how the loaded script fails, not this loader.
    sys.modules[name] = module
    try:
        exec(compile(source, str(path), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
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
        "target": {
            "kind": "theme-file",
            "identifier": "functions.php",
            "operation": "configure",
        },
        "snapshot": {"required": True, "artifact": str(snap)},
        "approval": {
            "required": True,
            "granted": True,
            "evidence": {
                "source": "Operator message recorded in the adversarial test fixture",
                "scope": "Configure the unused font preload in functions.php",
            },
        },
        "purge_layers": ["page-plugin"],
        "expected_effect": {
            "metric": "total_kb",
            "url": "https://example.com/",
            "direction": "decrease",
        },
        "rollback": "restore snap.bak",
        # A code change on a site with no declared staging must say how that is being managed.
        # Included by default because it is the common real case — most WordPress sites have no
        # staging — so every unrelated control below stays about the guard it is actually testing.
        # Cases that exercise the ABSENCE of a staging story clear this explicitly.
        "compensating_controls": {
            "mechanism": "small mu-plugin rather than functions.php",
            "verification": "php -l, then a visitor GET of the homepage",
            "rollback_trigger": "5xx or WordPress's critical-error page",
        },
    }
    change.update(over.pop("change", {}))
    plan = {
        "schema_version": "1.1",
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
    path.write_text(json.dumps(plan, sort_keys=True))
    return path


def write_stack(tmp: pathlib.Path, target: str, host="self-managed",
                host_confidence="high", cache_values=None,
                operator_confirmed=None) -> pathlib.Path:
    """A CONTRACT-VALID fingerprint. Every field but the target matches the plan, so a refusal
    can only come from the target binding under test."""
    values = {
        "edge": "none",
        "server": "none",
        "page-plugin": "wp-rocket",
        "object": "none",
    }
    values.update(cache_values or {})
    confirmations = operator_confirmed or {}
    profile = {
        field: {"value": "unknown", "confidence": "none", "evidence": []}
        for field in (
            "is_wordpress", "wp_version", "builder", "theme_slug", "theme_type", "server",
            "php_version", "cdn", "multilingual", "woocommerce", "multisite",
        )
    }
    profile["host_class"] = {
        "value": host,
        "confidence": host_confidence,
        "evidence": [] if host == "unknown" else ["header: fixture host-class signal"],
    }

    cache_layers = []
    for layer in CACHE_LAYERS:
        value = values[layer]
        entry = {
            "layer": layer,
            "value": value,
            "confidence": "none" if value == "unknown" else "high",
            "evidence": [] if value == "unknown" else [
                "probe: fixture positively establishes the cache-layer value"
            ],
        }
        if layer in confirmations:
            entry["operator_confirmed"] = confirmations[layer]
        cache_layers.append(entry)

    stack = {
        "schema_version": "1.1",
        "tool": "fingerprint",
        "tool_version": "0.1.0",
        "generated_at": "2026-08-12T00:00:00Z",
        "target": target,
        "pages_probed": [target],
        "notes": [],
        "profile": profile,
        "cache_layers": cache_layers,
    }
    path = tmp / "stack.json"
    path.write_text(json.dumps(stack, sort_keys=True))
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
                "target": {"kind": "wp-option", "identifier": "x", "operation": "configure"},
                "risk_lane": "direct"}), "--quiet"], 1)

        pending = write_plan(tmp, change={
            "approval": {"required": True, "granted": False},
            "snapshot": {"required": True, "artifact": str(tmp / "not-yet.bak")}})
        expect_exit("preflight accepts a plan pending approval+snapshot", [VALIDATE, pending, "--preflight", "--quiet"], 0)
        expect_exit("execution mode refuses that same plan", [VALIDATE, pending, "--quiet"], 1)

        print("\n=== validate_plan.py — staging changes the process, never whether work proceeds ===")
        # Staging is a capability, not a precondition: most WordPress sites have none, and refusing
        # to work on them would make this skill unused rather than safe. What is refused is a CODE
        # change with neither staging nor a stated plan for surviving without one, because a PHP
        # fatal there takes the whole site down. Taxonomy row WP-ESC-10.
        controls = {"mechanism": "small mu-plugin rather than functions.php",
                    "verification": "php -l, then a visitor GET of the homepage",
                    "rollback_trigger": "5xx or WordPress's critical-error page"}
        staged = {"url": "https://staging.example.com",
                  "confirmed_by": "MyKinsta staging environment for this site, seen in the panel"}

        def code_plan(**over) -> pathlib.Path:
            return write_plan(tmp, tier=3, **over)

        def db_plan(**over) -> pathlib.Path:
            change = {"target": {
                          "kind": "wp-option",
                          "identifier": "some_option",
                          "operation": "configure",
                      },
                      "risk_lane": "direct"}
            change.update(over.pop("change", {}))
            return write_plan(tmp, tier=2, change=change, **over)

        expect_exit("a code change with no staging and no stated controls is refused",
                    [VALIDATE, code_plan(change={"compensating_controls": None}),
                     "--preflight", "--quiet"], 1)
        expect_exit("CONTROL: the same change with declared staging is accepted",
                    [VALIDATE, code_plan(staging=staged, change={"compensating_controls": None}),
                     "--preflight", "--quiet"], 0)
        expect_exit("CONTROL: the same change with full compensating controls is accepted",
                    [VALIDATE, code_plan(change={"compensating_controls": controls}),
                     "--preflight", "--quiet"], 0)
        expect_exit("staging declared without a checkable confirmation is refused",
                    [VALIDATE, code_plan(staging={"url": "https://staging.example.com"},
                                         change={"compensating_controls": None}),
                     "--preflight", "--quiet"], 1)
        # A declaration that is not a usable URL, or that names production, would let a
        # "staging-first" change run straight against production while appearing satisfied.
        expect_exit("staging.url that is the production site is refused",
                    [VALIDATE, code_plan(staging={"url": "https://example.com",
                                                  "confirmed_by": "panel"},
                                         change={"compensating_controls": None}),
                     "--preflight", "--quiet"], 1)
        expect_exit("staging.url that is not a URL at all is refused",
                    [VALIDATE, code_plan(staging={"url": "yes we have staging",
                                                  "confirmed_by": "panel"},
                                         change={"compensating_controls": None}),
                     "--preflight", "--quiet"], 1)
        expect_exit("partially stated controls are not controls",
                    [VALIDATE, code_plan(change={"compensating_controls": {"mechanism": "careful"}}),
                     "--preflight", "--quiet"], 1)
        # A database change is reversible by setting the value back, and its snapshot already holds
        # the prior value — gating it on staging would refuse most performance work for no gain.
        expect_exit("CONTROL: a database change needs no staging at all",
                    [VALIDATE, db_plan(), "--preflight", "--quiet"], 0)

        print("\n=== validate_plan.py — a multi-change plan is a queue, not a pile ===")
        # `changes` is executed one at a time. Several are legitimate, because performance work has
        # real dependencies. What is refused is an unordered pile: a queue nobody sequenced.
        two = [
            {"id": "c1", "summary": "first", "catalog_entry": "frontend/fonts-preloaded-unused.md",
             "risk_lane": "direct", "target": {
                 "kind": "wp-option", "identifier": "a", "operation": "configure"},
             "snapshot": {"required": True, "artifact": str(tmp / "snap.bak")},
             "approval": {"required": True, "granted": True}, "purge_layers": ["page-plugin"],
             "expected_effect": {"metric": "total_kb", "url": "https://example.com/",
                                 "direction": "decrease"}, "rollback": "restore"},
        ]
        second = json.loads(json.dumps(two[0])); second["id"] = "c2"
        expect_exit("two queued changes with no stated ordering are refused",
                    [VALIDATE, write_plan(tmp, tier=2, changes=two + [second]),
                     "--preflight", "--quiet"], 1)
        expect_exit("CONTROL: the same two with a sequence_rationale are accepted",
                    [VALIDATE, write_plan(tmp, tier=2, changes=two + [second],
                                          sequence_rationale="Purge configuration first, so the "
                                          "second change is measured against a clean cache."),
                     "--preflight", "--quiet"], 0)
        expect_exit("CONTROL: a single change needs no rationale",
                    [VALIDATE, write_plan(tmp, tier=2, changes=two), "--preflight", "--quiet"], 0)

        print("\n=== validate_plan.py — the host's own policy, not the plan's label ===")
        # Until this gate existed, the refusal the whole skill advertises was a LABEL check: a
        # change was refused only when the plan had already written risk_lane 'prohibited'. A plan
        # declaring host_class wpengine while activating WP Rocket — a page cache WP Engine's own
        # disallowed list forbids — passed with zero problems. Taxonomy row WP-ESC-07.
        def cache_plan(host: str, plugin: str, operation="configure",
                       kind="plugin-setting", **extra) -> pathlib.Path:
            change = {"target": {
                          "kind": kind,
                          "identifier": plugin,
                          "operation": operation,
                      },
                      "risk_lane": "staging-first" if kind == "plugin-file" else "direct",
                      "catalog_entry": "caching/page-cache-missing-or-bypassed.md"}
            change.update(extra)
            tier = 3 if kind == "plugin-file" else 2
            return write_plan(tmp, tier=tier, host_class=host, change=change)

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
        # The bare slug was the ONLY form the gate recognised at first, and it is the least likely
        # one to appear: WordPress identifies a plugin by its basename, and a settings target names
        # an option. Both bypassed the gate entirely.
        for identifier in ("wp-rocket/wp-rocket.php", "wp_rocket_settings[minify_css]", "WP-Rocket"):
            expect_exit(f"…and so is the same plugin written as {identifier!r}",
                        [VALIDATE, cache_plan("wpengine", identifier), "--preflight", "--quiet"], 1)
        expect_exit("CONTROL: an unrelated plugin basename is still not gated",
                    [VALIDATE, cache_plan("wpengine", "contact-form-7/wp-contact-form-7.php"),
                     "--preflight", "--quiet"], 0)
        expect_exit("a page cache on kinsta is refused (banned list)",
                    [VALIDATE, cache_plan("kinsta", "wp-rocket"), "--preflight", "--quiet"], 1)
        expect_exit("a page cache siteground does not document is refused",
                    [VALIDATE, cache_plan("siteground", "wp-rocket"), "--preflight", "--quiet"], 1)
        # `rocket-net`, not `godaddy`, is the unconfirmable example here. GoDaddy WAS one until its
        # entry was researched and found to carry a published blocklist, at which point every case
        # below silently changed meaning — the confirmation case started failing and the other
        # three kept passing for the wrong reason, since a prohibition refuses them too. Pick the
        # host from the verdict the case is about, and a policy edit cannot quietly hollow it out.
        expect_exit("an unconfirmable host refuses a page cache by default",
                    [VALIDATE, cache_plan("rocket-net", "wp-rocket"), "--preflight", "--quiet"], 1)

        # The escape hatch, and its two limits. Without the hatch the gate would brick every audit
        # on the hosts that need it most; without the limits it would be a bypass.
        confirmed = {"source": "Rocket.net support ticket 1234567",
                     "scope": "this hosting product, WP Rocket activation on this account"}
        expect_exit("operator confirmation unblocks an UNCONFIRMABLE host",
                    [VALIDATE, cache_plan("rocket-net", "wp-rocket", host_confirmation=confirmed),
                     "--preflight", "--quiet"], 0)
        expect_exit("confirmation CANNOT override a published prohibition",
                    [VALIDATE, cache_plan("wpengine", "wp-rocket", host_confirmation=confirmed),
                     "--preflight", "--quiet"], 1)
        # There was a case here asserting confirmation could not override GoDaddy either. It was
        # written while that entry read `prohibited`; the entry is back to `unconfirmable` because
        # the class cannot establish which GoDaddy product a site is on, so confirmation overrides
        # it again and the case was removed rather than left asserting a withdrawn policy. See
        # docs/handoffs/godaddy-product-granularity.md.
        expect_exit("a confirmation with no checkable source is refused",
                    [VALIDATE, cache_plan("rocket-net", "wp-rocket",
                                          host_confirmation={"source": "", "scope": ""}),
                     "--preflight", "--quiet"], 1)
        expect_exit("host_confirmation: true is not a confirmation",
                    [VALIDATE, cache_plan("rocket-net", "wp-rocket", host_confirmation=True),
                     "--preflight", "--quiet"], 1)

        print("\n=== validate_plan.py — page-cache policy governs adding, never removal ===")
        # WP Engine is a published prohibition; godaddy and rocket-net are unconfirmable. Removal
        # must stay open in both lanes, while the paired add/enable operation stays closed.
        for host in ("wpengine", "godaddy", "rocket-net"):
            for removal, addition in zip(
                    PAGE_CACHE_REMOVAL_OPERATIONS, PAGE_CACHE_ADDITION_OPERATIONS):
                expect_exit(
                    f"{removal} of WP Rocket is accepted on {host}",
                    [VALIDATE, cache_plan(host, "wp-rocket/wp-rocket.php", removal),
                     "--preflight", "--quiet"], 0)
                expect_exit(
                    f"CONTROL: {addition} of WP Rocket is refused on {host}",
                    [VALIDATE, cache_plan(host, "wp-rocket/wp-rocket.php", addition),
                     "--preflight", "--quiet"], 1)

        print("\n=== validate_plan.py — target.kind cannot rename a cache activation ===")
        page_cache_targets = (
            ("plugin-setting", "wp-rocket"),
            ("plugin-file", "wp-rocket/wp-rocket.php"),
            ("wp-option", "active_plugins"),
        )
        for kind, identifier in page_cache_targets:
            expect_exit(
                f"WP Rocket activation as {kind} is refused on wpengine",
                [VALIDATE, cache_plan(
                    "wpengine", identifier, "activate", kind=kind,
                    summary="Activate the WP Rocket page-cache plugin"),
                 "--preflight", "--quiet"], 1)
        expect_exit(
            "CONTROL: an activation target with no page-cache plugin is unaffected",
            [VALIDATE, cache_plan(
                "wpengine", "contact-form-7/wp-contact-form-7.php", "activate",
                summary="Activate the unrelated contact-form plugin"),
             "--preflight", "--quiet"], 0)
        # THE BOUNDARY OF THIS GATE, asserted so it stays visible rather than being rediscovered.
        # `active_plugins` names no plugin, so the gate reads the summary. When the summary names
        # no page cache either, the change is PERMITTED — this case documents that, and it is a
        # limit, not a guarantee. Failing closed here was tried and reverted: it cannot tell "the
        # summary names nothing" from "the summary names a plugin that is not a page cache", so it
        # refused unrelated activations too, which is a blanket refusal of an ordinary case.
        # Closing it properly needs a structured field naming the plugin. Recorded in
        # host-policy.json's limits. What stands behind it meanwhile is the approval gate: an
        # `activate` is high-consequence, so a human must approve that operation by name.
        expect_exit(
            "KNOWN LIMIT: a container activation naming no page cache is permitted",
            [VALIDATE, cache_plan(
                "wpengine", "active_plugins", "activate", kind="wp-option",
                summary="Update the active plugin list"),
             "--preflight", "--quiet"], 0)
        expect_exit(
            "…but naming the cache anywhere the gate can read it is still refused",
            [VALIDATE, cache_plan(
                "wpengine", "active_plugins", "activate", kind="wp-option",
                summary="Add wp-rocket to the active plugin list"),
             "--preflight", "--quiet"], 1)
        expect_exit(
            "CONTROL: that same named-cache container change is accepted as a removal",
            [VALIDATE, cache_plan(
                "wpengine", "active_plugins", "deactivate", kind="wp-option",
                summary="Remove wp-rocket from the active plugin list"),
             "--preflight", "--quiet"], 0)

        print("\n=== validate_plan.py — approval is a recorded attestation ===")
        expect_exit(
            "approval.granted=true without evidence is refused at execution readiness",
            [VALIDATE, write_plan(tmp, change={
                "approval": {"required": True, "granted": True}}), "--quiet"], 1)
        expect_exit(
            "approval evidence with an empty source is refused",
            [VALIDATE, write_plan(tmp, change={"approval": {
                "required": True,
                "granted": True,
                "evidence": {"source": "", "scope": "Configure the font preload"},
            }}), "--quiet"], 1)
        expect_exit(
            "approval evidence with an empty scope is refused",
            [VALIDATE, write_plan(tmp, change={"approval": {
                "required": True,
                "granted": True,
                "evidence": {"source": "Operator message in this session", "scope": ""},
            }}), "--quiet"], 1)
        expect_exit(
            "CONTROL: well-formed approval evidence is accepted at execution readiness",
            [VALIDATE, write_plan(tmp), "--quiet"], 0)
        expect_exit(
            "CONTROL: preflight accepts granted=false with no approval evidence",
            [VALIDATE, write_plan(tmp, change={
                "approval": {"required": True, "granted": False}}),
             "--preflight", "--quiet"], 0)

        print("\n=== validate_plan.py — consequential approval names the operation ===")

        def consequential_plan(operation: str, scope: str) -> pathlib.Path:
            return write_plan(tmp, change={
                "summary": f"{operation.capitalize()} the performance helper plugin",
                "target": {
                    "kind": "plugin-file",
                    "identifier": "performance-helper/performance-helper.php",
                    "operation": operation,
                },
                "approval": {
                    "required": True,
                    "granted": True,
                    "evidence": {
                        "source": "Operator message recorded in this session",
                        "scope": scope,
                    },
                },
            })

        general_scope = "Proceed with the approved performance helper maintenance."
        for operation in HIGH_CONSEQUENCE_OPERATIONS:
            expect_exit(
                f"{operation} is refused when approval scope does not name the operation",
                [VALIDATE, consequential_plan(operation, general_scope), "--quiet"], 1)
            expect_exit(
                f"CONTROL: {operation} is accepted when approval scope names the operation",
                [VALIDATE, consequential_plan(
                    operation,
                    f"{operation.capitalize()} the performance helper plugin on production."),
                 "--quiet"], 0)
        expect_exit(
            "CONTROL: configure does not require its operation named in approval scope",
            [VALIDATE, write_plan(tmp, tier=2, change={
                "summary": "Adjust a performance helper setting",
                "risk_lane": "direct",
                "target": {
                    "kind": "plugin-setting",
                    "identifier": "performance-helper[font_preload]",
                    "operation": "configure",
                },
                "approval": {
                    "required": True,
                    "granted": True,
                    "evidence": {
                        "source": "Operator message recorded in this session",
                        "scope": "Adjust the performance helper's font preload setting.",
                    },
                },
            }), "--quiet"], 0)

        print("\n=== validate_plan.py — a fingerprint must belong to the plan's installation ===")
        expect_exit("CONTROL: identical plan and stack URLs are accepted",
                    [VALIDATE, write_plan(tmp), "--stack",
                     write_stack(tmp, "https://example.com"), "--quiet"], 0)
        expect_exit("CONTROL: matching stack profile is accepted",
                    [VALIDATE, write_plan(tmp), "--stack", write_stack(tmp, "https://example.com/"), "--quiet"], 0)
        expect_exit("CONTROL: a subdirectory installation matches itself",
                    [VALIDATE, write_plan(tmp, site="https://example.com/blog"), "--stack",
                     write_stack(tmp, "https://example.com/blog/"), "--quiet"], 0)
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
        expect_exit("stack profile from a NESTED install on the same origin",
                    [VALIDATE, write_plan(tmp), "--stack",
                     write_stack(tmp, "https://example.com/shop/"), "--quiet"], 1)
        expect_exit("a dot-segment stack URL is refused rather than normalized",
                    [VALIDATE, write_plan(tmp, site="https://example.com/site-a"), "--stack",
                     write_stack(tmp, "https://example.com/site-a/../site-b/"), "--quiet"], 1)
        expect_exit("an encoded-separator stack URL is refused",
                    [VALIDATE, write_plan(tmp, site="https://example.com/site-a"), "--stack",
                     write_stack(tmp, "https://example.com/site-a%2f..%2fsite-b/"),
                     "--quiet"], 1)

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

        print("\n=== validate_plan.py — higher-tier cache evidence fills public unknowns ===")
        server_confirmation = {
            "value": "other",
            "tier": 2,
            "evidence": ["wp-cli: cache gateway reports enabled"],
            "confirmed_by": "WP-CLI over SSH in the operator session",
        }
        expect_exit(
            "operator-confirmed server cache may be declared present",
            [VALIDATE, write_plan(
                tmp,
                cache_layers_present=["page-plugin", "server"],
                change={"purge_layers": ["page-plugin"]}),
             "--stack", write_stack(
                 tmp, "https://example.com/", cache_values={"server": "unknown"},
                 operator_confirmed={"server": server_confirmation}),
             "--quiet"], 0)
        expect_exit(
            "operator-confirmed server cache may be purged",
            [VALIDATE, write_plan(
                tmp,
                cache_layers_present=["page-plugin", "server"],
                change={"purge_layers": ["server"]}),
             "--stack", write_stack(
                 tmp, "https://example.com/", cache_values={"server": "unknown"},
                 operator_confirmed={"server": server_confirmation}),
             "--quiet"], 0)
        expect_exit(
            "an unknown public cache layer without operator evidence cannot be asserted",
            [VALIDATE, write_plan(
                tmp,
                cache_layers_present=["page-plugin", "server"],
                change={"purge_layers": ["server"]}),
             "--stack", write_stack(
                 tmp, "https://example.com/", cache_values={"server": "unknown"}),
             "--quiet"], 1)
        expect_exit(
            "CONTROL: a plan cannot declare a layer whose public finding is none",
            [VALIDATE, write_plan(
                tmp,
                cache_layers_present=["page-plugin", "server"],
                change={"purge_layers": ["server"]}),
             "--stack", write_stack(
                 tmp, "https://example.com/", cache_values={"server": "none"}),
             "--quiet"], 1)
        expect_exit(
            "CONTROL: a plan cannot omit a positively found public cache layer",
            [VALIDATE, write_plan(tmp),
             "--stack", write_stack(
                 tmp, "https://example.com/", cache_values={"server": "varnish"}),
             "--quiet"], 1)

    print("\n=== capabilities.py — a gap names the prerequisite that is actionable NOW ===")
    # The gap list is what the agent reads to the operator, so a gap naming the wrong prerequisite
    # sends them to install a tool that cannot help. With no target, no provider can measure
    # anything — the URL is the ask. An earlier fix prepended the target to the human `blocked_by`
    # string and left `kind` and `unlock` naming providers, so anything reading the STRUCTURE was
    # still told to install Lighthouse. These cases read only the structured fields, which is the
    # thing that was wrong; a prose-only fix cannot pass them.
    caps_mod = load_module("capabilities", CAPS)
    _absent_tools = {n: {"present": False, "version": None} for n in
                     ("curl", "python3", "lighthouse_cli", "chrome_devtools_mcp",
                      "psi_api_key", "wp_cli")}

    def gap_shape(public_url: bool):
        access = {"public_url": public_url, "rest_api": False, "wp_admin": False,
                  "wp_cli": False, "ssh": False, "deploy_path": False}
        can, gaps, _ = caps_mod.measurement_boundaries(access, _absent_tools)
        return can, gaps

    _can_no_target, gaps_no_target = gap_shape(False)
    tool_unlocks = [u for g in gaps_no_target for u in g["unlock"] if not u.startswith("Tier ")]
    record(not tool_unlocks,
           "with no target, no gap's unlock names a provider that cannot help",
           f"tool names found in unlock: {tool_unlocks[:3]}")
    record(all(g["kind"] == "access" for g in gaps_no_target),
           "…and every gap is keyed as an access ask, not a provider ask",
           f"kinds: {sorted({g['kind'] for g in gaps_no_target})}")
    # Scoped to the objective metrics — the ones re-keyed from provider to access. The tier-1/2/3
    # access gaps (slow queries, cron spikes) are blocked by their own tier and correctly say
    # nothing about a target; asserting over all gaps would have been a test bug, not a finding.
    objective_metrics = {o["metric"] for o in caps_mod.MEASUREMENT_OBJECTIVES}
    rekeyed = [g for g in gaps_no_target if g["metric"] in objective_metrics]
    record(bool(rekeyed) and all(
               "target" in str(g["blocked_by"]) and "also needs" in str(g["blocked_by"])
               for g in rekeyed),
           "…while blocked_by names BOTH the missing target and the provider still to come",
           f"{len(rekeyed)} re-keyed objective gap(s)")

    # CONTROL. Without this, re-keying EVERY gap to `access` unconditionally would pass the three
    # cases above while destroying the provider ask the step-2 checkpoint depends on.
    can_target, gaps_target = gap_shape(True)
    provider_gaps = [g["metric"] for g in gaps_target if g["kind"] == "provider"]
    record(bool(provider_gaps),
           "CONTROL: WITH a target, provider gaps still exist and still name providers",
           f"provider gaps: {provider_gaps}")
    record(any(not u.startswith("Tier ") for g in gaps_target for u in g["unlock"]),
           "CONTROL: …and their unlock lists real tools, not a tier",
           "tool names present in unlock")
    # CONTROL. The contract calls the two lists mutually exclusive and jointly the audit's
    # boundary; re-keying must not duplicate a metric into both or drop one out of both.
    for label, (can, gaps) in (("no target", (_can_no_target, gaps_no_target)),
                               ("with target", (can_target, gaps_target))):
        metrics = [g["metric"] for g in gaps]
        record(len(metrics) == len(set(metrics)) and not (set(can) & set(metrics)),
               f"CONTROL: {label} — gaps are unique and disjoint from can_measure",
               f"{len(metrics)} gaps, {len(can)} measurable, overlap {sorted(set(can) & set(metrics))}")

    print("\n=== capabilities.py — local evidence must belong to the audited installation ===")
    # The loopback fixture answers 200 on every path, so /site-a/ and /site-b/ are both reachable
    # and the only thing distinguishing them is the binding under test.
    try:
        base, server = start_fixture()
    except OSError as exc:
        why = f"loopback socket unavailable: {type(exc).__name__}: {exc}"
        skip("CONTROL: a checkout declared with --local-root DOES bind", why)
        skip("CONTROL: --local-root works from a DIFFERENT working directory", why)
        skip("the same checkout WITHOUT --local-root does not bind", why)
        skip("--local-root naming a non-WordPress directory binds nothing", why)
    else:
        try:
            with tempfile.TemporaryDirectory() as d:
                tmp = pathlib.Path(d)
                # Binding is now an explicit operator declaration rather than a URL inference, so
                # these cases no longer depend on WP-CLI being installed and cannot go vacuous.
                checkout = make_wordpress_checkout(tmp / "checkout", base)

                doc = capabilities_for(checkout, base + "/", local_root=checkout)
                bound = doc["access"].get("deploy_path") or doc["access"].get("wp_cli")
                record(bool(bound), "CONTROL: a checkout declared with --local-root DOES bind",
                       f"tier={doc['tier']['value']} "
                       f"deploy_path={doc['access'].get('deploy_path')}")

                # The flag's main case: running from somewhere else entirely. An earlier version
                # discovered the checkout only from the working directory, so --local-root
                # silently did nothing unless you were already standing inside the checkout.
                outside = tmp / "unrelated-working-dir"
                outside.mkdir()
                doc = capabilities_for(outside, base + "/", local_root=checkout)
                bound = doc["access"].get("deploy_path") or doc["access"].get("wp_cli")
                record(
                    bool(bound),
                    "CONTROL: --local-root works from a DIFFERENT working directory",
                    f"tier={doc['tier']['value']} "
                    f"deploy_path={doc['access'].get('deploy_path')}",
                )

                doc = capabilities_for(checkout, base + "/")
                unbound = (not doc["access"].get("deploy_path")
                           and not doc["access"].get("wp_cli"))
                record(unbound, "the same checkout WITHOUT --local-root does not bind",
                       f"tier={doc['tier']['value']} "
                       f"deploy_path={doc['access'].get('deploy_path')}")

                # Under explicit declaration, whatever the operator names IS the binding — so
                # "--local-root points somewhere else" is no longer a meaningful negative; it is
                # the operator changing their mind. The guard that still matters is that a
                # declared path which is not a WordPress checkout binds nothing.
                not_wordpress = tmp / "just-a-folder"
                not_wordpress.mkdir()
                doc = capabilities_for(checkout, base + "/", local_root=not_wordpress)
                unbound = (not doc["access"].get("deploy_path")
                           and not doc["access"].get("wp_cli"))
                record(unbound, "--local-root naming a non-WordPress directory binds nothing",
                       f"tier={doc['tier']['value']} "
                       f"deploy_path={doc['access'].get('deploy_path')}")
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

    print("\n=== fingerprint.py — a gateway is not a cache ===")
    # `x-gateway-*` is the GoDaddy HOST-detection prefix. Keying the server CACHE layer on the same
    # prefix meant `X-Gateway-Request-Id` — an ordinary header that proves a gateway exists and
    # nothing about caching — produced a positive server-cache finding. That is not cosmetic:
    # `validate_plan.cross_check_stack` treats a positive finding as a layer the plan MUST declare
    # and may NOT fill in with operator evidence, so one unrelated header forces a plan to declare a
    # cache that does not exist. The cache claim keys on `x-gateway-cache-status`; the host claim
    # keeps the broad prefix, and the pair below is what stops a fix to one silently changing the
    # other.
    def server_layer(headers):
        layers = fingerprint_mod.detect_cache_layers(
            headers, "", {"value": "unknown", "confidence": "none", "evidence": []})
        return next(entry for entry in layers if entry["layer"] == "server")

    noncache = server_layer({"x-gateway-request-id": "abc123"})
    record(noncache["value"] == "unknown",
           "a non-cache x-gateway-* header is NOT evidence of a server cache",
           f"got {noncache['value']!r} @ {noncache['confidence']!r}")
    cachey = server_layer({"x-gateway-cache-status": "HIT"})
    record(cachey["value"] == "other" and cachey["confidence"] == "medium",
           "CONTROL: the cache-specific gateway header IS still detected",
           f"got {cachey['value']!r} @ {cachey['confidence']!r}")
    record(bool(cachey["evidence"]) and "x-gateway-cache-status" in cachey["evidence"][0],
           "CONTROL: and it names the header it saw as its evidence",
           f"evidence: {cachey['evidence'][:1]}")
    # The host claim must NOT have been narrowed by the cache fix — they are separate uses of the
    # same prefix, and this is the control that keeps a fix to one from quietly breaking the other.
    record(any("x-gateway-" in prefix for prefix in fingerprint_mod.NON_NAMESPACED_HOST_PREFIXES),
           "CONTROL: host-class detection still keys on the broad x-gateway- prefix",
           f"prefixes: {fingerprint_mod.NON_NAMESPACED_HOST_PREFIXES}")

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

    # Discovery runs BEFORE sizing and is serial, so gating only the sizing pool left the exact
    # path that caused the motivating stall — font CSS on a host that resolved and never answered —
    # paying a full timeout per stylesheet. Driven against the real discovery function with curl
    # stubbed, because reproducing it needs a host that accepts and never replies.
    real_run_curl = probe.run_curl
    try:
        def stub(_binary, args):
            url = args[-1]
            if dead in url:
                return {"returncode": probe.CURL_TIMEOUT_CODE, "stdout": b"",
                        "error": "timed out", "unreachable": True}
            return {"returncode": 0, "stdout": b"HTTP/1.1 200 OK\r\n\r\n",
                    "error": "", "unreachable": False}
        probe.run_curl = stub
        probe.BREAKER.reset()
        links = "".join(f'<link rel="stylesheet" href="https://{dead}/f{i}.css">' for i in range(10))
        _res, errs, incomplete = probe.discover_resources(
            "/curl", "https://live.invalid/", f"<html><head>{links}</head></html>")
        # Named distinctly: `skipped` is the module-level list of SKIPPED CASES, and shadowing it
        # here broke the suite's own summary line.
        css_skipped = sum(1 for e in errs if "stopped answering" in e)
        record(css_skipped >= 6,
               "the breaker also covers stylesheet DISCOVERY, not just sizing",
               f"{css_skipped} of 10 stylesheets skipped after the circuit opened")
        record(incomplete is True,
               "a discovery cut short by the breaker is reported incomplete, not complete",
               f"discovery_incomplete={incomplete}")
    finally:
        probe.run_curl = real_run_curl
        probe.BREAKER.reset()

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

    # The sizing pool runs several requests at once, so three can time out and open the circuit
    # while a fourth to the same host is still in flight — and then answers. Leaving the circuit
    # open there keeps skipping a host just watched responding, and understates the payload for
    # the rest of the run. Found by review; the counter reset alone did not close the circuit.
    probe.BREAKER.reset()
    for _ in range(probe.HOST_TIMEOUT_CIRCUIT_LIMIT):
        probe.BREAKER.record_outcome(dead, True)
    record(probe.BREAKER.is_open(dead),
           "CONTROL: the circuit is open before the in-flight reply arrives",
           f"open={probe.BREAKER.is_open(dead)}")
    probe.BREAKER.record_outcome(dead, False)
    record(not probe.BREAKER.is_open(dead),
           "an in-flight request that answers CLOSES the circuit again",
           f"open={probe.BREAKER.is_open(dead)} after the host demonstrably replied")

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

    print("\n=== check_report.py — a Confidence column must be found however it is written ===")
    # The Stack provenance rule fires on a column header. It matched `Confidence` exactly, so
    # `**Confidence**` — a completely ordinary way to write a Markdown table header, and the Stack
    # section is explicitly free-form — skipped the rule and a Stack table with no Source column
    # passed. That is WP-ESC-11's miss-class again: a guard tested only with the input its author
    # had in mind. These cases ask the ORDINARY question instead.
    #
    # The fixture is the shipped template, which is known-conformant, with ONLY its Stack table
    # header rewritten. Anything else failing would fail every variant equally, including the
    # controls, so a broken fixture cannot masquerade as the guard working.
    template_text = (REPO / "skills/wp-perf-audit/references/findings-report-template.md").read_text(
        encoding="utf-8")

    def stack_variant(tmp: pathlib.Path, name: str, header: str, keep_source: bool) -> pathlib.Path:
        out, in_stack = [], False
        for line in template_text.splitlines():
            if line.startswith("## "):
                in_stack = line.strip() == "## Stack"
            if in_stack and line.startswith("| Layer |"):
                out.append(header)
                continue
            if in_stack and set(line.strip()) <= set("|-: ") and line.strip().startswith("|"):
                out.append("|---|---|---|" + ("---|" if keep_source else ""))
                continue
            if in_stack and line.startswith("| ") and not keep_source:
                out.append("|".join(line.rstrip().split("|")[:-2]) + " |")
                continue
            out.append(line)
        path = tmp / f"stack-{name}.md"
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
        return path

    with tempfile.TemporaryDirectory(prefix="wp-perf-stack-") as stack_tmp:
        stack_dir = pathlib.Path(stack_tmp)
        CHECK_REPORT = REPO / "skills/wp-perf-audit/scripts/check_report.py"
        for label, header in (
            ("bold", "| Layer | Detected | **Confidence** |"),
            ("lower", "| Layer | Detected | confidence |"),
            ("code", "| Layer | Detected | `Confidence` |"),
        ):
            expect_exit(
                f"a Stack table headed {header.split('|')[3].strip()} with no Source is refused",
                [CHECK_REPORT, "--template",
                 stack_variant(stack_dir, label, header, keep_source=False), "--quiet"], 1)
        expect_exit(
            "CONTROL: the same bold header WITH a Source column is accepted",
            [CHECK_REPORT, "--template",
             stack_variant(stack_dir, "bold-ok", "| Layer | Detected | **Confidence** | Source |",
                           keep_source=True), "--quiet"], 0)
        expect_exit(
            "CONTROL: a Stack table with no Confidence column at all is accepted",
            [CHECK_REPORT, "--template",
             stack_variant(stack_dir, "nocol", "| Layer | Detected | Notes |",
                           keep_source=False), "--quiet"], 0)
        expect_exit(
            "CONTROL: the shipped template itself still conforms",
            [CHECK_REPORT, "--template",
             REPO / "skills/wp-perf-audit/references/findings-report-template.md", "--quiet"], 0)

    failed = [r for r in results if not r[0]]
    print(f"\n=== {len(results) - len(failed)}/{len(results)} passed, {len(skipped)} skipped ===")
    for _ok, name, detail in failed:
        print(f"  FAILED: {name} — {detail}")
    for note in skipped:
        print(f"  SKIPPED: {note}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
