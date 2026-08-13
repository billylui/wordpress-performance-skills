# SPDX-License-Identifier: GPL-2.0-or-later
"""Identify a live WordPress stack from public HTTP signals.

Usage:
  python3 fingerprint.py URL [--json PATH] [--quiet] [--pages N]

The probe is read-only.  It fetches the target and a bounded number of
same-origin HTML pages, then reports only evidence visible in those responses.
"""

import argparse
import gzip
import html.parser
import json
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union


SCHEMA_VERSION = "1.0"
TOOL_VERSION = "0.1.0"

# Two pages balance broader builder coverage with a light production-site probe.
DEFAULT_TOTAL_PAGES = 2
# Twenty pages prevents an accidental broad crawl while permitting deliberate coverage.
MAX_TOTAL_PAGES = 20
# The target itself is always the first and only non-additional page.
TARGET_PAGE_COUNT = 1
# One additional page makes the default two pages total.
DEFAULT_ADDITIONAL_PAGES = DEFAULT_TOTAL_PAGES - TARGET_PAGE_COUNT
# Additional pages are bounded so the target plus crawl never exceeds the total cap.
MAX_ADDITIONAL_PAGES = MAX_TOTAL_PAGES - TARGET_PAGE_COUNT
# Fifteen seconds tolerates ordinary shared-hosting latency without hanging an audit.
REQUEST_TIMEOUT_SECONDS = 15
# Eight redirects accommodates common canonicalization chains while bounding loops.
MAX_REDIRECTS = 8
# Four MiB of transferred data is ample for HTML and bounds hostile or accidental payloads.
MAX_WIRE_BYTES = 4 * 1024 * 1024
# Four MiB of decoded HTML bounds memory use even when a compressed response expands greatly.
MAX_PAGE_BYTES = 4 * 1024 * 1024
# One KiB is sufficient to sniff the document prologue when Content-Type is absent.
HTML_SNIFF_BYTES = 1024
# A version is limited to four numeric components to avoid treating prose as a version string.
MAX_VERSION_COMPONENTS = 4

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
SKIPPED_PATH_PREFIXES = ("/wp-admin/", "/wp-login", "/feed/")
SKIPPED_EXTENSIONS = (
    ".7z", ".avi", ".css", ".csv", ".doc", ".docx", ".eot", ".gif",
    ".gz", ".ico", ".jpeg", ".jpg", ".js", ".json", ".m4a", ".m4v",
    ".map", ".mov", ".mp3", ".mp4", ".pdf", ".png", ".rar", ".rss",
    ".svg", ".tar", ".tiff", ".tsv", ".txt", ".wav", ".webm", ".webp",
    ".woff", ".woff2", ".xls", ".xlsx", ".xml", ".zip",
)

SignalValue = Union[bool, str]
Signal = Dict[str, object]


@dataclass
class FetchedPage:
    """One bounded HTTP fetch and the public metadata used by detectors."""

    requested_url: str
    final_url: str
    status: int
    headers: Dict[str, str]
    cookies: List[str]
    html: str
    truncated: bool
    error: str
    redirect_notes: List[str]


class PageParser(html.parser.HTMLParser):
    """Collect links and markup attributes without requiring valid HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: List[str] = []
        self.class_tokens: List[str] = []
        self.generators: List[str] = []
        self.link_records: List[Tuple[str, str]] = []
        self.element_ids: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        classes = values.get("class", "").split()
        self.class_tokens.extend(token.lower() for token in classes)
        if values.get("id"):
            self.element_ids.append(values["id"].lower())
        if tag.lower() == "a" and values.get("href"):
            self.hrefs.append(values["href"])
        if tag.lower() == "link":
            href = values.get("href", "")
            rel = values.get("rel", "").lower()
            self.link_records.append((rel, href))
        if tag.lower() == "meta" and values.get("name", "").lower() == "generator":
            self.generators.append(values.get("content", ""))


class RecordingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow HTTP redirects while recording every host boundary first."""

    max_redirections = MAX_REDIRECTS

    def __init__(self) -> None:
        super().__init__()
        self.notes: List[str] = []

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> Optional[urllib.request.Request]:
        absolute = urllib.parse.urljoin(req.full_url, newurl)
        parsed = urllib.parse.urlsplit(absolute)
        if parsed.scheme.lower() not in ("http", "https"):
            raise urllib.error.HTTPError(
                req.full_url, code, "redirect uses a non-HTTP scheme", headers, fp
            )
        old_host = (urllib.parse.urlsplit(req.full_url).hostname or "").lower()
        new_host = (parsed.hostname or "").lower()
        if old_host != new_host:
            self.notes.append(
                "Redirect crossed a host boundary before follow: "
                + old_host
                + " -> "
                + new_host
                + ". Registrable-domain equivalence is not guessed without a public suffix list."
            )
        return super().redirect_request(req, fp, code, msg, headers, absolute)


def make_signal(value: SignalValue, confidence: str, evidence: Sequence[str]) -> Signal:
    """Construct the shared contract's signal object."""

    return {
        "value": value,
        "confidence": confidence,
        "evidence": list(evidence),
    }


def unknown_signal() -> Signal:
    """Return the contract's first-class unknown signal."""

    return make_signal("unknown", "none", [])


def normalize_url(raw_url: str) -> str:
    """Validate and deterministically normalize an operator-supplied URL."""

    parsed = urllib.parse.urlsplit(raw_url.strip())
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise ValueError("target must be an absolute http:// or https:// URL")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("target contains an invalid port") from exc
    hostname = parsed.hostname.encode("idna").decode("ascii").lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = "[" + hostname + "]"
    default_port = (parsed.scheme.lower() == "http" and port == 80) or (
        parsed.scheme.lower() == "https" and port == 443
    )
    netloc = hostname if port is None or default_port else hostname + ":" + str(port)
    path = parsed.path or "/"
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), netloc, path, parsed.query, "")
    )


def origin(url: str) -> Tuple[str, str, int]:
    """Return the exact scheme/host/effective-port origin tuple."""

    parsed = urllib.parse.urlsplit(url)
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), port


def headers_to_dict(headers: object) -> Tuple[Dict[str, str], List[str]]:
    """Lowercase and deterministically combine headers, preserving cookies separately."""

    result: Dict[str, List[str]] = {}
    for name, value in headers.items():  # type: ignore[attr-defined]
        lower_name = str(name).lower()
        result.setdefault(lower_name, []).append(str(value).strip())
    combined = {name: ", ".join(values) for name, values in sorted(result.items())}
    cookies = sorted(result.get("set-cookie", []))
    return combined, cookies


def bounded_decompress(data: bytes, encoding: str) -> Tuple[bytes, bool]:
    """Decode supported HTTP compression without exceeding the decoded byte cap."""

    lower_encoding = encoding.lower().strip()
    if not lower_encoding or lower_encoding == "identity":
        return data[:MAX_PAGE_BYTES], len(data) > MAX_PAGE_BYTES
    if lower_encoding == "gzip":
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif lower_encoding == "deflate":
        decompressor = zlib.decompressobj()
    else:
        raise ValueError("unsupported content-encoding: " + lower_encoding)
    decoded = decompressor.decompress(data, MAX_PAGE_BYTES + 1)
    return decoded[:MAX_PAGE_BYTES], len(decoded) > MAX_PAGE_BYTES


def decode_html(data: bytes, headers: Dict[str, str]) -> str:
    """Decode HTML with a declared charset when usable and safe fallbacks otherwise."""

    content_type = headers.get("content-type", "")
    charset_match = re.search(r"charset\s*=\s*['\"]?([^;\s'\"]+)", content_type, re.I)
    encodings = [charset_match.group(1)] if charset_match else []
    encodings.extend(["utf-8", "windows-1252"])
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def fetch_page(url: str) -> FetchedPage:
    """Fetch one URL with bounded bytes, redirects, compression, and errors."""

    redirect_handler = RecordingRedirectHandler()
    opener = urllib.request.build_opener(redirect_handler)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            "Accept-Encoding": "gzip, deflate",
        },
        method="GET",
    )
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            status = int(response.getcode())
            final_url = normalize_url(response.geturl())
            headers, cookies = headers_to_dict(response.headers)
            wire_data = response.read(MAX_WIRE_BYTES + 1)
            wire_truncated = len(wire_data) > MAX_WIRE_BYTES
            wire_data = wire_data[:MAX_WIRE_BYTES]
            try:
                decoded, decoded_truncated = bounded_decompress(
                    wire_data, headers.get("content-encoding", "")
                )
            except (ValueError, zlib.error, gzip.BadGzipFile) as exc:
                return FetchedPage(
                    requested_url=url,
                    final_url=final_url,
                    status=status,
                    headers=headers,
                    cookies=cookies,
                    html="",
                    truncated=wire_truncated,
                    error="response could not be decoded: " + str(exc),
                    redirect_notes=redirect_handler.notes,
                )
            body = decode_html(decoded, headers)
            return FetchedPage(
                requested_url=url,
                final_url=final_url,
                status=status,
                headers=headers,
                cookies=cookies,
                html=body,
                truncated=wire_truncated or decoded_truncated,
                error="",
                redirect_notes=redirect_handler.notes,
            )
    except urllib.error.HTTPError as exc:
        final_url = normalize_url(exc.geturl()) if exc.geturl() else url
        headers, cookies = headers_to_dict(exc.headers) if exc.headers else ({}, [])
        return FetchedPage(
            requested_url=url,
            final_url=final_url,
            status=int(exc.code),
            headers=headers,
            cookies=cookies,
            html="",
            truncated=False,
            error="HTTP status " + str(exc.code),
            redirect_notes=redirect_handler.notes,
        )
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return FetchedPage(
            requested_url=url,
            final_url=url,
            status=0,
            headers={},
            cookies=[],
            html="",
            truncated=False,
            error="request failed: " + str(reason),
            redirect_notes=redirect_handler.notes,
        )


def is_html_response(page: FetchedPage) -> bool:
    """Accept declared HTML or conservatively sniff HTML when the header is absent."""

    content_type = page.headers.get("content-type", "").lower()
    if any(kind in content_type for kind in HTML_CONTENT_TYPES):
        return True
    if not content_type:
        prefix = page.html[:HTML_SNIFF_BYTES].lower()
        return "<html" in prefix or "<!doctype html" in prefix
    return False


def parse_page(page: FetchedPage) -> PageParser:
    """Parse a page without allowing malformed markup to escape as a traceback."""

    parser = PageParser()
    try:
        parser.feed(page.html)
        parser.close()
    except (AssertionError, ValueError):
        pass
    return parser


def crawl(target: str, total_pages: int) -> Tuple[List[FetchedPage], List[str], List[str]]:
    """Fetch the target and deterministic same-origin HTML links."""

    first = fetch_page(target)
    pages = [first]
    probed = [target]
    notes = list(first.redirect_notes)
    if first.error or not (200 <= first.status < 300) or not is_html_response(first):
        return pages, probed, notes

    crawl_origin = origin(first.final_url)
    queue: List[str] = []
    queued = set()
    index = 0
    while len(pages) < total_pages:
        current = pages[index] if index < len(pages) else None
        if current is not None and not current.error and is_html_response(current):
            parser = parse_page(current)
            candidates: List[str] = []
            for href in parser.hrefs:
                absolute = urllib.parse.urljoin(current.final_url, href)
                try:
                    normalized = normalize_url(absolute)
                except ValueError:
                    continue
                parsed = urllib.parse.urlsplit(normalized)
                lower_path = parsed.path.lower()
                if origin(normalized) != crawl_origin:
                    continue
                # Query-bearing links can encode logout, cart, or other GET actions; never crawl them.
                if parsed.query:
                    continue
                if any(lower_path.startswith(prefix) for prefix in SKIPPED_PATH_PREFIXES):
                    continue
                if lower_path.endswith(SKIPPED_EXTENSIONS):
                    continue
                if normalized in probed or normalized in queued:
                    continue
                candidates.append(normalized)
            for candidate in sorted(set(candidates)):
                queue.append(candidate)
                queued.add(candidate)
        index += 1
        if not queue:
            if index >= len(pages):
                break
            continue
        next_url = queue.pop(0)
        next_page = fetch_page(next_url)
        probed.append(next_url)
        pages.append(next_page)
        notes.extend(next_page.redirect_notes)
        if next_page.error:
            notes.append("Page probe failed for " + next_url + ": " + next_page.error + ".")
        elif not is_html_response(next_page):
            notes.append("Page probe returned non-HTML content for " + next_url + ".")
        elif next_page.truncated:
            notes.append("Page HTML was capped at the configured byte limit: " + next_url + ".")
    return pages, probed, notes


def successful_pages(pages: Sequence[FetchedPage]) -> List[FetchedPage]:
    """Return usable HTML pages in crawl order."""

    return [
        page for page in pages
        if not page.error and 200 <= page.status < 300 and is_html_response(page)
    ]


def detect_wordpress(
    pages: Sequence[FetchedPage], parsers: Sequence[PageParser]
) -> Tuple[Signal, Signal]:
    """Detect WordPress and an explicitly published generator version."""

    joined = "\n".join(page.html.lower() for page in pages)
    evidence: List[str] = []
    for marker in ("/wp-content/", "/wp-includes/"):
        count = joined.count(marker)
        if count:
            evidence.append("html: " + str(count) + " references containing " + marker)
    generators = sorted(
        {generator.strip() for parser in parsers for generator in parser.generators if generator.strip()}
    )
    wordpress_generators = [value for value in generators if "wordpress" in value.lower()]
    if wordpress_generators:
        evidence.append("html: generator meta declares " + wordpress_generators[0])
    rsd_count = sum(
        1 for parser in parsers for rel, href in parser.link_records
        if "edituri" in rel and "rsd" in href.lower()
    )
    if rsd_count:
        evidence.append("html: " + str(rsd_count) + " RSD EditURI link(s) found")
    wp_json_count = sum(
        1 for parser in parsers for _rel, href in parser.link_records
        if "wp-json" in href.lower()
    )
    if wp_json_count:
        evidence.append("html: " + str(wp_json_count) + " link(s) reference wp-json")
    if evidence:
        wordpress = make_signal(True, "high", evidence)
    else:
        # Absence of public markers is not evidence of absence, and this repo's first invariant is
        # that `unknown` is a first-class value. A CDN, an optimizer or a headless front end can
        # strip every marker from a site that is unmistakably WordPress, so a `false` here would be
        # a confident claim built on finding nothing. The observation is kept as evidence, because
        # "we looked across N pages and saw none" is genuinely useful — it is the conclusion drawn
        # from it that was wrong.
        wordpress = make_signal(
            "unknown",
            "none",
            [
                "probe: no public WordPress markers found across "
                + str(len(pages))
                + " HTML page(s); markers can be stripped by a CDN, an optimizer, or a headless "
                "front end, so this does not establish that the site is not WordPress"
            ],
        )

    versions: List[str] = []
    version_pattern = re.compile(
        r"\bwordpress\s+([0-9]+(?:\.[0-9]+){1," + str(MAX_VERSION_COMPONENTS - 1) + r"})\b",
        re.I,
    )
    for generator in wordpress_generators:
        match = version_pattern.search(generator)
        if match:
            versions.append(match.group(1))
    if versions:
        version = sorted(set(versions))[0]
        wp_version = make_signal(
            version, "high", ["html: WordPress generator meta publishes version " + version]
        )
    else:
        wp_version = unknown_signal()
    return wordpress, wp_version


def count_prefix(tokens: Iterable[str], prefixes: Sequence[str], exact: Sequence[str] = ()) -> int:
    """Count class tokens matching product-specific prefixes or exact names."""

    return sum(
        1 for token in tokens
        if token in exact or any(token.startswith(prefix) for prefix in prefixes)
    )


def detect_builder(
    pages: Sequence[FetchedPage], parsers: Sequence[PageParser], is_wordpress: Signal
) -> Signal:
    """Choose the dominant public builder markup family by element-token count."""

    tokens = [token for parser in parsers for token in parser.class_tokens]
    all_ids = [element_id for parser in parsers for element_id in parser.element_ids]
    joined = "\n".join(page.html.lower() for page in pages)
    counts = {
        "elementor": count_prefix(tokens, ("elementor-",)),
        "divi": count_prefix(tokens, ("et_pb_",)),
        "wpbakery": count_prefix(tokens, ("wpb_",), ("vc_row",)),
        "bricks": count_prefix(tokens, ("brxe-",)),
        "beaver-builder": count_prefix(tokens, ("fl-node",), ("fl-builder",)),
        "oxygen": count_prefix(tokens, ("oxy-",), ("ct-section",)),
        "breakdance": count_prefix(tokens, ("breakdance-",)),
        "brizy": count_prefix(tokens, ("brz-",)),
        "thrive": count_prefix(tokens, ("thrv-", "thrv_")),
        "block-editor": count_prefix(tokens, ("wp-block-",)),
        # Only real block-template markup counts. `global-styles-inline-css` is deliberately
        # NOT counted here: WordPress core emits that stylesheet for classic themes as well,
        # so it says "modern WordPress", not "site editor". Verified against a live classic
        # (hello-elementor) site that emits it — counting it invented a site-editor signal
        # on a site with no block templates at all.
        "site-editor": count_prefix(tokens, ("wp-container-",), ("wp-site-blocks",)),
    }
    positive = {name: count for name, count in counts.items() if count > 0}
    if not positive:
        if is_wordpress["value"] is True:
            return make_signal(
                "classic-none",
                "low",
                ["probe: WordPress markers found but no supported builder class markers were present"],
            )
        return unknown_signal()
    dominant = sorted(positive, key=lambda name: (-positive[name], name))[0]
    summary = ", ".join(name + "=" + str(positive[name]) for name in sorted(positive))
    evidence = [
        "html: builder element counts " + summary + "; selected dominant " + dominant
    ]
    asset_markers = {
        "elementor": "/plugins/elementor/",
        "divi": "/themes/divi/",
        "beaver-builder": "/plugins/beaver-builder/",
        "breakdance": "/plugins/breakdance/",
        "brizy": "/plugins/brizy/",
        "thrive": "/plugins/thrive-",
    }
    marker = asset_markers.get(dominant)
    if marker and marker in joined:
        evidence.append("html: dominant builder has vendor-namespaced asset path " + marker)
        confidence = "high"
    elif positive[dominant] >= DEFAULT_TOTAL_PAGES:
        confidence = "medium"
    else:
        confidence = "low"
    return make_signal(dominant, confidence, evidence)


def detect_theme(pages: Sequence[FetchedPage], parsers: Sequence[PageParser]) -> Tuple[Signal, Signal]:
    """Detect the public theme slug and classic/block/hybrid markup architecture."""

    joined = "\n".join(page.html.lower() for page in pages)
    slugs = re.findall(r"/wp-content/themes/([a-z0-9][a-z0-9._-]*)/", joined)
    if slugs:
        counts = {slug: slugs.count(slug) for slug in sorted(set(slugs))}
        slug = sorted(counts, key=lambda name: (-counts[name], name))[0]
        theme_slug = make_signal(
            slug,
            "medium" if counts[slug] >= DEFAULT_TOTAL_PAGES else "low",
            [
                "html: theme asset path /wp-content/themes/"
                + slug
                + "/ appears "
                + str(counts[slug])
                + " time(s)"
            ],
        )
    else:
        theme_slug = unknown_signal()

    tokens = [token for parser in parsers for token in parser.class_tokens]
    element_ids = [element_id for parser in parsers for element_id in parser.element_ids]
    block_markers: List[str] = []
    # A block theme is claimed only from markup the block template canvas actually renders.
    #
    # `global-styles-inline-css` is NOT such a marker, even though it looks like one: core
    # emits it for classic themes too (it carries theme.json/default presets), so it is present
    # on essentially every modern WordPress site. Treating it as block-theme evidence
    # misclassified a live classic-theme site (hello-elementor) as `block` at medium
    # confidence. Per contract invariant 3, an unsupported guess must become `unknown`.
    #
    # `wp-site-blocks` is checked against parsed CLASS TOKENS, never raw HTML text — the string
    # also appears inside global-styles CSS rules (`.wp-site-blocks { ... }`) on classic sites.
    if "wp-site-blocks" in tokens:
        block_markers.append("html: wp-site-blocks wrapper class is present")
    if any(token.startswith("wp-container-") for token in tokens):
        block_markers.append("html: wp-container-* global layout classes are present")
    classic_child = bool(
        re.search(r"id\s*=\s*['\"][^'\"]*child[^'\"]*(?:style|css)[^'\"]*['\"]", joined)
    )
    classic_evidence = "html: an explicitly named child-theme stylesheet id is present"
    if block_markers and classic_child:
        return theme_slug, make_signal("hybrid", "medium", block_markers + [classic_evidence])
    if block_markers:
        return theme_slug, make_signal("block", "medium", block_markers)
    if classic_child:
        return theme_slug, make_signal(
            "classic",
            "medium",
            [classic_evidence, "html: no block-theme markup markers were found"],
        )
    return theme_slug, unknown_signal()


def detect_server(headers: Dict[str, str]) -> Signal:
    """Normalize the public Server response header into the closed vocabulary."""

    raw = headers.get("server", "").strip()
    if not raw:
        return unknown_signal()
    lower = raw.lower()
    if "openlitespeed" in lower:
        value = "openlitespeed"
    elif "litespeed" in lower:
        value = "litespeed"
    elif "nginx" in lower:
        value = "nginx"
    elif "apache" in lower:
        value = "apache"
    elif "cloudflare" in lower:
        value = "cloudflare"
    else:
        value = "other"
    return make_signal(value, "high", ["header: Server: " + raw])


def detect_php(headers: Dict[str, str]) -> Signal:
    """Report PHP only when an explicit public response header publishes it."""

    powered_by = headers.get("x-powered-by", "")
    match = re.search(
        r"\bphp/([0-9]+(?:\.[0-9]+){1," + str(MAX_VERSION_COMPONENTS - 1) + r"})\b",
        powered_by,
        re.I,
    )
    if not match:
        return unknown_signal()
    version = match.group(1)
    return make_signal(version, "high", ["header: X-Powered-By publishes PHP/" + version])


def matching_header_evidence(headers: Dict[str, str], prefixes: Sequence[str]) -> List[str]:
    """Return sorted evidence for namespaced public headers."""

    return [
        "header: " + name + ": " + headers[name]
        for name in sorted(headers)
        if any(name == prefix or name.startswith(prefix) for prefix in prefixes)
    ]


# Host markers whose names are not vendor-namespaced. A match on one of these identifies the
# platform in practice but could in principle be emitted by something else, so it is reported at
# medium confidence rather than high.
NON_NAMESPACED_HOST_PREFIXES = ("x-gateway-",)


def detect_host(headers: Dict[str, str], target: str) -> Signal:
    """Detect a hosting class only from vendor-namespaced public signals."""

    marker_groups = (
        ("wpengine", ("x-wpe-",)),
        ("kinsta", ("x-kinsta-",)),
        ("siteground", ("x-sg-",)),
        ("godaddy", ("x-gd-",)),
        # `x-gateway-*` is GoDaddy Managed WordPress's gateway cache, observed on two independent
        # production sites behind Cloudflare. It is listed separately from `x-gd-` because the
        # name is not vendor-namespaced: something else could plausibly emit an `x-gateway-`
        # header, so this earns MEDIUM confidence rather than high, per the rubric in
        # docs/CONTRACTS.md. Without it, GoDaddy Managed WordPress reports as `unknown` — which
        # is what a live audit of a real GoDaddy site actually did.
        ("godaddy", ("x-gateway-",)),
        ("cloudways", ("x-cw-",)),
        ("flywheel", ("x-fw-",)),
        ("pressable", ("x-pressable-",)),
        ("rocket-net", ("x-rocketcdn-",)),
        ("hostinger", ("x-hcdn-",)),
        ("bluehost", ("x-bluehost-",)),
        ("pantheon", ("x-pantheon-", "x-styx-")),
        ("wpvip", ("x-vip-",)),
        ("wpcom", ("x-nananana",)),
        ("shared-cpanel", ("x-cpanel-",)),
    )
    candidates: List[Tuple[str, List[str]]] = []
    for value, prefixes in marker_groups:
        evidence = matching_header_evidence(headers, prefixes)
        if evidence:
            candidates.append((value, evidence))
    if candidates:
        value, evidence = sorted(candidates, key=lambda item: (-len(item[1]), item[0]))[0]
        # A vendor-namespaced header effectively cannot come from anything else, so it earns
        # high. A generically-named one is strong but not exclusive, so it earns medium and the
        # agent treats it as a hypothesis to confirm at a higher tier.
        namespaced = not any(
            header_line.startswith("header: " + prefix)
            for header_line in evidence
            for prefix in NON_NAMESPACED_HOST_PREFIXES
        )
        return make_signal(value, "high" if namespaced else "medium", evidence)

    hostname = (urllib.parse.urlsplit(target).hostname or "").lower()
    hostname_labels = set(re.split(r"[.-]", hostname))
    for value, _prefixes in marker_groups:
        compact = value.replace("-", "")
        if value in hostname_labels or compact in hostname_labels:
            return make_signal(
                value,
                "low",
                ["url: target hostname contains hosting-vendor label " + value],
            )
    return unknown_signal()


def detect_cdn(headers: Dict[str, str], server: Signal) -> Tuple[Signal, List[str]]:
    """Detect an edge provider and retain ambiguity as an operator note."""

    notes: List[str] = []
    if "cf-apo-via" in headers:
        evidence = ["header: cf-apo-via: " + headers["cf-apo-via"]]
        if "cf-cache-status" in headers:
            evidence.append("header: cf-cache-status: " + headers["cf-cache-status"])
        return make_signal("cloudflare-apo", "high", evidence), notes
    if "cf-cache-status" in headers or server.get("value") == "cloudflare":
        evidence = []
        if "cf-cache-status" in headers:
            evidence.append("header: cf-cache-status: " + headers["cf-cache-status"])
        if server.get("value") == "cloudflare":
            evidence.append("header: Server identifies cloudflare")
        return make_signal("cloudflare", "high", evidence), notes
    if "x-qc-cache" in headers:
        return make_signal(
            "quic-cloud", "high", ["header: x-qc-cache: " + headers["x-qc-cache"]]
        ), notes
    if "x-fastly-request-id" in headers:
        return make_signal(
            "fastly", "high", ["header: x-fastly-request-id: " + headers["x-fastly-request-id"]]
        ), notes
    if (
        "x-served-by" in headers
        and "x-cache" in headers
        and "varnish" in headers.get("via", "").lower()
    ):
        return make_signal(
            "fastly",
            "medium",
            [
                "header: x-served-by: " + headers["x-served-by"],
                "header: x-cache: " + headers["x-cache"],
                "header: Via contains Varnish",
            ],
        ), notes
    provider_markers = (
        ("bunny", ("cdn-pullzone", "cdn-uid")),
        ("keycdn", ("x-edge-location",)),
        ("akamai", ("x-akamai-", "akamai-grn")),
        ("stackpath", ("x-sp-cache", "x-hw")),
        ("aws-cloudfront", ("x-amz-cf-",)),
    )
    candidates: List[Tuple[str, List[str]]] = []
    for value, prefixes in provider_markers:
        evidence = matching_header_evidence(headers, prefixes)
        if evidence:
            candidates.append((value, evidence))
    if candidates:
        value, evidence = sorted(candidates, key=lambda item: (-len(item[1]), item[0]))[0]
        confidence = "low" if value == "keycdn" else "high"
        return make_signal(value, confidence, evidence), notes
    if "x-cache" in headers:
        notes.append(
            "The x-cache header is vendor-ambiguous; it is not enough to identify a CDN or host."
        )
    return unknown_signal(), notes


def choose_cache_candidate(candidates: Sequence[Tuple[str, str]]) -> Signal:
    """Choose a deterministic cache candidate from vendor-specific evidence."""

    if not candidates:
        return unknown_signal()
    grouped: Dict[str, List[str]] = {}
    for value, evidence in candidates:
        grouped.setdefault(value, []).append(evidence)
    value = sorted(grouped, key=lambda name: (-len(grouped[name]), name))[0]
    evidence = sorted(set(grouped[value]))
    return make_signal(value, "high", evidence)


def detect_cache_layers(
    headers: Dict[str, str], html_text: str, cdn: Signal
) -> List[Dict[str, object]]:
    """Return exactly the contract's four cache layers in fixed order."""

    edge = {
        "layer": "edge",
        "value": cdn["value"],
        "confidence": cdn["confidence"],
        "evidence": list(cdn["evidence"]),
    }

    server_candidates: List[Tuple[str, str]] = []
    if "x-litespeed-cache" in headers:
        server_candidates.append(
            ("litespeed", "header: x-litespeed-cache: " + headers["x-litespeed-cache"])
        )
    for name in ("x-fastcgi-cache", "x-cache-status"):
        if name in headers:
            server_candidates.append(("nginx-fastcgi", "header: " + name + ": " + headers[name]))
    if "x-varnish" in headers or "varnish" in headers.get("via", "").lower():
        detail = headers.get("x-varnish", headers.get("via", "varnish"))
        server_candidates.append(("varnish", "header: public Varnish marker: " + detail))
    if "generated by batcache" in html_text:
        server_candidates.append(("batcache", "html: generated by Batcache comment"))
    server_signal = choose_cache_candidate(server_candidates)
    server_layer = {"layer": "server", **server_signal}

    page_candidates: List[Tuple[str, str]] = []
    html_markers = (
        ("wp-rocket", ("wp rocket", "/plugins/wp-rocket/")),
        ("w3-total-cache", ("w3 total cache",)),
        ("wp-super-cache", ("wp-super-cache", "wp super cache")),
        ("wp-fastest-cache", ("wp fastest cache",)),
        ("sg-optimizer", ("sg optimizer", "siteground optimizer")),
        ("breeze", ("breeze cache", "/plugins/breeze/")),
        ("cache-enabler", ("cache enabler", "/plugins/cache-enabler/")),
        ("surge", ("surge cache",)),
    )
    for value, markers in html_markers:
        for marker in markers:
            if marker in html_text:
                page_candidates.append((value, "html: vendor marker " + marker))
    header_markers = (
        ("litespeed-cache", "x-litespeed-cache"),
        ("sg-optimizer", "x-proxy-cache-info"),
        ("wp-fastest-cache", "x-wp-cf-super-cache"),
        ("breeze", "x-breeze-cache"),
        ("surge", "x-surge-cache"),
        ("cache-enabler", "x-cache-enabler"),
    )
    for value, name in header_markers:
        if name in headers:
            page_candidates.append((value, "header: " + name + ": " + headers[name]))
    page_signal = choose_cache_candidate(page_candidates)
    page_layer = {"layer": "page-plugin", **page_signal}

    object_candidates: List[Tuple[str, str]] = []
    object_markers = (
        ("object-cache-pro", ("x-object-cache-pro",)),
        ("redis", ("x-redis-cache",)),
        ("memcached", ("x-memcached",)),
        ("apcu", ("x-apcu-cache",)),
    )
    for value, prefixes in object_markers:
        for evidence in matching_header_evidence(headers, prefixes):
            object_candidates.append((value, evidence))
    object_signal = choose_cache_candidate(object_candidates)
    object_layer = {"layer": "object", **object_signal}
    return [edge, server_layer, page_layer, object_layer]


def detect_multilingual(
    pages: Sequence[FetchedPage], parsers: Sequence[PageParser], cookies: Sequence[str]
) -> Tuple[Signal, List[str]]:
    """Detect supported multilingual products from their public namespaces."""

    joined = "\n".join(page.html.lower() for page in pages)
    tokens = [token for parser in parsers for token in parser.class_tokens]
    cookie_text = "\n".join(cookies).lower()
    markers = (
        ("wpml", ("/plugins/sitepress-multilingual-cms/", "wpml-", "_icl_")),
        ("polylang", ("/plugins/polylang/", "polylang", "pll_")),
        ("translatepress", ("/plugins/translatepress-multilingual/", "trp-")),
        ("weglot", ("weglot",)),
        ("gtranslate", ("gtranslate", "gt_switcher")),
        ("multilingualpress", ("multilingualpress",)),
    )
    candidates: List[Tuple[str, List[str]]] = []
    token_text = " ".join(tokens)
    for value, product_markers in markers:
        evidence: List[str] = []
        for marker in product_markers:
            if marker in joined or marker in token_text:
                evidence.append("html: multilingual product marker " + marker)
            if marker in cookie_text:
                evidence.append("cookie: multilingual product marker " + marker)
        if evidence:
            candidates.append((value, sorted(set(evidence))))
    notes: List[str] = []
    if candidates:
        value, evidence = sorted(candidates, key=lambda item: (-len(item[1]), item[0]))[0]
        if value == "translatepress":
            notes.append(
                "TranslatePress markers indicate rendered-HTML translation at runtime."
            )
        confidence = "high" if any("/plugins/" in item for item in evidence) else "medium"
        return make_signal(value, confidence, evidence), notes

    has_hreflang = "hreflang=" in joined or "hreflang =" in joined
    if has_hreflang:
        notes.append(
            "hreflang markup is present, but it does not identify a supported multilingual product."
        )
        return unknown_signal(), notes
    # `none` is a positive claim that the site is monolingual, and finding no marker does not
    # support it: a translation layer can run entirely server-side, or on paths this crawl never
    # reached. It matters because per-language cache keys change what cache advice is correct.
    return make_signal(
        "unknown",
        "none",
        [
            "probe: no supported multilingual product markers found across "
            + str(len(pages))
            + " HTML page(s); a server-side or unsupported translation layer would leave none"
        ],
    ), notes


def detect_woocommerce(pages: Sequence[FetchedPage], parsers: Sequence[PageParser]) -> Signal:
    """Detect WooCommerce from public classes, assets, and endpoint references."""

    joined = "\n".join(page.html.lower() for page in pages)
    tokens = [token for parser in parsers for token in parser.class_tokens]
    evidence: List[str] = []
    class_count = sum(1 for token in tokens if token.startswith("woocommerce"))
    if class_count:
        evidence.append("html: " + str(class_count) + " woocommerce* class token(s)")
    if "/plugins/woocommerce/" in joined:
        evidence.append("html: vendor-namespaced /plugins/woocommerce/ asset path")
    if "wc-ajax" in joined:
        evidence.append("html: wc-ajax endpoint reference")
    if evidence:
        confidence = "high" if "/plugins/woocommerce/" in joined else "medium"
        return make_signal(True, confidence, evidence)
    # The most consequential of the three. This project's own catalog entry says a false result
    # "does not prove that no store exists", and warns that brochure-site caching advice applied to
    # a store can expose private cart or order state to another visitor. A crawl that never reached
    # a shop page sees no markers on a site that certainly sells things.
    return make_signal(
        "unknown",
        "none",
        [
            "probe: no WooCommerce public markers found across "
            + str(len(pages))
            + " HTML page(s); the crawl may not have reached a shop, cart or checkout page, so "
            "this does not establish that no store exists"
        ],
    )


def build_profile(target: str, total_pages: int) -> Tuple[Optional[Dict[str, object]], int, str]:
    """Crawl and build a complete stack-profile document plus an exit disposition."""

    pages, pages_probed, notes = crawl(target, total_pages)
    first = pages[0]
    if first.status == 0:
        return None, 3, "Target unreachable: " + first.error
    if first.error or not (200 <= first.status < 300):
        return None, 4, "Target reachable but unusable: " + (first.error or "non-success HTTP status")
    if not is_html_response(first):
        content_type = first.headers.get("content-type", "missing Content-Type")
        return None, 4, "Target reachable but unusable: expected HTML, received " + content_type

    usable = successful_pages(pages)
    parsers = [parse_page(page) for page in usable]
    if first.truncated:
        notes.append("Target HTML was capped at the configured byte limit: " + target + ".")
    if not first.headers.get("content-type"):
        notes.append("Content-Type was absent; the target was accepted after conservative HTML sniffing.")

    is_wordpress, wp_version = detect_wordpress(usable, parsers)
    builder = detect_builder(usable, parsers, is_wordpress)
    theme_slug, theme_type = detect_theme(usable, parsers)
    server = detect_server(first.headers)
    php_version = detect_php(first.headers)
    host_class = detect_host(first.headers, first.final_url)
    cdn, cdn_notes = detect_cdn(first.headers, server)
    multilingual, multilingual_notes = detect_multilingual(
        usable, parsers, [cookie for page in usable for cookie in page.cookies]
    )
    woocommerce = detect_woocommerce(usable, parsers)
    html_text = "\n".join(page.html.lower() for page in usable)

    notes.extend(cdn_notes)
    notes.extend(multilingual_notes)
    if wp_version["value"] == "unknown" and is_wordpress["value"] is True:
        notes.append("WordPress does not publish a generator version in the probed HTML.")
    if theme_slug["value"] == "unknown" and is_wordpress["value"] is True:
        notes.append("No public /wp-content/themes/ asset path exposed a theme slug.")
    if theme_type["value"] == "unknown" and is_wordpress["value"] is True:
        notes.append("No definitive classic-child or block-theme markup identified the theme type.")
    if php_version["value"] == "unknown":
        if "x-powered-by" not in first.headers:
            notes.append(
                "X-Powered-By is absent; PHP version is not determinable from public tier-0 signals."
            )
        else:
            notes.append(
                "X-Powered-By does not publish a PHP version; PHP version remains unknown at tier 0."
            )
    if server["value"] == "unknown":
        notes.append("Server header is absent or stripped; origin server software is unknown.")
    if host_class["value"] == "unknown":
        notes.append("No vendor-specific public hosting marker was found; host class is unknown.")
    if cdn["value"] == "unknown":
        notes.append("No vendor-specific public edge marker was found; CDN remains unknown.")
    notes.append(
        "WordPress multisite normally has no definitive public marker; multisite remains unknown at tier 0."
    )

    document: Dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "tool": "fingerprint",
        "tool_version": TOOL_VERSION,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "target": target,
        "pages_probed": pages_probed,
        "profile": {
            "is_wordpress": is_wordpress,
            "wp_version": wp_version,
            "builder": builder,
            "theme_slug": theme_slug,
            "theme_type": theme_type,
            "server": server,
            "php_version": php_version,
            "host_class": host_class,
            "cdn": cdn,
            "multilingual": multilingual,
            "woocommerce": woocommerce,
            "multisite": unknown_signal(),
        },
        "cache_layers": detect_cache_layers(first.headers, html_text, cdn),
        "notes": sorted(set(notes)),
    }
    return document, 0, ""


def json_text(document: Dict[str, object]) -> str:
    """Serialize deterministically for clean before/after diffs."""

    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def human_report(document: Dict[str, object]) -> str:
    """Render a compact operator-facing report without changing machine output."""

    profile = document["profile"]
    assert isinstance(profile, dict)
    lines = [
        "Stack fingerprint: " + str(document["target"]),
        "Pages probed: " + str(len(document["pages_probed"])),
    ]
    for key in (
        "is_wordpress", "wp_version", "builder", "theme_slug", "theme_type",
        "server", "php_version", "host_class", "cdn", "multilingual",
        "woocommerce", "multisite",
    ):
        signal = profile[key]
        assert isinstance(signal, dict)
        lines.append(
            key.replace("_", " ").title()
            + ": "
            + str(signal["value"])
            + " ("
            + str(signal["confidence"])
            + ")"
        )
    return "\n".join(lines) + "\n"


def additional_pages(value: str) -> int:
    """Argparse converter for the bounded --pages additional-page count."""

    try:
        pages = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if pages < 0 or pages > MAX_ADDITIONAL_PAGES:
        raise argparse.ArgumentTypeError(
            "must be between 0 and " + str(MAX_ADDITIONAL_PAGES)
        )
    return pages


def make_parser() -> argparse.ArgumentParser:
    """Create the contract-compatible command-line parser."""

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("url", help="absolute public HTTP(S) target URL")
    parser.add_argument("--json", metavar="PATH", help="write JSON to PATH; - means stdout")
    parser.add_argument("--quiet", action="store_true", help="suppress the human report; emit JSON only")
    parser.add_argument(
        "--pages",
        type=additional_pages,
        default=DEFAULT_ADDITIONAL_PAGES,
        metavar="N",
        help="maximum additional same-origin HTML pages (default: %(default)s; two total)",
    )
    return parser


def run(argv: Optional[Sequence[str]] = None) -> int:
    """Run the CLI and return only a shared-contract exit code."""

    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        target = normalize_url(args.url)
    except ValueError as exc:
        parser.error(str(exc))

    document, exit_code, error = build_profile(target, args.pages + TARGET_PAGE_COUNT)
    if document is None:
        print(error, file=sys.stderr)
        return exit_code

    serialized = json_text(document)
    json_to_stdout = args.json == "-" or (args.quiet and args.json is None)
    try:
        if args.json and args.json != "-":
            with open(args.json, "w", encoding="utf-8", newline="\n") as output:
                output.write(serialized)
        if json_to_stdout:
            sys.stdout.write(serialized)
        if not args.quiet:
            report_stream = sys.stderr if args.json == "-" else sys.stdout
            report_stream.write(human_report(document))
    except (OSError, UnicodeError) as exc:
        destination = args.json if args.json and args.json != "-" else "standard output"
        print("Could not write output to {}: {}".format(destination, exc), file=sys.stderr)
        return 2
    return 0


def main() -> int:
    """Contain unexpected failures so a raw traceback never reaches an operator."""

    try:
        return run()
    except KeyboardInterrupt:
        print("Fingerprint interrupted by operator.", file=sys.stderr)
        return 4
    except BrokenPipeError:
        return 0
    except Exception as exc:  # Defensive CLI boundary; detector errors must be actionable.
        print("Fingerprint could not complete: " + str(exc), file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
