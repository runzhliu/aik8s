#!/usr/bin/env python3
"""Generate deterministic public-report SVG charts for Ling-3.0-flash."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import median


ROOT = Path(__file__).resolve().parents[2]
RESULTS = Path(__file__).resolve().parent / "results/2026-09-03-h20-bf16"
ASSETS = ROOT / "docs/assets/practices/ling3-flash-h20"
FONT = 'Arial,"PingFang SC","Microsoft YaHei",sans-serif'
COLORS = {"sglang": "#2563eb", "vllm": "#e4572e"}


def load_summary(name: str) -> dict[str, dict[str, str]]:
    with (RESULTS / name).open(encoding="utf-8") as handle:
        return {row["case_id"]: row for row in csv.DictReader(handle)}


def header(title: str, desc: str, height: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="{height}" viewBox="0 0 1500 {height}" role="img" aria-labelledby="title desc">',
        f'  <title id="title">{title}</title>',
        f'  <desc id="desc">{desc}</desc>',
        "  <style>",
        f"    .title{{font:700 38px {FONT};fill:#172033}}",
        f"    .sub{{font:400 19px {FONT};fill:#596579}}",
        f"    .axis{{font:400 17px {FONT};fill:#596579}}",
        f"    .value{{font:700 17px {FONT};fill:#172033}}",
        f"    .legend{{font:700 18px {FONT};fill:#172033}}",
        f"    .panel{{font:700 24px {FONT};fill:#172033}}",
        f"    .note{{font:400 16px {FONT};fill:#596579}}",
        "  </style>",
        f'  <rect width="1500" height="{height}" fill="#fbfcfe"/>',
    ]


def legend(lines: list[str], y: int = 126, left: int = 1060) -> None:
    lines.extend(
        [
            f'  <rect x="{left}" y="{y - 18}" width="24" height="24" rx="5" fill="{COLORS["sglang"]}"/>',
            f'  <text class="legend" x="{left + 36}" y="{y}">SGLang</text>',
            f'  <rect x="{left + 185}" y="{y - 18}" width="24" height="24" rx="5" fill="{COLORS["vllm"]}"/>',
            f'  <text class="legend" x="{left + 221}" y="{y}">vLLM</text>',
        ]
    )


def grouped_bars(
    lines: list[str],
    cases: list[tuple[str, str]],
    left: int,
    right: int,
    top: int,
    bottom: int,
    ymax: int,
    tick: int,
    sglang: dict[str, dict[str, str]],
    vllm: dict[str, dict[str, str]],
) -> None:
    for value in range(0, ymax + 1, tick):
        y = bottom - (bottom - top) * value / ymax
        lines.append(f'  <line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="#dfe5ee"/>')
        lines.append(f'  <text class="axis" x="{left - 16}" y="{y + 6:.1f}" text-anchor="end">{value}</text>')
    group_w = (right - left) / len(cases)
    bar_w = min(72, group_w * 0.28)
    gap = 14
    for index, (label, case_id) in enumerate(cases):
        center = left + group_w * (index + 0.5)
        values = (
            ("sglang", float(sglang[case_id]["median_output_throughput"])),
            ("vllm", float(vllm[case_id]["median_output_throughput"])),
        )
        for offset, (engine, value) in zip((-(bar_w + gap) / 2, (bar_w + gap) / 2), values):
            x = center + offset - bar_w / 2
            height = (bottom - top) * value / ymax
            y = bottom - height
            lines.append(f'  <rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{height:.1f}" rx="7" fill="{COLORS[engine]}"/>')
            lines.append(f'  <text class="value" x="{x + bar_w / 2:.1f}" y="{y - 10:.1f}" text-anchor="middle">{value:.1f}</text>')
        lines.append(f'  <text class="axis" x="{center:.1f}" y="{bottom + 30}" text-anchor="middle">{label}</text>')


def baseline_comparison(
    sglang: dict[str, dict[str, str]], vllm: dict[str, dict[str, str]]
) -> str:
    lines = header(
        "Ling-3.0-flash BF16 基线吞吐",
        "单台四卡 H20 上 SGLang 与 vLLM 的在线负载和长上下文输出吞吐中位数。",
        1040,
    )
    lines.extend(
        [
            '  <text class="title" x="72" y="66">基线：常规负载偏 SGLang，超长上下文转向 vLLM</text>',
            '  <text class="sub" x="72" y="103">Ling-3.0-flash · BF16 · 单节点 4×H20 141GB · TP4 · Speculative Off · 每轮清 Prefix Cache</text>',
        ]
    )
    legend(lines)
    lines.append('  <text class="panel" x="72" y="175">常规在线负载（输出 token/s）</text>')
    grouped_bars(
        lines,
        [("Short C16", "short-128-64-c16"), ("RAG 4K C8", "rag-4k-128-c8"), ("Long 16K C8", "long-16k-256-c8"), ("Decode 1K C8", "decode-128-1k-c8")],
        118, 1420, 215, 545, 1800, 300, sglang, vllm,
    )
    lines.append('  <text class="panel" x="72" y="625">单请求长上下文（输出 token/s；独立纵轴）</text>')
    grouped_bars(
        lines,
        [("32K", "ctx-32k-128-c1"), ("64K", "ctx-64k-128-c1"), ("128K", "ctx-128k-128-c1"), ("256K", "ctx-256k-128-c1")],
        118, 1420, 665, 895, 100, 20, sglang, vllm,
    )
    lines.extend(
        [
            '  <rect x="72" y="958" width="1356" height="52" rx="12" fill="#eef3f9"/>',
            '  <text class="note" x="750" y="980" text-anchor="middle">上图与下图使用独立纵轴；同一客户端、Checkpoint、GPU、TP、Context、请求集合与三轮中位数</text>',
            '  <text class="note" x="750" y="1002" text-anchor="middle">256K 为单次能力探针；其余 Case 每轮前调用服务端缓存重置接口</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines) + "\n"


def speculative_delta(
    sglang_base: dict[str, dict[str, str]],
    sglang_spec: dict[str, dict[str, str]],
    vllm_base: dict[str, dict[str, str]],
    vllm_spec: dict[str, dict[str, str]],
) -> str:
    cases = [
        ("Short 128→64 C1", "short-128-64-c1"),
        ("Short 128→64 C4", "short-128-64-c4"),
        ("Short 128→64 C8", "short-128-64-c8"),
        ("Short 128→64 C16", "short-128-64-c16"),
        ("RAG 4K→128 C4", "rag-4k-128-c4"),
        ("RAG 4K→128 C8", "rag-4k-128-c8"),
        ("Decode 128→1K C1", "decode-128-1k-c1"),
        ("Decode 128→1K C8", "decode-128-1k-c8"),
    ]
    lines = header(
        "Ling-3.0-flash Speculative Decoding 吞吐变化",
        "SGLang NEXTN 和 vLLM MTP 相对各自关闭 speculative decoding 基线的输出吞吐变化。",
        1080,
    )
    lines.extend(
        [
            '  <text class="title" x="72" y="66">Speculative Decoding：低并发 Decode 获益，高并发并非总是更快</text>',
            '  <text class="sub" x="72" y="103">相对各自 Off 基线的输出吞吐变化 · SGLang NEXTN / vLLM MTP（3 tokens）· 三轮中位数</text>',
        ]
    )
    legend(lines)
    chart_left, chart_right, min_value, max_value = 360, 1420, -65, 60
    x_zero = chart_left + (0 - min_value) / (max_value - min_value) * (chart_right - chart_left)
    for tick in (-60, -40, -20, 0, 20, 40, 60):
        x = chart_left + (tick - min_value) / (max_value - min_value) * (chart_right - chart_left)
        lines.append(f'  <line x1="{x:.1f}" y1="165" x2="{x:.1f}" y2="925" stroke="#dfe5ee"/>')
        lines.append(f'  <text class="axis" x="{x:.1f}" y="954" text-anchor="middle">{tick:+d}%</text>')
    lines.append(f'  <line x1="{x_zero:.1f}" y1="150" x2="{x_zero:.1f}" y2="932" stroke="#596579" stroke-width="2"/>')
    for index, (label, case_id) in enumerate(cases):
        y = 195 + index * 91
        lines.append(f'  <text class="axis" x="330" y="{y + 13}" text-anchor="end">{label}</text>')
        values = (
            ("sglang", (float(sglang_spec[case_id]["median_output_throughput"]) / float(sglang_base[case_id]["median_output_throughput"]) - 1) * 100),
            ("vllm", (float(vllm_spec[case_id]["median_output_throughput"]) / float(vllm_base[case_id]["median_output_throughput"]) - 1) * 100),
        )
        for offset, (engine, value) in zip((-13, 13), values):
            x_value = chart_left + (value - min_value) / (max_value - min_value) * (chart_right - chart_left)
            x = min(x_zero, x_value)
            width = abs(x_value - x_zero)
            lines.append(f'  <rect x="{x:.1f}" y="{y + offset:.1f}" width="{width:.1f}" height="20" rx="5" fill="{COLORS[engine]}"/>')
            anchor = "start" if value >= 0 else "end"
            label_x = x_value + (8 if value >= 0 else -8)
            lines.append(f'  <text class="value" x="{label_x:.1f}" y="{y + offset + 16:.1f}" text-anchor="{anchor}">{value:+.1f}%</text>')
    lines.extend(
        [
            '  <rect x="72" y="988" width="1356" height="58" rx="12" fill="#eef3f9"/>',
            '  <text class="note" x="750" y="1012" text-anchor="middle">正值表示 speculative 更快；负值表示更慢。NEXTN/MTP 不是“开启即加速”，收益取决于请求长度与并发。</text>',
            '  <text class="note" x="750" y="1036" text-anchor="middle">未记录 acceptance length，因此本文只报告端到端吞吐结果，不把变化归因于单一 Kernel 或接受率。</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines) + "\n"


def load_needle(name: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in (RESULTS / name).read_text(encoding="utf-8").splitlines()]


def correctness(sglang: list[dict[str, object]], vllm: list[dict[str, object]]) -> str:
    lines = header(
        "Ling-3.0-flash 长上下文正确性 Gate",
        "SGLang 与 vLLM 在 32K、64K、128K、256K 的三个 Needle 深度均通过。",
        860,
    )
    lines.extend(
        [
            '  <text class="title" x="72" y="66">长上下文正确性：两引擎均为 12 / 12 PASS</text>',
            '  <text class="sub" x="72" y="103">32K / 64K / 128K / 256K · Needle 深度 10% / 50% / 90% · 唯一字符串精确匹配</text>',
        ]
    )
    legend(lines)
    contexts = [(32768, "32K"), (65536, "64K"), (131072, "128K"), (262144, "256K")]
    for row, (target, label) in enumerate(contexts):
        y = 160 + row * 125
        lines.append(f'  <rect x="72" y="{y}" width="150" height="100" rx="18" fill="#172033"/>')
        lines.append(f'  <text x="147" y="{y + 61}" text-anchor="middle" style=\'font:700 30px {FONT};fill:#ffffff\'>{label}</text>')
        for column, (engine, records) in enumerate((("sglang", sglang), ("vllm", vllm))):
            selected = [item for item in records if int(item["context_target"]) == target]
            if len(selected) != 3 or not all(bool(item["pass"]) for item in selected):
                raise ValueError(f"missing PASS records for {engine} {target}")
            elapsed = median(float(item["elapsed_seconds"]) for item in selected)
            x = 248 + column * 590
            lines.append(f'  <rect x="{x}" y="{y}" width="565" height="100" rx="18" fill="#ffffff" stroke="#dfe5ee" stroke-width="2"/>')
            lines.append(f'  <circle cx="{x + 44}" cy="{y + 40}" r="18" fill="{COLORS[engine]}"/>')
            lines.append(f'  <text x="{x + 44}" y="{y + 47}" text-anchor="middle" style=\'font:700 20px {FONT};fill:#ffffff\'>✓</text>')
            lines.append(f'  <text class="panel" x="{x + 80}" y="{y + 47}">3 / 3 PASS</text>')
            lines.append(f'  <text class="note" x="{x + 44}" y="{y + 78}">三位置中位耗时 {elapsed:.2f}s（仅作执行证据）</text>')
    lines.extend(
        [
            '  <rect x="72" y="690" width="1356" height="105" rx="18" fill="#eef3f9"/>',
            '  <text class="panel" x="104" y="728">OpenAI 兼容功能 Smoke</text>',
            '  <text class="sub" x="104" y="762">Models · Thinking On/Off · Streaming · Multi-turn · Tool Call：SGLang PASS / vLLM PASS</text>',
            '  <text class="note" x="1428" y="830" text-anchor="end">Needle 耗时包含顺序执行状态，不用于引擎性能排名</text>',
            "</svg>",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    sglang_base = load_summary("sglang-baseline-summary.csv")
    sglang_spec = load_summary("sglang-nextn-summary.csv")
    vllm_base = load_summary("vllm-baseline-summary.csv")
    vllm_spec = load_summary("vllm-mtp-summary.csv")
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "baseline-throughput.svg").write_text(
        baseline_comparison(sglang_base, vllm_base), encoding="utf-8"
    )
    (ASSETS / "speculative-delta.svg").write_text(
        speculative_delta(sglang_base, sglang_spec, vllm_base, vllm_spec), encoding="utf-8"
    )
    (ASSETS / "correctness-gates.svg").write_text(
        correctness(load_needle("sglang-needle.jsonl"), load_needle("vllm-needle.jsonl")),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
