"""Standalone discovery regression tests: python3 -m unittest discover -s scripts -p test_article_discovery.py."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from itertools import permutations
import unittest

try:
    from .article_discovery import TAG_LABELS, TYPE_LABELS, infer_discovery, related_items
except ImportError:
    from article_discovery import TAG_LABELS, TYPE_LABELS, infer_discovery, related_items


@dataclass(frozen=True)
class Article:
    url: str
    tags: tuple[str, ...] = ()
    category: str = "practices"
    published: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)
    updated: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)
    is_index: bool = False
    content_type: str = "overview"


class InferenceTests(unittest.TestCase):
    def test_label_contract(self):
        self.assertEqual(set(TYPE_LABELS), {"overview", "tutorial", "benchmark", "troubleshooting"})
        self.assertEqual(set(TAG_LABELS), {
            "kubernetes", "gpu", "inference", "training", "agent", "sandbox",
            "observability", "networking", "storage", "scheduling", "rag", "platform", "security",
        })
        for identifier, labels in (TAG_LABELS | TYPE_LABELS).items():
            self.assertRegex(identifier, r"^[a-z]+$")
            self.assertEqual(len(labels), 2)
            self.assertTrue(all(isinstance(label, str) and label for label in labels))

    def test_translated_metadata_cannot_change_path_tags(self):
        path = "ai-k8s/practices/gpu-topology-fragmentation-scheduling.md"
        chinese = {"title": "GPU 拓扑与调度实践", "description": "Kubernetes 平台上的网络与监控"}
        english = {"title": "GPU topology scheduling", "description": "Training performance"}
        expected = (("gpu", "scheduling"), "tutorial")
        self.assertEqual(infer_discovery(path, chinese), expected)
        self.assertEqual(infer_discovery(path, english), expected)
        self.assertEqual(infer_discovery("en/" + path, english), expected)
        self.assertNotIn("rag", expected[0])  # fragmentation is not RAG

    def test_namespace_is_not_kubernetes_evidence(self):
        self.assertEqual(infer_discovery("ai-k8s/misc.md", {}), ((), "overview"))
        tags, _ = infer_discovery("ai-k8s/inference/engines.md", {})
        self.assertEqual(tags, ("inference",))
        self.assertNotIn("kubernetes", tags)
        self.assertEqual(infer_discovery("ai-k8s/cluster/kubernetes.md", {})[0], ("kubernetes",))

    def test_agent_section_does_not_imply_rag(self):
        tags, _ = infer_discovery('ai-k8s/rag-agent/agent-memory-technology-overview.md', {})
        self.assertIn('agent', tags)
        self.assertNotIn('rag', tags)
        self.assertIn('rag', infer_discovery('ai-k8s/rag-agent/rag-infrastructure.md', {})[0])

    def test_title_and_description_fallback_are_bilingual(self):
        cases = [
            ("Kubernetes GPU inference tutorial", "Kubernetes GPU 推理教程"),
            ("Training scheduling overview", "训练调度概述"),
            ("Agent sandbox security benchmark", "智能体沙箱安全评测"),
            ("Observability networking storage troubleshooting", "可观测性网络存储故障排查"),
            ("RAG platform overview", "检索增强生成平台综述"),
        ]
        for english, chinese in cases:
            for field in ("title", "description"):
                with self.subTest(english=english, field=field):
                    self.assertEqual(infer_discovery("notes/001.md", {field: english}),
                                     infer_discovery("notes/001.md", {field: chinese}))

    def test_all_types_inferred_from_paths(self):
        cases = {
            "overview": "inference/kv-cache-overview.md",
            "tutorial": "guides/gpu-platform-lab.md",
            "benchmark": "practices/inference-engine-benchmark.md",
            "troubleshooting": "practices/nccl-unhandled-cuda-error-host-memory-oom.md",
        }
        for kind, path in cases.items():
            with self.subTest(kind=kind):
                self.assertEqual(infer_discovery(path, {})[1], kind)

    def test_explicit_json_and_csv_replace_inference_in_canonical_order(self):
        for value in ('["security", "agent", "agent"]', "security, agent, agent"):
            self.assertEqual(infer_discovery("inference/gpu.md", {
                "tags": value, "content_type": "troubleshooting",
            }), (("agent", "security"), "troubleshooting"))

    def test_empty_explicit_tags_disable_inference(self):
        for value in ("", "  ", "[]"):
            self.assertEqual(infer_discovery("gpu.md", {"tags": value})[0], ())

    def test_overrides_are_independent(self):
        self.assertEqual(infer_discovery("inference/benchmark.md", {"tags": "storage"}),
                         (("storage",), "benchmark"))
        self.assertEqual(infer_discovery("inference/benchmark.md", {"content_type": "tutorial"}),
                         (("inference",), "tutorial"))

    def test_invalid_tags_fail_clearly(self):
        for value in ("made-up", "GPU", "gpu,", '["gpu", "oops"]', '["gpu", 5]',
                      '["gpu"', '{"gpu": true}', '"gpu"', None, ["gpu"]):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "tags"):
                    infer_discovery("gpu.md", {"tags": value})

    def test_invalid_types_fail_clearly(self):
        for value in ("news", "", "Benchmark", None, ["tutorial"]):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "content_type.*allowed IDs"):
                    infer_discovery("gpu.md", {"content_type": value})

    def test_windows_underscores_and_percent_encoded_paths(self):
        expected = infer_discovery("ai-k8s/practices/gpu-pending.md", {})
        self.assertEqual(infer_discovery(r"ai-k8s\practices\GPU_pending.md", {}), expected)
        self.assertEqual(infer_discovery("ai-k8s/practices/%67pu-pending.md", {}), expected)


class RelatedTests(unittest.TestCase):
    def setUp(self):
        self.item = Article("https://example.org/ai-k8s/practices/current/", ("gpu", "inference"))

    def test_excludes_self_url_aliases_and_index_pages(self):
        alias = replace(self.item, url=self.item.url + "?lang=zh#heading")
        index = replace(self.item, url="https://example.org/ai-k8s/inference/", is_index=True)
        other = replace(self.item, url="https://example.org/ai-k8s/inference/other/")
        self.assertEqual(related_items(self.item, [self.item, alias, index, other]), [other])
        html_alias = replace(self.item, url=self.item.url + "index.html")
        self.assertEqual(related_items(self.item, [html_alias]), [])

    def test_no_unrelated_padding_or_type_only_relevance(self):
        unrelated = Article("https://example.org/ai-k8s/practices/storage/", ("storage",))
        other = Article("https://example.org/misc/unrelated/", (), category="")
        self.assertEqual(related_items(self.item, [unrelated, other]), [])

    def test_shared_tags_outrank_directory_and_type(self):
        source = replace(self.item, url="https://example.org/ai-k8s/inference/current/", category="inference")
        strong = Article("https://example.org/elsewhere/strong/", ("gpu", "inference"), category="other", content_type="tutorial")
        single = Article("https://example.org/elsewhere/single/", ("gpu",), category="other")
        weak = Article("https://example.org/ai-k8s/inference/weak/", ("networking",), category="inference")
        self.assertEqual(related_items(source, [weak, single, strong]), [strong, single, weak])

    def test_same_meaningful_directory_is_weak_evidence(self):
        source = replace(self.item, url="https://example.org/ai-k8s/training/current/", tags=(), category="")
        sibling = Article("https://example.org/ai-k8s/training/other/", (), category="")
        distant = Article("https://example.org/ai-k8s/networking/other/", (), category="")
        self.assertEqual(related_items(source, [distant, sibling]), [sibling])

    def test_deterministic_ties_independent_of_input_order(self):
        articles = [replace(self.item, url=f"https://example.org/ai-k8s/practices/{name}/")
                    for name in ("c", "b", "a")]
        expected = sorted(articles, key=lambda article: article.url)
        for order in permutations(articles):
            self.assertEqual(related_items(self.item, iter(order)), expected)

    def test_recency_uses_update_then_publication(self):
        old = replace(self.item, url="https://example.org/old/")
        published = replace(old, url="https://example.org/published/", published=datetime(2026, 2, 1, tzinfo=timezone.utc))
        updated = replace(old, url="https://example.org/updated/", updated=datetime(2026, 3, 1, tzinfo=timezone.utc))
        self.assertEqual(related_items(self.item, [old, published, updated]), [updated, published, old])

    def test_same_type_is_a_tiebreak_not_a_relevance_signal(self):
        same = replace(self.item, url="https://example.org/z/")
        other = replace(self.item, url="https://example.org/a/", content_type="tutorial")
        self.assertEqual(related_items(self.item, [other, same]), [same, other])

    def test_limit_and_duplicates(self):
        articles = [replace(self.item, url=f"https://example.org/{number}/") for number in range(6)]
        self.assertEqual(related_items(self.item, articles), articles[:4])
        self.assertEqual(related_items(self.item, articles, limit=2), articles[:2])
        self.assertEqual(related_items(self.item, articles, limit=0), [])
        self.assertEqual(related_items(self.item, articles, limit=-1), [])
        self.assertEqual(related_items(self.item, articles[:1] * 3, limit=4), articles[:1])

    def test_naive_datetimes_have_deterministic_utc_interpretation(self):
        aware = replace(self.item, url="https://example.org/b/")
        naive = replace(self.item, url="https://example.org/a/",
                        updated=self.item.updated.replace(tzinfo=None),
                        published=self.item.published.replace(tzinfo=None))
        self.assertEqual(related_items(self.item, [aware, naive]), [naive, aware])


if __name__ == "__main__":
    unittest.main()
