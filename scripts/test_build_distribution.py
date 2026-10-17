"""Regression coverage for non-article pages leaking into public feeds."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import build_distribution


class DistributionTests(unittest.TestCase):
    def test_timeline_is_complete_localized_escaped_and_sorted_by_publication(self):
        from datetime import datetime, timezone
        timestamp = lambda day: datetime(2026, 9, day, 20, tzinfo=timezone.utc)
        articles = [
            build_distribution.FeedItem('Old <article>', 'A & B', 'https://example.org/old/',
                                        timestamp(1), timestamp(25), 'test', False),
            build_distribution.FeedItem('New article', 'Latest publication', 'https://example.org/new/',
                                        timestamp(3), timestamp(3), 'test', False),
        ]
        shell = ('<html><head><title>Home</title><meta name="description" content="Home">'
                 '<link rel="canonical" href="https://example.org/en/">'
                 '<link rel="alternate" hreflang="en" href="https://example.org/en/">'
                 '<link rel="next" href="article/">'
                 '</head><body><a href="" class="md-nav__link md-nav__link--active">Home</a>'
                 '<a href="#old-home-heading" class="md-skip">Skip to content</a>'
                 '<label class="md-nav__link md-nav__link--active" for="__toc">Old TOC toggle</label>'
                 '<nav class="md-nav md-nav--secondary"><a href="#old-toc">Old TOC</a>'
                 '<nav class="md-nav"><a href="#nested">Nested</a></nav>'
                 '<a href="#after-nested">After nested nav</a></nav>'
                 '<a href="timeline.html" data-aik8s-timeline title="Timeline">icon</a>'
                 '<a href="/" hreflang="zh">中文</a><a href="/en/" hreflang="en">English</a>'
                 '<article class="md-content__inner"><h1>Home</h1><p>Old homepage</p></article>'
                 '<script src="assets/app.js"></script></body></html>')
        with TemporaryDirectory() as temporary:
            site = Path(temporary)
            (site / 'index.html').write_text(shell)
            for language in ('zh-CN', 'en'):
                with self.subTest(language=language), patch.object(build_distribution, 'SITE_LANGUAGE', language):
                    url = 'https://example.org/en/' if language == 'en' else 'https://example.org/'
                    item = build_distribution.write_timeline(articles, site, url)
                    output = (site / 'timeline.html').read_text()
                    self.assertTrue(item.is_index)
                    self.assertEqual(item.url, url + 'timeline.html')
                    self.assertLess(output.index('New article'), output.index('Old &lt;article&gt;'))
                    self.assertIn('A &amp; B', output)
                    self.assertIn('2026-09-04</time>', output)  # Asia/Shanghai, not UTC
                    self.assertIn('hreflang="en" href="https://example.org/en/timeline.html"', output)
                    self.assertIn('href="/en/timeline.html" hreflang="en"', output)
                    self.assertIn('href="/timeline.html" hreflang="zh"', output)
                    self.assertIn('href="./"', output)
                    self.assertIn('assets/app.js', output)
                    self.assertNotIn('Old homepage', output)
                    self.assertNotIn('href=""', output)
                    self.assertNotIn('md-nav__link--active', output)
                    self.assertNotIn('old-toc', output)
                    self.assertNotIn('#nested', output)
                    self.assertNotIn('#after-nested', output)
                    self.assertNotIn('old-home-heading', output)
                    self.assertIn('href="#article-timeline"', output)
                    self.assertIn('id="article-timeline"', output)
                    self.assertNotIn('rel="next"', output)
                    self.assertIn('Browse by category' if language == 'en' else '按分类浏览文章', output)
                    build_distribution.inject_metadata(site / 'timeline.html', url, {build_distribution.normalize_url(item.url): item})
                    enhanced = (site / 'timeline.html').read_text()
                    self.assertIn('CollectionPage', enhanced)
                    self.assertNotIn('TechArticle', enhanced)
                    self.assertNotIn('AIK8S article dates', enhanced)

    def test_english_metadata_uses_source_history_and_english_dates(self):
        from datetime import datetime, timezone
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            docs, original, site = root / 'en', root / 'docs', root / 'site'
            docs.mkdir()
            original.mkdir()
            site.mkdir()
            (docs / 'article.md').write_text('# A translated article\n\nAn explanation.\n')
            (original / 'article.md').write_text('---\ntags: ["gpu", "inference"]\ncontent_type: benchmark\n---\n# 中文原文\n\n解释。\n')
            published = datetime(2026, 8, 1, tzinfo=timezone.utc)
            updated = datetime(2026, 10, 1, tzinfo=timezone.utc)
            history = {'docs/article.md': [published, updated]}
            with patch.object(build_distribution, 'load_git_history', return_value=history) as loader:
                items = build_distribution.collect_items(docs, root, 'https://example.org/en/', original)
                loader.assert_called_once_with(root, original)
            self.assertEqual(items[0].url, 'https://example.org/en/article/')
            self.assertEqual(items[0].published, published)
            self.assertEqual(items[0].updated, updated)
            self.assertEqual(set(items[0].tags), {'gpu', 'inference'})
            self.assertEqual(items[0].content_type, 'benchmark')
            with patch.object(build_distribution, 'SITE_LANGUAGE', 'en'):
                result = build_distribution.inject_article_dates('<article><h1>A translated article</h1></article>', items[0])
                self.assertIn('Published', result)
                self.assertIn('Updated', result)
                self.assertNotIn('创建于', result)

    def test_article_discovery_is_static_localized_and_idempotent(self):
        from datetime import datetime, timezone
        timestamp = datetime(2026, 10, 1, tzinfo=timezone.utc)
        item = build_distribution.FeedItem('Main', 'Summary', 'https://example.org/en/main/', timestamp, timestamp, 'inference', False, ('inference',), 'overview')
        candidate = build_distribution.FeedItem('Related <article>', 'A & B', 'https://example.org/en/related/', timestamp, timestamp, 'inference', False, ('inference',), 'tutorial')
        shell = '<article><h1>Main</h1><p>Original article</p></article>'
        with patch.object(build_distribution, 'SITE_LANGUAGE', 'en'):
            output = build_distribution.inject_article_discovery(shell, item, [item, candidate], 'https://example.org/en/')
            self.assertIn('Related articles', output)
            self.assertIn('Related &lt;article&gt;', output)
            self.assertIn('A &amp; B', output)
            self.assertIn('href="https://example.org/en/timeline.html?tag=inference"', output)
            self.assertIn('href="https://example.org/en/related/"', output)
            repeated = build_distribution.inject_article_discovery(output, item, [item, candidate], 'https://example.org/en/')
            self.assertEqual(repeated.count('class="aik8s-related"'), 1)
            self.assertEqual(repeated.count('class="aik8s-article-tags"'), 1)
            self.assertNotIn('<h2', repeated)  # Do not disrupt bilingual authored-heading pairing.
            index = build_distribution.FeedItem('Index', 'Overview', 'https://example.org/en/', timestamp, timestamp, 'index', True)
            self.assertEqual(build_distribution.inject_article_discovery(shell, index, [candidate], 'https://example.org/en/'), shell)
            self.assertNotIn('aik8s-related', build_distribution.inject_article_discovery(shell, item, [item], 'https://example.org/en/'))

    def test_discovery_assets_use_content_versions_and_keep_relative_links(self):
        import hashlib
        with TemporaryDirectory() as temporary:
            site = Path(temporary)
            (site / 'stylesheets').mkdir()
            (site / 'javascripts').mkdir()
            css = site / 'stylesheets/timeline.css'
            css.write_text('first version')
            (site / 'javascripts/timeline.js').write_text('/* script */')
            page = site / 'index.html'
            page.write_text('<link href="../stylesheets/timeline.css?v=old">'
                            '<script src="javascripts/timeline.js"></script><link href="other.css">')
            build_distribution.version_discovery_assets(site)
            first = page.read_text()
            version = hashlib.sha256(css.read_bytes()).hexdigest()[:12]
            self.assertIn('../stylesheets/timeline.css?v=' + version, first)
            self.assertRegex(first, r'javascripts/timeline\.js\?v=[a-f0-9]{12}')
            self.assertIn('href="other.css"', first)
            build_distribution.version_discovery_assets(site)
            self.assertEqual(first, page.read_text())
            css.write_text('second version')
            build_distribution.version_discovery_assets(site)
            self.assertNotEqual(first, page.read_text())
            self.assertNotIn('?v=' + version, page.read_text())

    def test_feeds_only_contain_articles_and_sitemap_keeps_section_indexes(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            docs = root / "docs"
            site = root / "site"
            site.mkdir()
            (site / 'index.html').write_text('<html><head><title>Home</title>'
                                             '<link rel="canonical" href="https://example.org/">'
                                             '</head><body><article><h1>Home</h1></article></body></html>')
            fixtures = {
                "index.md": ("Home", "Site overview"),
                "ai-k8s/rag-agent/index.md": ("Agents", "Section overview"),
                "ai-k8s/rag-agent/recovery.md": ("Agent recovery", "A public article"),
                "assets/rag-agent/recovery/README.md": ("Recovery diagrams", "Image provenance"),
                "assets/rag-agent/recovery/notes.md": ("Drawing notes", "Asset documentation"),
                "ai-k8s/rag-agent/README.md": ("Editor notes", "Not an article"),
            }
            for name, (title, description) in fixtures.items():
                path = docs / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"# {title}\n\n{description}\n", encoding="utf-8")
            (docs / 'ai-k8s/rag-agent/old.md').write_text(
                '---\ntitle: Old address\ndescription: Article moved\n'
                'redirect_to: /ai-k8s/rag-agent/recovery/\n---\n\n# Article moved\n')

            arguments = [
                "build_distribution.py", "--docs-dir", str(docs),
                "--site-dir", str(site), "--site-url", "https://example.org/",
            ]
            with patch("sys.argv", arguments), patch.object(Path, "cwd", return_value=root), \
                    patch.object(build_distribution, "load_git_history", return_value={}), \
                    redirect_stdout(StringIO()):
                build_distribution.main()

            expected = "https://example.org/ai-k8s/rag-agent/recovery/"
            for name in ("rss.xml", "feed.xml"):
                entries = ET.parse(site / name).findall("./channel/item")
                self.assertEqual([entry.findtext("link") for entry in entries], [expected])
                self.assertEqual([entry.findtext("title") for entry in entries], ["Agent recovery"])
            atom = {"a": "http://www.w3.org/2005/Atom"}
            entries = ET.parse(site / "atom.xml").findall("a:entry", atom)
            self.assertEqual([entry.findtext("a:id", namespaces=atom) for entry in entries], [expected])
            sitemap = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
            urls = ET.parse(site / "sitemap.xml").findall("s:url/s:loc", sitemap)
            self.assertEqual({entry.text for entry in urls}, {
                "https://example.org/", "https://example.org/ai-k8s/rag-agent/", expected,
                "https://example.org/timeline.html",
            })
            self.assertTrue((docs / "assets/rag-agent/recovery/README.md").exists())


if __name__ == "__main__":
    unittest.main()
