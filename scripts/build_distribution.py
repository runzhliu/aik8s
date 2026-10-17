#!/usr/bin/env python3
"""Build discovery feeds, sitemap, and social/search metadata for the site."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from email.utils import format_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin
from zoneinfo import ZoneInfo

from article_discovery import TAG_LABELS, TYPE_LABELS, infer_discovery, related_items


SITE_TITLE = "AI/LLM on Kubernetes 基础设施"
SITE_DESCRIPTION = "GPU、大数据、调度、训练、推理、RAG、Agent 与生产运维"
SITE_LANGUAGE = "zh-CN"
AUTHOR_NAME = "runzhliu"
AUTHOR_URL = "https://github.com/runzhliu"
FEED_MARKER = "<!-- AIK8S distribution metadata -->"
ARTICLE_DATES_PATTERN = re.compile(
    r"\n?<!-- AIK8S article dates -->.*?<!-- /AIK8S article dates -->\n?",
    re.DOTALL,
)
ARTICLE_HEADING_PATTERN = re.compile(
    r"(<article\b[^>]*>.*?</h1\s*>)", re.IGNORECASE | re.DOTALL
)
DISPLAY_TIMEZONE = ZoneInfo("Asia/Shanghai")
HEAD_END_PATTERN = re.compile(r"</head\s*>", re.IGNORECASE)
TITLE_PATTERN = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
DESCRIPTION_PATTERN = re.compile(
    r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']\s*/?>',
    re.IGNORECASE | re.DOTALL,
)
CANONICAL_PATTERN = re.compile(
    r'<link\s+rel=["\']canonical["\']\s+href=["\'](.*?)["\']\s*/?>',
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class FeedItem:
    title: str
    description: str
    url: str
    published: datetime
    updated: datetime
    category: str
    is_index: bool
    tags: tuple[str, ...] = ()
    content_type: str = "overview"


class BreadcrumbParser(HTMLParser):
    """Extract the visible Zensical breadcrumb navigation from generated HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_path = False
        self.current_href: str | None = None
        self.current_text: list[str] = []
        self.items: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "nav" and "md-path" in (attributes.get("class") or "").split():
            self.in_path = True
        elif self.in_path and tag == "a":
            self.current_href = attributes.get("href")
            self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.in_path and self.current_href is not None:
            self.current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.in_path and tag == "a" and self.current_href is not None:
            label = re.sub(r"\s+", " ", "".join(self.current_text)).strip()
            if label:
                self.items.append((label, self.current_href))
            self.current_href = None
            self.current_text = []
        elif tag == "nav" and self.in_path:
            self.in_path = False


def parse_front_matter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    metadata: dict[str, str] = {}
    if text.startswith("---\n"):
        _, raw, body = text.split("---", 2)
        for line in raw.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            value = value.strip()
            if value.startswith('"') and value.endswith('"'):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    value = value.strip('"')
            else:
                value = value.strip("'")
            metadata[key.strip()] = value
    else:
        body = text

    if not metadata.get("title"):
        heading = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        if heading:
            metadata["title"] = heading.group(1).strip()
    if not metadata.get("description"):
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        for paragraph in paragraphs:
            if paragraph.startswith(("#", "```", "<", "- ", "|")):
                continue
            metadata["description"] = re.sub(r"[`*_\[\]]", "", paragraph)[:240]
            break
    return metadata


def load_git_history(repo_root: Path, docs_dir: Path) -> dict[str, list[datetime]]:
    history: dict[str, list[datetime]] = {}
    try:
        docs_path = str(docs_dir.relative_to(repo_root))
        result = subprocess.run(
            [
                "git", "-c", "core.quotepath=false", "log", "--reverse",
                "--format=__AIK8S_COMMIT__%cI", "--name-status", "--find-renames",
                "--", docs_path,
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        current_date: datetime | None = None
        for line in result.stdout.splitlines():
            if line.startswith("__AIK8S_COMMIT__"):
                value = line.removeprefix("__AIK8S_COMMIT__")
                try:
                    current_date = datetime.fromisoformat(value).astimezone(timezone.utc)
                except ValueError:
                    current_date = None
            elif current_date is not None and line.strip():
                change = line.split("\t")
                if len(change) == 3 and change[0].startswith("R"):
                    old_path, new_path = change[1:]
                    previous = history.pop(old_path, [])
                    history.setdefault(new_path, []).extend(previous)
                    history[new_path].append(current_date)
                elif len(change) == 2:
                    history.setdefault(change[1], []).append(current_date)
    except (OSError, subprocess.CalledProcessError, ValueError):
        return {}
    return history


def git_dates(
    path: Path,
    repo_root: Path,
    reviewed: str | None,
    history_by_path: dict[str, list[datetime]],
) -> tuple[datetime, datetime]:
    history = history_by_path.get(str(path.relative_to(repo_root)), [])
    if history:
        try:
            published = min(history)
            latest = max(history)
        except ValueError:
            history = []
    if not history:
        fallback = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        published = fallback
        latest = fallback

    updated_candidates = [latest]
    if reviewed:
        try:
            updated_candidates.append(datetime.combine(date.fromisoformat(reviewed), time(0), timezone.utc))
        except ValueError:
            pass
    return published, max(updated_candidates)


def page_url(path: Path, docs_dir: Path, site_url: str) -> str:
    relative = path.relative_to(docs_dir)
    if relative.name == "index.md":
        page_path = relative.parent.as_posix().strip("/")
    else:
        page_path = relative.with_suffix("").as_posix().strip("/")
    return site_url if not page_path else urljoin(site_url, page_path + "/")


def category_for(path: Path, docs_dir: Path) -> str:
    parts = path.relative_to(docs_dir).parts
    if len(parts) > 2 and parts[0] == "ai-k8s":
        return parts[1]
    return parts[0] if len(parts) > 1 else "Home" if SITE_LANGUAGE == "en" else "首页"


def collect_items(docs_dir: Path, repo_root: Path, site_url: str, source_docs_dir: Path | None = None) -> list[FeedItem]:
    items: list[FeedItem] = []
    history_by_path = load_git_history(repo_root, source_docs_dir or docs_dir)
    for path in sorted(docs_dir.rglob("*.md")):
        # Asset provenance and repository notes are not published articles.
        if path.relative_to(docs_dir).parts[0] == "assets" or path.name.lower() == "readme.md":
            continue
        metadata = parse_front_matter(path)
        if metadata.get('redirect_to'):
            continue
        title = metadata.get("title")
        description = metadata.get("description")
        if not title or not description:
            continue
        history_path = source_docs_dir / path.relative_to(docs_dir) if source_docs_dir else path
        published, updated = git_dates(history_path, repo_root, metadata.get("last_reviewed"), history_by_path)
        # English pages inherit discovery metadata from the original document,
        # just like their dates, so filters remain stable across languages.
        discovery_metadata = parse_front_matter(history_path) if source_docs_dir else metadata
        tags, content_type = infer_discovery(path.relative_to(docs_dir).as_posix(), discovery_metadata)
        items.append(
            FeedItem(
                title=title,
                description=description,
                url=page_url(path, docs_dir, site_url),
                published=published,
                updated=updated,
                category=category_for(path, docs_dir),
                is_index=path.name == "index.md",
                tags=tags,
                content_type=content_type,
            )
        )
    return sorted(items, key=lambda item: (item.updated, item.url), reverse=True)


def write_rss(items: list[FeedItem], output: Path, site_url: str, limit: int) -> None:
    ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = SITE_TITLE
    ET.SubElement(channel, "link").text = site_url
    ET.SubElement(channel, "description").text = SITE_DESCRIPTION
    ET.SubElement(channel, "language").text = SITE_LANGUAGE
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))
    ET.SubElement(
        channel,
        "{http://www.w3.org/2005/Atom}link",
        {"href": urljoin(site_url, "rss.xml"), "rel": "self", "type": "application/rss+xml"},
    )
    for entry in items[:limit]:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = entry.title
        ET.SubElement(item, "link").text = entry.url
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = entry.url
        ET.SubElement(item, "pubDate").text = format_datetime(entry.updated)
        ET.SubElement(item, "description").text = entry.description
        ET.SubElement(item, "category").text = entry.category
    ET.indent(rss, space="  ")
    ET.ElementTree(rss).write(output, encoding="utf-8", xml_declaration=True)


def write_atom(items: list[FeedItem], output: Path, site_url: str, limit: int) -> None:
    atom_ns = "http://www.w3.org/2005/Atom"
    ET.register_namespace("", atom_ns)
    feed = ET.Element(f"{{{atom_ns}}}feed")
    ET.SubElement(feed, f"{{{atom_ns}}}title").text = SITE_TITLE
    ET.SubElement(feed, f"{{{atom_ns}}}id").text = site_url
    ET.SubElement(feed, f"{{{atom_ns}}}updated").text = datetime.now(timezone.utc).isoformat()
    ET.SubElement(feed, f"{{{atom_ns}}}subtitle").text = SITE_DESCRIPTION
    ET.SubElement(feed, f"{{{atom_ns}}}link", {"href": site_url, "rel": "alternate"})
    ET.SubElement(
        feed,
        f"{{{atom_ns}}}link",
        {"href": urljoin(site_url, "atom.xml"), "rel": "self", "type": "application/atom+xml"},
    )
    for item in items[:limit]:
        entry = ET.SubElement(feed, f"{{{atom_ns}}}entry")
        ET.SubElement(entry, f"{{{atom_ns}}}title").text = item.title
        ET.SubElement(entry, f"{{{atom_ns}}}id").text = item.url
        ET.SubElement(entry, f"{{{atom_ns}}}link", {"href": item.url})
        ET.SubElement(entry, f"{{{atom_ns}}}updated").text = item.updated.isoformat()
        ET.SubElement(entry, f"{{{atom_ns}}}summary").text = item.description
        ET.SubElement(entry, f"{{{atom_ns}}}category", {"term": item.category})
    ET.indent(feed, space="  ")
    ET.ElementTree(feed).write(output, encoding="utf-8", xml_declaration=True)


def write_sitemap(items: list[FeedItem], output: Path) -> None:
    sitemap_ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
    ET.register_namespace("", sitemap_ns)
    urlset = ET.Element(f"{{{sitemap_ns}}}urlset")
    for item in sorted(items, key=lambda entry: entry.url):
        url = ET.SubElement(urlset, f"{{{sitemap_ns}}}url")
        ET.SubElement(url, f"{{{sitemap_ns}}}loc").text = item.url
        ET.SubElement(url, f"{{{sitemap_ns}}}lastmod").text = item.updated.isoformat()
    ET.indent(urlset, space="  ")
    ET.ElementTree(urlset).write(output, encoding="utf-8", xml_declaration=True)


def meta_tag(property_name: str, content: str, *, property_attribute: str = "property") -> str:
    return f'  <meta {property_attribute}="{property_name}" content="{html.escape(content, quote=True)}">\n'


def normalize_url(url: str) -> str:
    return url.rstrip("/") + "/"


def extract_breadcrumbs(source: str, canonical: str, title: str) -> list[dict[str, object]]:
    parser = BreadcrumbParser()
    parser.feed(source)
    entries: list[tuple[str, str]] = []
    for label, href in parser.items:
        url = urljoin(canonical, href)
        if not entries or normalize_url(entries[-1][1]) != normalize_url(url):
            entries.append((label, url))
    if not entries or normalize_url(entries[-1][1]) != normalize_url(canonical):
        entries.append((title, canonical))
    return [
        {"@type": "ListItem", "position": position, "name": label, "item": url}
        for position, (label, url) in enumerate(entries, start=1)
    ]


def structured_data(item: FeedItem, source: str, site_url: str, image_url: str) -> str:
    website_id = site_url + "#website"
    graph: list[dict[str, object]] = [
        {
            "@type": "WebSite",
            "@id": website_id,
            "url": site_url,
            "name": SITE_TITLE,
            "description": SITE_DESCRIPTION,
            "inLanguage": SITE_LANGUAGE,
        }
    ]
    if normalize_url(item.url) != normalize_url(site_url):
        if item.is_index:
            graph.append(
                {
                    "@type": "CollectionPage",
                    "@id": item.url,
                    "url": item.url,
                    "name": item.title,
                    "description": item.description,
                    "inLanguage": SITE_LANGUAGE,
                    "isPartOf": {"@id": website_id},
                    "dateModified": item.updated.isoformat(),
                }
            )
        else:
            graph.append(
                {
                    "@type": "TechArticle",
                    "@id": item.url + "#article",
                    "url": item.url,
                    "headline": item.title,
                    "description": item.description,
                    "inLanguage": SITE_LANGUAGE,
                    "datePublished": item.published.isoformat(),
                    "dateModified": item.updated.isoformat(),
                    "mainEntityOfPage": {"@type": "WebPage", "@id": item.url},
                    "isPartOf": {"@id": website_id},
                    "image": [image_url],
                    "author": {"@type": "Person", "name": AUTHOR_NAME, "url": AUTHOR_URL},
                    "publisher": {
                        "@type": "Organization",
                        "name": SITE_TITLE,
                        "url": site_url,
                        "logo": {"@type": "ImageObject", "url": image_url},
                    },
                }
            )

    breadcrumbs = extract_breadcrumbs(source, item.url, item.title)
    if len(breadcrumbs) >= 2:
        graph.append(
            {
                "@type": "BreadcrumbList",
                "@id": item.url + "#breadcrumb",
                "itemListElement": breadcrumbs,
            }
        )
    payload = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)
    return '  <script type="application/ld+json">' + payload.replace("</", "<\\/") + "</script>\n"


def inject_article_dates(source: str, item: FeedItem | None) -> str:
    source = ARTICLE_DATES_PATTERN.sub("\n", source)
    if item is None or item.is_index:
        return source
    heading = ARTICLE_HEADING_PATTERN.search(source)
    if heading is None:
        raise ValueError(f"missing article heading for {item.url}")
    dates = []
    labels = ("Published", "Updated") if SITE_LANGUAGE == "en" else ("创建于", "更新于")
    time_label = " (UTC+08:00)" if SITE_LANGUAGE == "en" else "（北京时间）"
    group_label = "Article publication and update dates" if SITE_LANGUAGE == "en" else "文章创建与更新时间"
    for label, timestamp in zip(labels, (item.published, item.updated)):
        local = timestamp.astimezone(DISPLAY_TIMEZONE)
        dates.append(
            f'  <span>{label} <time datetime="{timestamp.isoformat()}" '
            f'title="{local:%Y-%m-%d %H:%M:%S}{time_label}">{local:%Y-%m-%d}</time></span>'
        )
    block = (
        '\n<!-- AIK8S article dates -->\n'
        f'<div class="aik8s-article-dates" role="group" aria-label="{group_label}">\n'
        + "\n".join(dates)
        + '\n</div>\n<!-- /AIK8S article dates -->\n'
    )
    return source[:heading.end()] + block + source[heading.end():].lstrip("\n")


def discovery_label(labels: dict[str, tuple[str, str]], value: str) -> str:
    return labels[value][1 if SITE_LANGUAGE == 'en' else 0]


def tag_links(item: FeedItem, site_url: str) -> str:
    return ' '.join(
        '<a class="aik8s-tag" href="' + html.escape(urljoin(site_url, 'timeline.html') + '?' + urlencode({'tag': tag}), quote=True)
        + '">' + html.escape(discovery_label(TAG_LABELS, tag)) + '</a>' for tag in item.tags
    )


def inject_article_discovery(source: str, item: FeedItem | None, articles: list[FeedItem], site_url: str) -> str:
    """Add crawlable topic links and deterministic recommendations, never requiring JS."""
    source = re.sub(r'\n?<!-- AIK8S discovery -->.*?<!-- /AIK8S discovery -->\n?', '\n', source, flags=re.S)
    if item is None or item.is_index:
        return source
    english = SITE_LANGUAGE == 'en'
    if item.tags:
        label = 'Article topics' if english else '文章标签'
        block = '\n<!-- AIK8S discovery -->\n<nav class="aik8s-article-tags" aria-label="' + label + '">' + tag_links(item, site_url) + '</nav>\n<!-- /AIK8S discovery -->\n'
        dates = ARTICLE_DATES_PATTERN.search(source)
        heading = ARTICLE_HEADING_PATTERN.search(source)
        anchor = dates.end() if dates else heading.end() if heading else None
        if anchor is not None:
            source = source[:anchor] + block + source[anchor:]
    recommendations = related_items(item, articles)
    if recommendations:
        title = 'Related articles' if english else '相关文章'
        entries = ''.join(
            '<li><a href="' + html.escape(candidate.url, quote=True) + '">' + html.escape(candidate.title)
            + '</a><p>' + html.escape(candidate.description) + '</p></li>' for candidate in recommendations
        )
        # A labelled aside avoids altering authored heading/anchor parity in the
        # bilingual builder while keeping recommendations accessible as a landmark.
        block = '\n<!-- AIK8S discovery -->\n<aside class="aik8s-related" aria-labelledby="aik8s-related-title"><p class="aik8s-related__title" id="aik8s-related-title"><strong>' + title + '</strong></p><ul>' + entries + '</ul></aside>\n<!-- /AIK8S discovery -->\n'
        source = re.sub(r'</article\s*>', lambda match: block + match[0], source, count=1, flags=re.I)
    return source


def inject_metadata(path: Path, site_url: str, items_by_url: dict[str, FeedItem], articles: list[FeedItem] | None = None) -> bool:
    original = path.read_text(encoding="utf-8")
    canonical_match = CANONICAL_PATTERN.search(original)
    canonical = canonical_match.group(1).strip() if canonical_match else site_url
    item = items_by_url.get(normalize_url(canonical)) if canonical_match else None
    source = inject_article_dates(original, item)
    if articles is not None:
        source = inject_article_discovery(source, item, articles, site_url)
    if FEED_MARKER in source:
        if source == original:
            return False
        path.write_text(source, encoding="utf-8")
        return True
    head_end = HEAD_END_PATTERN.search(source)
    if head_end is None:
        raise ValueError(f"missing </head> in {path}")

    title_match = TITLE_PATTERN.search(source)
    description_match = DESCRIPTION_PATTERN.search(source)
    title = html.unescape(title_match.group(1).strip()) if title_match else SITE_TITLE
    description = html.unescape(description_match.group(1).strip()) if description_match else SITE_DESCRIPTION
    if item:
        title = item.title
        description = item.description
    image_url = urljoin(site_url, "assets/brand/aik8s-logo.png")

    tags = (
        f"  {FEED_MARKER}\n"
        f'  <link rel="alternate" type="application/rss+xml" title="{SITE_TITLE} RSS" href="{urljoin(site_url, "rss.xml")}">\n'
        f'  <link rel="alternate" type="application/atom+xml" title="{SITE_TITLE} Atom" href="{urljoin(site_url, "atom.xml")}">\n'
        + meta_tag("og:type", "article")
        + meta_tag("og:site_name", SITE_TITLE)
        + meta_tag("og:title", title)
        + meta_tag("og:description", description)
        + meta_tag("og:url", canonical)
        + meta_tag("og:image", image_url)
        + meta_tag("twitter:card", "summary", property_attribute="name")
        + meta_tag("twitter:title", title, property_attribute="name")
        + meta_tag("twitter:description", description, property_attribute="name")
        + meta_tag("twitter:image", image_url, property_attribute="name")
        + (structured_data(item, source, site_url, image_url) if item else "")
    )
    updated = source[: head_end.start()] + tags + source[head_end.start() :]
    path.write_text(updated, encoding="utf-8")
    return True


def without_page_toc(source: str) -> str:
    """Remove whole TOC trees, including nested navs, without reserializing HTML."""
    class TocParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.lines = [0] + [match.end() for match in re.finditer(r'\n', source)]
            self.depth = 0
            self.start = 0
            self.ranges = []

        def position(self):
            line, column = self.getpos()
            return self.lines[line - 1] + column

        def handle_starttag(self, tag, attrs):
            if tag != 'nav':
                return
            if self.depth:
                self.depth += 1
            elif 'md-nav--secondary' in dict(attrs).get('class', '').split():
                self.start = self.position()
                self.depth = 1

        def handle_endtag(self, tag):
            if tag == 'nav' and self.depth:
                self.depth -= 1
                if not self.depth:
                    self.ranges.append((self.start, source.index('>', self.position()) + 1))

    parser = TocParser()
    parser.feed(source)
    for start, end in reversed(parser.ranges):
        source = source[:start] + source[end:]
    return source


def timeline_controls(articles: list[FeedItem]) -> str:
    english = SITE_LANGUAGE == 'en'
    def label(zh: str, en: str) -> str:
        return en if english else zh
    def options(values, labels):
        return ''.join('<option value="' + html.escape(value, quote=True) + '">' + html.escape(discovery_label(labels, value)) + '</option>' for value in sorted(values))
    tags = {tag for item in articles for tag in item.tags}
    types = {item.content_type for item in articles}
    return (
        '<form class="aik8s-timeline-controls" data-timeline-controls hidden role="search" aria-label="' + label('筛选文章', 'Filter articles') + '">'
        '<label>' + label('排序', 'Sort by') + '<select name="sort"><option value="published">' + label('最新发布', 'Newest published') + '</option><option value="updated">' + label('最近更新', 'Recently updated') + '</option></select></label>'
        '<label>' + label('主题标签', 'Topic') + '<select name="tag"><option value="">' + label('全部标签', 'All topics') + '</option>' + options(tags, TAG_LABELS) + '</select></label>'
        '<label>' + label('文章类型', 'Article type') + '<select name="type"><option value="">' + label('全部类型', 'All types') + '</option>' + options(types, TYPE_LABELS) + '</select></label>'
        '<label class="aik8s-timeline-controls__search">' + label('关键词', 'Keywords') + '<input type="search" name="q" autocomplete="off" placeholder="' + label('搜索标题、摘要或标签', 'Search titles, summaries or topics') + '"></label>'
        '<button type="reset">' + label('重置筛选', 'Reset filters') + '</button></form>'
    )


def write_timeline(articles: list[FeedItem], site_dir: Path, site_url: str) -> FeedItem:
    """Reuse the built homepage shell, keeping root-relative assets valid without JS."""
    english = SITE_LANGUAGE == "en"
    title = "Article timeline" if english else "文章时间线"
    description = (
        "Browse all articles by publication or update date (UTC+08:00)."
        if english else "按发布或更新时间浏览全部文章，时间统一为北京时间。"
    )
    ordered = sorted(articles, key=lambda item: (item.published, item.url), reverse=True)
    escape = html.escape
    parts = [
        f'<h1 id="article-timeline">{title}</h1>', f'<p>{description}</p>',
        timeline_controls(articles),
        f'<p class="aik8s-timeline__count" data-timeline-count aria-live="polite" aria-atomic="true">{len(ordered)} ' + ("articles" if english else "篇文章") + '</p>',
        '<p data-timeline-empty hidden>' + ('No matching articles. Try another filter.' if english else '没有符合条件的文章，请尝试其他筛选条件。') + '</p>',
        '<div class="aik8s-timeline">',
    ]
    month = None
    for item in ordered:
        local = item.published.astimezone(DISPLAY_TIMEZONE)
        group = local.strftime("%Y-%m")
        if group != month:
            if month is not None:
                parts.append('</ol></section>')
            month = group
            parts.append(f'<section aria-labelledby="month-{group}"><h2 id="month-{group}">{group}</h2><ol>')
        search_text = ' '.join([item.title, item.description, *(discovery_label(TAG_LABELS, tag) for tag in item.tags), *item.tags, discovery_label(TYPE_LABELS, item.content_type)])
        parts.append(
            '<li data-timeline-item data-published="' + item.published.isoformat() + '" data-updated="' + item.updated.isoformat()
            + '" data-tags="' + escape(' '.join(item.tags), quote=True) + '" data-content-type="' + escape(item.content_type, quote=True)
            + '" data-search="' + escape(search_text, quote=True) + '"><time data-timeline-date datetime="' + item.published.isoformat() + f'">{local:%Y-%m-%d}</time>'
            '<div><a href="' + escape(item.url, quote=True) + '">' + escape(item.title) + '</a>'
            '<p>' + escape(item.description) + '</p><div class="aik8s-timeline__tags">'
            + '<span class="aik8s-tag">' + escape(discovery_label(TYPE_LABELS, item.content_type)) + '</span> '
            + tag_links(item, site_url) + '</div></div></li>'
        )
    if month is not None:
        parts.append('</ol></section>')
    parts.append('</div>')
    source = (site_dir / 'index.html').read_text(encoding='utf-8')
    source = re.sub(re.escape(FEED_MARKER) + r'.*?(?=</head\s*>)', '', source, flags=re.S)
    source, count = re.subn(
        r'(<article\b[^>]*>).*?(</article>)',
        lambda match: match[1] + '\n' + '\n'.join(parts) + '\n' + match[2],
        source, count=1, flags=re.S,
    )
    if count != 1:
        raise ValueError('missing homepage article shell for timeline')
    # Homepage-relative empty links must return home, not reload timeline.html.
    source = re.sub(r'\bhref=(["\'])\1', 'href="./"', source)
    source = re.sub(r'<a\b[^>]*\bhref="\./"[^>]*>',
                    lambda tag: tag[0].replace('md-nav__link--active', '').replace('aria-current="page"', ''), source)
    # Discard both desktop and mobile copies of the homepage-only TOC.
    source = re.sub(r'<label\b[^>]*\bfor="__toc"[^>]*>.*?</label>', '', source, flags=re.S)
    source = source.replace(' md-nav__item--active', '')
    source = without_page_toc(source)
    source = re.sub(
        r'(<a\b[^>]*class="[^"]*md-skip[^"]*"[^>]*>)',
        lambda tag: re.sub(r'\bhref=["\'][^"\']*["\']', 'href="#article-timeline"', tag[0]), source,
    )
    source = re.sub(r'<body\b', '<body data-aik8s-view="timeline"', source, count=1)
    source = TITLE_PATTERN.sub(lambda _: '<title>' + title + ' - ' + escape(SITE_TITLE) + '</title>', source)
    source = re.sub(r'(<div\b[^>]*data-md-component="header-topic"[^>]*>\s*<span\b[^>]*>).*?(</span>)',
                    lambda match: match[1] + title + match[2], source, flags=re.S)
    source = DESCRIPTION_PATTERN.sub(lambda _: meta_tag('description', description, property_attribute='name').strip(), source)
    url = urljoin(site_url, 'timeline.html')
    source = CANONICAL_PATTERN.sub(lambda _: '<link rel="canonical" href="' + escape(url, quote=True) + '">', source)
    # The homepage's adjacent-page links and footer do not describe this collection.
    source = re.sub(r'<link\b[^>]*\brel=["\'](?:prev|next)["\'][^>]*>', '', source)
    source = re.sub(r'<nav\b[^>]*class="[^"]*md-footer__inner[^"]*"[^>]*>.*?</nav>', '', source, flags=re.S)
    source = re.sub(
        r'<(?:a|link)\b[^>]*\bhreflang=["\'][^"\']+["\'][^>]*>',
        lambda tag: re.sub(r'(\bhref=["\'])([^"\']*)(["\'])',
                           lambda match: match[1] + match[2].rstrip('/') + '/timeline.html' + match[3],
                           tag[0]), source,
    )
    label = 'Browse by category' if english else '按分类浏览文章'
    source = re.sub(
        r'<a\b[^>]*\bdata-aik8s-timeline\b[^>]*>.*?</a>',
        lambda _: '<a href="./" class="md-header__button md-icon" data-aik8s-timeline '
        'aria-label="' + label + '" title="' + label + '">'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" aria-hidden="true">'
        '<path d="M3 3h7v7H3zm11 0h7v7h-7zM3 14h7v7H3zm11 0h7v7h-7z"/></svg></a>',
        source, flags=re.S,
    )
    (site_dir / 'timeline.html').write_text(source, encoding='utf-8')
    fallback = datetime.now(timezone.utc)
    return FeedItem(title, description, url,
                    min((item.published for item in ordered), default=fallback),
                    max((item.updated for item in ordered), default=fallback), 'timeline', True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs-dir", type=Path, default=Path("docs"))
    parser.add_argument("--site-dir", type=Path, default=Path("site"))
    parser.add_argument("--site-url", default="https://aik8s.run/")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--language", choices=("zh", "en"), default="zh")
    parser.add_argument("--source-docs-dir", type=Path)
    args = parser.parse_args()

    global SITE_TITLE, SITE_DESCRIPTION, SITE_LANGUAGE
    if args.language == "en":
        SITE_TITLE = "AI/LLM on Kubernetes Infrastructure"
        SITE_DESCRIPTION = "GPUs, data, scheduling, training, inference, RAG, agents, and production operations"
        SITE_LANGUAGE = "en"
    else:
        SITE_TITLE = "AI/LLM on Kubernetes 基础设施"
        SITE_DESCRIPTION = "GPU、大数据、调度、训练、推理、RAG、Agent 与生产运维"
        SITE_LANGUAGE = "zh-CN"

    repo_root = Path.cwd()
    docs_dir = args.docs_dir.resolve()
    site_dir = args.site_dir.resolve()
    if not docs_dir.is_dir() or not site_dir.is_dir():
        parser.error("--docs-dir and --site-dir must exist")
    if args.limit < 1:
        parser.error("--limit must be positive")

    site_url = args.site_url.rstrip("/") + "/"
    items = collect_items(docs_dir, repo_root, site_url, args.source_docs_dir.resolve() if args.source_docs_dir else None)
    if not items:
        parser.error("no feed items found")

    articles = [item for item in items if not item.is_index]
    rss_path = site_dir / "rss.xml"
    write_rss(articles, rss_path, site_url, args.limit)
    write_atom(articles, site_dir / "atom.xml", site_url, args.limit)
    shutil.copyfile(rss_path, site_dir / "feed.xml")
    timeline = write_timeline(articles, site_dir, site_url)
    items = [*items, timeline]
    write_sitemap(items, site_dir / "sitemap.xml")
    items_by_url = {normalize_url(item.url): item for item in items}
    injected = sum(inject_metadata(path, site_url, items_by_url, articles) for path in site_dir.rglob("*.html"))
    print(
        f"Generated RSS/Atom with {min(len(articles), args.limit)} items and Sitemap with "
        f"{len(items)} URLs; enhanced {injected} HTML files"
    )


if __name__ == "__main__":
    main()
