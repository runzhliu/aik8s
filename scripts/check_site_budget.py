#!/usr/bin/env python3
"""Enforce small, explicit local-asset budgets; never claim to measure real-user speed.

Counts authored root JS/CSS per language (not duplicate theme/vendor assets), plus
largest HTML. Third-party ad/analytics payloads require separate live monitoring;
this offline gate neither removes those scripts nor changes their consent policy.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

DEFAULT = Path(__file__).with_name('performance-budget.json')
KEYS = ('custom_javascript_bytes', 'custom_stylesheet_bytes', 'single_html_bytes')


def check_budget(site_dir: Path, limits: dict) -> tuple[list[str], list[str]]:
    for key in KEYS:
        if type(limits.get(key)) is not int or limits[key] <= 0:
            raise ValueError(f'{key} must be a positive integer byte budget')
    report, errors = [], []
    roots = [site_dir] + ([site_dir / 'en'] if (site_dir / 'en').is_dir() else [])
    for root in roots:
        for folder, suffix, key in [('javascripts', '.js', KEYS[0]), ('stylesheets', '.css', KEYS[1])]:
            files = sorted((root / folder).glob('*' + suffix))
            size = sum(file.stat().st_size for file in files if file.is_file())
            label = f'{root.relative_to(site_dir).as_posix()}/{folder}'
            report.append(f'{label}: {size:,} raw bytes / {limits[key]:,} budget ({len(files)} files)')
            if size > limits[key]:
                errors.append(f'{label} exceeds {key}: {size} > {limits[key]}')
    pages = sorted(site_dir.rglob('*.html'))
    if not pages:
        errors.append('No built HTML found')
    else:
        largest = max(pages, key=lambda page: page.stat().st_size)
        size = largest.stat().st_size
        report.append(f'Largest HTML: {largest.relative_to(site_dir)} ({size:,} raw bytes / {limits[KEYS[2]]:,} budget)')
        for page in pages:
            if page.stat().st_size > limits[KEYS[2]]:
                errors.append(f'{page.relative_to(site_dir)} exceeds {KEYS[2]}')
    return report, errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-dir', type=Path, default=Path('site'))
    parser.add_argument('--budget-file', type=Path, default=DEFAULT)
    args = parser.parse_args(argv)
    if not args.site_dir.is_dir():
        parser.error('--site-dir must be a built directory')
    try:
        report, errors = check_budget(args.site_dir, json.loads(args.budget_file.read_text()))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print('Offline performance budget — uncompressed local file sizes only')
    print('\n'.join(report))
    for error in errors:
        print('ERROR:', error)
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
