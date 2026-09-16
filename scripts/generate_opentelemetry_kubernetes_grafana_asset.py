#!/usr/bin/env python3
"""Build a public, 16:9 article figure from a sanitized Grafana screenshot."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/assets/practices/opentelemetry-kubernetes/grafana-k8s-components-light.png"
FONT_PATH = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
WIDTH, HEIGHT = 1200, 675

BG = "#F7F8FC"
INK = "#172033"
MUTED = "#667085"
LINE = "#D9DFEA"
WHITE = "#FFFFFF"
GREEN = "#15966A"
GREEN_LIGHT = "#E7F7F0"
PURPLE = "#6D4AFF"
PURPLE_LIGHT = "#F0ECFF"


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size=size, index=1 if bold else 0)


def fit_cover(source: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Resize and center-crop source so it completely fills size."""
    target_width, target_height = size
    scale = max(target_width / source.width, target_height / source.height)
    resized = source.resize(
        (round(source.width * scale), round(source.height * scale)),
        Image.Resampling.LANCZOS,
    )
    left = (resized.width - target_width) // 2
    top = (resized.height - target_height) // 2
    return resized.crop((left, top, left + target_width, top + target_height))


def pill(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    *,
    fill: str,
    color: str,
) -> int:
    face = font(16, bold=True)
    bounds = draw.textbbox((0, 0), text, font=face)
    width = bounds[2] - bounds[0] + 34
    draw.rounded_rectangle((x, y, x + width, y + 38), radius=19, fill=fill)
    draw.text((x + 17, y + 8), text, font=face, fill=color)
    return x + width + 12


def build(source_path: Path, output_path: Path) -> None:
    source = Image.open(source_path).convert("RGB")
    # Remove browser/sidebar/breadcrumb information. The retained area contains
    # only the dashboard panels and their generic metric names.
    dashboard = source.crop((170, 65, min(1970, source.width), min(760, source.height)))
    dashboard = fit_cover(dashboard, (1100, 430))

    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.text(
        (50, 29),
        "Kubernetes 组件指标：OpenTelemetry → Prometheus → Grafana",
        font=font(31, bold=True),
        fill=INK,
    )
    draw.text(
        (52, 74),
        "API Server · Scheduler · Controller Manager · etcd · CoreDNS · Cluster State",
        font=font(16),
        fill=MUTED,
    )

    draw.rounded_rectangle((42, 112, 1158, 558), radius=18, fill=WHITE, outline=LINE, width=2)
    image.paste(dashboard, (50, 120))

    x = 50
    x = pill(draw, x, 585, "6 个采集目标在线", fill=GREEN_LIGHT, color=GREEN)
    x = pill(draw, x, 585, "11 个 Ready 节点", fill=GREEN_LIGHT, color=GREEN)
    x = pill(draw, x, 585, "API Server ≈ 57 req/s", fill=PURPLE_LIGHT, color=PURPLE)
    pill(draw, x, 585, "etcd leader = 1", fill=GREEN_LIGHT, color=GREEN)
    draw.text(
        (52, 640),
        "浅色 Grafana 实测截图 · 指标经 OTel Collector 汇聚并统一使用 otel_k8s_ 前缀",
        font=font(14),
        fill=MUTED,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("screenshot", type=Path, help="source Grafana screenshot")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    build(args.screenshot, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
