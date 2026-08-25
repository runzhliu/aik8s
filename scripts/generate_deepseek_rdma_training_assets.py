#!/usr/bin/env python3
"""Generate public SVG figures from the DeepSeek V4 TCP/RDMA result JSON."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULT = (
    ROOT
    / "examples/llm-sft-lab/meaningful-sft/results"
    / "h20-deepseek-v4-rdma-tcp-20260825.json"
)
CONVERGENCE_RESULT = (
    ROOT
    / "examples/llm-sft-lab/meaningful-sft/results"
    / "h20-deepseek-v4-convergence-20260825.json"
)
OUTPUT = ROOT / "docs/assets/training/deepseek-v4-rdma"

NAVY = "#0b1f44"
BLUE = "#2563eb"
CYAN = "#06b6d4"
ORANGE = "#f97316"
GREEN = "#10b981"
SLATE = "#64748b"
LIGHT = "#f8fafc"
GRID = "#dbe4f0"


def svg_start(title: str, subtitle: str) -> list[str]:
    return [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">',
        f'<rect width="1280" height="720" fill="{LIGHT}"/>',
        f'<text x="64" y="76" font-family="system-ui,sans-serif" font-size="34" font-weight="700" fill="{NAVY}">{title}</text>',
        f'<text x="64" y="112" font-family="system-ui,sans-serif" font-size="18" fill="{SLATE}">{subtitle}</text>',
    ]


def finish(parts: list[str], note: str) -> str:
    parts.extend(
        [
            f'<text x="64" y="684" font-family="system-ui,sans-serif" font-size="15" fill="{SLATE}">{note}</text>',
            "</svg>",
        ]
    )
    return "\n".join(parts) + "\n"


def render_sft(data: dict) -> str:
    runs = data["positive_case"]["runs"]
    summary = data["positive_case"]["median_of_run_means"]
    tcp = [item["stable_mean_seconds_per_step"] for item in runs["tcp"]]
    rdma = [item["stable_mean_seconds_per_step"] for item in runs["rdma"]]
    parts = svg_start(
        "真实 MoE SFT：三轮 A/B 都显示 RDMA 更快",
        "DeepSeek V4 Flash · 2 节点 × 8 GPU · PP=1 / EP=16 / Dense DP=16 · 稳定 Step 6–20",
    )
    x0, y0, chart_w, chart_h = 110, 180, 1050, 330
    for tick in range(6):
        x = x0 + chart_w * tick / 5
        parts.append(f'<line x1="{x:.1f}" y1="{y0}" x2="{x:.1f}" y2="{y0 + chart_h}" stroke="{GRID}"/>')
        parts.append(f'<text x="{x:.1f}" y="{y0 + chart_h + 30}" text-anchor="middle" font-family="system-ui,sans-serif" font-size="15" fill="{SLATE}">{tick}</text>')
    for index, (tcp_value, rdma_value) in enumerate(zip(tcp, rdma), start=1):
        y = y0 + 28 + (index - 1) * 96
        for offset, value, color, label in ((0, tcp_value, ORANGE, "TCP"), (34, rdma_value, BLUE, "RDMA")):
            width = chart_w * value / 5
            parts.append(f'<rect x="{x0}" y="{y + offset}" width="{width:.1f}" height="25" rx="7" fill="{color}"/>')
            parts.append(f'<text x="{x0 - 18}" y="{y + offset + 18}" text-anchor="end" font-family="system-ui,sans-serif" font-size="16" fill="{NAVY}">R{index} {label}</text>')
            parts.append(f'<text x="{x0 + width + 12:.1f}" y="{y + offset + 18}" font-family="system-ui,sans-serif" font-size="16" font-weight="700" fill="{NAVY}">{value:.3f} s</text>')
    parts.append(f'<rect x="64" y="566" width="1152" height="76" rx="16" fill="{NAVY}"/>')
    parts.append(f'<text x="100" y="614" font-family="system-ui,sans-serif" font-size="25" font-weight="700" fill="white">三轮中位数：{summary["tcp_seconds_per_step"]:.3f} → {summary["rdma_seconds_per_step"]:.3f} s/Step</text>')
    parts.append(f'<text x="914" y="614" text-anchor="middle" font-family="system-ui,sans-serif" font-size="28" font-weight="800" fill="{CYAN}">吞吐 +{summary["rdma_throughput_gain_percent"]:.2f}%</text>')
    return finish(parts, "口径：相同节点、模型、数据、Batch、镜像与 Rank 映射；仅切换 NCCL Transport。")


def render_nccl(data: dict) -> str:
    median = data["collective_microbenchmark"]["median_at_256_mib_per_rank"]
    parts = svg_start(
        "NCCL 微基准：链路能力与真实训练收益要分开看",
        "World Size 16 · 256 MiB/Rank · 5 次预热 + 20 次计时 · 三轮中位数",
    )
    panels = [
        ("AllReduce", median["all_reduce"], "对应 DP / FSDP / ZeRO 的梯度与参数同步"),
        ("All-to-All", median["all_to_all"], "对应 MoE Expert Parallel 的 Token Dispatch / Combine"),
    ]
    for idx, (name, values, description) in enumerate(panels):
        x = 64 + idx * 588
        parts.append(f'<rect x="{x}" y="154" width="548" height="452" rx="22" fill="white" stroke="{GRID}" stroke-width="2"/>')
        parts.append(f'<text x="{x + 30}" y="204" font-family="system-ui,sans-serif" font-size="27" font-weight="700" fill="{NAVY}">{name}</text>')
        parts.append(f'<text x="{x + 30}" y="236" font-family="system-ui,sans-serif" font-size="15" fill="{SLATE}">{description}</text>')
        max_value = values["rdma_GBps"] * 1.08
        for row, (label, value, color) in enumerate((("TCP", values["tcp_GBps"], ORANGE), ("RDMA", values["rdma_GBps"], BLUE))):
            y = 294 + row * 105
            width = 438 * value / max_value
            parts.append(f'<text x="{x + 30}" y="{y + 23}" font-family="system-ui,sans-serif" font-size="18" fill="{NAVY}">{label}</text>')
            parts.append(f'<rect x="{x + 106}" y="{y}" width="438" height="34" rx="9" fill="#eef2f7"/>')
            parts.append(f'<rect x="{x + 106}" y="{y}" width="{max(width, 3):.1f}" height="34" rx="9" fill="{color}"/>')
            if width < 120:
                value_x, anchor, text_color = x + 106 + width + 12, "start", NAVY
            else:
                value_x, anchor, text_color = x + 106 + width - 10, "end", "white"
            parts.append(f'<text x="{value_x:.1f}" y="{y + 24}" text-anchor="{anchor}" font-family="system-ui,sans-serif" font-size="16" font-weight="700" fill="{text_color}">{value:.2f} GB/s</text>')
        parts.append(f'<text x="{x + 274}" y="535" text-anchor="middle" font-family="system-ui,sans-serif" font-size="32" font-weight="800" fill="{GREEN}">{values["rdma_to_tcp_ratio"]:.2f}×</text>')
        parts.append(f'<text x="{x + 274}" y="568" text-anchor="middle" font-family="system-ui,sans-serif" font-size="16" fill="{SLATE}">RDMA / TCP 算法带宽</text>')
    return finish(parts, "注意：GB/s 是 16 Rank Collective 的算法带宽，不是单张网卡线速，也不是端到端训练加速比。")


def render_topology(data: dict) -> str:
    negative = data["negative_control"]
    positive = data["positive_case"]["median_of_run_means"]
    parts = svg_start(
        "为什么同一套 RDMA，一组没收益，另一组快 32%？",
        "决定因素不是“有没有 RDMA”，而是关键 Collective 是否跨节点并进入 Step 关键路径",
    )
    cards = [
        (64, "负对照：PP=2 / EP=8", "EP 与 DP 组留在单节点", "跨机只传 Pipeline Activation", f'RDMA 变化 {negative["rdma_step_time_change_percent"]:+.2f}%：无可测收益', ORANGE),
        (656, "正向案例：PP=1 / EP=16", "EP 与 Dense DP 都跨两节点", "All-to-All + 同步进入跨机路径", f'稳定 Step -{positive["rdma_step_time_reduction_percent"]:.2f}% · 吞吐 +{positive["rdma_throughput_gain_percent"]:.2f}%', BLUE),
    ]
    for x, title, line1, line2, result, color in cards:
        parts.append(f'<rect x="{x}" y="154" width="560" height="466" rx="24" fill="white" stroke="{GRID}" stroke-width="2"/>')
        parts.append(f'<text x="{x + 32}" y="205" font-family="system-ui,sans-serif" font-size="25" font-weight="700" fill="{NAVY}">{title}</text>')
        for node_index in range(2):
            nx = x + 58 + node_index * 256
            parts.append(f'<rect x="{nx}" y="258" width="188" height="138" rx="18" fill="#eff6ff" stroke="{BLUE}" stroke-width="2"/>')
            parts.append(f'<text x="{nx + 94}" y="290" text-anchor="middle" font-family="system-ui,sans-serif" font-size="16" font-weight="700" fill="{NAVY}">Node {node_index + 1}</text>')
            for gpu in range(4):
                gx = nx + 20 + (gpu % 2) * 82
                gy = 310 + (gpu // 2) * 38
                parts.append(f'<rect x="{gx}" y="{gy}" width="66" height="27" rx="6" fill="{NAVY}"/>')
                parts.append(f'<text x="{gx + 33}" y="{gy + 19}" text-anchor="middle" font-family="system-ui,sans-serif" font-size="12" fill="white">GPU</text>')
        if x == 64:
            parts.append(f'<line x1="{x + 246}" y1="327" x2="{x + 314}" y2="327" stroke="{ORANGE}" stroke-width="5" stroke-dasharray="10 8"/>')
            parts.append(f'<text x="{x + 280}" y="315" text-anchor="middle" font-family="system-ui,sans-serif" font-size="13" fill="{ORANGE}">PP</text>')
        else:
            for offset in (-25, 0, 25):
                parts.append(f'<line x1="{x + 246}" y1="{327 + offset}" x2="{x + 314}" y2="{327 + offset}" stroke="{CYAN}" stroke-width="5"/>')
            parts.append(f'<text x="{x + 280}" y="292" text-anchor="middle" font-family="system-ui,sans-serif" font-size="13" fill="{BLUE}">EP / DP</text>')
        parts.append(f'<text x="{x + 280}" y="446" text-anchor="middle" font-family="system-ui,sans-serif" font-size="18" fill="{NAVY}">{line1}</text>')
        parts.append(f'<text x="{x + 280}" y="478" text-anchor="middle" font-family="system-ui,sans-serif" font-size="17" fill="{SLATE}">{line2}</text>')
        parts.append(f'<rect x="{x + 30}" y="520" width="500" height="64" rx="14" fill="{color}"/>')
        parts.append(f'<text x="{x + 280}" y="560" text-anchor="middle" font-family="system-ui,sans-serif" font-size="20" font-weight="750" fill="white">{result}</text>')
    return finish(parts, "拓扑图只展示通信域关系；每个节点实际使用 8 张 GPU。")


def render_convergence(data: dict) -> str:
    validation = data["metrics"]["validation_loss"]
    best_step = data["metrics"]["best_validation_step"]
    best_loss = data["metrics"]["best_validation_loss"]
    final_loss = validation[-1]["loss"]
    increase = data["metrics"]["validation_loss_increase_best_to_step60_percent"]
    parts = svg_start(
        "60 Step 收敛实验：Train Loss 继续下降，Validation 已经回升",
        "DeepSeek V4 Flash · 2 节点 × 8 GPU · EP=16 · GDRDMA · 每 10 Step 验证",
    )
    x0, y0, chart_w, chart_h = 110, 180, 1050, 330
    max_loss = 0.6
    for tick in range(7):
        value = tick * 0.1
        y = y0 + chart_h - chart_h * value / max_loss
        parts.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x0 + chart_w}" y2="{y:.1f}" stroke="{GRID}"/>')
        parts.append(f'<text x="{x0 - 18}" y="{y + 5:.1f}" text-anchor="end" font-family="system-ui,sans-serif" font-size="15" fill="{SLATE}">{value:.1f}</text>')
    for item in validation:
        x = x0 + chart_w * (item["step"] - 10) / 50
        parts.append(f'<line x1="{x:.1f}" y1="{y0}" x2="{x:.1f}" y2="{y0 + chart_h}" stroke="{GRID}"/>')
        parts.append(f'<text x="{x:.1f}" y="{y0 + chart_h + 30}" text-anchor="middle" font-family="system-ui,sans-serif" font-size="15" fill="{SLATE}">{item["step"]}</text>')
    best_x = x0 + chart_w * (best_step - 10) / 50
    parts.append(f'<rect x="{best_x:.1f}" y="{y0}" width="{x0 + chart_w - best_x:.1f}" height="{chart_h}" fill="#fff7ed" opacity="0.85"/>')
    points = []
    for item in validation:
        x = x0 + chart_w * (item["step"] - 10) / 50
        y = y0 + chart_h - chart_h * item["loss"] / max_loss
        points.append(f"{x:.1f},{y:.1f}")
    parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{BLUE}" stroke-width="6" stroke-linejoin="round" stroke-linecap="round"/>')
    for item in validation:
        x = x0 + chart_w * (item["step"] - 10) / 50
        y = y0 + chart_h - chart_h * item["loss"] / max_loss
        color = GREEN if item["step"] == best_step else BLUE
        radius = 10 if item["step"] == best_step else 7
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{color}" stroke="white" stroke-width="4"/>')
        parts.append(f'<text x="{x:.1f}" y="{y - 18:.1f}" text-anchor="middle" font-family="system-ui,sans-serif" font-size="15" font-weight="700" fill="{NAVY}">{item["loss"]:.4f}</text>')
    parts.append(f'<text x="{best_x + 24:.1f}" y="{y0 + 34}" font-family="system-ui,sans-serif" font-size="17" font-weight="700" fill="{ORANGE}">Step {best_step} 之后：过拟合观察区</text>')
    parts.append(f'<rect x="64" y="566" width="1152" height="76" rx="16" fill="{NAVY}"/>')
    parts.append(f'<text x="100" y="614" font-family="system-ui,sans-serif" font-size="24" font-weight="700" fill="white">最佳 Validation Loss：{best_loss:.5f}（Step {best_step}）</text>')
    parts.append(f'<text x="1160" y="614" text-anchor="end" font-family="system-ui,sans-serif" font-size="23" font-weight="800" fill="{ORANGE}">Step 60：{final_loss:.5f} · 回升 {increase:.2f}%</text>')
    return finish(parts, "结论：继续压低 Train Loss 不等于泛化继续改善；保存间隔应与验证间隔对齐。")


def main() -> None:
    data = json.loads(RESULT.read_text(encoding="utf-8"))
    convergence = json.loads(CONVERGENCE_RESULT.read_text(encoding="utf-8"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    assets = {
        "sft-step-time.svg": render_sft(data),
        "nccl-bandwidth.svg": render_nccl(data),
        "topology-matters.svg": render_topology(data),
        "convergence-validation.svg": render_convergence(convergence),
    }
    for name, content in assets.items():
        (OUTPUT / name).write_text(content, encoding="utf-8")
        print(OUTPUT / name)


if __name__ == "__main__":
    main()
