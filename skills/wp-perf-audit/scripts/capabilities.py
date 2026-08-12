# SPDX-License-Identifier: GPL-2.0-or-later
"""Report which WordPress performance measurements are currently available.

Usage:
  python3 capabilities.py [--target URL] [--json PATH] [--quiet]

The script performs only local presence checks and unauthenticated public GETs.
It never reads credential values or attempts to log in to a target site.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union


SCHEMA_VERSION = "1.0"
TOOL_VERSION = "0.1.0"

# Five seconds is ample for local version/configuration probes without letting a
# broken executable stall an audit session.
LOCAL_PROBE_TIMEOUT_SECONDS = 5
# Fifteen seconds allows a normal public response while keeping an unreachable
# production target actionable for an operator.
NETWORK_TIMEOUT_SECONDS = 15
# REST indexes are normally small; 1 MiB is enough to recognize one without
# allowing an unexpectedly large response to consume unbounded memory.
MAX_RESPONSE_BYTES = 1024 * 1024
# MCP configuration files should be tiny; 1 MiB safely covers real configs while
# bounding local reads of a malformed or misidentified file.
MAX_CONFIG_BYTES = 1024 * 1024
# Version output is single-line in normal tools; this cap avoids retaining noisy
# output from a wrapper while remaining generous to legitimate banners.
MAX_VERSION_OUTPUT_CHARS = 8192

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_UNREACHABLE = 3
EXIT_UNUSABLE = 4

# HTTP status boundaries are named because they decide whether a public probe is
# usable rather than merely network-reachable.
HTTP_SUCCESS_MIN = 200
HTTP_SUCCESS_MAX_EXCLUSIVE = 400

UNKNOWN = "unknown"
TIER_NAMES = {0: "public", 1: "admin", 2: "cli", 3: "code"}

PUBLIC_CAPABILITIES = (
    "origin-vs-edge TTFB",
    "payload weight",
    "public stack fingerprint",
    "render-blocking resources",
)
BROWSER_CAPABILITIES = (
    "Cumulative Layout Shift (CLS)",
    "Interaction to Next Paint (INP)",
    "Largest Contentful Paint (LCP)",
)
ADMIN_CAPABILITIES = (
    "active caching stack",
    "plugin and theme inventory",
)
CLI_CAPABILITIES = (
    "autoloaded option size",
    "cron spikes",
    "object cache hit rate",
    "slow queries",
)
CODE_CAPABILITY = "theme and plugin source attribution"
AUDIT_CAPABILITIES = tuple(
    sorted(
        PUBLIC_CAPABILITIES
        + BROWSER_CAPABILITIES
        + ADMIN_CAPABILITIES
        + CLI_CAPABILITIES
        + (CODE_CAPABILITY,)
    )
)

# Only names are inspected. Values are deliberately never retrieved because
# these variables may contain secrets.
PSI_KEY_ENV_NAMES = (
    "GOOGLE_PAGESPEED_API_KEY",
    "PAGESPEED_INSIGHTS_API_KEY",
    "PSI_API_KEY",
)
REMOTE_ACCESS_ENV_NAMES = (
    "RSYNC_TARGET",
    "SFTP_TARGET",
    "SSH_TARGET",
    "WP_CLI_SSH",
)

TOOL_PROBES = {
    "curl": ("curl", ("--version",), re.compile(r"\bcurl\s+([^\s]+)", re.I)),
    "docker": (
        "docker",
        ("--version",),
        re.compile(r"\bDocker\s+version\s+([^,\s]+)", re.I),
    ),
    "git": ("git", ("--version",), re.compile(r"\bgit\s+version\s+([^\s]+)", re.I)),
    "lighthouse_cli": (
        "lighthouse",
        ("--version",),
        re.compile(r"(?:^|\s)v?([0-9]+(?:\.[0-9A-Za-z-]+)+)", re.I),
    ),
    "python3": (
        "python3",
        ("--version",),
        re.compile(r"\bPython\s+([^\s]+)", re.I),
    ),
    "rsync": (
        "rsync",
        ("--version",),
        re.compile(r"\brsync\s+version\s+([^\s]+)", re.I),
    ),
    "ssh": (
        "ssh",
        ("-V",),
        re.compile(r"\bOpenSSH[_\s]([^,\s]+)", re.I),
    ),
    "wp_cli": (
        "wp",
        ("--version",),
        re.compile(r"\bWP-CLI\s+([^\s]+)", re.I),
    ),
}


class TargetUnreachable(Exception):
    """The target could not be reached at the network layer."""


class TargetUnusable(Exception):
    """The target responded but did not provide a usable public response."""


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects only when they stay on the operator-supplied origin."""

    def __init__(self, allowed_origin: Tuple[str, str]) -> None:
        super().__init__()
        self.allowed_origin = allowed_origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        parsed = urllib.parse.urlsplit(newurl)
        if (parsed.scheme.lower(), parsed.netloc.lower()) != self.allowed_origin:
            raise urllib.error.HTTPError(
                req.full_url,
                code,
                "cross-origin redirect was not followed",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def utc_timestamp() -> str:
    """Return a contract-compatible UTC timestamp."""

    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def normalize_target(raw_target: str) -> str:
    """Validate and normalize an operator-supplied HTTP(S) target."""

    parsed = urllib.parse.urlsplit(raw_target)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        raise ValueError("--target must be an absolute http:// or https:// URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("--target must not contain credentials")
    if any(character.isspace() for character in raw_target):
        raise ValueError("--target must not contain whitespace")
    path = parsed.path or "/"
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, path, parsed.query, "")
    )


def origin_for(target: str) -> Tuple[str, str]:
    """Return the normalized scheme/netloc tuple used by the redirect guard."""

    parsed = urllib.parse.urlsplit(target)
    return parsed.scheme.lower(), parsed.netloc.lower()


def public_get(url: str, allowed_origin: Tuple[str, str]) -> Tuple[int, str, bytes]:
    """Perform one credential-free public GET and return status, final URL, body."""

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "wp-perf-capabilities/{}".format(TOOL_VERSION)},
        method="GET",
    )
    opener = urllib.request.build_opener(SameOriginRedirectHandler(allowed_origin))
    try:
        with opener.open(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            return int(response.status), response.geturl(), body[:MAX_RESPONSE_BYTES]
    except urllib.error.HTTPError as exc:
        raise TargetUnusable("HTTP {} from {}".format(exc.code, url)) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise TargetUnreachable("{} ({})".format(url, reason)) from None


def probe_target(target: str) -> Tuple[Dict[str, bool], List[str], str]:
    """Exercise public target access and, non-fatally, its REST index."""

    allowed_origin = origin_for(target)
    status, final_url, _body = public_get(target, allowed_origin)
    if not HTTP_SUCCESS_MIN <= status < HTTP_SUCCESS_MAX_EXCLUSIVE:
        raise TargetUnusable("HTTP {} from {}".format(status, target))

    access = {
        "deploy_path": False,
        "public_url": True,
        "rest_api": False,
        "ssh": False,
        "wp_admin": False,
        "wp_cli": False,
    }
    notes: List[str] = []
    evidence = "url: public GET {} returned HTTP {}".format(final_url, status)

    parsed = urllib.parse.urlsplit(target)
    rest_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/wp-json/", "", ""))
    try:
        rest_status, _rest_final_url, rest_body = public_get(rest_url, allowed_origin)
        rest_document = json.loads(rest_body.decode("utf-8", errors="replace"))
        # `namespaces` is the reliable marker. `routes` is deliberately NOT required to be a
        # JSON object: PHP encodes an empty associative array as `[]`, so a site whose REST
        # index has been trimmed by security hardening emits `"routes":[]` while still being a
        # genuine WordPress REST API. Requiring a dict there false-negatived a live WordPress
        # site that plainly advertised `wp/v2` — and under-reporting access silently shrinks
        # what the audit is willing to check.
        namespaces = rest_document.get("namespaces") if isinstance(rest_document, dict) else None
        if (
            HTTP_SUCCESS_MIN <= rest_status < HTTP_SUCCESS_MAX_EXCLUSIVE
            and isinstance(namespaces, list)
            and any(isinstance(entry, str) and "/v" in entry for entry in namespaces)
        ):
            access["rest_api"] = True
        else:
            notes.append("The public REST index did not identify itself as WordPress REST API.")
    except (TargetUnreachable, TargetUnusable, UnicodeError, ValueError, json.JSONDecodeError):
        notes.append("The public WordPress REST index could not be confirmed.")

    notes.append(
        "Authenticated wp-admin or REST access was not tested; no credential or login was used."
    )
    return access, notes, evidence


def parse_tool_version(output: str, pattern: re.Pattern) -> Optional[str]:
    """Extract a version defensively from a bounded tool banner."""

    match = pattern.search(output[:MAX_VERSION_OUTPUT_CHARS])
    if not match:
        return None
    version = match.group(1).strip().strip(",;")
    return version or None


def probe_tool(
    executable_name: str, arguments: Sequence[str], version_pattern: re.Pattern
) -> Dict[str, Union[bool, Optional[str]]]:
    """Check PATH presence and run the tool's own local version command."""

    executable = shutil.which(executable_name)
    if executable_name == "python3" and executable is None:
        executable = sys.executable
    if executable is None:
        return {"present": False, "version": None}
    try:
        completed = subprocess.run(
            [executable] + list(arguments),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=LOCAL_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {"present": True, "version": None}
    output = completed.stdout or ""
    return {"present": True, "version": parse_tool_version(output, version_pattern)}


def package_version(package_json: Path) -> Optional[str]:
    """Return a local package version without failing on malformed metadata."""

    try:
        with package_json.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None
    version = document.get("version") if isinstance(document, dict) else None
    return version if isinstance(version, str) and version.strip() else None


def ancestor_directories(start: Path) -> List[Path]:
    """Return start and its parents once each, nearest first."""

    directories = [start]
    directories.extend(start.parents)
    return directories


def chrome_package_candidates() -> List[Path]:
    """Return deterministic local package locations, including npm's global root."""

    home = Path.home()
    candidates = [
        home / ".npm-global/lib/node_modules/chrome-devtools-mcp/package.json",
        Path("/opt/homebrew/lib/node_modules/chrome-devtools-mcp/package.json"),
        Path("/usr/local/lib/node_modules/chrome-devtools-mcp/package.json"),
    ]
    for directory in ancestor_directories(Path.cwd()):
        candidates.append(directory / "node_modules/chrome-devtools-mcp/package.json")

    npm = shutil.which("npm")
    if npm is not None:
        try:
            completed = subprocess.run(
                [npm, "root", "-g"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=LOCAL_PROBE_TIMEOUT_SECONDS,
                check=False,
            )
            global_root = (completed.stdout or "").strip()
            if completed.returncode == EXIT_OK and global_root:
                candidates.append(Path(global_root) / "chrome-devtools-mcp/package.json")
        except (OSError, subprocess.SubprocessError):
            pass
    return sorted(set(candidates), key=lambda path: path.as_posix())


def mcp_config_candidates() -> List[Path]:
    """Return known MCP client config paths without inspecting credential stores."""

    home = Path.home()
    candidates = [
        home / ".claude.json",
        home / ".claude/settings.json",
        home / ".codex/config.toml",
        home / ".config/claude/claude_desktop_config.json",
        home / "Library/Application Support/Claude/claude_desktop_config.json",
    ]
    for directory in ancestor_directories(Path.cwd()):
        candidates.append(directory / ".mcp.json")
    return sorted(set(candidates), key=lambda path: path.as_posix())


def config_references_chrome_mcp(config_path: Path) -> bool:
    """Check only for the package name in a bounded local client config."""

    try:
        with config_path.open("r", encoding="utf-8", errors="replace") as handle:
            content = handle.read(MAX_CONFIG_BYTES)
    except OSError:
        return False
    return "chrome-devtools-mcp" in content.lower()


def probe_chrome_devtools_mcp() -> Tuple[Dict[str, Union[bool, Optional[str]]], str]:
    """Detect a local package or an MCP client configuration reference."""

    for candidate in chrome_package_candidates():
        if candidate.is_file():
            return {"present": True, "version": package_version(candidate)}, "package"
    for candidate in mcp_config_candidates():
        if candidate.is_file() and config_references_chrome_mcp(candidate):
            return {"present": True, "version": None}, "config"
    return {"present": False, "version": None}, "unconfirmed"


def probe_tools() -> Tuple[Dict[str, Dict[str, Union[bool, Optional[str]]]], List[str]]:
    """Build the complete fixed tooling map and explanatory notes."""

    tools = {}
    notes: List[str] = []
    for tool_name, (executable, arguments, pattern) in sorted(TOOL_PROBES.items()):
        tools[tool_name] = probe_tool(executable, arguments, pattern)

    chrome_tool, chrome_source = probe_chrome_devtools_mcp()
    tools["chrome_devtools_mcp"] = chrome_tool
    tools["psi_api_key"] = {
        "present": any(name in os.environ for name in PSI_KEY_ENV_NAMES),
        "version": None,
    }
    if chrome_source == "config":
        notes.append(
            "chrome-devtools-mcp is referenced by local MCP client configuration; its package version could not be confirmed."
        )
    elif chrome_source == "unconfirmed":
        notes.append(
            "chrome-devtools-mcp could not be confirmed locally; a browser path may still be available through the agent's own MCP tools."
        )
    return dict(sorted(tools.items())), notes


def find_local_wordpress_root(start: Path) -> Optional[Path]:
    """Find a WordPress checkout at the current directory or an ancestor."""

    for directory in ancestor_directories(start.resolve()):
        if (directory / "wp-load.php").is_file() and (
            directory / "wp-includes/version.php"
        ).is_file():
            return directory
    return None


def exercise_wp_cli(wp_tool: Dict[str, Union[bool, Optional[str]]], root: Optional[Path]) -> bool:
    """Exercise WP-CLI against local WordPress files without loading credentials."""

    if not wp_tool["present"] or root is None:
        return False
    executable = shutil.which("wp")
    if executable is None:
        return False
    try:
        completed = subprocess.run(
            [
                executable,
                "--path={}".format(root.as_posix()),
                "--no-color",
                "core",
                "version",
                "--skip-plugins",
                "--skip-themes",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=LOCAL_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == EXIT_OK and bool((completed.stdout or "").strip())


def exercise_git_deploy_path(
    git_tool: Dict[str, Union[bool, Optional[str]]], root: Optional[Path]
) -> bool:
    """Confirm a writable local WP Git checkout with a configured push remote."""

    if not git_tool["present"] or root is None or not os.access(str(root), os.W_OK):
        return False
    executable = shutil.which("git")
    if executable is None:
        return False
    try:
        worktree = subprocess.run(
            [executable, "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=LOCAL_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
        if worktree.returncode != EXIT_OK or (worktree.stdout or "").strip() != "true":
            return False
        remotes = subprocess.run(
            [executable, "-C", str(root), "remote"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=LOCAL_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return remotes.returncode == EXIT_OK and bool((remotes.stdout or "").strip())


def determine_tier(
    access: Dict[str, bool], root: Optional[Path], public_evidence: Optional[str]
) -> Dict[str, Union[int, str, List[str]]]:
    """Return the highest locally exercised access tier signal."""

    if access["deploy_path"]:
        return {
            "confidence": "high",
            "evidence": [
                "probe: writable local WordPress Git checkout has a configured push remote at {}".format(
                    root.as_posix() if root is not None else UNKNOWN
                )
            ],
            "name": TIER_NAMES[3],
            "value": 3,
        }
    if access["wp_cli"]:
        return {
            "confidence": "high",
            "evidence": [
                "probe: WP-CLI core version succeeded against local WordPress files at {}".format(
                    root.as_posix() if root is not None else UNKNOWN
                )
            ],
            "name": TIER_NAMES[2],
            "value": 2,
        }
    if access["wp_admin"]:
        return {
            "confidence": "high",
            "evidence": ["probe: authenticated WordPress administration access was exercised"],
            "name": TIER_NAMES[1],
            "value": 1,
        }
    if access["public_url"]:
        return {
            "confidence": "high",
            "evidence": [public_evidence] if public_evidence is not None else [],
            "name": TIER_NAMES[0],
            "value": 0,
        }
    return {"confidence": "none", "evidence": [], "name": UNKNOWN, "value": UNKNOWN}


def measurement_boundaries(
    access: Dict[str, bool], tools: Dict[str, Dict[str, Union[bool, Optional[str]]]]
) -> Tuple[List[str], List[str], List[str]]:
    """Partition the complete audit surface into available and unavailable lists."""

    available = set()
    notes: List[str] = []
    lighthouse_available = bool(tools["lighthouse_cli"]["present"])
    interactive_browser_available = bool(tools["chrome_devtools_mcp"]["present"])

    if access["public_url"]:
        available.update(PUBLIC_CAPABILITIES)
        if interactive_browser_available:
            available.update(BROWSER_CAPABILITIES)
        elif lighthouse_available:
            available.update(
                ("Cumulative Layout Shift (CLS)", "Largest Contentful Paint (LCP)")
            )
            notes.append(
                "Lighthouse can measure lab LCP and CLS, but it cannot establish INP without a real interaction path."
            )
        else:
            notes.append(
                "No browser-capable tool found; Core Web Vitals cannot be measured in this session."
            )
    else:
        notes.append("No public target was confirmed; public performance measurements are unavailable.")

    if access["wp_admin"] or access["wp_cli"]:
        available.update(ADMIN_CAPABILITIES)
    else:
        notes.append(
            "No authenticated admin path or working WP-CLI install was confirmed; plugin, theme, and active caching inventory are unavailable."
        )

    if access["wp_cli"]:
        available.update(CLI_CAPABILITIES)
    else:
        notes.append(
            "WP-CLI was not exercised against a local install; database, query, cron, and object-cache measurements are unavailable."
        )

    if access["deploy_path"]:
        available.add(CODE_CAPABILITY)
    else:
        notes.append(
            "No deploy path was confirmed; theme and plugin source attribution is unavailable."
        )

    can_measure = sorted(available)
    cannot_measure = sorted(set(AUDIT_CAPABILITIES) - available)
    return can_measure, cannot_measure, notes


def build_profile(target: Optional[str]) -> Dict[str, object]:
    """Build one complete capability-profile document."""

    tools, notes = probe_tools()
    access = {
        "deploy_path": False,
        "public_url": False,
        "rest_api": False,
        "ssh": False,
        "wp_admin": False,
        "wp_cli": False,
    }
    public_evidence: Optional[str] = None

    if target is not None:
        target_access, target_notes, public_evidence = probe_target(target)
        access.update(target_access)
        notes.extend(target_notes)
    else:
        notes.append("No target URL was supplied; public access could not be exercised.")

    wordpress_root = find_local_wordpress_root(Path.cwd())
    access["wp_cli"] = exercise_wp_cli(tools["wp_cli"], wordpress_root)
    access["deploy_path"] = exercise_git_deploy_path(tools["git"], wordpress_root)

    if tools["wp_cli"]["present"] and not access["wp_cli"]:
        notes.append(
            "WP-CLI is installed but was not confirmed against a local WordPress checkout."
        )
    if tools["ssh"]["present"]:
        notes.append(
            "The SSH client is installed, but no SSH access was exercised because that could use credentials."
        )
    if any(name in os.environ for name in REMOTE_ACCESS_ENV_NAMES):
        notes.append(
            "A remote-access variable is set, but its value was not read and it does not confirm usable SSH, SFTP, or rsync access."
        )
    if access["deploy_path"]:
        notes.append(
            "The local Git deploy path is confirmed; remote reachability and push credentials were not tested."
        )

    tier = determine_tier(access, wordpress_root, public_evidence)
    can_measure, cannot_measure, boundary_notes = measurement_boundaries(access, tools)
    notes.extend(boundary_notes)

    return {
        "access": dict(sorted(access.items())),
        "can_measure": can_measure,
        "cannot_measure": cannot_measure,
        "generated_at": utc_timestamp(),
        "notes": sorted(set(notes)),
        "schema_version": SCHEMA_VERSION,
        "target": target if target is not None else UNKNOWN,
        "tier": tier,
        "tool": "capabilities",
        "tool_version": TOOL_VERSION,
        "tools": tools,
    }


def render_human(profile: Dict[str, object]) -> str:
    """Render a concise report suitable for a non-developer site owner."""

    tier = profile["tier"]
    assert isinstance(tier, dict)
    can_measure = profile["can_measure"]
    cannot_measure = profile["cannot_measure"]
    notes = profile["notes"]
    lines = [
        "Capability profile",
        "Target: {}".format(profile["target"]),
        "Access tier: {} ({})".format(tier["value"], tier["name"]),
        "",
        "Can measure:",
    ]
    lines.extend("  - {}".format(item) for item in can_measure)  # type: ignore[union-attr]
    if not can_measure:
        lines.append("  - none confirmed")
    lines.extend(["", "Cannot measure:"])
    lines.extend("  - {}".format(item) for item in cannot_measure)  # type: ignore[union-attr]
    if not cannot_measure:
        lines.append("  - none")
    lines.extend(["", "Notes:"])
    lines.extend("  - {}".format(item) for item in notes)  # type: ignore[union-attr]
    return "\n".join(lines)


def json_text(profile: Dict[str, object]) -> str:
    """Serialize deterministically with a trailing newline."""

    return json.dumps(profile, indent=2, sort_keys=True) + "\n"


def write_outputs(profile: Dict[str, object], json_path: Optional[str], quiet: bool) -> int:
    """Write the requested human and machine-readable outputs."""

    destination = json_path
    if quiet and destination is None:
        destination = "-"

    if not quiet:
        human_stream = sys.stderr if destination == "-" else sys.stdout
        print(render_human(profile), file=human_stream)

    if destination == "-":
        sys.stdout.write(json_text(profile))
    elif destination is not None:
        output_path = Path(destination)
        try:
            with output_path.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(json_text(profile))
        except OSError as exc:
            print(
                "capabilities: cannot write JSON to {}: {}".format(
                    output_path.as_posix(), exc
                ),
                file=sys.stderr,
            )
            return EXIT_USAGE
    return EXIT_OK


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse the shared CLI conventions plus the optional public target."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", help="public WordPress URL to probe without authentication")
    parser.add_argument("--json", metavar="PATH", help="write JSON to PATH; - means stdout")
    parser.add_argument("--quiet", action="store_true", help="suppress the human report; JSON only")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point with contract exit codes and no raw tracebacks."""

    try:
        args = parse_args(argv)
        target = normalize_target(args.target) if args.target is not None else None
        profile = build_profile(target)
        return write_outputs(profile, args.json, args.quiet)
    except ValueError as exc:
        print("capabilities: {}".format(exc), file=sys.stderr)
        return EXIT_USAGE
    except TargetUnreachable as exc:
        print("capabilities: target unreachable: {}".format(exc), file=sys.stderr)
        return EXIT_UNREACHABLE
    except TargetUnusable as exc:
        print("capabilities: target reachable but unusable: {}".format(exc), file=sys.stderr)
        return EXIT_UNUSABLE
    except BrokenPipeError:
        return EXIT_OK
    except Exception as exc:  # Defensive CLI boundary: never expose a raw traceback.
        print("capabilities: could not complete capability detection: {}".format(exc), file=sys.stderr)
        return EXIT_UNUSABLE


if __name__ == "__main__":
    sys.exit(main())
