"""Deterministic, dependency-free bilingual article discovery.

IDs (not display labels) are persisted in feeds. Path evidence takes precedence
*as a whole* over translated prose, so translating metadata cannot add tags to
an already classified source path. For opaque paths, title/description provide
bilingual fallback rules. An explicit ``tags`` value replaces inferred tags,
including ``[]`` or an empty string. Explicit values must be defined IDs.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Iterable, Protocol, TypeVar
from urllib.parse import unquote, urlsplit


TAG_LABELS: dict[str, tuple[str, str]] = {
    "kubernetes": ("Kubernetes", "Kubernetes"),
    "gpu": ("GPU 与加速器", "GPU & Accelerators"),
    "inference": ("模型推理", "Inference"),
    "training": ("模型训练", "Training"),
    "agent": ("智能体", "Agents"),
    "sandbox": ("沙箱", "Sandbox"),
    "observability": ("可观测性", "Observability"),
    "networking": ("网络", "Networking"),
    "storage": ("存储", "Storage"),
    "scheduling": ("调度", "Scheduling"),
    "rag": ("检索增强生成", "RAG"),
    "platform": ("平台工程", "Platform Engineering"),
    "security": ("安全", "Security"),
}

TYPE_LABELS: dict[str, tuple[str, str]] = {
    "overview": ("综述", "Overview"),
    "tutorial": ("实践教程", "Tutorial"),
    "benchmark": ("评测对比", "Benchmark"),
    "troubleshooting": ("故障排查", "Troubleshooting"),
}

# ASCII boundaries avoid matching "rag" inside "fragmentation", or "agent"
# inside an unrelated word, while allowing hyphens, underscores and Chinese.
_KEYWORDS = {
    "kubernetes": ("kubernetes", "k8s", "kube-apiserver", "kubelet", "kubevirt", "karmada"),
    "gpu": ("gpu", "cuda", "nvidia", "accelerator", "accelerators", "nccl", "h20", "l20", "加速器", "显卡"),
    "inference": ("inference", "inferencing", "serving", "vllm", "sglang", "aibrix", "ollama", "kv-cache", "推理"),
    "training": ("training", "finetuning", "fine-tuning", "pytorch", "deepspeed", "fsdp", "训练", "微调"),
    "agent": ("agent", "agents", "agentic", "openclaw", "langgraph", "智能体"),
    "sandbox": ("sandbox", "sandboxes", "cubesandbox", "firecracker", "gvisor", "沙箱"),
    "observability": ("observability", "monitoring", "telemetry", "opentelemetry", "prometheus", "grafana", "langfuse", "tsdb", "可观测", "监控", "链路追踪"),
    "networking": ("network", "networks", "networking", "rdma", "cni", "cilium", "contiv", "ovs", "gateway", "routing", "load-balancing", "网络", "网关", "路由", "负载均衡"),
    "storage": ("storage", "data-storage", "ceph", "rbd", "csi", "model-artifacts", "model-distribution", "weight-delivery", "存储", "模型分发", "权重分发"),
    "scheduling": ("scheduling", "scheduler", "kueue", "volcano", "slurm", "koordinator", "gpu-pending", "调度", "排队"),
    "rag": ("rag", "retrieval", "vector-database", "检索增强", "向量检索", "向量数据库"),
    "platform": ("platform", "mlops", "notebook", "平台", "工程化"),
    "security": ("security", "secure", "red-team", "air-gapped", "rbac", "authentication", "authorization", "cert", "安全", "鉴权", "认证", "授权", "证书", "红队"),
}
_TYPE_KEYWORDS = {
    "troubleshooting": ("troubleshooting", "debug", "debugging", "incident", "failure", "fix", "fixes", "error", "oom", "pending", "故障", "排障", "排查", "修复", "错误", "事故"),
    "benchmark": ("benchmark", "benchmarking", "evaluation", "evaluate", "comparison", "vs", "test-plan", "评测", "基准", "对比", "测试计划"),
    "tutorial": ("tutorial", "guide", "guides", "practice", "practices", "lab", "deployment", "getting-started", "how-to", "教程", "实践", "实战", "部署", "入门"),
    "overview": ("overview", "introduction", "fundamentals", "architecture", "综述", "概览", "概述", "架构", "基础"),
}


def _matches(text: str, keyword: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])", text) is not None


def _path_text(relative_path: str) -> str:
    parts = unquote(relative_path).replace("\\", "/").casefold().split("/")
    # The site namespace says nothing about an individual article's topic.
    # This combined navigation section contains many non-RAG agent articles.
    parts = ['agent' if part == 'rag-agent' else part for part in parts]
    return "/".join(part for part in parts if part not in {"ai-k8s", "docs", "en", "zh", "zh-cn"}).replace("_", "-")


def _infer_type(text: str) -> str | None:
    for kind, keywords in _TYPE_KEYWORDS.items():
        if any(_matches(text, word) for word in keywords):
            return kind
    return None


def _explicit_tags(raw: str) -> tuple[str, ...]:
    if not isinstance(raw, str):
        raise ValueError("tags must be a JSON array string or comma-separated tag IDs")
    raw = raw.strip()
    if raw.startswith("[") or raw.startswith("{") or raw.startswith('"'):
        try:
            values = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("tags must contain a valid JSON array of tag IDs") from exc
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError("tags JSON must be an array of strings")
    else:
        values = [] if not raw else [value.strip() for value in raw.split(",")]
    invalid = [value for value in values if value not in TAG_LABELS]
    if invalid:
        raise ValueError(f"Unknown tags: {invalid!r}; allowed IDs: {', '.join(TAG_LABELS)}")
    # Canonical order also normalizes repeated or differently ordered overrides.
    return tuple(tag for tag in TAG_LABELS if tag in values)


def infer_discovery(relative_path: str, metadata: dict[str, str]) -> tuple[tuple[str, ...], str]:
    """Return canonical tag IDs and one of the four TYPE_LABELS IDs.

    ``tags`` and ``content_type`` overrides are independent. Unknown IDs, malformed
    JSON and non-string overrides raise ValueError rather than silently falling back.
    """
    path = _path_text(relative_path)
    prose = " ".join((metadata.get("title", ""), metadata.get("description", ""))).casefold().replace("_", "-")
    if "tags" in metadata:
        tags = _explicit_tags(metadata["tags"])
    else:
        tags = tuple(tag for tag, words in _KEYWORDS.items() if any(_matches(path, word) for word in words))
        if not tags:
            tags = tuple(tag for tag, words in _KEYWORDS.items() if any(_matches(prose, word) for word in words))
    if "content_type" in metadata:
        kind = metadata["content_type"]
        if not isinstance(kind, str) or kind not in TYPE_LABELS:
            raise ValueError(f"Unknown content_type: {kind!r}; allowed IDs: {', '.join(TYPE_LABELS)}")
    else:
        kind = _infer_type(path) or _infer_type(prose) or "overview"
    return tags, kind


class _Article(Protocol):
    tags: tuple[str, ...]
    category: str
    url: str
    published: datetime
    updated: datetime
    is_index: bool
    content_type: str


_ArticleT = TypeVar("_ArticleT", bound=_Article)
_GENERIC_DIRS = {"", "ai-k8s", "docs", "en", "zh", "zh-cn", "practices", "guides", "foundations", "home", "首页"}

# Recommendation-only path evidence: these are products/series, not new tag IDs.
# An explicit allowlist avoids treating arbitrary slug words ("architecture",
# "practice", etc.) as evidence, and does not depend on translated metadata.
_PRODUCTS = (
    "kubevirt", "aibrix", "cubesandbox", "openclaw", "vllm", "sglang",
    "koordinator", "karmada", "kueue", "volcano", "slurm", "ollama",
    "firecracker", "gvisor", "langgraph", "langchain", "langfuse",
    "opentelemetry", "prometheus", "grafana", "cilium", "contiv",
    "ceph", "pytorch", "deepspeed", "ray", "kube-apiserver",
)
_PRODUCT_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:" + "|".join(map(re.escape, _PRODUCTS)) + r")(?![a-z0-9])"
)
_TAG_WEIGHTS = {tag: 0.15 if tag in {"kubernetes", "platform"} else 1.0 for tag in TAG_LABELS}


def _products(url: str) -> set[str]:
    return set(_PRODUCT_PATTERN.findall(_path_text(urlsplit(url).path)))


def _overlap(own_tags: set[str], tags: set[str], own_products: set[str], products: set[str]) -> float:
    """Weighted Jaccard penalizes broad candidates with many unrelated topics."""
    shared = sum(_TAG_WEIGHTS[tag] for tag in sorted(own_tags & tags))
    union = sum(_TAG_WEIGHTS[tag] for tag in sorted(own_tags | tags))
    shared += 4.0 * len(own_products & products)
    union += 4.0 * len(own_products | products)
    return shared / union if union else 0.0


def _url_key(url: str) -> str:
    parsed = urlsplit(url)
    path = unquote(parsed.path).rstrip("/")
    if path.endswith("/index.html"):
        path = path[:-len("/index.html")]
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def _directory(url: str) -> str:
    path = unquote(urlsplit(url).path).strip("/")
    parts = path.split("/")[:-1]
    return "/".join(parts) if parts and parts[-1].casefold() not in _GENERIC_DIRS else ""


def _timestamp(value: datetime) -> float:
    # FeedItem uses aware datetimes; accept naive fixtures consistently as UTC.
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).timestamp()


def related_items(item: _ArticleT, articles: Iterable[_ArticleT], limit: int = 4) -> list[_ArticleT]:
    """Rank shared URL products first, then weighted relative topic overlap.

    Kubernetes/platform tags carry little weight; extra unrelated topics dilute
    overlap rather than rewarding broad surveys. Directory/category and type only
    break relevance ties, never admit an otherwise unrelated candidate. Further
    ties use newest update/publication, canonical URL, then raw URL (for aliases).
    The supplied objects are returned unchanged; no FeedItem import is required.
    """
    if limit <= 0:
        return []
    own_url = _url_key(item.url)
    own_directory = _directory(item.url)
    own_tags = set(item.tags)
    own_products = _products(item.url)
    ranked = []
    for candidate in articles:
        key = _url_key(candidate.url)
        if candidate is item or key == own_url or candidate.is_index:
            continue
        tags = set(candidate.tags)
        products = _products(candidate.url)
        shared_product = bool(own_products & products)
        if not (shared_product or own_tags & tags):
            continue
        similarity = _overlap(own_tags, tags, own_products, products)
        same_directory = bool(own_directory and own_directory == _directory(candidate.url))
        same_category = bool(item.category and item.category == candidate.category
                             and item.category.casefold() not in _GENERIC_DIRS)
        rank = (-int(shared_product), -similarity, -int(same_directory), -int(same_category),
                -int(item.content_type == candidate.content_type),
                -_timestamp(candidate.updated), -_timestamp(candidate.published), key, candidate.url)
        ranked.append((rank, candidate))
    ranked.sort(key=lambda pair: pair[0])
    result: list[_ArticleT] = []
    seen: set[str] = set()
    for _, candidate in ranked:
        key = _url_key(candidate.url)
        if key not in seen:
            seen.add(key)
            result.append(candidate)
            if len(result) == limit:
                break
    return result
