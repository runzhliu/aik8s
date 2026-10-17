#!/usr/bin/env python3
"""Check a built static site without modifying it (standard library only).

Offline by default. HTML navigation, assets and HTML fragments are checked;
CSS contents (including @import/url()), SVG-internal fragments and JavaScript
are not parsed. The exact dynamic anchor ``comments`` is allowed by default;
--allow-dynamic-anchor adds individual names, never a wildcard.

Optional external checking sends only collected HTTP(S) link URLs (no page
contents), uses bounded HEAD/GET requests, and never makes CI fail. Redirects
remain subject to the HTTP(S)-only rule. 403/429 require human review.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from http.client import HTTPException
from pathlib import Path
import re
import ipaddress
import socket
import threading
import time
from urllib import error, parse, request


@dataclass(frozen=True)
class Reference:
    source: Path
    line: int
    column: int
    url: str
    kind: str

    def location(self, root: Path) -> str:
        return f"{self.source.relative_to(root)}:{self.line}:{self.column}"


@dataclass
class Report:
    pages: int = 0
    references: int = 0
    internal: int = 0
    unique_internal: int = 0
    external: dict[str, list[Reference]] = field(default_factory=dict)
    errors: dict[str, list[Reference]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    ignored: int = 0


def srcset_urls(value: str) -> list[str]:
    """Extract candidates, preserving commas inside data URLs."""
    result = []
    rest = value.strip()
    while rest:
        rest = rest.lstrip(" ,\t\r\n")
        if not rest:
            break
        match = re.match(r"\S+", rest)
        assert match
        token = match.group()
        if token.lower().startswith("data:"):
            result.append(token.rstrip(","))
            rest = rest[len(token):]
            if token.endswith(","):
                continue
        else:
            # Ordinary candidates may omit descriptor/space after a comma.
            token = token.split(",", 1)[0]
            result.append(token)
            rest = rest[len(token):]
            if rest.startswith(","):
                rest = rest[1:]
                continue
        # Skip optional descriptors up to the next candidate separator.
        comma = rest.find(",")
        rest = rest[comma + 1:] if comma >= 0 else ""
    return result


class PageParser(HTMLParser):
    def __init__(self, source: Path):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.anchors: set[str] = set()
        self.references: list[Reference] = []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id") is not None:
            self.anchors.add(attrs["id"])
        if tag == "a" and attrs.get("name") is not None:
            self.anchors.add(attrs["name"])
        fields = []
        if tag in {"a", "area"}:
            fields.append(("href", "action" if "data-aik8s-feedback" in attrs else "navigation"))
        if tag == "link" and set((attrs.get("rel") or "").lower().split()) & {
            "stylesheet", "icon", "apple-touch-icon", "mask-icon", "preload", "modulepreload"
        }:
            fields.append(("href", "resource"))
        if tag in {"img", "script", "iframe", "source", "audio", "video", "track", "embed", "input"}:
            fields.append(("src", "iframe" if tag == "iframe" else "resource"))
        if tag == "video":
            fields.append(("poster", "resource"))
        if tag == "object":
            fields.append(("data", "resource"))
        for attribute, kind in fields:
            if attrs.get(attribute) is not None:
                self.add(attrs[attribute], kind)
        if tag in {"img", "source"} and attrs.get("srcset"):
            for url in srcset_urls(attrs["srcset"]):
                self.add(url, "resource")

    def add(self, url, kind):
        line, column = self.getpos()
        self.references.append(Reference(self.source, line, column + 1, url, kind))


def origin(url):
    parts = parse.urlsplit(url)
    return parts.scheme.lower(), (parts.hostname or "").lower(), parts.port or (443 if parts.scheme.lower() == "https" else 80)


class SiteChecker:
    def __init__(self, site_dir, site_url, dynamic_anchors=()):
        self.root = Path(site_dir).resolve()
        parts = parse.urlsplit(site_url)
        if parts.scheme not in {"http", "https"} or not parts.netloc or parts.query or parts.fragment or parts.username or parts.password:
            raise ValueError("--site-url must be an HTTP(S) site root without credentials, query or fragment")
        self.origin = origin(site_url)
        self.site_url = site_url.rstrip("/") + "/"
        self.base_path = parse.unquote(parse.urlsplit(self.site_url).path)
        if "\\" in self.base_path or "\x00" in self.base_path or any(x in {".", ".."} for x in self.base_path.split("/")):
            raise ValueError("unsafe --site-url path")
        self.dynamic_anchors = {"comments", *dynamic_anchors}
        self.pages: dict[Path, PageParser] = {}
        self.report = Report()
        self.checked: dict[tuple[Path, str], str | None] = {}

    def safe_path(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("unsafe path escapes site directory (including symlinks)")
        return resolved

    def load_page(self, path):
        path = self.safe_path(path)
        if path not in self.pages:
            parser = PageParser(path)
            parser.feed(path.read_text(encoding="utf-8", errors="replace"))
            self.pages[path] = parser
        return self.pages[path]

    def resolve(self, ref):
        raw = unescape(ref.url).strip()
        if not raw or raw == "#":
            return "ignored", None, ""
        if any(ord(c) < 32 for c in raw):
            raise ValueError("unsafe URL contains control character")
        parts = parse.urlsplit(raw)
        if parts.scheme and parts.scheme.lower() not in {"http", "https"}:
            return "ignored", None, ""
        relative = ref.source.relative_to(self.root).as_posix()
        source_url = parse.urljoin(self.site_url, parse.quote(relative))
        absolute = parse.urljoin(source_url, raw)
        target = parse.urlsplit(absolute)
        if origin(absolute) != self.origin:
            # Do not probe embedded external services or prefilled feedback actions.
            return ("ignored" if ref.kind in {"iframe", "action"} else "external"), parse.urlunsplit(target._replace(fragment="")), ""
        if target.username or target.password:
            raise ValueError("credentials are not allowed in internal URLs")
        # Check BEFORE urljoin normalizes away '..', and AFTER percent decoding.
        decoded = parse.unquote(parts.path or ("/" if parts.netloc else ""), errors="strict")
        if "\\" in decoded or "\x00" in decoded or any(ord(c) < 32 for c in decoded):
            raise ValueError("unsafe path contains backslash or control character")
        if re.search(r"%(?![0-9a-fA-F]{2})", parts.path):
            raise ValueError("invalid percent escape in path")
        if decoded.startswith("/"):
            base = self.base_path
            if not decoded.startswith(base):
                # /prefix itself may map to its directory index.
                if decoded == base.rstrip("/"):
                    decoded += "/"
                else:
                    raise ValueError("unsafe same-origin path outside site URL root")
            components = decoded[len(base):].split("/")
            stack = []
        else:
            components = decoded.split("/")
            stack = relative.split("/")[:-1] if decoded else relative.split("/")
        for component in components:
            if component == "..":
                if not stack:
                    raise ValueError("unsafe traversal outside site root")
                stack.pop()
            elif component not in {"", "."}:
                stack.append(component)
        path = self.safe_path(self.root.joinpath(*stack))
        if path.is_dir():
            path = self.safe_path(path / "index.html")
        return "internal", path, parse.unquote(target.fragment)

    def check(self):
        if not self.root.is_dir():
            raise ValueError(f"site directory does not exist: {self.root}")
        # Never follow a symlink before validating its resolved destination.
        for path in sorted(self.root.rglob("*")):
            if path.suffix.lower() not in {".html", ".htm"}:
                continue
            try:
                self.load_page(path)
            except (OSError, ValueError) as exc:
                self.report.errors.setdefault(f"cannot read {path.relative_to(self.root)}: {exc}", [])
        self.report.pages = len(self.pages)
        for parser in list(self.pages.values()):
            for ref in parser.references:
                self.report.references += 1
                try:
                    kind, target, fragment = self.resolve(ref)
                    if kind == "ignored":
                        self.report.ignored += 1
                    elif kind == "external":
                        self.report.external.setdefault(target, []).append(ref)
                    else:
                        self.report.internal += 1
                        key = (target, fragment)
                        if key not in self.checked:
                            problem = None
                            if not target.is_file():
                                problem = f"missing {ref.kind} target: {target.relative_to(self.root)}"
                            elif fragment and target.suffix.lower() in {".html", ".htm"}:
                                if fragment not in self.dynamic_anchors and fragment not in self.load_page(target).anchors:
                                    problem = f"missing HTML anchor: {target.relative_to(self.root)}#{fragment}"
                            self.checked[key] = problem
                        if self.checked[key]:
                            self.report.errors.setdefault(self.checked[key], []).append(ref)
                except (OSError, ValueError, UnicodeError) as exc:
                    self.report.errors.setdefault(f"invalid/unsafe URL {ref.url!r}: {exc}", []).append(ref)
        self.report.unique_internal = len(self.checked)
        return self.report


def require_public_url(url):
    """Do not probe tutorial examples pointing at local/private network services."""
    target = parse.urlsplit(url)
    if target.scheme not in {'http', 'https'} or not target.hostname or target.username or target.password:
        raise ValueError('Only public HTTP(S) URLs without credentials may be checked')
    host = target.hostname.rstrip('.').lower()
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal', '.svc', '.cluster.local')):
        raise ValueError('Local/private example URL skipped')
    addresses = socket.getaddrinfo(host, target.port or (443 if target.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise ValueError('Non-public network address skipped')


class HTTPOnlyRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if parse.urlsplit(newurl).scheme.lower() not in {"http", "https"}:
            raise error.URLError("non-HTTP(S) redirect refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ExternalChecker:
    """Rate-limit initial requests, fallbacks and redirects per host."""
    def __init__(self, workers=4, interval=1.0, timeout=10.0, opener=None):
        self.workers = workers
        self.interval = interval
        self.timeout = timeout
        self.lock = threading.Lock()
        self.next_request = {}
        self.opener = opener

    def pace(self, url):
        host = (parse.urlsplit(url).hostname or "").lower()
        with self.lock:
            now = time.monotonic()
            when = max(now, self.next_request.get(host, now))
            self.next_request[host] = when + self.interval
        if when > now:
            time.sleep(when - now)

    def check_one(self, url):
        checker = self

        class PacedHTTP(request.HTTPHandler):
            def http_open(self, req):
                require_public_url(req.full_url)
                checker.pace(req.full_url)
                return super().http_open(req)

        class PacedHTTPS(request.HTTPSHandler):
            def https_open(self, req):
                require_public_url(req.full_url)
                checker.pace(req.full_url)
                return super().https_open(req)

        opener = self.opener or request.build_opener(HTTPOnlyRedirect(), PacedHTTP(), PacedHTTPS())
        for method in ("HEAD", "GET"):
            req = request.Request(url, method=method, headers={"User-Agent": "StaticSiteLinkChecker/1.0", "Range": "bytes=0-1023"})
            try:
                if self.opener is not None:
                    self.pace(url)
                with opener.open(req, timeout=self.timeout) as response:
                    status = response.status
                    # No response-body read: GET fallback is headers-only too.
                if status >= 400:
                    return self.status_warning(url, status)
                return None
            except error.HTTPError as exc:
                status = exc.code
                exc.close()
                if method == "HEAD" and status in {405, 501}:
                    continue
                return self.status_warning(url, status)
            except (OSError, ValueError, error.URLError, HTTPException) as exc:
                return f"{url}: request failed ({type(exc).__name__}); needs review"
        return None

    @staticmethod
    def status_warning(url, status):
        label = "needs review (access/rate limited, not proof of a broken link)" if status in {403, 429} else "HTTP anomaly; needs review"
        return f"{url}: HTTP {status}; {label}"

    def check(self, urls):
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return [warning for warning in pool.map(self.check_one, urls) if warning]


def print_report(report, root):
    print("## Site link check")
    print(f"HTML pages: {report.pages}; references: {report.references}; internal: {report.internal}; "
          f"unique internal targets/fragments: {report.unique_internal}; "
          f"external URLs: {len(report.external)}; ignored: {report.ignored}")
    print(f"Internal errors: {len(report.errors)}; external warnings: {len(report.warnings)}")
    for problem, refs in report.errors.items():
        print(f"ERROR: {problem}")
        for ref in refs:
            print(f"  - {ref.location(root)} [{ref.kind}] {ref.url}")
    for warning in report.warnings:
        print(f"WARNING: {warning}")
        for url, refs in report.external.items():
            if warning.startswith(url + ":"):
                for ref in refs:
                    print(f"  - {ref.location(root)} [{ref.kind}] {ref.url}")
                break
    print("Offline internal validation; CSS contents, JS-created anchors (except exact allowlist), and SVG fragments are not inspected.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site-dir", default="site")
    parser.add_argument("--site-url", default="https://aik8s.run/")
    parser.add_argument("--allow-dynamic-anchor", action="append", default=[], metavar="EXACT_ID", help="allow one exact JS-created anchor (comments is allowed by default)")
    parser.add_argument("--external", action="store_true", help="warn about external HTTP(S) anomalies; never affects exit status")
    parser.add_argument("--external-limit", type=int, default=100, help="maximum external URLs to check; 0 means all (default: 100)")
    parser.add_argument("--external-workers", type=int, default=4)
    parser.add_argument("--external-host-interval", type=float, default=1.0, help="minimum seconds between requests per host (at least 0.1)")
    parser.add_argument("--external-timeout", type=float, default=10.0, help="per-request timeout, at most 30 seconds")
    args = parser.parse_args(argv)
    if args.external_limit < 0 or not 1 <= args.external_workers <= 16 or not 0.1 <= args.external_host_interval <= 60 or not 0 < args.external_timeout <= 30:
        parser.error("invalid external bounds: limit >= 0; workers 1..16; interval 0.1..60; timeout (0,30]")
    try:
        checker = SiteChecker(args.site_dir, args.site_url, args.allow_dynamic_anchor)
        report = checker.check()
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}")
        return 1
    if args.external:
        urls = sorted(report.external)
        selected = urls[:args.external_limit] if args.external_limit else urls
        print(f"External checking: {len(selected)}/{len(urls)} URLs (0 limit means all); link URLs only, no page contents.")
        report.warnings = ExternalChecker(args.external_workers, args.external_host_interval, args.external_timeout).check(selected)
    print_report(report, checker.root)
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
