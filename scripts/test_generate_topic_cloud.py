#!/usr/bin/env python3
"""Tests use isolated temporary corpora and never write the real site assets."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import generate_topic_cloud as cloud


class TopicCountsTest(unittest.TestCase):
    def labels(self, text, language=0):
        return {cloud.TOPICS[i][language]: count for i, count in cloud.count_topics(cloud.clean_markdown(text)).items()}

    def test_aliases_boundaries_and_longest_non_overlapping(self):
        counts = self.labels("K8S kubernetes k8sX xK8s_GPU GPU gPUs 大语言模型 大模型 模型 分布式训练 训练")
        self.assertEqual(counts, {"Kubernetes": 2, "GPU": 2, "大模型": 2, "模型": 1, "分布式训练": 1, "训练": 1})
        self.assertEqual(self.labels("smart AGENTS and agent", 1), {"Agent": 2})

    def test_cleaning_visible_prose_only(self):
        markdown = '''---
title: GPU
---
GPU [K8s](https://example.com/GPU_(模型) "GPU")
![GPU](pic-GPU.png) ![GPU][img] <img alt="GPU" src="GPU.png">
`GPU` ``GPU ` GPU``
```yaml
GPU 模型
```
> ~~~
> GPU
> ~~~
    GPU
<!-- GPU --> <code>GPU</code> <pre>GPU</pre> <script>GPU</script>
https://example.com/GPU www.example.com/GPU <https://example.com/GPU>
[img]: https://example.com/GPU.png
'''
        self.assertEqual(self.labels(markdown), {"GPU": 1, "Kubernetes": 1})


class PairedCloudTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "docs").mkdir()
        (self.root / "translations" / "en").mkdir(parents=True)

    def put(self, language, name, text):
        base = self.root / ("docs" if language == "zh" else "translations/en")
        path = base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_paired_exclusions_independence_and_sort(self):
        self.put("zh", "a.md", "GPU GPU K8s 模型")
        self.put("en", "a.md", "model model kubernetes")
        self.put("zh", "sub/b.md", "kubernetes GPU")
        self.put("en", "sub/b.md", "K8S GPU gpu")
        self.put("zh", "empty.md", "无匹配内容")
        self.put("en", "empty.md", "No selected vocabulary here.")
        for name in ("index.md", "sub/README.md", "404.md", "reference/glossary.md", "术语表.md"):
            self.put("zh", name, "GPU " * 10)
            self.put("en", name, "GPU " * 10)
        self.put("zh", "only-zh.md", "GPU " * 10)
        self.put("en", "only-en.md", "GPU " * 10)
        clouds = cloud.build_topic_clouds(self.root)
        self.assertEqual(clouds["zh"], {"article_count": 3, "topics": [
            {"term": "GPU", "count": 3, "article_count": 2},
            {"term": "Kubernetes", "count": 2, "article_count": 2},
            {"term": "模型", "count": 1, "article_count": 1},
        ]})
        self.assertEqual(clouds["en"], {"article_count": 3, "topics": [
            {"term": "GPU", "count": 2, "article_count": 1},
            {"term": "Kubernetes", "count": 2, "article_count": 2},
            {"term": "Model", "count": 2, "article_count": 1},
        ]})

    def test_cli_output_is_deterministic_and_limited(self):
        self.put("zh", "a.md", " ".join(row[2][0] for row in cloud.TOPICS))
        self.put("en", "a.md", " ".join(row[2][0] for row in cloud.TOPICS))
        output = self.root / "out"
        command = [sys.executable, str(Path(cloud.__file__).resolve()), "--root", str(self.root), "--output-dir", str(output)]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        subprocess.run(command, check=True, capture_output=True, env=env)
        first = {lang: (output / f"topic-cloud-{lang}.json").read_bytes() for lang in ("zh", "en")}
        subprocess.run(command, check=True, capture_output=True, env=env)
        for lang in ("zh", "en"):
            self.assertEqual(first[lang], (output / f"topic-cloud-{lang}.json").read_bytes())
            data = json.loads(first[lang])
            self.assertEqual(data["article_count"], 1)
            self.assertEqual(len(data["topics"]), 50)
            self.assertTrue(all(topic["count"] > 0 for topic in data["topics"]))
            self.assertEqual(data["topics"], sorted(data["topics"], key=lambda t: (-t["count"], t["term"])))

    def test_missing_corpus_fails(self):
        with self.assertRaises(ValueError):
            cloud.build_topic_clouds(self.root / "missing")


if __name__ == "__main__":
    unittest.main()
