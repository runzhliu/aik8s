#!/usr/bin/env python3
"""Build two independently localized sites, then combine their discovery metadata."""
from __future__ import annotations

import argparse
from copy import deepcopy
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from urllib.parse import unquote

from bilingual import ROOT, coverage, protect, restore
from translate_assets import ASSET_MAP, asset_errors, localize_asset
from translate_text_blocks import block_errors, english_readings
from preserve_prompt_originals import prompt_errors, preserve_prompt_originals

WORK = ROOT / ".local/i18n-build"
SITEMAP = "http://www.sitemaps.org/schemas/sitemap/0.9"
XHTML = "http://www.w3.org/1999/xhtml"


def localize_document_links(source: str, homepage=False):
    protected, literals = protect(source)
    def localize(value):
        if value.startswith('https://aik8s.run/') and not value.startswith('https://aik8s.run/en/'):
            return value.replace('https://aik8s.run/', 'https://aik8s.run/en/', 1)
        if value.startswith(('/assets/', '/ai-k8s/', '/cases/', '/k3s-upgrade/')) or (value == '/' and not homepage):
            return '/en' + value
        return value
    # The full code blocks and inline code were frozen as single literals, so
    # executable examples are not changed by URL localization.
    literals = {key: localize(value) for key, value in literals.items()}
    protected = re.sub(r'''\b(src|href)=(['"])(/[^'"<>]+)\2''', lambda m: m.group(1)+'='+m.group(2)+localize(m.group(3))+m.group(2), protected)
    protected = re.sub(r'^redirect_to: (/[^\s]+)$', lambda m: 'redirect_to: ' + localize(m.group(1)), protected, flags=re.M)
    return restore(protected, literals)


def toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(x) for x in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(json.dumps(k, ensure_ascii=False) + " = " + toml_value(v) for k, v in value.items()) + "}"
    raise TypeError(type(value).__name__)


def translate_navigation(value, labels, available=None):
    if isinstance(value, str):
        return value if available is None or not value.endswith(".md") or value in available else None
    if isinstance(value, list):
        return [translated for child in value if (translated := translate_navigation(child, labels, available)) is not None]
    result = {}
    for label, child in value.items():
        translated = translate_navigation(child, labels, available)
        if translated:
            if label not in labels:
                raise ValueError(f"missing English navigation label: {label}")
            result[labels[label]] = translated
    return result or None


def prepare(preview=False):
    report = coverage()
    incomplete = report["missing"] or report["stale"] or report["invalid"] or report['readme_errors']
    if incomplete and not preview:
        raise ValueError(f"incomplete bilingual coverage: {len(report['current'])}/{report['total']} current; run scripts/bilingual.py --json")
    missing_assets = asset_errors()
    if missing_assets and not preview:
        raise ValueError(f"missing or stale English visual labels: {missing_assets}")
    missing_blocks = block_errors()
    if missing_blocks and not preview:
        raise ValueError(f"missing English readings of {len(missing_blocks)} Chinese plaintext blocks")
    if not preview and (errors := prompt_errors()):
        raise ValueError(f"quoted experiment prompts need review: {errors}")
    if not report["current"]:
        raise ValueError("no verified English pages")
    print(f"Bilingual coverage: {len(report['current'])}/{report['total']}" + (" (private partial preview)" if preview else ""), flush=True)
    WORK.mkdir(parents=True, exist_ok=True)
    staged = WORK / "english-docs"
    if staged.exists():
        shutil.rmtree(staged)
    # This staging tree is generated; source documents and original evidence stay untouched.
    shutil.copytree(ROOT / "docs", staged, ignore=shutil.ignore_patterns("*.md"))
    if ASSET_MAP.exists():
        for name, record in json.loads(ASSET_MAP.read_text()).items():
            (staged / name).write_text(localize_asset(ROOT / "docs" / name, record))
    for name in report["current"]:
        target = staged / name
        target.parent.mkdir(parents=True, exist_ok=True)
        source = (ROOT / "translations/en" / name).read_text()
        source = preserve_prompt_originals(name, source)
        source = localize_document_links(source, homepage=name == 'index.md')
        source = english_readings(source)
        # The homepage's Chinese/English language buttons deliberately retain their targets.
        if name == "index.md":
            source = source.replace('[简体中文](/){ .md-button .md-button--primary }\n[English](/en/){ .md-button }', '[简体中文](/){ .md-button }\n[English](/en/){ .md-button .md-button--primary }')
        target.write_text(source)
    config = tomllib.loads((ROOT / "zensical.toml").read_text())
    labels = json.loads((ROOT / "translations/navigation.en.json").read_text())
    for language in ("zh", "en"):
        project = deepcopy(config["project"])
        project["docs_dir"] = os.path.relpath(ROOT / "docs" if language == "zh" else staged, ROOT)
        project["site_dir"] = os.path.relpath(ROOT / "site" / ("en" if language == "en" else ""), ROOT)
        project["theme"]["custom_dir"] = "overrides"
        if language == "en":
            project["site_name"] = "AI/LLM on Kubernetes Infrastructure"
            project["site_description"] = "Infrastructure notes for platform engineers and SREs: GPUs, data, scheduling, training, inference, RAG, agents, and production operations"
            project["site_url"] = "https://aik8s.run/en/"
            project["theme"]["language"] = "en"
            project["nav"] = translate_navigation(project["nav"], labels, set(report["current"]) if preview else None)
            for palette in project["theme"].get("palette", []):
                palette["toggle"]["name"] = "Switch to dark mode" if palette["scheme"] == "default" else "Switch to light mode"
        output = "[project]\n" + "\n".join(json.dumps(k) + " = " + toml_value(v) for k, v in project.items()) + "\n"
        # Zensical treats the config's directory as the project root, and requires
        # site_dir to stay inside it. Generated configs therefore live at ROOT.
        path = ROOT / (".zensical-" + language + ".generated.toml")
        path.write_text(output)
        # Check the generated config before invoking the static site builder.
        tomllib.loads(output)
    return report


def heading_aliases(chinese: str, english: str) -> str:
    article = re.compile(r"<article\b[^>]*>.*?</article>", re.S)
    heading = re.compile(r'<h([1-6])\b[^>]*\bid="([^"]+)"[^>]*>')
    zh_article, en_article = article.search(chinese), article.search(english)
    if not zh_article or not en_article:
        raise ValueError("missing article element")
    source = heading.findall(zh_article.group())
    targets = list(heading.finditer(en_article.group()))
    if [level for level, _ in source] != [match.group(1) for match in targets]:
        raise ValueError("rendered Chinese/English heading structures differ")
    existing = set(re.findall(r'\bid="([^"]+)"', english))
    content = en_article.group()
    for (_, original), target in reversed(list(zip(source, targets))):
        if original not in existing:
            alias = '<span class="aik8s-heading-alias" id="' + html.escape(html.unescape(original), quote=True) + '" aria-hidden="true"></span>'
            content = content[:target.start()] + alias + content[target.start():]
            existing.add(original)
    return english[:en_article.start()] + content + english[en_article.end():]


def bind_linked_heading_ids(markdown: str, chinese: str, required: set[str]) -> str:
    """Bind referenced source IDs before strict compilation; retain other English slugs."""
    article = re.search(r'<article\b[^>]*>.*?</article>', chinese, re.S)
    if not article:
        raise ValueError('missing source article for heading IDs')
    headings = re.findall(r'<h([1-6])\b[^>]*\bid="([^"]+)"', article.group())
    output, fence, index = [], None, 0
    for line in markdown.splitlines(keepends=True):
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            if fence is None:
                fence = marker.group(1)
            elif marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence):
                fence = None
            output.append(line)
            continue
        heading = re.match(r'^(#{1,6})\s+', line) if fence is None else None
        if heading:
            if index >= len(headings) or len(heading.group(1)) != int(headings[index][0]):
                raise ValueError('source HTML and translated Markdown heading structures differ')
            original = html.unescape(headings[index][1])
            if original in required and not re.search(r'\{\s*#[^}]+\}\s*$', line):
                ending = '\n' if line.endswith('\n') else ''
                line = line.rstrip('\r\n') + ' { #' + original + ' }' + ending
            index += 1
        output.append(line)
    if index != len(headings):
        raise ValueError('source HTML and translated Markdown heading counts differ')
    return ''.join(output)


def bind_referenced_source_headings(report):
    staged = WORK / 'english-docs'
    documents = {name: (staged / name).read_text() for name in report['current']}
    required = {unquote(html.unescape(fragment)) for text in documents.values()
                for fragment in re.findall(r'(?:\]\([^\n)]*#|href=[\"\'][^\"\']*#)([^\s\)\"\']+)', text)}
    for name, text in documents.items():
        source = (ROOT / 'site' / rendered_path(name)).read_text()
        (staged / name).write_text(bind_linked_heading_ids(text, source, required))


def combine_sitemaps(site: Path):
    chinese, english = ET.parse(site / "sitemap.xml"), ET.parse(site / "en/sitemap.xml")
    # Finalization may be retried after an interrupted build. Remove the prior
    # English merge and regenerate alternates rather than duplicating entries.
    for element in list(chinese.getroot()):
        if (element.findtext(f'{{{SITEMAP}}}loc') or '').startswith('https://aik8s.run/en/'):
            chinese.getroot().remove(element)
    for tree in (chinese, english):
        for element in tree.getroot():
            for alternate in list(element.findall(f'{{{XHTML}}}link')):
                element.remove(alternate)
    zh_urls = {element.findtext(f"{{{SITEMAP}}}loc"): element for element in chinese.getroot()}
    en_urls = {element.findtext(f"{{{SITEMAP}}}loc"): element for element in english.getroot()}
    for url, element in list(zh_urls.items()) + list(en_urls.items()):
        base = url.replace("https://aik8s.run/en/", "https://aik8s.run/", 1)
        alternative = base.replace("https://aik8s.run/", "https://aik8s.run/en/", 1)
        if base in zh_urls and alternative in en_urls:
            for language, link in (("zh-Hans", base), ("en", alternative), ("x-default", base)):
                ET.SubElement(element, f"{{{XHTML}}}link", {"rel": "alternate", "hreflang": language, "href": link})
    for element in english.getroot():
        chinese.getroot().append(deepcopy(element))
    ET.register_namespace("", SITEMAP)
    ET.register_namespace("xhtml", XHTML)
    chinese.write(site / "sitemap.xml", encoding="utf-8", xml_declaration=True)
    english.write(site / "en/sitemap.xml", encoding="utf-8", xml_declaration=True)
    # Zensical's compressed sitemap would otherwise describe only one language.
    for sitemap in (site / "sitemap.xml", site / "en/sitemap.xml"):
        import gzip
        sitemap.with_suffix(".xml.gz").write_bytes(gzip.compress(sitemap.read_bytes(), mtime=0))


def rendered_path(name: str):
    path = Path(name)
    return path.with_suffix(".html") if path.name == "404.md" else path.parent / "index.html" if path.name.lower() in ("index.md", "readme.md") else path.with_suffix("") / "index.html"


def finalize(report):
    for name in report["current"]:
        path = rendered_path(name)
        target = ROOT / "site/en" / path
        if not target.exists():
            raise ValueError(f"missing English output: {name}")
        source = target.read_text()
        if not re.search(r'<html\b[^>]*\blang="en"', source):
            raise ValueError(f"wrong English document language: {name}")
        target.write_text(heading_aliases((ROOT / "site" / path).read_text(), source))
    combine_sitemaps(ROOT / "site")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", action="store_true", help="use the pinned Docker image instead of a local Zensical")
    parser.add_argument("--preview", action="store_true", help="allow a private partial preview; never use for publication")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    report = prepare(args.preview)
    if args.prepare_only:
        return
    if args.docker:
        builder = ["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "-v", f"{ROOT}:/docs", "-w", "/docs", "zensical/zensical:0.0.51"]
    else:
        builder = ["zensical"]
    for language in ("zh", "en"):
        if language == 'en':
            bind_referenced_source_headings(report)
        command = builder + ["build", "--clean", "--config-file", f".zensical-{language}.generated.toml"]
        if not args.preview:
            command.append("--strict")
        log = WORK / f"{language}-build.log"
        with log.open("w") as output:
            result = subprocess.run(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
        summary = re.sub(r'\x1b\[[0-9;]*m', '', log.read_text()).splitlines()[-3:]
        print(f"{language}: " + " | ".join(summary) + f"; full log: {log.relative_to(ROOT)}", flush=True)
        if result.returncode:
            raise RuntimeError(f"{language} build failed; inspect {log}")
        distribution = [sys.executable, "scripts/build_distribution.py", "--docs-dir", "docs" if language == "zh" else ".local/i18n-build/english-docs", "--site-dir", "site" if language == "zh" else "site/en", "--site-url", "https://aik8s.run/" if language == "zh" else "https://aik8s.run/en/", "--language", language]
        if language == "en":
            distribution += ["--source-docs-dir", "docs"]
        subprocess.run(distribution, cwd=ROOT, check=True)
    finalize(report)
    print("Built Chinese / and English /en/ with paired language links, dates, feeds, and sitemaps.")


if __name__ == "__main__":
    main()
