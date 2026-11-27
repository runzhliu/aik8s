#!/usr/bin/env python3
"""Unit and integration tests for scripts/build_zim.py."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_zim


HAS_LIBZIM = importlib.util.find_spec("libzim") is not None and importlib.util.find_spec("PIL") is not None


class RewriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.files = {
            "index.html",
            "timeline.html",
            "en/index.html",
            "ai-k8s/practices/demo/index.html",
            "en/ai-k8s/practices/demo/index.html",
            "assets/brand/favicon.png",
            "stylesheets/engagement.css",
        }
        self.dirs = {
            "en",
            "ai-k8s/practices/demo",
            "en/ai-k8s/practices/demo",
        }

    def test_rewrite_root_domain_directory_and_query(self) -> None:
        raw = (
            '<html><head>'
            '<link rel="canonical" href="https://aik8s.run/ai-k8s/practices/demo/">'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Inter">'
            '<link rel="stylesheet" href="../../../stylesheets/engagement.css?v=12345">'
            '<script src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js"></script>'
            '</head><body>'
            '<a href="/">Home</a>'
            '<a href="/en/">EN</a>'
            '<a href="https://aik8s.run/timeline.html?sort=updated">Timeline</a>'
            '<a href="https://aik8s.run/ai-k8s/practices/demo/#sec1">Related</a>'
            '<a href="https://example.com/out">External</a>'
            '</body></html>'
        )
        out = build_zim.rewrite_html_for_zim(raw, "ai-k8s/practices/demo/index.html", self.files, self.dirs)
        self.assertNotIn("fonts.googleapis.com", out)
        self.assertNotIn("fonts.gstatic.com", out)
        self.assertNotIn("googlesyndication.com", out)
        # Canonical link stays untouched.
        self.assertIn('rel="canonical" href="https://aik8s.run/ai-k8s/practices/demo/"', out)
        # Static asset query string stripped.
        self.assertIn('href="../../../stylesheets/engagement.css"', out)
        # Root-abs and domain links rewritten to relative explicit index.html paths.
        self.assertIn('href="../../../index.html"', out)
        self.assertIn('href="../../../en/index.html"', out)
        self.assertIn('href="../../../timeline.html?sort=updated"', out)
        self.assertIn('href="index.html#sec1"', out)
        # External link preserved.
        self.assertIn('href="https://example.com/out"', out)

    def test_rewrite_search_json(self) -> None:
        raw = json.dumps(
            {
                "items": [
                    {"location": "", "title": "Home"},
                    {"location": "#top", "title": "Top"},
                    {"location": "ai-k8s/practices/demo/", "title": "Demo"},
                    {"location": "ai-k8s/practices/demo/#sec1", "title": "Sec1"},
                ]
            }
        )
        out = json.loads(build_zim.rewrite_search_json(raw, "", self.files, self.dirs))
        locs = [item["location"] for item in out["items"]]
        self.assertEqual(
            locs,
            [
                "index.html",
                "index.html#top",
                "ai-k8s/practices/demo/index.html",
                "ai-k8s/practices/demo/index.html#sec1",
            ],
        )


@unittest.skipUnless(HAS_LIBZIM, "libzim and Pillow are required for ZIM archive integration tests")
class BuildZimIntegrationTests(unittest.TestCase):
    def test_end_to_end_zim_archive(self) -> None:
        from PIL import Image
        from libzim.reader import Archive

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = root / "site"
            (site / "en" / "assets").mkdir(parents=True)
            (site / "assets").mkdir(parents=True)
            (site / "ai-k8s" / "demo").mkdir(parents=True)
            (site / "en" / "ai-k8s" / "demo").mkdir(parents=True)

            favicon = root / "favicon.png"
            Image.new("RGBA", (64, 64), (45, 106, 86, 255)).save(favicon)
            shared_png = favicon.read_bytes()
            (site / "assets" / "shared.png").write_bytes(shared_png)
            (site / "en" / "assets" / "shared.png").write_bytes(shared_png)

            (site / "index.html").write_text(
                '<html><head><title>AI/LLM on Kubernetes 首页</title></head>'
                '<body><article><h1>GPU 集群调度</h1><a href="/en/">English</a>'
                '<a href="ai-k8s/demo/">Demo</a><img src="assets/shared.png"></article></body></html>',
                encoding="utf-8",
            )
            (site / "en" / "index.html").write_text(
                '<html><head><title>AI/LLM on Kubernetes Home</title></head>'
                '<body><article><h1>GPU Cluster Scheduling</h1><a href="/">中文</a>'
                '<a href="ai-k8s/demo/">Demo</a><img src="assets/shared.png"></article></body></html>',
                encoding="utf-8",
            )
            (site / "ai-k8s" / "demo" / "index.html").write_text(
                '<html><head><title>GPU 实战</title></head>'
                '<body><article><h1>低利用率 GPU 治理</h1><a href="https://aik8s.run/">返回</a></article></body></html>',
                encoding="utf-8",
            )
            (site / "en" / "ai-k8s" / "demo" / "index.html").write_text(
                '<html><head><title>GPU Practice</title></head>'
                '<body><article><h1>Low Utilization GPU Governance</h1><a href="https://aik8s.run/en/">Back</a></article></body></html>',
                encoding="utf-8",
            )

            out_zim = root / "test.zim"
            stats = build_zim.build_zim(site, out_zim, favicon, workers=1)
            self.assertEqual(stats["html_pages"], 4)
            self.assertEqual(stats["dedup_redirects"], 1)
            build_zim.verify_zim(out_zim, sample_queries=["Kubernetes", "GPU", "低利用率"])

            archive = Archive(out_zim)
            # Directory redirect resolves cleanly.
            self.assertEqual(archive.get_entry_by_path("ai-k8s/demo/").get_redirect_entry().path, "ai-k8s/demo/index.html")
            # Deduplicated English asset resolves cleanly to root asset.
            self.assertEqual(archive.get_entry_by_path("en/assets/shared.png").get_redirect_entry().path, "assets/shared.png")


if __name__ == "__main__":
    unittest.main()
