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
    def test_english_metadata_uses_source_history_and_english_dates(self):
        from datetime import datetime, timezone
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            docs, original, site = root / 'en', root / 'docs', root / 'site'
            docs.mkdir()
            original.mkdir()
            site.mkdir()
            (docs / 'article.md').write_text('# A translated article\n\nAn explanation.\n')
            (original / 'article.md').write_text('# 中文原文\n\n解释。\n')
            published = datetime(2026, 8, 1, tzinfo=timezone.utc)
            updated = datetime(2026, 10, 1, tzinfo=timezone.utc)
            history = {'docs/article.md': [published, updated]}
            with patch.object(build_distribution, 'load_git_history', return_value=history) as loader:
                items = build_distribution.collect_items(docs, root, 'https://example.org/en/', original)
                loader.assert_called_once_with(root, original)
            self.assertEqual(items[0].url, 'https://example.org/en/article/')
            self.assertEqual(items[0].published, published)
            self.assertEqual(items[0].updated, updated)
            with patch.object(build_distribution, 'SITE_LANGUAGE', 'en'):
                result = build_distribution.inject_article_dates('<article><h1>A translated article</h1></article>', items[0])
                self.assertIn('Published', result)
                self.assertIn('Updated', result)
                self.assertNotIn('创建于', result)

    def test_feeds_only_contain_articles_and_sitemap_keeps_section_indexes(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            docs = root / "docs"
            site = root / "site"
            site.mkdir()
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
            })
            self.assertTrue((docs / "assets/rag-agent/recovery/README.md").exists())


if __name__ == "__main__":
    unittest.main()
