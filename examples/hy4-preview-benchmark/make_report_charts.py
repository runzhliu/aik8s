#!/usr/bin/env python3
"""Generate deterministic public-report SVG charts from benchmark summaries."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[2]
RESULTS = Path(__file__).resolve().parent / "results/2026-09-01-h20-bf16"
ASSETS = ROOT / "docs/assets/practices/hy4-preview-h20"
FONT = 'Arial,"PingFang SC","Microsoft YaHei",sans-serif'
COLORS = {"sglang": "#2563eb", "vllm": "#e4572e"}


def load_summary(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return {row["case_id"]: row for row in csv.DictReader(handle)}


def load_correctness(path: Path) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    needles: list[dict[str, object]] = []
    agent: dict[str, object] = {}
    summary: dict[str, object] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("NIAH_RESULT "):
            needles.append(json.loads(line.removeprefix("NIAH_RESULT ")))
        elif line.startswith("AGENT_RESULT "):
            agent = json.loads(line.removeprefix("AGENT_RESULT "))
        elif line.startswith("CORRECTNESS_SUMMARY "):
            summary = json.loads(line.removeprefix("CORRECTNESS_SUMMARY "))
    if len(needles) != 9 or agent.get("status") != "PASS" or summary.get("status") != "PASS":
        raise ValueError(f"incomplete correctness evidence: {path}")
    return needles, agent, summary


def svg_header(title: str, desc: str) -> list[str]:
    return [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="860" viewBox="0 0 1500 860" role="img" aria-labelledby="title desc">',
        f'  <title id="title">{title}</title>',
        f'  <desc id="desc">{desc}</desc>',
        "  <style>",
        f"    .title{{font:700 38px {FONT};fill:#172033}}",
        f"    .sub{{font:400 19px {FONT};fill:#596579}}",
        f"    .axis{{font:400 17px {FONT};fill:#596579}}",
        f"    .value{{font:700 18px {FONT};fill:#172033}}",
        f"    .legend{{font:700 18px {FONT};fill:#172033}}",
        f"    .note{{font:400 16px {FONT};fill:#596579}}",
        "  </style>",
        '  <rect width="1500" height="860" fill="#fbfcfe"/>',
    ]


def legend(lines: list[str], y: int = 128) -> None:
    lines.extend(
        [
            f'  <rect x="1060" y="{y - 18}" width="24" height="24" rx="5" fill="{COLORS["sglang"]}"/>',
            f'  <text class="legend" x="1096" y="{y}">SGLang · TP16</text>',
            f'  <rect x="1265" y="{y - 18}" width="24" height="24" rx="5" fill="{COLORS["vllm"]}"/>',
            f'  <text class="legend" x="1301" y="{y}">vLLM · TP8×PP2</text>',
        ]
    )


def short_throughput(sglang: dict[str, dict[str, str]], vllm: dict[str, dict[str, str]]) -> str:
    cases = [
        ("C1", "short-128-64-c1"),
        ("C4", "short-128-64-c4"),
        ("C8", "short-128-64-c8"),
        ("C16", "short-128-64-c16"),
        ("C32", "short-128-64-c32"),
    ]
    lines = svg_header(
        "Hy4-preview BF16 短请求输出吞吐",
        "两台八卡 H20 上，SGLang TP16 和 vLLM TP8 乘 PP2 的 128 输入 64 输出吞吐中位数对比。",
    )
    lines.extend(
        [
            '  <text class="title" x="72" y="68">短请求：SGLang 在全部并发档位领先</text>',
            '  <text class="sub" x="72" y="104">Hy4-preview BF16 · 2×8 H20 · 128 输入 / 64 输出 · MTP Off · 三轮中位数</text>',
        ]
    )
    legend(lines)
    left, right, top, bottom, ymax = 118, 1420, 180, 690, 400
    for tick in range(0, ymax + 1, 100):
        y = bottom - (bottom - top) * tick / ymax
        lines.append(f'  <line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="#dfe5ee"/>')
        lines.append(f'  <text class="axis" x="102" y="{y + 6:.1f}" text-anchor="end">{tick}</text>')
    group_w = (right - left) / len(cases)
    bar_w, gap = 82, 18
    for index, (label, case_id) in enumerate(cases):
        center = left + group_w * (index + 0.5)
        values = [
            ("sglang", float(sglang[case_id]["median_output_throughput"])),
            ("vllm", float(vllm[case_id]["median_output_throughput"])),
        ]
        for offset, (engine, value) in zip((-(bar_w + gap) / 2, (bar_w + gap) / 2), values):
            x = center + offset - bar_w / 2
            height = (bottom - top) * value / ymax
            y = bottom - height
            lines.append(f'  <rect x="{x:.1f}" y="{y:.1f}" width="{bar_w}" height="{height:.1f}" rx="8" fill="{COLORS[engine]}"/>')
            lines.append(f'  <text class="value" x="{x + bar_w / 2:.1f}" y="{y - 12:.1f}" text-anchor="middle">{value:.1f}</text>')
        lines.append(f'  <text class="axis" x="{center:.1f}" y="728" text-anchor="middle">{label}</text>')
    lines.extend(
        [
            '  <text class="axis" x="38" y="445" transform="rotate(-90 38 445)" text-anchor="middle">输出吞吐（token/s）</text>',
            '  <text class="axis" x="770" y="770" text-anchor="middle">最大并发</text>',
            '  <rect x="72" y="796" width="1356" height="42" rx="12" fill="#eef3f9"/>',
            '  <text class="note" x="750" y="823" text-anchor="middle">同一 vLLM bench serve 客户端、请求集合与参数；并行拓扑不同，因此这是部署配方对比，不是纯引擎微基准</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines) + "\n"


def long_context_ttft(sglang: dict[str, dict[str, str]], vllm: dict[str, dict[str, str]]) -> str:
    cases = [
        ("32K / 128", "ctx-32k-128-c1"),
        ("64K / 128", "ctx-64k-128-c1"),
        ("130K / 1K", "ctx-127k-1k-c1"),
    ]
    lines = svg_header(
        "Hy4-preview BF16 长上下文 P50 TTFT",
        "两台八卡 H20 上关闭前缀缓存后的 32K、64K 和 130K 单并发首 token 延迟中位数。",
    )
    lines.extend(
        [
            '  <text class="title" x="72" y="68">长上下文：64K 起 vLLM 的 TTFT 反超</text>',
            '  <text class="sub" x="72" y="104">Hy4-preview BF16 · 2×8 H20 · C1 · Prefix Cache Off · 两轮中位数</text>',
        ]
    )
    legend(lines)
    left, right, top, bottom, ymax = 118, 1420, 180, 690, 50
    for tick in range(0, ymax + 1, 10):
        y = bottom - (bottom - top) * tick / ymax
        lines.append(f'  <line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="#dfe5ee"/>')
        lines.append(f'  <text class="axis" x="102" y="{y + 6:.1f}" text-anchor="end">{tick}</text>')
    group_w = (right - left) / len(cases)
    bar_w, gap = 132, 28
    for index, (label, case_id) in enumerate(cases):
        center = left + group_w * (index + 0.5)
        values = [
            ("sglang", float(sglang[case_id]["median_p50_ttft_ms"]) / 1000),
            ("vllm", float(vllm[case_id]["median_p50_ttft_ms"]) / 1000),
        ]
        for offset, (engine, value) in zip((-(bar_w + gap) / 2, (bar_w + gap) / 2), values):
            x = center + offset - bar_w / 2
            height = (bottom - top) * value / ymax
            y = bottom - height
            lines.append(f'  <rect x="{x:.1f}" y="{y:.1f}" width="{bar_w}" height="{height:.1f}" rx="8" fill="{COLORS[engine]}"/>')
            lines.append(f'  <text class="value" x="{x + bar_w / 2:.1f}" y="{y - 12:.1f}" text-anchor="middle">{value:.2f}s</text>')
        lines.append(f'  <text class="axis" x="{center:.1f}" y="728" text-anchor="middle">{label}</text>')
    lines.extend(
        [
            '  <text class="axis" x="38" y="445" transform="rotate(-90 38 445)" text-anchor="middle">P50 TTFT（秒，越低越好）</text>',
            '  <rect x="72" y="786" width="1356" height="52" rx="12" fill="#eef3f9"/>',
            '  <text class="note" x="750" y="808" text-anchor="middle">SGLang 使用 disable-radix-cache；vLLM 使用 no-enable-prefix-caching</text>',
            '  <text class="note" x="750" y="830" text-anchor="middle">130K Case 为 130,000 输入 / 1,024 输出；其余为 128 输出</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines) + "\n"


def correctness_gates(
    sglang: tuple[list[dict[str, object]], dict[str, object], dict[str, object]],
    vllm: tuple[list[dict[str, object]], dict[str, object], dict[str, object]],
) -> str:
    engines = [("sglang", sglang), ("vllm", vllm)]
    contexts = [(32768, "32K"), (65536, "64K"), (126000, "126K")]
    lines = svg_header(
        "Hy4-preview BF16 长上下文正确性 Gate",
        "SGLang 与 vLLM 在 32K、64K、126K 三档上下文和三个 Needle 深度均通过，并通过多轮 Agent 工具链；1M 因运行时容量不足未进入请求阶段。",
    )
    lines.extend(
        [
            '  <text class="title" x="72" y="68">长上下文正确性：两引擎 9/9 PASS</text>',
            '  <text class="sub" x="72" y="104">Hy4-preview BF16 · 2×8 H20 · Needle 深度 10% / 50% / 90% · 服务端 Token 校准</text>',
        ]
    )
    legend(lines)

    left, top = 72, 164
    label_w, card_w, row_h, gap = 150, 565, 124, 22
    for row, (target, label) in enumerate(contexts):
        y = top + row * (row_h + gap)
        lines.extend(
            [
                f'  <rect x="{left}" y="{y}" width="{label_w}" height="{row_h}" rx="18" fill="#172033"/>',
                f"  <text x=\"{left + label_w / 2}\" y=\"{y + 58}\" text-anchor=\"middle\" style='font:700 30px {FONT};fill:#ffffff'>{label}</text>",
                f"  <text x=\"{left + label_w / 2}\" y=\"{y + 88}\" text-anchor=\"middle\" style='font:400 16px {FONT};fill:#d7dfeb'>Context</text>",
            ]
        )
        for column, (engine, evidence) in enumerate(engines):
            records = [item for item in evidence[0] if int(item["target_tokens"]) == target]
            if len(records) != 3 or any(item["status"] != "PASS" for item in records):
                raise ValueError(f"missing PASS records for {engine} target={target}")
            elapsed = [float(item["elapsed_seconds"]) for item in records]
            x = left + label_w + gap + column * (card_w + gap)
            lines.extend(
                [
                    f'  <rect x="{x}" y="{y}" width="{card_w}" height="{row_h}" rx="18" fill="#ffffff" stroke="#dfe5ee" stroke-width="2"/>',
                    f'  <circle cx="{x + 38}" cy="{y + 38}" r="17" fill="{COLORS[engine]}"/>',
                    f"  <text x=\"{x + 38}\" y=\"{y + 45}\" text-anchor=\"middle\" style='font:700 19px {FONT};fill:#ffffff'>✓</text>",
                    f"  <text x=\"{x + 70}\" y=\"{y + 45}\" style='font:700 24px {FONT};fill:#172033'>3 / 3 PASS</text>",
                    f'  <text class="sub" x="{x + 38}" y="{y + 82}">10% {elapsed[0]:.2f}s · 50% {elapsed[1]:.2f}s · 90% {elapsed[2]:.2f}s</text>',
                    f'  <text class="note" x="{x + 38}" y="{y + 108}">中位耗时 {median(elapsed):.2f}s</text>',
                ]
            )

    agent_y = 610
    lines.extend(
        [
            f'  <rect x="72" y="{agent_y}" width="1356" height="86" rx="18" fill="#eef3f9"/>',
            f"  <text x=\"102\" y=\"{agent_y + 34}\" style='font:700 22px {FONT};fill:#172033'>Agent 工具链</text>",
            f"  <text x=\"102\" y=\"{agent_y + 64}\" style='font:400 19px {FONT};fill:#596579'>查询库存  →  计算运费  →  预留库存  →  汇总</text>",
            f'  <rect x="1040" y="{agent_y + 18}" width="168" height="50" rx="25" fill="{COLORS["sglang"]}"/>',
            f"  <text x=\"1124\" y=\"{agent_y + 50}\" text-anchor=\"middle\" style='font:700 18px {FONT};fill:#ffffff'>SGLang PASS</text>",
            f'  <rect x="1224" y="{agent_y + 18}" width="168" height="50" rx="25" fill="{COLORS["vllm"]}"/>',
            f"  <text x=\"1308\" y=\"{agent_y + 50}\" text-anchor=\"middle\" style='font:700 18px {FONT};fill:#ffffff'>vLLM PASS</text>",
            '  <rect x="72" y="724" width="1356" height="84" rx="18" fill="#fff4e8" stroke="#ffc98c"/>',
            f"  <text x=\"102\" y=\"758\" style='font:700 22px {FONT};fill:#9a4b00'>1M Capacity Gate 未通过</text>",
            f"  <text x=\"102\" y=\"790\" style='font:400 19px {FONT};fill:#754314'>Runtime 容量：SGLang 233,920 · vLLM 193,152 · 模型声明 1,048,576 Token</text>",
            '  <text class="note" x="1428" y="840" text-anchor="end">数据源：2026-09-01 两引擎 correctness 原始日志</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    sglang = load_summary(RESULTS / "sglang-rdma-summary.csv")
    vllm = load_summary(RESULTS / "vllm-rdma-summary.csv")
    sglang_correctness = load_correctness(RESULTS / "sglang-correctness.log")
    vllm_correctness = load_correctness(RESULTS / "vllm-correctness.log")
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "short-throughput.svg").write_text(short_throughput(sglang, vllm), encoding="utf-8")
    (ASSETS / "long-context-ttft.svg").write_text(long_context_ttft(sglang, vllm), encoding="utf-8")
    (ASSETS / "correctness-gates.svg").write_text(
        correctness_gates(sglang_correctness, vllm_correctness), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
