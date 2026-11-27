#!/usr/bin/env python3
"""Package the built bilingual aik8s.run site into a Kiwix-compatible offline ZIM archive."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import html
from html.parser import HTMLParser
import io
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import sys
from urllib.parse import urlsplit, urlunsplit

SKIP_FILES = {
    "sitemap.xml",
    "sitemap.xml.gz",
    "robots.txt",
    "ads.txt",
    "rss.xml",
    "atom.xml",
    "feed.xml",
    "objects.inv",
    "en/sitemap.xml",
    "en/sitemap.xml.gz",
    "en/rss.xml",
    "en/atom.xml",
    "en/feed.xml",
    "en/objects.inv",
}

NO_COMPRESS_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".avif",
    ".ico",
    ".woff",
    ".woff2",
    ".zip",
    ".gz",
    ".br",
    ".mp4",
    ".webm",
    ".pdf",
}

STATIC_QUERY_STRIP_EXTS = {
    ".css",
    ".js",
    ".json",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".avif",
    ".ico",
    ".woff",
    ".woff2",
}

SITE_HOSTS = {"aik8s.run", "www.aik8s.run"}

EXTERNAL_LINK_STRIP_RE = re.compile(
    r"""<link\b[^>]*(?:fonts\.googleapis\.com|fonts\.gstatic\.com)[^>]*>\s*""",
    re.I,
)
PRODUCTION_SCRIPT_STRIP_RE = re.compile(
    r"""<script\b[^>]*(?:googlesyndication\.com|cloudflareinsights\.com)[^>]*>\s*</script>\s*""",
    re.I,
)
TAG_WITH_URL_RE = re.compile(
    r"""<(?P<tag>a|link|script|img|source|iframe|audio|video|object|embed)\b(?P<attrs>[^<>]*?)(?P<close>/?>)""",
    re.I | re.S,
)
ATTR_URL_RE = re.compile(
    r"""(?P<prefix>\b(?:href|src|poster|data)\s*=\s*)(?P<quote>["'])(?P<value>[^"']*)(?P=quote)""",
    re.I,
)
META_REFRESH_RE = re.compile(
    r"""(<meta\b[^>]*http-equiv\s*=\s*["']refresh["'][^>]*content\s*=\s*["']\s*\d+\s*;\s*url=)([^"']+)(["'][^>]*>)""",
    re.I,
)
JS_REDIRECT_RE = re.compile(
    r"""(window\.location\.replace\()(["'])(/[^"']+)(["'])(\s*\+\s*window\.location\.search)""",
)
TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.I | re.S)
ARTICLE_RE = re.compile(r"<article\b[^>]*>(.*?)</article>", re.I | re.S)
ASIDE_RELATED_RE = re.compile(r'<aside\b[^>]*class="[^"]*aik8s-related[^"]*"[^>]*>.*?</aside>', re.I | re.S)


class PlainTextExtractor(HTMLParser):
    """Extract clean visible text from an HTML fragment for ZIM full-text indexing."""

    SKIP_TAGS = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in self.SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._chunks.append(text)

    def get_text(self) -> str:
        return " ".join(self._chunks)


def extract_title_and_text(raw_html: str, fallback_title: str) -> tuple[str, str]:
    title_match = TITLE_RE.search(raw_html)
    title = html.unescape(re.sub(r"\s+", " ", title_match.group(1)).strip()) if title_match else fallback_title
    article_match = ARTICLE_RE.search(raw_html)
    fragment = article_match.group(1) if article_match else raw_html
    fragment = ASIDE_RELATED_RE.sub("", fragment)
    parser = PlainTextExtractor()
    parser.feed(fragment)
    parser.close()
    body_text = re.sub(r"\s+", " ", parser.get_text()).strip()
    return title or fallback_title, body_text


def normalize_target_path(path_part: str, current_dir: str, existing_files: set[str], existing_dirs: set[str]) -> str | None:
    """Resolve an internal site path to a concrete file key in existing_files, or None if not local."""
    if path_part == "":
        candidate = posixpath.join(current_dir, "index.html") if current_dir else "index.html"
        return candidate if candidate in existing_files else None

    if path_part.startswith("/"):
        norm = posixpath.normpath(path_part.lstrip("/"))
    else:
        joined = posixpath.join(current_dir, path_part) if current_dir else path_part
        norm = posixpath.normpath(joined)

    if norm in (".", ""):
        return "index.html" if "index.html" in existing_files else None
    if norm.startswith(".."):
        return None
    if norm in existing_files:
        return norm
    if norm in existing_dirs:
        index_candidate = f"{norm}/index.html"
        if index_candidate in existing_files:
            return index_candidate
    return None


def make_relative(from_file: str, to_file: str) -> str:
    from_dir = posixpath.dirname(from_file)
    if not from_dir:
        return to_file
    return posixpath.relpath(to_file, start=from_dir)


def rewrite_url(
    raw_url: str,
    current_file: str,
    existing_files: set[str],
    existing_dirs: set[str],
) -> str:
    """Rewrite internal absolute/domain/directory URLs into Kiwix-safe relative ZIM paths."""
    value = raw_url.strip()
    if not value or value.startswith(("#", "mailto:", "tel:", "javascript:", "data:", "blob:")):
        return raw_url

    parsed = urlsplit(value)
    path_part = parsed.path
    query = parsed.query
    fragment = parsed.fragment

    if parsed.scheme in ("http", "https"):
        if parsed.netloc.lower() not in SITE_HOSTS:
            return raw_url
        # Internal aik8s.run link: treat path as root-absolute if it exists locally.
        if not path_part:
            path_part = "/"
    elif parsed.scheme or parsed.netloc:
        return raw_url

    current_dir = posixpath.dirname(current_file)
    target = normalize_target_path(path_part, current_dir, existing_files, existing_dirs)
    if target is None:
        return raw_url

    rel = make_relative(current_file, target)
    ext = PurePosixPath(target).suffix.lower()
    if query and ext in STATIC_QUERY_STRIP_EXTS:
        query = ""

    return urlunsplit(("", "", rel, query, fragment))


def rewrite_html_for_zim(
    raw_html: str,
    current_file: str,
    existing_files: set[str],
    existing_dirs: set[str],
) -> str:
    """Clean online-only tags and rewrite links inside an HTML page for offline ZIM viewing."""
    text = EXTERNAL_LINK_STRIP_RE.sub("", raw_html)
    text = PRODUCTION_SCRIPT_STRIP_RE.sub("", text)

    def replace_tag(match: re.Match[str]) -> str:
        tag = match.group("tag")
        attrs = match.group("attrs")
        close = match.group("close")
        # Keep SEO/feed metadata intact on canonical/alternate <link> tags.
        if tag.lower() == "link" and re.search(r"""\brel\s*=\s*["'](?:canonical|alternate|preconnect)["']""", attrs, re.I):
            return match.group(0)

        def replace_attr(attr_match: re.Match[str]) -> str:
            original = html.unescape(attr_match.group("value"))
            updated = rewrite_url(original, current_file, existing_files, existing_dirs)
            if updated == original:
                return attr_match.group(0)
            escaped = html.escape(updated, quote=True)
            return f"{attr_match.group('prefix')}{attr_match.group('quote')}{escaped}{attr_match.group('quote')}"

        new_attrs = ATTR_URL_RE.sub(replace_attr, attrs)
        return f"<{tag}{new_attrs}{close}"

    text = TAG_WITH_URL_RE.sub(replace_tag, text)

    def replace_meta_refresh(match: re.Match[str]) -> str:
        target = rewrite_url(match.group(2), current_file, existing_files, existing_dirs)
        return f"{match.group(1)}{html.escape(target, quote=True)}{match.group(3)}"

    text = META_REFRESH_RE.sub(replace_meta_refresh, text)

    def replace_js_redirect(match: re.Match[str]) -> str:
        target = rewrite_url(match.group(3), current_file, existing_files, existing_dirs)
        return f"{match.group(1)}{match.group(2)}{target}{match.group(4)}{match.group(5)}"

    text = JS_REDIRECT_RE.sub(replace_js_redirect, text)
    return text


def rewrite_search_json(raw_json: str, prefix: str, existing_files: set[str], existing_dirs: set[str]) -> str:
    """Rewrite Zensical search.json directory locations to explicit index.html paths for Kiwix."""
    data = json.loads(raw_json)
    for item in data.get("items", []):
        loc = item.get("location")
        if not isinstance(loc, str):
            continue
        path_part, sep, frag = loc.partition("#")
        if path_part == "":
            new_path = "index.html"
        elif path_part.endswith("/"):
            candidate = posixpath.join(prefix, path_part, "index.html") if prefix else posixpath.join(path_part, "index.html")
            new_path = path_part + "index.html" if candidate in existing_files else path_part
        else:
            candidate_dir = posixpath.join(prefix, path_part) if prefix else path_part
            if candidate_dir in existing_dirs:
                new_path = path_part + "/index.html"
            else:
                new_path = path_part
        item["location"] = f"{new_path}#{frag}" if sep else new_path
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def patch_offline_js(rel_path: str, content: str) -> str:
    """Adjust site JS modules for smooth offline Kiwix usage while preserving interactive features."""
    name = PurePosixPath(rel_path).name
    if name == "engagement.js":
        # Keep calculators and image/Mermaid lightbox; disable online Giscus comments and social share bar.
        content = content.replace(
            "initializeComments(article, policy);",
            "/* disabled in offline ZIM */",
        )
        content = content.replace(
            "initializeShare(article, policy);",
            "/* disabled in offline ZIM */",
        )
    elif name == "agent-explore.js":
        content = content.replace(
            "const base = new URL(english ? '/en/' : '/', window.location.origin);",
            "const base = new URL('./', document.baseURI);",
        )
    elif name == "moments.js":
        # Load the bundled static snapshot directly instead of hitting GitHub APIs offline.
        content = content.replace(
            "const urls=['https://raw.githubusercontent.com/runzhliu/aik8s/moments-data/moments-issues.json?v='+Math.floor(Date.now()/300000),'/assets/data/moments-issues.json'];",
            "const urls=[new URL('../assets/data/moments-issues.json', document.baseURI).href, new URL('assets/data/moments-issues.json', document.baseURI).href];",
        )
        content = content.replace(
            "const res=await fetch(url,{headers:{Accept:'application/vnd.github+json'},signal:AbortSignal.timeout(7000)});",
            "throw new Error('offline zim');",
        )
    return content


def guess_mimetype(path: str) -> str:
    ext = PurePosixPath(path).suffix.lower()
    overrides = {
        ".html": "text/html",
        ".css": "text/css",
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".avif": "image/avif",
        ".gif": "image/gif",
        ".ico": "image/x-icon",
        ".woff2": "font/woff2",
        ".woff": "font/woff",
        ".ttf": "font/ttf",
        ".zip": "application/zip",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".yaml": "text/yaml",
        ".yml": "text/yaml",
        ".xml": "application/xml",
    }
    if ext in overrides:
        return overrides[ext]
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def make_illustration_48(favicon_path: Path) -> bytes:
    """Produce a crisp 48x48 PNG icon for Kiwix library display."""
    from PIL import Image

    with Image.open(favicon_path) as img:
        resized = img.convert("RGBA").resize((48, 48), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


def build_zim(
    site_dir: Path,
    output_path: Path,
    favicon_path: Path,
    *,
    name: str = "aik8s_mul_all",
    title: str = "AI/LLM on Kubernetes 基础设施 (aik8s.run)",
    description: str = "AI/LLM on Kubernetes 基础设施中英文双语离线知识库：GPU、调度、训练、推理、RAG、Agent 与生产实战",
    release_date: str | None = None,
    workers: int = 4,
) -> dict[str, int]:
    from libzim.writer import Compression, Creator, FileProvider, Hint, IndexData, Item, StringProvider

    class ZimIndexData(IndexData):
        def __init__(self, idx_title: str, idx_content: str) -> None:
            super().__init__()
            self._title = idx_title
            self._content = idx_content

        def has_indexdata(self) -> bool:
            return bool(self._title or self._content)

        def get_title(self) -> str:
            return self._title

        def get_content(self) -> str:
            return self._content

        def get_keywords(self) -> str:
            return ""

        def get_wordcount(self) -> int:
            return len(self._content.split())

    class StaticStringItem(Item):
        def __init__(
            self,
            path: str,
            item_title: str,
            mimetype: str,
            content: str | bytes,
            *,
            front_article: bool = False,
            compress: bool = True,
            index_text: str | None = None,
        ) -> None:
            super().__init__()
            self._path = path
            self._title = item_title
            self._mimetype = mimetype
            self._content = content
            self._front_article = front_article
            self._compress = compress
            self._index_text = index_text

        def get_path(self) -> str:
            return self._path

        def get_title(self) -> str:
            return self._title

        def get_mimetype(self) -> str:
            return self._mimetype

        def get_contentprovider(self):
            return StringProvider(self._content)

        def get_hints(self):
            return {
                Hint.FRONT_ARTICLE: self._front_article,
                Hint.COMPRESS: self._compress,
            }

        def get_indexdata(self):
            if self._front_article and self._index_text is not None:
                return ZimIndexData(self._title, self._index_text)
            return None

    class StaticFileItem(Item):
        def __init__(self, path: str, filepath: Path, mimetype: str, compress: bool) -> None:
            super().__init__()
            self._path = path
            self._filepath = filepath
            self._mimetype = mimetype
            self._compress = compress

        def get_path(self) -> str:
            return self._path

        def get_title(self) -> str:
            return ""

        def get_mimetype(self) -> str:
            return self._mimetype

        def get_contentprovider(self):
            return FileProvider(self._filepath)

        def get_hints(self):
            return {
                Hint.FRONT_ARTICLE: False,
                Hint.COMPRESS: self._compress,
            }

    site_dir = site_dir.resolve()
    if not (site_dir / "index.html").is_file():
        raise FileNotFoundError(f"missing site root index.html in {site_dir}")

    all_files: dict[str, Path] = {}
    for file_path in sorted(site_dir.rglob("*")):
        if not file_path.is_file():
            continue
        rel = file_path.relative_to(site_dir).as_posix()
        if rel in SKIP_FILES:
            continue
        all_files[rel] = file_path

    existing_files = set(all_files.keys())
    existing_dirs = {
        posixpath.dirname(rel)
        for rel in existing_files
        if rel.endswith("/index.html")
    }

    # Build SHA-256 index for root binary assets to deduplicate identical copies under en/.
    zh_asset_hashes: dict[str, str] = {}
    for rel, fp in all_files.items():
        if not rel.startswith("en/") and PurePosixPath(rel).suffix.lower() not in {".html", ".json", ".js"}:
            zh_asset_hashes[rel] = hashlib.sha256(fp.read_bytes()).hexdigest()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    creator = (
        Creator(output_path)
        .config_compression(Compression.zstd)
        .config_indexing(True, "zho")
        .config_nbworkers(max(1, workers))
    )

    stats = {
        "html_pages": 0,
        "static_files": 0,
        "dedup_redirects": 0,
        "dir_redirects": 0,
        "dedup_bytes_saved": 0,
    }

    with creator:
        creator.set_mainpath("index.html")
        creator.add_metadata("Name", name)
        creator.add_metadata("Title", title)
        creator.add_metadata("Description", description)
        creator.add_metadata("Language", "zho,eng")
        creator.add_metadata("Creator", "runzhliu")
        creator.add_metadata("Publisher", "aik8s.run")
        creator.add_metadata("Date", release_date or date.today().isoformat())
        creator.add_metadata(
            "Tags",
            "kubernetes;ai;llm;gpu;infrastructure;bilingual;_ftindex:yes;_pictures:yes;_videos:no",
        )
        creator.add_metadata("Scraper", "aik8s/scripts/build_zim.py")

        if favicon_path.is_file():
            creator.add_illustration(make_illustration_48(favicon_path), 48)

        for rel, fp in all_files.items():
            ext = PurePosixPath(rel).suffix.lower()
            mime = guess_mimetype(rel)

            if ext == ".html":
                raw = fp.read_text(encoding="utf-8", errors="replace")
                rewritten = rewrite_html_for_zim(raw, rel, existing_files, existing_dirs)
                is_front = not rel.endswith("404.html")
                page_title, page_text = extract_title_and_text(rewritten, fallback_title=rel)
                creator.add_item(
                    StaticStringItem(
                        rel,
                        page_title if is_front else "",
                        mime,
                        rewritten,
                        front_article=is_front,
                        compress=True,
                        index_text=page_text if is_front else None,
                    )
                )
                stats["html_pages"] += 1
            elif rel in ("search.json", "en/search.json"):
                prefix = "en" if rel.startswith("en/") else ""
                rewritten = rewrite_search_json(fp.read_text(encoding="utf-8"), prefix, existing_files, existing_dirs)
                creator.add_item(
                    StaticStringItem(rel, "", mime, rewritten, front_article=False, compress=True)
                )
                stats["static_files"] += 1
            elif ext == ".js" and PurePosixPath(rel).name in {"engagement.js", "agent-explore.js", "moments.js"}:
                patched = patch_offline_js(rel, fp.read_text(encoding="utf-8"))
                creator.add_item(
                    StaticStringItem(rel, "", mime, patched, front_article=False, compress=True)
                )
                stats["static_files"] += 1
            else:
                # Deduplicate byte-identical assets between root and en/.
                if rel.startswith("en/"):
                    zh_counterpart = rel[3:]
                    if zh_counterpart in zh_asset_hashes:
                        if hashlib.sha256(fp.read_bytes()).hexdigest() == zh_asset_hashes[zh_counterpart]:
                            creator.add_redirection(rel, "", zh_counterpart, {})
                            stats["dedup_redirects"] += 1
                            stats["dedup_bytes_saved"] += fp.stat().st_size
                            continue
                compress = ext not in NO_COMPRESS_EXTS
                creator.add_item(StaticFileItem(rel, fp, mime, compress=compress))
                stats["static_files"] += 1

        # Register directory redirects (dir/ and dir -> dir/index.html) for full Kiwix compatibility.
        for directory in sorted(existing_dirs):
            target = f"{directory}/index.html"
            for alias in (f"{directory}/", directory):
                if alias not in existing_files:
                    creator.add_redirection(alias, "", target, {})
                    stats["dir_redirects"] += 1

    return stats


def verify_zim(zim_path: Path, sample_queries: list[str]) -> None:
    from libzim.reader import Archive
    from libzim.search import Query, Searcher

    archive = Archive(zim_path)
    if not archive.check():
        raise RuntimeError(f"ZIM integrity check failed: {zim_path}")
    if not archive.has_main_entry:
        raise RuntimeError("ZIM is missing main entry")
    if not archive.has_fulltext_index:
        raise RuntimeError("ZIM is missing full-text index")
    if not archive.has_title_index:
        raise RuntimeError("ZIM is missing title index")
    if not archive.has_illustration(48):
        raise RuntimeError("ZIM is missing 48x48 illustration")

    for required in ("index.html", "en/index.html"):
        if not archive.has_entry_by_path(required):
            raise RuntimeError(f"ZIM is missing required entry: {required}")

    # Verify rewritten HTML has no root-absolute <a href="/..."> or internal aik8s.run page links
    # (explicit online-only RSS/Atom feed URLs are allowed to remain absolute).
    bad_links: list[tuple[str, list[str]]] = []
    allowed_online_re = re.compile(r"^https?://aik8s\.run/(?:en/)?(?:rss|atom|feed)\.xml$", re.I)
    for sample in ("index.html", "en/index.html"):
        entry = archive.get_entry_by_path(sample)
        content = bytes(entry.get_item().content).decode("utf-8")
        hits = [
            href
            for href in re.findall(r"""<a\b[^>]*href=["']((?:/|https?://aik8s\.run/)[^"']*)["']""", content, re.I)
            if not allowed_online_re.match(href)
        ]
        if hits:
            bad_links.append((sample, hits[:5]))
    if bad_links:
        raise RuntimeError(f"Found unrewritten root/domain <a> links in ZIM entries: {bad_links}")

    searcher = Searcher(archive)
    for term in sample_queries:
        results = searcher.search(Query().set_query(term))
        if results.get_estimated_matches() < 1:
            raise RuntimeError(f"ZIM full-text search returned 0 hits for '{term}'")

    print(
        f"Verified ZIM OK: {zim_path.name} "
        f"({zim_path.stat().st_size / (1024 * 1024):.1f} MiB, "
        f"articles={archive.article_count}, entries={archive.all_entry_count}, "
        f"main={archive.main_entry.path}, checksum={archive.checksum[:12]}...)",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", type=Path, default=Path("site"))
    parser.add_argument("--output", type=Path, default=Path("dist/aik8s_mul_all.zim"))
    parser.add_argument("--favicon", type=Path, default=Path("docs/assets/brand/favicon.png"))
    parser.add_argument("--name", default="aik8s_mul_all")
    parser.add_argument("--title", default="AI/LLM on Kubernetes 基础设施 (aik8s.run)")
    parser.add_argument(
        "--description",
        default="AI/LLM on Kubernetes 基础设施中英文双语离线知识库：GPU、调度、训练、推理、RAG、Agent 与生产实战",
    )
    parser.add_argument("--date", default=None, help="ISO date YYYY-MM-DD for ZIM Date metadata")
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 2))
    parser.add_argument("--verify", action="store_true", help="Run libzim integrity and search checks after build")
    args = parser.parse_args()

    stats = build_zim(
        args.site_dir,
        args.output,
        args.favicon,
        name=args.name,
        title=args.title,
        description=args.description,
        release_date=args.date,
        workers=args.workers,
    )
    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(
        f"Built ZIM: {args.output} ({size_mb:.1f} MiB) | "
        f"html={stats['html_pages']}, static={stats['static_files']}, "
        f"dedup_redirects={stats['dedup_redirects']} (saved {stats['dedup_bytes_saved'] / (1024 * 1024):.1f} MiB), "
        f"dir_redirects={stats['dir_redirects']}",
        flush=True,
    )
    if args.verify:
        verify_zim(args.output, sample_queries=["Kubernetes", "GPU"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
