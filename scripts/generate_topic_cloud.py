#!/usr/bin/env python3
"""Generate independent bilingual topic clouds from paired Markdown articles.

This uses a deliberately curated technical vocabulary, NOT general-purpose word
segmentation. Aliases share a topic, including across languages; the display
labels are localized. At each position the longest non-overlapping alias wins;
ASCII aliases use ASCII word boundaries and matching is case-insensitive.
Counts are unweighted occurrences in cleaned Markdown prose. Article counts
include paired articles with no matches. Sorting is by descending count, then
Unicode label; only the first 50 topics with actual matches are emitted.

Run: python3 scripts/generate_topic_cloud.py [--root ROOT] [--output-dir DIR]
ROOT contains docs/ and translations/en/; the default output is ROOT/docs/assets.
The Markdown cleaner is intentionally lightweight, not a full Markdown parser.
"""

from __future__ import annotations

import argparse
from collections import Counter
import html
import json
from pathlib import Path
import re

# (Chinese label, English label, equivalent surface forms). Proper names and
# established acronyms are intentionally unchanged in both languages.
TOPICS = (
    ("Kubernetes", "Kubernetes", ("Kubernetes", "K8s")),
    ("GPU", "GPU", ("GPU", "GPUs", "图形处理器", "显卡")),
    ("CPU", "CPU", ("CPU", "CPUs")),
    ("大模型", "Large language model", ("大语言模型", "大型语言模型", "大模型", "large language models", "large language model", "LLMs", "LLM")),
    ("模型", "Model", ("模型", "models", "model")),
    ("智能体", "Agent", ("智能体", "agents", "agent", "agentic")),
    ("多智能体", "Multi-agent", ("多智能体", "multi-agent", "multi agent")),
    ("推理", "Inference", ("推理", "inference", "inferencing")),
    ("训练", "Training", ("训练", "training")),
    ("分布式训练", "Distributed training", ("分布式训练", "distributed training")),
    ("微调", "Fine-tuning", ("微调", "fine-tuning", "fine tuning", "finetuning")),
    ("集群", "Cluster", ("集群", "clusters", "cluster")),
    ("部署", "Deployment", ("部署", "deployments", "deployment", "deploy")),
    ("服务", "Serving", ("服务", "serving")),
    ("平台", "Platform", ("平台", "platforms", "platform")),
    ("容器", "Container", ("容器", "containers", "container")),
    ("调度", "Scheduling", ("调度器", "调度", "schedulers", "scheduler", "scheduling")),
    ("性能", "Performance", ("性能", "performance")),
    ("网络", "Networking", ("网络", "networking", "networks", "network")),
    ("存储", "Storage", ("存储", "storage")),
    ("安全", "Security", ("安全", "security")),
    ("节点", "Node", ("节点", "nodes", "node")),
    ("监控", "Monitoring", ("监控", "monitoring")),
    ("缓存", "Cache", ("缓存", "caches", "cache")),
    ("数据", "Data", ("数据", "data")),
    ("大数据", "Big data", ("大数据", "big data")),
    ("故障恢复", "Failure recovery", ("故障恢复", "failure recovery", "fault recovery")),
    ("可观测性", "Observability", ("可观测性", "可观测", "observability")),
    ("分布式", "Distributed", ("分布式", "distributed")),
    ("沙箱", "Sandbox", ("沙箱", "sandboxes", "sandbox")),
    ("多租户", "Multi-tenancy", ("多租户", "multi-tenancy", "multitenancy", "multi-tenant")),
    ("工作负载", "Workload", ("工作负载", "workloads", "workload")),
    ("延迟", "Latency", ("延迟", "latency")),
    ("吞吐量", "Throughput", ("吞吐量", "吞吐", "throughput")),
    ("可靠性", "Reliability", ("可靠性", "reliability")),
    ("成本", "Cost", ("成本", "costs", "cost")),
    ("网关", "Gateway", ("网关", "gateways", "gateway")),
    ("键值缓存", "KV Cache", ("键值缓存", "KV 缓存", "KV cache", "KV-cache", "KV_cache")),
    ("检查点", "Checkpoint", ("检查点", "checkpoints", "checkpoint", "checkpointing")),
    ("多模态", "Multimodal", ("多模态", "multi-modal", "multimodal")),
    ("日志", "Logs", ("日志", "logging", "logs", "log")),
    ("基准测试", "Benchmark", ("基准测试", "benchmarks", "benchmarking", "benchmark")),
    ("微服务", "Microservices", ("微服务", "microservices", "microservice")),
    ("负载均衡", "Load balancing", ("负载均衡", "load balancing", "load balancer")),
    ("高可用", "High availability", ("高可用", "high availability")),
    ("弹性伸缩", "Autoscaling", ("弹性伸缩", "自动扩缩容", "扩缩容", "autoscaling", "auto-scaling")),
    ("量化", "Quantization", ("量化", "quantization")),
    ("词元", "Token", ("词元", "tokens", "token")),
    ("API 服务器", "API Server", ("API 服务器", "API server", "apiserver")),
    ("张量并行", "Tensor parallelism", ("张量并行", "tensor parallelism", "tensor parallel")),
    ("数据并行", "Data parallelism", ("数据并行", "data parallelism", "data parallel")),
    ("注意力", "Attention", ("注意力机制", "注意力", "attention")),
    ("向量数据库", "Vector database", ("向量数据库", "vector databases", "vector database")),
    ("RAG", "RAG", ("RAG", "检索增强生成", "retrieval-augmented generation", "retrieval augmented generation")),
    ("API", "API", ("API", "APIs")),
    *((name, name, aliases) for name, aliases in (
        ("vLLM", ("vLLM",)), ("SGLang", ("SGLang",)), ("DeepSeek", ("DeepSeek", "深度求索")),
        ("OpenClaw", ("OpenClaw",)), ("RDMA", ("RDMA",)), ("Ray", ("Ray",)),
        ("NVIDIA", ("NVIDIA", "英伟达")), ("Prometheus", ("Prometheus",)),
        ("Grafana", ("Grafana",)), ("OpenTelemetry", ("OpenTelemetry", "OTel")),
        ("Docker", ("Docker",)), ("KubeRay", ("KubeRay",)), ("Kueue", ("Kueue",)),
        ("Volcano", ("Volcano",)), ("SFT", ("SFT", "监督微调", "supervised fine-tuning")),
        ("LoRA", ("LoRA", "low-rank adaptation")), ("Python", ("Python",)),
        ("Qwen", ("Qwen", "通义千问")), ("PyTorch", ("PyTorch",)), ("AIBrix", ("AIBrix",)),
        ("Higress", ("Higress",)), ("AI", ("AI",)), ("HTTP", ("HTTP",)),
        ("Linux", ("Linux",)), ("YAML", ("YAML",)), ("CUDA", ("CUDA",)),
        ("MCP", ("MCP", "Model Context Protocol")), ("Istio", ("Istio",)),
        ("Cilium", ("Cilium",)), ("eBPF", ("eBPF",)), ("Ceph", ("Ceph",)),
    )),
)


def _compile_topics():
    aliases = {}
    for index, (_, _, variants) in enumerate(TOPICS):
        for variant in variants:
            key = variant.casefold()
            if key in aliases and aliases[key] != index:
                raise ValueError(f"Ambiguous topic alias: {variant}")
            aliases[key] = index
    # Factor shared boundaries outside each alternation. This avoids repeated
    # lookarounds at every character, without expensive named capture groups.
    groups = {}
    for alias in sorted(aliases, key=lambda value: (-len(value), value)):
        left = alias[0].isascii() and alias[0].isalnum()
        right = alias[-1].isascii() and alias[-1].isalnum()
        groups.setdefault(left, []).append(re.escape(alias) + (r"(?![a-z0-9_])" if right else ""))
    patterns = []
    for left, variants in groups.items():
        patterns.append((r"(?<![a-z0-9_])" if left else "") + "(?:" + "|".join(variants) + ")")
    return re.compile("|".join(patterns), re.IGNORECASE | re.ASCII), aliases


_TOPIC_PATTERN, _ALIASES = _compile_topics()


def _remove_fences_and_indented_code(text: str) -> str:
    output = []
    fence_char = ""
    fence_length = 0
    for line in text.splitlines(keepends=True):
        # Fences in quotes/list nesting are common in this corpus.
        candidate = re.sub(r"^[ \t]*(?:>[ \t]*)*", "", line)
        marker = re.match(r"(`{3,}|~{3,})(.*)", candidate)
        if fence_char:
            if marker and marker[1][0] == fence_char and len(marker[1]) >= fence_length and not marker[2].strip():
                fence_char = ""
            output.append("\n")
        elif marker:
            fence_char, fence_length = marker[1][0], len(marker[1])
            output.append("\n")
        elif line.startswith(("    ", "\t")):
            output.append("\n")
        else:
            output.append(line)
    return "".join(output)


def _remove_inline_code(text: str) -> str:
    output = []
    position = 0
    while match := re.search(r"`+", text[position:]):
        start, end = position + match.start(), position + match.end()
        output.append(text[position:start])
        closing = re.search(r"(?<!`)`{" + str(end - start) + r"}(?!`)", text[end:])
        if closing:
            output.append(" ")
            position = end + closing.end()
        else:
            output.append(text[start:end])
            position = end
    output.append(text[position:])
    return "".join(output)


def _balanced_end(text: str, start: int, opening: str, closing: str) -> int | None:
    depth = 0
    pos = start
    while pos < len(text):
        char = text[pos]
        if char == "\\":
            pos += 2
            continue
        if opening == "(" and char == "<":
            end = text.find(">", pos + 1)
            if end != -1:
                pos = end + 1
                continue
        if opening == "(" and char in "\"'" and pos > start and text[pos - 1].isspace():
            quote = char
            pos += 1
            while pos < len(text):
                if text[pos] == "\\":
                    pos += 2
                elif text[pos] == quote:
                    pos += 1
                    break
                else:
                    pos += 1
            continue
        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if not depth:
                return pos + 1
        pos += 1
    return None


def _remove_links_and_images(text: str) -> str:
    output = []
    pos = 0
    while pos < len(text):
        image = text.startswith("![", pos)
        start = pos + 1 if image else pos
        if text[start:start + 1] != "[":
            output.append(text[pos])
            pos += 1
            continue
        end = _balanced_end(text, start, "[", "]")
        if end is None:
            output.append(text[pos])
            pos += 1
            continue
        target_end = None
        if text[end:end + 1] == "(":
            target_end = _balanced_end(text, end, "(", ")")
        elif text[end:end + 1] == "[":
            target_end = _balanced_end(text, end, "[", "]")
        output.append(" " if image else _remove_links_and_images(text[start + 1:end - 1]))
        pos = target_end or end
    return "".join(output)


def clean_markdown(markdown: str) -> str:
    """Retain visible prose; strip metadata, code, destinations and images."""
    text = markdown.lstrip("\ufeff")
    text = re.sub(r"\A---[ \t]*\r?\n[\s\S]*?^(?:---|\.\.\.)[ \t]*(?:\r?\n|$)", " ", text, count=1, flags=re.M)
    text = _remove_fences_and_indented_code(text)
    text = _remove_inline_code(text)
    text = re.sub(r"<!--[\s\S]*?(?:-->|\Z)", " ", text)
    text = re.sub(r"<(script|style|pre|code)\b[^>]*>[\s\S]*?</\1\s*>", " ", text, flags=re.I)
    text = re.sub(r"(?m)^[ \t]{0,3}\[[^\]\n]+\]:[^\n]*(?:\n[ \t]+[^\n]+)*", " ", text)
    text = _remove_links_and_images(text)
    text = re.sub(r"<[^>]*>", " ", text)
    text = html.unescape(text)
    return re.sub(r"(?i)\b(?:https?://|ftp://|www\.|mailto:)[^\s<>\"']+", " ", text)


def count_topics(text: str) -> Counter[int]:
    """Count topic IDs in already-cleaned prose."""
    return Counter(_ALIASES[match[0].casefold()] for match in _TOPIC_PATTERN.finditer(text))


def paired_articles(root: Path) -> list[Path]:
    """Pair by identical path relative to the two language roots."""
    docs, english = root / "docs", root / "translations" / "en"
    for directory in (docs, english):
        if not directory.is_dir():
            raise ValueError(f"Missing article directory: {directory}")
    paths = []
    for path in docs.rglob("*.md"):
        relative = path.relative_to(docs)
        if path.stem.casefold() in {"index", "readme", "404", "glossary", "术语表"}:
            continue
        if (english / relative).is_file():
            paths.append(relative)
    return sorted(paths, key=lambda path: path.as_posix())


def build_topic_clouds(root: Path) -> dict[str, dict]:
    """Return JSON-ready language clouds, without writing any files."""
    root = Path(root)
    paths = paired_articles(root)
    result = {}
    for language, directory, label in (("zh", root / "docs", 0), ("en", root / "translations" / "en", 1)):
        totals, articles = Counter(), Counter()
        for path in paths:
            counts = count_topics(clean_markdown((directory / path).read_text(encoding="utf-8")))
            totals.update(counts)
            articles.update(counts.keys())
        topics = [{"term": TOPICS[index][label], "count": count, "article_count": articles[index]}
                  for index, count in totals.items()]
        topics.sort(key=lambda topic: (-topic["count"], topic["term"]))
        result[language] = {"article_count": len(paths), "topics": topics[:50]}
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="repository root containing docs and translations/en")
    parser.add_argument("--output-dir", type=Path, help="output directory (default: ROOT/docs/assets)")
    args = parser.parse_args(argv)
    try:
        clouds = build_topic_clouds(args.root)
    except ValueError as exc:
        parser.error(str(exc))
    output_dir = args.output_dir if args.output_dir is not None else args.root / "docs" / "assets"
    output_dir.mkdir(parents=True, exist_ok=True)
    for language, cloud in clouds.items():
        path = output_dir / f"topic-cloud-{language}.json"
        path.write_text(json.dumps(cloud, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {len(cloud['topics'])} topics from {cloud['article_count']} articles to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
