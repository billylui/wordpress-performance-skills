# SPDX-License-Identifier: GPL-2.0-or-later
"""Measure public WordPress timing and payload metrics, or compare two runs.

Usage:
  python3 perf-probe.py --site https://example.com [--urls-file PATH | --url U --url U ...]
                        [--json PATH] [--label NAME] [--repeats N] [--quick] [--quiet]
                        [--delay SECONDS] [--user-agent STRING]
  python3 perf-probe.py --diff A.json B.json

Origin TTFB uses a unique cache-busting query value for every request. Edge
TTFB uses the bare URL a visitor requests. Full mode discovers resources from
HTML and CSS, then sizes them with polite, bounded parallel HEAD requests.
"""

import argparse
import concurrent.futures
import datetime
import html.parser
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import uuid
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit


SCHEMA_VERSION = "1.0"
TOOL_NAME = "perf-probe"
TOOL_VERSION = "0.1.0"

# Three samples are enough for a useful median without burdening a production site.
DEFAULT_REPEATS = 3
# One request is the minimum needed to produce a timing measurement.
MIN_REPEATS = 1
# Thirty seconds tolerates slow uncached WordPress renders without hanging indefinitely.
HTTP_TIMEOUT_SECONDS = 30
# Ten seconds distinguishes a failed connection from a merely slow application response.
CONNECT_TIMEOUT_SECONDS = 10
# Five seconds lets curl terminate cleanly after its own network deadline expires.
CURL_SHUTDOWN_GRACE_SECONDS = 5
SUBPROCESS_TIMEOUT_SECONDS = HTTP_TIMEOUT_SECONDS + CURL_SHUTDOWN_GRACE_SECONDS
# Six concurrent HEAD requests keep payload walks useful without resembling an attack on shared hosting.
HEAD_WORKER_COUNT = 6
# A minute between requests is already extreme pacing; beyond it a typo has become a hang.
MAX_REQUEST_DELAY_SECONDS = 60.0
# 0 means no cap, which is the default: silently truncating a measurement is the failure this
# tool exists to avoid, so the operator opts in.
NO_ASSET_CAP = 0
MAX_ASSETS = NO_ASSET_CAP
# Five MiB is ample for text HTML/CSS while bounding memory on malformed or hostile responses.
MAX_TEXT_RESPONSE_BYTES = 5 * 1024 * 1024
# Three import levels cover normal compiled themes while bounding cyclic CSS dependency graphs.
MAX_CSS_IMPORT_DEPTH = 3
# One decimal place matches the contract examples and avoids meaningless timing/byte precision.
METRIC_DECIMAL_PLACES = 1
# HTTP 2xx and 3xx responses are usable after curl has followed redirects.
HTTP_USABLE_MIN = 200
HTTP_ERROR_MIN = 400
# These are the registered media types that positively identify an HTML document.
HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
# The reference implementation and contract examples report binary kilobytes.
BYTES_PER_KB = 1024.0
# Curl reports seconds while the metrics contract requires milliseconds.
MILLISECONDS_PER_SECOND = 1000.0
# Percentage deltas use the conventional one-hundred-point scale.
PERCENT_SCALE = 100.0
# A short suffix keeps table rows readable while still distinguishing long URLs.
REPORT_URL_WIDTH = 48

DEFAULT_LABEL = "baseline"
CACHE_BUSTER_PARAMETER = "_wp_perf_probe"
CURL_TIMING_MARKER = "__WP_PERF_PROBE_TIMING__"
# A dedicated trailer separates a bounded text body from curl's final HTTP status.
CURL_TEXT_STATUS_MARKER = "__WP_PERF_PROBE_TEXT_STATUS__"
# Identify as a browser, matching fingerprint.py.
#
# An honest bot string is the intuitive choice and it was the original one, but it measures the
# wrong thing. Security plugins, hosting WAFs and CDN bot rules routinely answer a non-browser
# User-Agent with a challenge, a 403 or a stripped page — so the probe would faithfully time an
# error page and report it as the site's performance. That is a fabricated measurement, which is
# worse than no measurement.
#
# It also made this project's own two scripts disagree: fingerprint.py already sent a browser
# string, so on a bot-protected site the two would describe different pages.
#
# The probe stays polite in the way that actually matters — it is read-only, it is bounded, and
# its concurrency is capped. Override with --user-agent when a site needs something specific.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
USER_AGENT = DEFAULT_USER_AGENT

# Ordered from outer edge indicators toward increasingly generic cache indicators.
CACHE_HEADER_NAMES = (
    "cf-cache-status",
    "x-litespeed-cache",
    "x-cache",
    "x-qc-cache",
    "x-proxy-cache",
    "x-cache-status",
    "x-fastcgi-cache",
    "x-varnish-cache",
)
CACHE_STATUSES = {"HIT", "MISS", "BYPASS", "DYNAMIC"}
# These curl failures exactly represent DNS/proxy resolution, connect failure, or total timeout.
UNREACHABLE_CURL_CODES = {5, 6, 7, 28}

METRICS_TOP_LEVEL_KEYS = {
    "schema_version",
    "tool",
    "tool_version",
    "generated_at",
    "label",
    "site",
    "repeats",
    "quick",
    "urls",
    "totals",
}
METRICS_URL_KEYS = {
    "url",
    "http_status",
    "origin_ttfb_ms",
    "edge_ttfb_ms",
    "origin_ttfb_samples_ms",
    "edge_ttfb_samples_ms",
    "cache_status",
    "cache_header",
    "requests",
    "html_kb",
    "css_kb",
    "js_kb",
    "img_kb",
    "font_kb",
    "other_kb",
    "total_kb",
    "unsized_resources",
    "discovery_incomplete",
    "asset_cap_applied",
    "errors",
}
METRICS_TOTAL_KEYS = {
    "url_count",
    "all_urls_total_kb",
    "all_urls_requests",
    "all_urls_unsized_resources",
}
PAYLOAD_FIELDS = ("html_kb", "css_kb", "js_kb", "img_kb", "font_kb", "other_kb")
ASSET_KINDS = ("css", "js", "img", "font", "other")

FONT_EXTENSIONS = (".woff", ".woff2", ".otf", ".ttf", ".eot")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg", ".ico")
SCRIPT_EXTENSIONS = (".js", ".mjs")
STYLE_EXTENSIONS = (".css",)

CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
CSS_IMPORT_RE = re.compile(
    r"@import\s+(?:url\(\s*)?(['\"])(.*?)\1\s*\)?", re.IGNORECASE
)


def utc_now() -> str:
    """Return a stable, timezone-explicit contract timestamp."""
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return now.isoformat().replace("+00:00", "Z")


def rounded(value: float) -> float:
    return round(value, METRIC_DECIMAL_PLACES)


def median(values: Iterable[float]) -> Optional[float]:
    collected = list(values)
    return rounded(statistics.median(collected)) if collected else None


def sanitize_error(value: str) -> str:
    """Keep operator-facing errors actionable, single-line, and diff-friendly."""
    return " ".join(value.replace("\x00", "").split())


def is_html_content_type(value: str) -> bool:
    """Return whether a declared Content-Type positively identifies HTML."""
    media_type = value.partition(";")[0].strip().lower()
    return media_type in HTML_CONTENT_TYPES


def find_curl() -> Optional[str]:
    """Find curl without assuming the caller's PATH is populated."""
    discovered = shutil.which("curl")
    if discovered:
        return discovered
    system_curl = "/usr/bin/curl"
    if os.path.isfile(system_curl) and os.access(system_curl, os.X_OK):
        return system_curl
    return None


def curl_command(curl_binary: str, extra_args: Sequence[str]) -> List[str]:
    return [
        curl_binary,
        "--silent",
        "--show-error",
        "--location",
        "--compressed",
        "--user-agent",
        USER_AGENT,
        "--connect-timeout",
        str(CONNECT_TIMEOUT_SECONDS),
        "--max-time",
        str(HTTP_TIMEOUT_SECONDS),
        "--proto",
        "=http,https",
        "--proto-redir",
        "=http,https",
        *extra_args,
    ]


class RequestPacer:
    """Bound the aggregate request rate across every worker thread.

    Some sites throttle sustained probing, and a throttled read is a fabricated finding: the
    probe would faithfully time the site's rate limiter and report it as the site's performance.
    Pacing is the operator's lever for that.

    The interval is enforced globally rather than per thread, so the cap holds whatever the
    worker count is — `--delay 1` means at most one request per second in total, not one per
    second per worker.

    **The wait cannot contaminate a measurement.** curl times the request internally and reports
    `time_starttransfer`, so sleeping before curl is invoked changes when the request happens,
    never what it measures.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._min_interval = 0.0
        self._next_allowed = 0.0

    def configure(self, delay_seconds: float) -> None:
        self._min_interval = max(0.0, delay_seconds)
        self._next_allowed = 0.0

    def wait(self) -> None:
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            remaining = self._next_allowed - now
            if remaining > 0:
                time.sleep(remaining)
                now = time.monotonic()
            self._next_allowed = now + self._min_interval


PACER = RequestPacer()


# Consecutive timed-out REQUESTS from one host before the walk stops asking it for anything else.
# Counted per request, not per resource, because a resource whose HEAD times out then pays the
# same timeout again on the GET fallback — so a single dead resource contributes two.
# Three, because one timeout is ordinary on a busy origin and two can still be coincidence, while
# three in a row from the same host has never yet been anything but a host that will not answer.
HOST_TIMEOUT_CIRCUIT_LIMIT = 3

# curl's exit code for "operation timed out". Deliberately the only code that trips the breaker:
# a host that refuses a connection or fails to resolve costs milliseconds and is self-limiting,
# whereas a host that accepts the connection and never answers burns the full timeout every time.
# Wall-clock is what the breaker exists to protect, so only the slow failure counts.
CURL_TIMEOUT_CODE = 28


class HostCircuitBreaker:
    """Stop requesting a host once it has timed out N times in a row.

    `--max-assets` caps how many resources are sized, which bounds the symptom. It does not stop
    one unreachable host from consuming the entire budget: on a real audit, font CSS pointed at a
    staging domain that resolved but never answered, and every font request burned the full
    timeout before failing. Capping the count still leaves each surviving request paying it.

    The counter resets on any answered request, so a host that is merely slow or intermittently
    loaded recovers instead of being written off after a bad patch. Only an unbroken run of
    timeouts opens the circuit.

    Nothing skipped is ever counted as zero bytes. Skipped resources are reported as unsized with
    the reason, exactly like any other resource that could not be measured, so the payload total
    stays a floor rather than becoming a quiet understatement.

    State is shared across the sizing pool's worker threads and across every URL in a run — a host
    that is dead for one page is dead for the next, and re-testing it per page would give back the
    time the breaker just saved.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._consecutive_timeouts: Dict[str, int] = {}
        self._open_hosts: Set[str] = set()
        self._skipped: Dict[str, int] = {}

    def reset(self) -> None:
        with self._lock:
            self._consecutive_timeouts.clear()
            self._open_hosts.clear()
            self._skipped.clear()

    def is_open(self, host: str) -> bool:
        with self._lock:
            return host in self._open_hosts

    def record_outcome(self, host: str, timed_out: bool) -> None:
        with self._lock:
            if not timed_out:
                self._consecutive_timeouts[host] = 0
                return
            count = self._consecutive_timeouts.get(host, 0) + 1
            self._consecutive_timeouts[host] = count
            if count >= HOST_TIMEOUT_CIRCUIT_LIMIT:
                self._open_hosts.add(host)

    def record_skip(self, host: str) -> None:
        with self._lock:
            self._skipped[host] = self._skipped.get(host, 0) + 1

    def skip_counts(self) -> Dict[str, int]:
        """Snapshot skips per host, so a caller can report only what happened on its own watch."""

        with self._lock:
            return dict(self._skipped)


BREAKER = HostCircuitBreaker()


def host_of(url: str) -> str:
    """Return the host a request will actually go to, lowercased for stable keying."""

    return urlsplit(url).netloc.lower()


def select_within_cap(
    ordered_resources: Sequence[Tuple[str, str]], cap: int
) -> Tuple[List[Tuple[str, str]], int]:
    """Choose which resources to size when a cap applies, and report how many were skipped.

    Selection is a deterministic round-robin across resource kinds, not the first N of a sorted
    list. A sorted prefix would take every `assets/a*.css` and reach no images at all, so the
    per-kind breakdown of a capped run would describe the alphabet rather than the page. Taking
    them in rotation keeps the shape of the page visible even when the walk is cut short.
    """

    if cap == NO_ASSET_CAP or len(ordered_resources) <= cap:
        return list(ordered_resources), 0

    by_kind: Dict[str, List[Tuple[str, str]]] = {}
    for entry in ordered_resources:
        by_kind.setdefault(entry[1], []).append(entry)

    rotated: List[Tuple[str, str]] = []
    while len(rotated) < len(ordered_resources):
        for kind in list(by_kind):
            if by_kind[kind]:
                rotated.append(by_kind[kind].pop(0))
    return rotated[:cap], len(ordered_resources) - cap


def run_curl(curl_binary: str, extra_args: Sequence[str]) -> Dict[str, object]:
    PACER.wait()
    try:
        completed = subprocess.run(
            curl_command(curl_binary, extra_args),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "returncode": 28,
            "stdout": b"",
            "error": "request exceeded the total timeout",
            "unreachable": True,
        }
    except OSError as exc:
        return {
            "returncode": None,
            "stdout": b"",
            "error": "could not execute curl: {}".format(sanitize_error(str(exc))),
            "unreachable": False,
        }

    stderr = sanitize_error(completed.stderr.decode("utf-8", "replace"))
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "error": stderr or "curl exited with code {}".format(completed.returncode),
        "unreachable": completed.returncode in UNREACHABLE_CURL_CODES,
    }


def parse_final_headers(raw: str) -> Tuple[Optional[int], Dict[str, str]]:
    """Return only the final response block after proxies and redirects."""
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    blocks = [block.strip() for block in normalized.split("\n\n") if block.strip()]
    response_blocks = [block for block in blocks if block.splitlines()[0].startswith("HTTP/")]
    if not response_blocks:
        return None, {}

    lines = response_blocks[-1].splitlines()
    status = None
    status_parts = lines[0].split()
    if len(status_parts) >= 2:
        try:
            status = int(status_parts[1])
        except ValueError:
            status = None

    headers: Dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        key = name.strip().lower()
        cleaned = value.strip()
        if key in headers:
            headers[key] = "{}, {}".format(headers[key], cleaned)
        else:
            headers[key] = cleaned
    return status, headers


def timed_request(curl_binary: str, url: str) -> Dict[str, object]:
    write_out = (
        "\n{}\t%{{time_starttransfer}}\t%{{size_download}}\t%{{http_code}}"
        "\t%{{content_type}}\t%{{url_effective}}"
    ).format(CURL_TIMING_MARKER)
    result = run_curl(
        curl_binary,
        ["--dump-header", "-", "--output", os.devnull, "--write-out", write_out, url],
    )
    if result["returncode"] != 0:
        return result

    text = result["stdout"].decode("utf-8", "replace")
    marker = "\n{}\t".format(CURL_TIMING_MARKER)
    if marker not in text:
        return {
            "returncode": None,
            "error": "curl returned no parseable timing record",
            "unreachable": False,
        }
    header_text, timing_text = text.rsplit(marker, 1)
    fields = timing_text.strip().split("\t", 4)
    if len(fields) != 5:
        return {
            "returncode": None,
            "error": "curl returned an incomplete timing record",
            "unreachable": False,
        }
    try:
        ttfb_ms = rounded(float(fields[0]) * MILLISECONDS_PER_SECOND)
        size_bytes = int(float(fields[1]))
        http_status = int(fields[2])
    except (TypeError, ValueError):
        return {
            "returncode": None,
            "error": "curl returned invalid numeric timing data",
            "unreachable": False,
        }
    parsed_status, headers = parse_final_headers(header_text)
    return {
        "returncode": 0,
        "unreachable": False,
        "ttfb_ms": ttfb_ms,
        "size_bytes": size_bytes,
        "http_status": parsed_status if parsed_status is not None else http_status,
        "headers": headers,
        "content_type": fields[3].strip().lower(),
        "effective_url": fields[4].strip(),
    }


def fetch_text(curl_binary: str, url: str) -> Dict[str, object]:
    write_out = "\n{}%{{http_code}}".format(CURL_TEXT_STATUS_MARKER)
    result = run_curl(
        curl_binary,
        [
            "--max-filesize",
            str(MAX_TEXT_RESPONSE_BYTES),
            "--output",
            "-",
            "--write-out",
            write_out,
            url,
        ],
    )
    if result["returncode"] != 0:
        return result
    marker = "\n{}".format(CURL_TEXT_STATUS_MARKER).encode("ascii")
    if marker not in result["stdout"]:
        return {
            "returncode": None,
            "error": "curl returned no parseable HTTP status for text response",
            "unreachable": False,
        }
    body, raw_status = result["stdout"].rsplit(marker, 1)
    try:
        http_status = int(raw_status.strip())
    except ValueError:
        return {
            "returncode": None,
            "error": "curl returned an invalid HTTP status for text response",
            "unreachable": False,
        }
    if http_status < HTTP_USABLE_MIN or http_status >= HTTP_ERROR_MIN:
        return {
            "returncode": None,
            "error": "HTTP {} while reading text response".format(http_status),
            "unreachable": False,
        }
    if len(body) > MAX_TEXT_RESPONSE_BYTES:
        return {
            "returncode": None,
            "error": "text response exceeded {} bytes".format(MAX_TEXT_RESPONSE_BYTES),
            "unreachable": False,
        }
    return {
        "returncode": 0,
        "stdout": body,
        "text": body.decode("utf-8", "replace"),
        "unreachable": False,
    }


def get_size(curl_binary: str, url: str, hint: str, head_error: str) -> Dict[str, object]:
    """Size a resource by downloading it and counting the bytes actually transferred.

    The fallback path when HEAD cannot answer. It is slower, so it is never the first choice,
    but on modern stacks it is frequently the ONLY choice: servers that compress text assets on
    the fly respond with chunked transfer encoding and no content-length, and some CDNs reject
    HEAD outright with a 4xx. Measured against a live Elementor site, HEAD alone could not size
    a single CSS or JS file — which silently reduced page weight, the tool's headline output, to
    "unknown" on exactly the sites people most need to measure.

    Counting received bytes is also the more faithful number: it is what the browser actually
    pulls over the wire, compression included, rather than what the origin claims.

    The download is bounded by the shared --max-time; a resource too slow to finish inside it
    stays unsized rather than being guessed at.
    """

    host = host_of(url)
    if BREAKER.is_open(host):
        # Reached when the HEAD above was the request that opened the circuit. Retrying the same
        # dead host with a GET would pay a second full timeout to learn what was just established.
        BREAKER.record_skip(host)
        return {
            "url": url,
            "kind": hint,
            "size_bytes": None,
            "error": "host {} stopped answering; GET fallback not attempted ({})".format(
                host, head_error
            ),
            "circuit_skipped": True,
        }

    result = run_curl(
        curl_binary,
        ["--output", os.devnull, "--write-out", "%{size_download} %{http_code} %{content_type}", url],
    )
    BREAKER.record_outcome(host, result["returncode"] == CURL_TIMEOUT_CODE)
    if result["returncode"] != 0:
        return {"url": url, "kind": hint, "size_bytes": None, "error": head_error}

    fields = result["stdout"].decode("utf-8", "replace").strip().split(" ", 2)
    if len(fields) < 2:
        return {"url": url, "kind": hint, "size_bytes": None, "error": head_error}

    content_type = fields[2].strip().lower() if len(fields) > 2 else ""
    kind = classify_resource(url, content_type, hint)
    try:
        size_bytes = int(float(fields[0]))
        status = int(fields[1])
    except (TypeError, ValueError):
        return {"url": url, "kind": kind, "size_bytes": None, "error": head_error}

    if status < HTTP_USABLE_MIN or status >= HTTP_ERROR_MIN:
        return {
            "url": url,
            "kind": kind,
            "size_bytes": None,
            "error": "HTTP {} on both HEAD and GET".format(status),
        }
    if size_bytes <= 0:
        return {
            "url": url,
            "kind": kind,
            "size_bytes": None,
            "error": "GET fallback transferred no bytes ({})".format(head_error),
        }
    return {"url": url, "kind": kind, "size_bytes": size_bytes, "error": None}


def head_size(curl_binary: str, url: str, hint: str) -> Dict[str, object]:
    """Size a resource, preferring a cheap HEAD and falling back to a counted GET.

    The circuit breaker is consulted here rather than inside `run_curl`, because it must govern
    the asset walk alone. The site being audited is the whole point of the run: if its own origin
    is timing out, that is the measurement, not a reason to stop asking.
    """

    host = host_of(url)
    if BREAKER.is_open(host):
        BREAKER.record_skip(host)
        return {
            "url": url,
            "kind": hint,
            "size_bytes": None,
            "error": "host {} stopped answering; not requested".format(host),
            "circuit_skipped": True,
        }

    result = run_curl(
        curl_binary,
        ["--head", "--dump-header", "-", "--output", os.devnull, url],
    )
    BREAKER.record_outcome(host, result["returncode"] == CURL_TIMEOUT_CODE)
    if result["returncode"] != 0:
        return get_size(curl_binary, url, hint, str(result["error"]))

    status, headers = parse_final_headers(result["stdout"].decode("utf-8", "replace"))
    content_type = headers.get("content-type", "").lower()
    kind = classify_resource(url, content_type, hint)
    if status is None or status < HTTP_USABLE_MIN or status >= HTTP_ERROR_MIN:
        # Some CDNs answer HEAD with 4xx while serving GET normally, so this is not yet a failure.
        return get_size(
            curl_binary,
            url,
            kind,
            "HEAD returned HTTP {}".format(status if status is not None else "unknown"),
        )

    raw_length = headers.get("content-length")
    if raw_length is None:
        return get_size(curl_binary, url, kind, "HEAD response had no content-length")
    try:
        size_bytes = int(raw_length.split(",")[-1].strip())
    except ValueError:
        return get_size(
            curl_binary, url, kind, "HEAD response had invalid content-length {!r}".format(raw_length)
        )
    if size_bytes < 0:
        return get_size(curl_binary, url, kind, "HEAD response had negative content-length")
    return {"url": url, "kind": kind, "size_bytes": size_bytes, "error": None}


def cache_signal(headers: Dict[str, str]) -> Tuple[str, str]:
    for header_name in CACHE_HEADER_NAMES:
        if header_name not in headers:
            continue
        tokens = re.findall(r"[A-Z]+", headers[header_name].upper())
        for status in ("HIT", "MISS", "BYPASS", "DYNAMIC"):
            if status in tokens:
                return status, header_name
        return "unknown", header_name
    return "unknown", "unknown"


def add_cache_buster(url: str, sample_number: int) -> str:
    parsed = urlsplit(url)
    unique_value = "{}-{}-{}-{}".format(
        time.time_ns(), os.getpid(), sample_number, uuid.uuid4().hex
    )
    query = parsed.query
    addition = "{}={}".format(CACHE_BUSTER_PARAMETER, unique_value)
    query = "{}&{}".format(query, addition) if query else addition
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


def classify_resource(url: str, content_type: str = "", hint: str = "other") -> str:
    path = urlsplit(url).path.lower()
    if path.endswith(FONT_EXTENSIONS) or content_type.startswith(("font/", "application/font")):
        return "font"
    if path.endswith(STYLE_EXTENSIONS) or "text/css" in content_type:
        return "css"
    if path.endswith(SCRIPT_EXTENSIONS) or "javascript" in content_type:
        return "js"
    if path.endswith(IMAGE_EXTENSIONS) or content_type.startswith("image/"):
        return "img"
    return hint if hint in ASSET_KINDS else "other"


def safe_asset_url(base_url: str, raw_url: str) -> Tuple[Optional[str], Optional[str]]:
    candidate = raw_url.strip().strip("'\"")
    if not candidate or candidate.startswith(("#", "data:", "blob:", "javascript:", "mailto:", "tel:")):
        return None, None
    try:
        absolute, _fragment = urldefrag(urljoin(base_url, candidate))
        parsed = urlsplit(absolute)
    except ValueError as exc:
        return None, "invalid asset URL: {}".format(sanitize_error(str(exc)))
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        return None, None
    if parsed.username is not None or parsed.password is not None:
        return None, "skipped asset URL containing embedded credentials"
    return absolute, None


def srcset_urls(value: str) -> Iterable[str]:
    """Yield each candidate URL from a srcset attribute, following the HTML parsing rule.

    Splitting on every comma is wrong, because a srcset URL may legitimately contain commas.
    Cloudflare's image-resizing paths are the common real-world case —
    `/cdn-cgi/image/f=auto,w=1120/photo.webp 1120w` — and a naive split fabricated two broken
    URLs from each one. Measured against a live site, every such image then 404'd and went
    unsized, silently dropping images (usually the largest component) out of page weight.

    The rule that removes the ambiguity: a candidate URL runs to the next WHITESPACE, not the
    next comma. Only a trailing comma ends a candidate early, in which case it has no descriptor.
    """

    index = 0
    length = len(value)
    while index < length:
        while index < length and (value[index].isspace() or value[index] == ","):
            index += 1
        start = index
        while index < length and not value[index].isspace():
            index += 1
        token = value[start:index]
        if not token:
            continue
        trimmed = token.rstrip(",")
        if trimmed:
            yield trimmed
        if trimmed != token:
            # The URL carried its own trailing comma, so this candidate has no descriptor.
            continue
        # Skip the descriptor ("1120w", "2x") up to the comma that ends this candidate.
        while index < length and value[index] != ",":
            index += 1


class ResourceParser(html.parser.HTMLParser):
    """Collect static browser resources without executing page content."""

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.resources: Dict[str, str] = {}
        self.inline_css: List[str] = []
        self.errors: List[str] = []
        self._inside_style = False

    def add(self, raw_url: str, hint: str) -> None:
        absolute, error = safe_asset_url(self.base_url, raw_url)
        if error:
            self.errors.append(error)
        if absolute is None:
            return
        classified = classify_resource(absolute, hint=hint)
        existing = self.resources.get(absolute)
        if existing is None or existing == "other":
            self.resources[absolute] = classified

    def add_css_text(self, css_text: str, css_base: Optional[str] = None) -> None:
        base = css_base or self.base_url
        for _quote, raw_url in CSS_URL_RE.findall(css_text):
            absolute, error = safe_asset_url(base, raw_url)
            if error:
                self.errors.append(error)
            if absolute:
                self.resources.setdefault(absolute, classify_resource(absolute))
        for _quote, raw_url in CSS_IMPORT_RE.findall(css_text):
            absolute, error = safe_asset_url(base, raw_url)
            if error:
                self.errors.append(error)
            if absolute:
                self.resources[absolute] = "css"

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        attributes = {name.lower(): (value or "") for name, value in attrs}
        tag = tag.lower()
        if "style" in attributes:
            self.add_css_text(attributes["style"])

        if tag == "style":
            self._inside_style = True
        elif tag == "link":
            href = attributes.get("href")
            rel = set(attributes.get("rel", "").lower().split())
            if href and "stylesheet" in rel:
                self.add(href, "css")
            elif href and rel.intersection({"preload", "modulepreload"}):
                as_value = attributes.get("as", "").lower()
                hint = {
                    "style": "css",
                    "script": "js",
                    "image": "img",
                    "font": "font",
                }.get(as_value, "other")
                self.add(href, hint)
            elif href and rel.intersection({"icon", "apple-touch-icon"}):
                self.add(href, "img")
        elif tag == "script" and attributes.get("src"):
            self.add(attributes["src"], "js")
        elif tag == "img":
            for name in ("src", "data-src", "data-lazy-src"):
                if attributes.get(name):
                    self.add(attributes[name], "img")
            for name in ("srcset", "data-srcset"):
                for raw_url in srcset_urls(attributes.get(name, "")):
                    self.add(raw_url, "img")
        elif tag == "source":
            hint = "img" if attributes.get("type", "").lower().startswith("image/") else "other"
            if attributes.get("src"):
                self.add(attributes["src"], hint)
            for raw_url in srcset_urls(attributes.get("srcset", "")):
                self.add(raw_url, "img")
        elif tag in ("video", "audio"):
            if attributes.get("src"):
                self.add(attributes["src"], "other")
            if tag == "video" and attributes.get("poster"):
                self.add(attributes["poster"], "img")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "style":
            self._inside_style = False

    def handle_data(self, data: str) -> None:
        if self._inside_style:
            self.inline_css.append(data)
            self.add_css_text(data)


def discover_resources(
    curl_binary: str, page_url: str, document: str
) -> Tuple[Dict[str, str], List[str], bool]:
    parser = ResourceParser(page_url)
    try:
        parser.feed(document)
        parser.close()
    except ValueError as exc:
        parser.errors.append("HTML parse failed: {}".format(sanitize_error(str(exc))))
        return parser.resources, parser.errors, True

    errors = list(parser.errors)
    parser_error_count = len(parser.errors)
    discovery_incomplete = False
    pending = sorted(url for url, kind in parser.resources.items() if kind == "css")
    fetched_css: Set[str] = set()

    for _depth in range(MAX_CSS_IMPORT_DEPTH):
        current = [url for url in pending if url not in fetched_css]
        if not current:
            break
        pending = []
        for css_url in sorted(current):
            fetched_css.add(css_url)
            # Discovery is serial and runs BEFORE any sizing, so a dead host reached here pays the
            # full timeout per stylesheet with nothing to stop it. That is not a hypothetical: the
            # audit this breaker was built for stalled on font CSS pointing at a staging domain
            # that resolved and never answered. Gating only the sizing pool would have missed the
            # exact path that caused it.
            css_host = host_of(css_url)
            if BREAKER.is_open(css_host):
                BREAKER.record_skip(css_host)
                errors.append(
                    "CSS discovery skipped for {}: host {} stopped answering".format(
                        css_url, css_host
                    )
                )
                discovery_incomplete = True
                continue
            result = fetch_text(curl_binary, css_url)
            BREAKER.record_outcome(css_host, result["returncode"] == CURL_TIMEOUT_CODE)
            if result["returncode"] != 0:
                errors.append(
                    "CSS discovery failed for {}: {}".format(css_url, result["error"])
                )
                discovery_incomplete = True
                continue
            before = set(parser.resources)
            parser.add_css_text(result["text"], css_url)
            for discovered_url in sorted(set(parser.resources) - before):
                if parser.resources[discovered_url] == "css":
                    pending.append(discovered_url)
        errors.extend(parser.errors[parser_error_count:])
        parser_error_count = len(parser.errors)

    if any(url not in fetched_css for url in pending):
        errors.append("CSS discovery stopped at the configured import-depth limit")
        discovery_incomplete = True
    return dict(sorted(parser.resources.items())), sorted(set(errors)), discovery_incomplete


def payload_metrics(
    curl_binary: str,
    url: str,
    html_text: str,
    html_bytes: Optional[int],
) -> Tuple[Dict[str, object], List[str]]:
    resources, errors, discovery_incomplete = discover_resources(curl_binary, url, html_text)
    # Each bucket reports the bytes actually MEASURED, alongside a count of what could not be
    # measured. An earlier all-or-nothing design nulled a whole bucket — and therefore the page
    # total — as soon as one resource resisted sizing. Measured against a live site that meant a
    # single third-party widget answering 400 to both HEAD and GET erased an 11 MB image total,
    # which destroys the tool's whole purpose: a before/after comparison is worthless when both
    # sides are null. Partial sums stay comparable across runs because the same assets are
    # measured each time; `unsized_resources` is what keeps the number honest rather than
    # silently understated. Nothing unmeasured is ever counted as zero.
    buckets: Dict[str, int] = {kind: 0 for kind in ASSET_KINDS}
    unsized = 0

    ordered_resources = sorted(resources.items())
    selected_resources, skipped_by_cap = select_within_cap(ordered_resources, MAX_ASSETS)
    if skipped_by_cap:
        unsized += skipped_by_cap
        errors.append(
            "asset cap of {} reached: {} discovered resource(s) were not sized and are excluded "
            "from the totals".format(MAX_ASSETS, skipped_by_cap)
        )
    skips_before = BREAKER.skip_counts()
    with concurrent.futures.ThreadPoolExecutor(max_workers=HEAD_WORKER_COUNT) as executor:
        futures = [
            executor.submit(head_size, curl_binary, asset_url, hint)
            for asset_url, hint in selected_resources
        ]
        for future in futures:
            result = future.result()
            if result["size_bytes"] is None:
                unsized += 1
                # Resources the breaker skipped are still unsized — never zero — but they are
                # reported once per host below rather than once per resource. A dead host with
                # fifty assets would otherwise bury every other error under fifty copies of the
                # same sentence.
                if not result.get("circuit_skipped"):
                    errors.append(
                        "could not size {}: {}".format(result["url"], result["error"])
                    )
            else:
                buckets[result["kind"]] += result["size_bytes"]

    skips_after = BREAKER.skip_counts()
    for dead_host in sorted(skips_after):
        skipped_here = skips_after[dead_host] - skips_before.get(dead_host, 0)
        if skipped_here > 0:
            errors.append(
                "host {} stopped answering after {} consecutive timeouts: {} resource(s) on it "
                "were not sized and are excluded from the totals".format(
                    dead_host, HOST_TIMEOUT_CIRCUIT_LIMIT, skipped_here
                )
            )

    result_metrics: Dict[str, object] = {
        "requests": 1 + len(resources),
        "html_kb": rounded(html_bytes / BYTES_PER_KB) if html_bytes is not None else None,
        # Resources a failed stylesheet read would have revealed are unknown in number, not just
        # in size, so discovery failure is reported rather than folded into the byte counts.
        "discovery_incomplete": discovery_incomplete,
        # A capped total is a floor over a sample, not a page weight. Stated as its own field so
        # a consumer cannot mistake it for a complete measurement.
        "asset_cap_applied": bool(skipped_by_cap),
    }
    for kind in ASSET_KINDS:
        result_metrics["{}_kb".format(kind)] = rounded(buckets[kind] / BYTES_PER_KB)
    payload_values = [result_metrics[field] for field in PAYLOAD_FIELDS]
    measured = [value for value in payload_values if value is not None]
    # null only when the page itself could not be read at all; otherwise a measured total.
    result_metrics["total_kb"] = rounded(sum(measured)) if measured else None
    result_metrics["unsized_resources"] = unsized
    return result_metrics, sorted(set(errors))


def empty_url_row(url: str) -> Dict[str, object]:
    return {
        "url": url,
        "http_status": None,
        "origin_ttfb_ms": None,
        "edge_ttfb_ms": None,
        "origin_ttfb_samples_ms": [],
        "edge_ttfb_samples_ms": [],
        "cache_status": "unknown",
        "cache_header": "unknown",
        "requests": 1,
        "html_kb": None,
        "css_kb": None,
        "js_kb": None,
        "img_kb": None,
        "font_kb": None,
        "other_kb": None,
        "total_kb": None,
        "unsized_resources": 0,
        "discovery_incomplete": False,
        "asset_cap_applied": False,
        "errors": [],
    }


def measure_url(
    curl_binary: str, url: str, repeats: int, quick: bool
) -> Tuple[Dict[str, object], bool, bool]:
    row = empty_url_row(url)
    errors: List[str] = []
    origin_results: List[Dict[str, object]] = []
    edge_results: List[Dict[str, object]] = []
    all_http_results: List[Dict[str, object]] = []
    unreachable_failures = 0
    non_unreachable_failures = 0

    for sample_number in range(repeats):
        result = timed_request(curl_binary, add_cache_buster(url, sample_number))
        if result["returncode"] != 0:
            errors.append(
                "origin sample {} failed: {}".format(sample_number + 1, result["error"])
            )
            if result.get("unreachable"):
                unreachable_failures += 1
            else:
                non_unreachable_failures += 1
            continue
        all_http_results.append(result)
        status, header_name = cache_signal(result["headers"])
        if status == "HIT":
            errors.append(
                "origin sample {} reported HIT in {}; cache-buster may be ignored".format(
                    sample_number + 1, header_name
                )
            )
            continue
        origin_results.append(result)

    for sample_number in range(repeats):
        result = timed_request(curl_binary, url)
        if result["returncode"] != 0:
            errors.append("edge sample {} failed: {}".format(sample_number + 1, result["error"]))
            if result.get("unreachable"):
                unreachable_failures += 1
            else:
                non_unreachable_failures += 1
            continue
        all_http_results.append(result)
        edge_results.append(result)

    successful_results = edge_results or origin_results
    # Only DNS, connection, and total-timeout failures qualify for exit 3.
    # TLS, redirect, protocol, and response-parse failures mean the host was
    # reached but was unusable, which is exit 4 when every target is affected.
    reachable = bool(all_http_results) or non_unreachable_failures > 0
    status_results = successful_results or all_http_results
    if status_results:
        row["http_status"] = status_results[-1]["http_status"]
    row["origin_ttfb_samples_ms"] = [result["ttfb_ms"] for result in origin_results]
    row["edge_ttfb_samples_ms"] = [result["ttfb_ms"] for result in edge_results]
    row["origin_ttfb_ms"] = median(row["origin_ttfb_samples_ms"])
    row["edge_ttfb_ms"] = median(row["edge_ttfb_samples_ms"])

    if edge_results:
        row["cache_status"], row["cache_header"] = cache_signal(edge_results[-1]["headers"])

    statuses = [result["http_status"] for result in successful_results]
    bad_statuses = sorted(
        {status for status in statuses if status < HTTP_USABLE_MIN or status >= HTTP_ERROR_MIN}
    )
    for status in bad_statuses:
        errors.append("HTTP {} returned for {}".format(status, url))

    html_source = status_results[-1] if status_results else None
    html_bytes = html_source["size_bytes"] if html_source is not None else None
    if quick:
        row["html_kb"] = rounded(html_bytes / BYTES_PER_KB) if html_bytes is not None else None
        usable = bool(
            reachable
            and row["http_status"] is not None
            and HTTP_USABLE_MIN <= row["http_status"] < HTTP_ERROR_MIN
        )
        declared_content_type = html_source.get("content_type", "") if html_source else ""
        if usable and not is_html_content_type(declared_content_type):
            received = declared_content_type or "no content type"
            errors.append("quick probe requires HTML but received {}".format(received))
            usable = False
        row["errors"] = sorted(set(errors))
        return row, reachable, usable

    usable = False
    if (
        reachable
        and row["http_status"] is not None
        and HTTP_USABLE_MIN <= row["http_status"] < HTTP_ERROR_MIN
    ):
        declared_content_type = html_source.get("content_type", "") if html_source else ""
        if declared_content_type and not is_html_content_type(declared_content_type):
            errors.append("payload walk requires HTML but received {}".format(declared_content_type))
        else:
            body_result = fetch_text(curl_binary, url)
            if body_result["returncode"] != 0:
                errors.append("HTML fetch failed: {}".format(body_result["error"]))
            else:
                payload, payload_errors = payload_metrics(
                    curl_binary, url, body_result["text"], html_bytes
                )
                row.update(payload)
                errors.extend(payload_errors)
                usable = True
    row["errors"] = sorted(set(errors))
    if not reachable and unreachable_failures == 0:
        row["errors"].append("target produced no usable HTTP response")
        row["errors"] = sorted(set(row["errors"]))
    return row, reachable, usable


def normalize_site(raw_site: str) -> str:
    value = raw_site.strip()
    if any(character in value for character in ("\n", "\r", "\t")):
        raise ValueError("site URL must not contain control characters")
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("--site must be an absolute public HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("--site must not contain embedded credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("--site must not contain a query string or fragment")
    path = parsed.path.rstrip("/")
    return urlunsplit(("https", parsed.netloc, path, "", ""))


def normalize_target(site: str, raw_target: str) -> str:
    value = raw_target.strip()
    if not value:
        raise ValueError("target URL or path must not be empty")
    if any(character in value for character in ("\n", "\r", "\t")):
        raise ValueError("target URL must not contain control characters")
    absolute = urljoin(site + "/", value)
    parsed = urlsplit(absolute)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("target {!r} must resolve to an absolute HTTPS URL".format(value))
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("target {!r} must not contain embedded credentials".format(value))
    clean, _fragment = urldefrag(absolute)
    return clean


def load_url_file(path: str) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return [
                line.strip()
                for line in handle
                if line.strip() and not line.lstrip().startswith("#")
            ]
    except OSError as exc:
        raise ValueError("could not read --urls-file {}: {}".format(path, sanitize_error(str(exc))))


def validate_metrics_document(document: object) -> List[str]:
    errors: List[str] = []
    if not isinstance(document, dict):
        return ["document must be a JSON object"]
    if set(document) != METRICS_TOP_LEVEL_KEYS:
        errors.append("top-level keys do not match the metrics contract")
    if document.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must be {}".format(SCHEMA_VERSION))
    if document.get("tool") != TOOL_NAME:
        errors.append("tool must be {}".format(TOOL_NAME))
    if not isinstance(document.get("repeats"), int) or document.get("repeats", 0) < MIN_REPEATS:
        errors.append("repeats must be a positive integer")
    if not isinstance(document.get("quick"), bool):
        errors.append("quick must be boolean")
    rows = document.get("urls")
    if not isinstance(rows, list):
        errors.append("urls must be an array")
        rows = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != METRICS_URL_KEYS:
            errors.append("urls[{}] keys do not match the metrics contract".format(index))
            continue
        if row.get("cache_status") not in CACHE_STATUSES.union({"unknown"}):
            errors.append("urls[{}].cache_status is invalid".format(index))
        for samples_key in ("origin_ttfb_samples_ms", "edge_ttfb_samples_ms"):
            samples = row.get(samples_key)
            if not isinstance(samples, list) or any(
                not isinstance(value, (int, float)) or isinstance(value, bool) for value in samples
            ):
                errors.append("urls[{}].{} must contain only numbers".format(index, samples_key))
        for payload_key in PAYLOAD_FIELDS + ("total_kb",):
            value = row.get(payload_key)
            if value is not None and (
                not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0
            ):
                errors.append("urls[{}].{} must be non-negative or null".format(index, payload_key))
        if not isinstance(row.get("errors"), list) or any(
            not isinstance(value, str) for value in row.get("errors", [])
        ):
            errors.append("urls[{}].errors must contain only strings".format(index))
    totals = document.get("totals")
    if not isinstance(totals, dict) or set(totals) != METRICS_TOTAL_KEYS:
        errors.append("totals keys do not match the metrics contract")
    return sorted(set(errors))


def build_document(
    site: str,
    label: str,
    repeats: int,
    quick: bool,
    rows: List[Dict[str, object]],
) -> Dict[str, object]:
    # Sum the URLs that were measurable. A single unreachable URL in a fleet must not erase the
    # fleet total; `all_urls_unsized_resources` reports how much measurement is missing.
    total_values = [row["total_kb"] for row in rows if row["total_kb"] is not None]
    all_urls_total_kb = rounded(sum(total_values)) if total_values else None
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "generated_at": utc_now(),
        "label": label,
        "site": site,
        "repeats": repeats,
        "quick": quick,
        "urls": rows,
        "totals": {
            "url_count": len(rows),
            "all_urls_total_kb": all_urls_total_kb,
            "all_urls_requests": sum(row["requests"] for row in rows),
            "all_urls_unsized_resources": sum(row["unsized_resources"] for row in rows),
        },
    }


def display_number(value: object, suffix: str = "") -> str:
    if value is None:
        return "unknown"
    if isinstance(value, float):
        return "{:,.1f}{}".format(value, suffix)
    return "{:,}{}".format(value, suffix)


def human_report(document: Dict[str, object]) -> str:
    lines = [
        "WordPress public performance probe — {}".format(document["generated_at"]),
        "label={}  site={}  repeats={}  mode={}".format(
            document["label"],
            document["site"],
            document["repeats"],
            "quick" if document["quick"] else "full",
        ),
        "",
        "origin_ttfb = unique cache-buster per request (uncached origin render)",
        "edge_ttfb   = bare URL (visitor-facing cache path)",
        "",
    ]
    header = (
        "{:<{width}} {:>6} {:>10} {:>10} {:>9} {:>9} {:>8} {:>8} {:>8} {:>8} {:>9} {:>5}"
    ).format(
        "URL",
        "status",
        "origin ms",
        "edge ms",
        "cache",
        "html KB",
        "css KB",
        "js KB",
        "img KB",
        "font KB",
        "total KB",
        "req",
        width=REPORT_URL_WIDTH,
    )
    lines.extend([header, "-" * len(header)])
    for row in document["urls"]:
        shown_url = row["url"]
        if len(shown_url) > REPORT_URL_WIDTH:
            shown_url = shown_url[: REPORT_URL_WIDTH - 1] + "…"
        lines.append(
            "{:<{width}} {:>6} {:>10} {:>10} {:>9} {:>9} {:>8} {:>8} {:>8} {:>8} {:>9} {:>5}".format(
                shown_url,
                display_number(row["http_status"]),
                display_number(row["origin_ttfb_ms"]),
                display_number(row["edge_ttfb_ms"]),
                row["cache_status"],
                display_number(row["html_kb"]),
                display_number(row["css_kb"]),
                display_number(row["js_kb"]),
                display_number(row["img_kb"]),
                display_number(row["font_kb"]),
                display_number(row["total_kb"]),
                display_number(row["requests"]),
                width=REPORT_URL_WIDTH,
            )
        )
        for error in row["errors"]:
            lines.append("  error: {}".format(error))

    lines.extend(
        [
            "",
            "fleet payload: {} across {} URL(s); {} referenced request(s)".format(
                display_number(document["totals"]["all_urls_total_kb"], " KB"),
                document["totals"]["url_count"],
                document["totals"]["all_urls_requests"],
            ),
            "",
            "Legend:",
            "  Font KB sums referenced font sources, including @font-face URLs found in CSS.",
            "  Removing only an unused font preload may not lower this total while its source remains declared.",
            "  Measurements immediately after a cache flush are transient and not comparable.",
            "  Warm the cache and re-measure before declaring a regression.",
            "  unknown payload values are never summed as zero.",
            "  A capped run reports a floor over a sample, not a page weight.",
        ]
    )
    return "\n".join(lines)


def load_json_document(path: str) -> Dict[str, object]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("could not read {}: {}".format(path, sanitize_error(str(exc))))
    if not isinstance(document, dict):
        raise ValueError("{} does not contain a JSON object".format(path))
    return document


def diff_value(before: object, after: object, unit: str = "") -> str:
    if before is None or after is None:
        return "{} -> {}".format(display_number(before, unit), display_number(after, unit))
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return "{} -> {}".format(before, after)
    if before == 0:
        delta = "n/a" if after != 0 else "+0.0%"
    else:
        delta = "{:+.1f}%".format((after - before) / before * PERCENT_SCALE)
    return "{} -> {} ({})".format(display_number(before, unit), display_number(after, unit), delta)


def render_diff(before: Dict[str, object], after: Dict[str, object]) -> str:
    before_rows = {row["url"]: row for row in before["urls"]}
    after_rows = {row["url"]: row for row in after["urls"]}
    urls = sorted(set(before_rows).union(after_rows))
    lines = [
        "Performance diff: {} -> {}".format(before.get("label", "unknown"), after.get("label", "unknown")),
        "",
        "{:<{width}} {:<31} {:<31} {:<31}".format(
            "URL", "origin TTFB", "edge TTFB", "total payload", width=REPORT_URL_WIDTH
        ),
    ]
    lines.append("-" * len(lines[-1]))
    for url in urls:
        left = before_rows.get(url)
        right = after_rows.get(url)
        if left is None:
            lines.append("{:<{width}} added in after document".format(url[:REPORT_URL_WIDTH], width=REPORT_URL_WIDTH))
            continue
        if right is None:
            lines.append("{:<{width}} missing from after document".format(url[:REPORT_URL_WIDTH], width=REPORT_URL_WIDTH))
            continue
        lines.append(
            "{:<{width}} {:<31} {:<31} {:<31}".format(
                url[:REPORT_URL_WIDTH],
                diff_value(left.get("origin_ttfb_ms"), right.get("origin_ttfb_ms"), " ms"),
                diff_value(left.get("edge_ttfb_ms"), right.get("edge_ttfb_ms"), " ms"),
                diff_value(left.get("total_kb"), right.get("total_kb"), " KB"),
                width=REPORT_URL_WIDTH,
            )
        )
    lines.extend(
        [
            "",
            "fleet payload delta: {}".format(
                diff_value(
                    before["totals"].get("all_urls_total_kb"),
                    after["totals"].get("all_urls_total_kb"),
                    " KB",
                )
            ),
        ]
    )
    return "\n".join(lines)


def positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an integer")
    if parsed < MIN_REPEATS:
        raise argparse.ArgumentTypeError("must be at least {}".format(MIN_REPEATS))
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", help="base public HTTPS site URL")
    targets = parser.add_mutually_exclusive_group()
    targets.add_argument("--urls-file", help="path containing one URL or path per line")
    targets.add_argument("--url", action="append", default=[], help="URL or site-relative path; repeatable")
    parser.add_argument("--json", metavar="PATH", help="write metrics JSON to PATH; - means stdout")
    parser.add_argument("--label", default=DEFAULT_LABEL, help="measurement label")
    parser.add_argument("--repeats", type=positive_integer, default=DEFAULT_REPEATS, help="timing samples per path")
    parser.add_argument("--quick", action="store_true", help="skip payload discovery and HEAD sizing")
    parser.add_argument(
        "--max-assets",
        type=int,
        default=NO_ASSET_CAP,
        metavar="N",
        help=(
            "size at most N discovered resources during the payload walk. Use on very heavy "
            "pages where a full walk would not finish. Resources are taken in rotation across "
            "kinds so the breakdown stays representative, the skipped ones are counted in "
            "unsized_resources, and asset_cap_applied marks the run so a capped total is never "
            "mistaken for a page weight. Default 0, meaning no cap."
        ),
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help=(
            "minimum seconds between requests, enforced across all workers. Use when a site "
            "rate-limits sustained probing: a throttled read reports the rate limiter's timing "
            "as the site's own. Increases total run time proportionally. Default 0."
        ),
    )
    parser.add_argument(
        "--user-agent",
        metavar="STRING",
        help=(
            "override the User-Agent sent with every request. Needed when a site's bot rules "
            "answer the default with a challenge or a 403, which would otherwise be measured as "
            "the site's own performance."
        ),
    )
    parser.add_argument("--quiet", action="store_true", help="suppress the human report; emit JSON only")
    parser.add_argument("--diff", nargs=2, metavar=("A.json", "B.json"), help="compare two metrics documents")
    return parser


def write_json(document: Dict[str, object], destination: str) -> None:
    serialized = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if destination == "-":
        sys.stdout.write(serialized)
        return
    try:
        with open(destination, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
    except OSError as exc:
        raise ValueError("could not write {}: {}".format(destination, sanitize_error(str(exc))))


def run_diff(paths: Sequence[str]) -> int:
    try:
        before = load_json_document(paths[0])
        after = load_json_document(paths[1])
    except ValueError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2
    before_version = before.get("schema_version")
    after_version = after.get("schema_version")
    if before_version != after_version:
        print(
            "error: schema_version mismatch: {} has {!r}, {} has {!r}".format(
                paths[0], before_version, paths[1], after_version
            ),
            file=sys.stderr,
        )
        return 2
    validation_errors = validate_metrics_document(before) + validate_metrics_document(after)
    if validation_errors:
        print("error: invalid metrics document: {}".format("; ".join(sorted(set(validation_errors)))), file=sys.stderr)
        return 2
    print(render_diff(before, after))
    return 0


def measurement_targets(parser: argparse.ArgumentParser, args: argparse.Namespace, site: str) -> List[str]:
    raw_targets: List[str]
    if args.urls_file:
        try:
            raw_targets = load_url_file(args.urls_file)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        raw_targets = list(args.url)
    if not raw_targets:
        raw_targets = [site + "/"]
    try:
        return sorted(set(normalize_target(site, target) for target in raw_targets))
    except ValueError as exc:
        parser.error(str(exc))
    return []


def apply_user_agent(override: Optional[str]) -> None:
    """Set the module-level User-Agent before any request is issued."""

    global USER_AGENT
    if override is not None:
        stripped = override.strip()
        if not stripped or any(c in stripped for c in ("\n", "\r")):
            raise ValueError("--user-agent must be a non-empty single-line string")
        USER_AGENT = stripped


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        # Applied before any request is issued, so every probe in the run shares one identity.
        apply_user_agent(getattr(args, "user_agent", None))
    except ValueError as exc:
        parser.error(str(exc))
    delay = getattr(args, "delay", 0.0) or 0.0
    if delay < 0 or delay > MAX_REQUEST_DELAY_SECONDS:
        parser.error(
            "--delay must be between 0 and {} seconds".format(MAX_REQUEST_DELAY_SECONDS)
        )
    PACER.configure(delay)
    # Module-level state, so a second run inside one process must not inherit the first run's
    # verdict about a host. Matters for the adversarial tests, which drive several runs in-process.
    BREAKER.reset()
    max_assets = getattr(args, "max_assets", NO_ASSET_CAP) or NO_ASSET_CAP
    if max_assets < 0:
        parser.error("--max-assets must be 0 (no cap) or a positive count")
    global MAX_ASSETS
    MAX_ASSETS = max_assets
    if args.diff:
        measurement_values_present = any(
            [args.site, args.urls_file, args.url, args.json, args.quick, args.quiet]
        ) or args.label != DEFAULT_LABEL or args.repeats != DEFAULT_REPEATS
        if measurement_values_present:
            parser.error("--diff cannot be combined with measurement options")
        return run_diff(args.diff)

    if not args.site:
        parser.error("--site is required unless --diff is used")
    if not args.label.strip():
        parser.error("--label must not be empty")
    try:
        site = normalize_site(args.site)
    except ValueError as exc:
        parser.error(str(exc))
    targets = measurement_targets(parser, args, site)

    curl_binary = find_curl()
    if curl_binary is None:
        print("error: curl is required but was not found in PATH or /usr/bin/curl", file=sys.stderr)
        return 4

    if not args.quiet:
        print(
            "Measuring {} URL(s), {} repeat(s), {} mode...".format(
                len(targets), args.repeats, "quick" if args.quick else "full"
            ),
            file=sys.stderr,
        )

    rows: List[Dict[str, object]] = []
    reachable_count = 0
    usable_count = 0
    for index, target in enumerate(targets):
        if not args.quiet:
            print("  [{}/{}] {}".format(index + 1, len(targets), target), file=sys.stderr)
        row, reachable, usable = measure_url(curl_binary, target, args.repeats, args.quick)
        rows.append(row)
        reachable_count += int(reachable)
        usable_count += int(usable)

    document = build_document(site, args.label.strip(), args.repeats, args.quick, rows)
    validation_errors = validate_metrics_document(document)
    if validation_errors:
        print("error: generated metrics failed contract validation: {}".format("; ".join(validation_errors)), file=sys.stderr)
        return 4

    json_destination = args.json
    if args.quiet and json_destination is None:
        json_destination = "-"
    try:
        if json_destination is not None:
            write_json(document, json_destination)
    except ValueError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 2

    report = human_report(document)
    if not args.quiet:
        if json_destination == "-":
            print(report, file=sys.stderr)
        else:
            print(report)

    if reachable_count == 0:
        print("error: all target URLs were unreachable", file=sys.stderr)
        return 3
    if usable_count == 0:
        print("error: target URLs were reachable but none supplied usable HTML", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("error: measurement interrupted by operator", file=sys.stderr)
        sys.exit(4)
    except BrokenPipeError:
        sys.exit(0)
    except Exception as exc:
        print("error: unexpected failure: {}".format(sanitize_error(str(exc))), file=sys.stderr)
        sys.exit(4)
