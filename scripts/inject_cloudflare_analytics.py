#!/usr/bin/env python3
"""Inject Cloudflare Web Analytics into production HTML files."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


TOKEN_PATTERN = re.compile(r"[a-f0-9]{32}")
BODY_END_PATTERN = re.compile(r"</body\s*>", re.IGNORECASE)
BEACON_PATTERN = re.compile(r"data-cf-beacon\s*=", re.IGNORECASE)


def analytics_tag(token: str) -> str:
    return (
        "  <!-- Cloudflare Web Analytics (production only) -->\n"
        '  <script type="module" '
        'src="https://static.cloudflareinsights.com/beacon.min.js"\n'
        f"          data-cf-beacon='{{\"token\":\"{token}\"}}'></script>\n"
        "  <!-- End Cloudflare Web Analytics -->\n"
    )


def inject(path: Path, token: str) -> bool:
    html = path.read_text(encoding="utf-8")
    marker = f'{{"token":"{token}"}}'
    if marker in html and BEACON_PATTERN.search(html):
        return False
    if BEACON_PATTERN.search(html):
        raise ValueError(f"existing Cloudflare Web Analytics beacon in {path}")

    match = BODY_END_PATTERN.search(html)
    if match is None:
        raise ValueError(f"missing </body> in {path}")

    updated = html[: match.start()] + analytics_tag(token) + html[match.start() :]
    path.write_text(updated, encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-dir", type=Path, required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    if TOKEN_PATTERN.fullmatch(args.token) is None:
        parser.error("--token must be a 32-character lowercase hexadecimal string")
    if not args.site_dir.is_dir():
        parser.error(f"site directory does not exist: {args.site_dir}")

    html_files = sorted(args.site_dir.rglob("*.html"))
    if not html_files:
        parser.error(f"no HTML files found under: {args.site_dir}")

    injected = sum(inject(path, args.token) for path in html_files)
    print(f"Cloudflare Web Analytics injected into {injected} of {len(html_files)} HTML files")


if __name__ == "__main__":
    main()
