#!/usr/bin/env python3
"""Inject the Google AdSense loader into production HTML files."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


CLIENT_PATTERN = re.compile(r"ca-pub-\d+")
HEAD_END_PATTERN = re.compile(r"</head\s*>", re.IGNORECASE)


def adsense_tag(client: str) -> str:
    return (
        "  <!-- Google AdSense (production only) -->\n"
        '  <script async src="https://pagead2.googlesyndication.com/pagead/js/'
        f'adsbygoogle.js?client={client}"\n'
        '          crossorigin="anonymous"></script>\n'
    )


def inject(path: Path, client: str) -> bool:
    html = path.read_text(encoding="utf-8")
    marker = f"adsbygoogle.js?client={client}"
    if marker in html:
        return False

    match = HEAD_END_PATTERN.search(html)
    if match is None:
        raise ValueError(f"missing </head> in {path}")

    updated = html[: match.start()] + adsense_tag(client) + html[match.start() :]
    path.write_text(updated, encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-dir", type=Path, required=True)
    parser.add_argument("--client", required=True)
    args = parser.parse_args()

    if CLIENT_PATTERN.fullmatch(args.client) is None:
        parser.error("--client must look like ca-pub-1234567890")
    if not args.site_dir.is_dir():
        parser.error(f"site directory does not exist: {args.site_dir}")

    html_files = sorted(args.site_dir.rglob("*.html"))
    if not html_files:
        parser.error(f"no HTML files found under: {args.site_dir}")

    injected = sum(inject(path, args.client) for path in html_files)
    print(f"AdSense injected into {injected} of {len(html_files)} HTML files")


if __name__ == "__main__":
    main()
