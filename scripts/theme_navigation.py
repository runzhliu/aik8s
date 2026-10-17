"""Adapt Zensical's stock language navigation to our per-page alternate URLs.

The pinned Zensical 0.0.51 bundle assumes hreflang URLs are language *roots* and
loads sitemap.xml relative to each. Our custom alternate partial already resolves
article-to-article links, so that controller causes nested sitemap 404s and can
rewrite correct links. Disable only its bootstrap, retaining the normal root
sitemap, previews, search, and all other theme controllers. Fail explicitly when
a theme upgrade changes the recognizable controller instead of patching blindly.
"""
from pathlib import Path
import re

MARKER = '/* AIK8S: per-page language links are resolved at build time */'


def adapt_language_navigation(source: str) -> str:
    if MARKER in source:
        return source
    controller = re.search(
        r'function ([A-Za-z_$][\w$]*)\(\{document\$:[\w$]+\}\)\{'
        r'(?=[^{}]{0,250}["\']link\[rel=alternate\]["\'])', source,
    )
    if controller is None:
        raise ValueError('Zensical language controller changed; review theme_navigation.py before publishing')
    bootstrap = re.compile(r'(?<![\w$])' + re.escape(controller[1]) + r'\(\{document\$:[\w$]+\}\);')
    result, count = bootstrap.subn(MARKER + ';', source)
    if count != 1:
        raise ValueError(f'Expected one Zensical language bootstrap, found {count}')
    return result


def adapt_theme_assets(site_dir: Path) -> None:
    for bundle in (site_dir / 'assets/javascripts').glob('bundle.*.min.js'):
        original = bundle.read_text(encoding='utf-8')
        source = adapt_language_navigation(original)
        if source != original:
            bundle.write_text(source, encoding='utf-8')
