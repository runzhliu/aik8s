#!/usr/bin/env python3
"""Render Qwen-Image-2.1 extended-test figures in the MiniMax-M3 layout."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/assets/practices/qwen-image21-l20"
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
BG = "#f6f8fc"
PANEL = "#ffffff"
INK = "#18233b"
MUTED = "#6d7890"
GRID = "#dce3ef"
BLUE = "#1769e0"
PURPLE = "#7558df"
GREEN = "#16856b"
RED = "#d34f5f"
AMBER = "#d27a12"


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT, size, index=1 if bold else 0)


def text(draw, xy, value, size=24, fill=INK, anchor=None, bold=False):
    draw.text(xy, value, font=font(size, bold), fill=fill, anchor=anchor)


def rounded(draw, box, fill=PANEL, outline=GRID, radius=18, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def native_matrix(rows: list[dict[str, str]], output: Path):
    image = Image.new("RGB", (1200, 675), BG)
    draw = ImageDraw.Draw(image)
    text(draw, (52, 31), "官方原生画幅：默认配置与 VAE Tiling 的边界", 35, bold=True)
    text(draw, (53, 80), "单卡 L20 · 40 步 · C1 · 每格 1 次预热 + 3 个正式请求", 19, MUTED)

    columns = [
        ("SGLang", "default", "SGLang\n默认"),
        ("SGLang", "vae-tiling", "SGLang\nTiling"),
        ("vLLM-Omni Preview", "default", "vLLM-Omni\n默认"),
        ("vLLM-Omni Preview", "vae-tiling", "vLLM-Omni\nTiling"),
    ]
    sizes = ["2048x2048", "2400x1792", "1792x2400", "2528x1696", "1696x2528", "2752x1536", "1536x2752"]
    lookup = {(row["engine"], row["profile"], row["size"]): row for row in rows if row["kind"] == "text-to-image"}
    x0, y0, row_h = 50, 120, 60
    widths = [170, 235, 235, 235, 235]
    xs = [x0]
    for width in widths:
        xs.append(xs[-1] + width)
    rounded(draw, (x0, y0, xs[-1], y0 + row_h * 8), radius=16)
    draw.rectangle((x0, y0, xs[-1], y0 + row_h), fill="#eaf0ff")
    text(draw, (x0 + 18, y0 + row_h / 2), "输出尺寸", 19, bold=True, anchor="lm")
    for index, (_, _, label) in enumerate(columns):
        cx = (xs[index + 1] + xs[index + 2]) / 2
        a, b = label.split("\n")
        text(draw, (cx, y0 + 20), a, 18, bold=True, anchor="mm")
        text(draw, (cx, y0 + 42), b, 16, PURPLE if "Tiling" in b else MUTED, anchor="mm")
    for row_index, size in enumerate(sizes, 1):
        top = y0 + row_index * row_h
        if row_index % 2 == 0:
            draw.rectangle((x0 + 1, top, xs[-1] - 1, top + row_h), fill="#fbfcff")
        draw.line((x0, top, xs[-1], top), fill=GRID, width=1)
        text(draw, (x0 + 18, top + row_h / 2), size.replace("x", "×"), 18, bold=True, anchor="lm")
        for col_index, (engine, profile, _) in enumerate(columns):
            item = lookup.get((engine, profile, size))
            left, right = xs[col_index + 1], xs[col_index + 2]
            if not item:
                label, detail, color = "—", "未执行", MUTED
            elif item["status"] == "PASS":
                label = "PASS"
                detail = f"P50 {float(item['p50_seconds']):.1f}s"
                color = GREEN
            else:
                label = "FAIL"
                detail = f"{item['succeeded']}/{item['attempted']}"
                color = RED
            cx = (left + right) / 2
            text(draw, (cx, top + 21), label, 17, color, anchor="mm", bold=True)
            text(draw, (cx, top + 43), detail, 15, MUTED, anchor="mm")
    for x in xs[1:-1]:
        draw.line((x, y0, x, y0 + row_h * 8), fill=GRID, width=1)
    text(draw, (600, 645), "FAIL 保留原始分母；Tiling 组没有降低尺寸、步数或参考图数量。", 17, MUTED, anchor="mm")
    image.save(output)


def first_success(root: Path, case: str) -> Path | None:
    case_root = root / case
    for result_path in sorted(case_root.glob("measured-*.result.json")):
        import json

        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("success") and result.get("images"):
            return case_root / result["images"][0]["path"]
    return None


def fit(path: Path, size: tuple[int, int]) -> Image.Image:
    with Image.open(path) as source:
        source.load()
        return ImageOps.fit(source.convert("RGB"), size, method=Image.Resampling.LANCZOS)


def editing_gallery(sglang: Path, vllm: Path, output: Path):
    image = Image.new("RGB", (1200, 675), BG)
    draw = ImageDraw.Draw(image)
    text(draw, (52, 29), "图片编辑：1、4、10 张参考图进入同一条服务链路", 35, bold=True)
    text(draw, (53, 79), "1024×1024 · 40 步 · 图中为正式请求原始 PNG；配置与失败原因见正文", 18, MUTED)
    cases = [("edit-ref1-1024", "1 张参考图"), ("edit-ref4-1024", "4 张参考图"), ("edit-ref10-1024", "10 张参考图")]
    roots = [(sglang, "SGLang", BLUE), (vllm, "vLLM-Omni", PURPLE)]
    for col, (case, label) in enumerate(cases):
        x = 70 + col * 365
        text(draw, (x + 155, 119), label, 20, INK, anchor="mm", bold=True)
        for row, (root, engine, color) in enumerate(roots):
            y = 148 + row * 226
            rounded(draw, (x, y, x + 310, y + 202), radius=15)
            path = first_success(root, case)
            if path:
                thumb = fit(path, (174, 174))
                image.paste(thumb, (x + 12, y + 14))
                draw.rectangle((x + 12, y + 14, x + 186, y + 188), outline=GRID, width=1)
                text(draw, (x + 199, y + 65), engine, 17, color, bold=True)
                text(draw, (x + 199, y + 99), "HTTP、PNG", 15, MUTED)
                text(draw, (x + 199, y + 124), "尺寸校验通过", 15, GREEN)
            else:
                text(draw, (x + 155, y + 82), engine, 18, color, anchor="mm", bold=True)
                text(draw, (x + 155, y + 122), "未取得成功图片", 17, RED, anchor="mm")
    text(draw, (600, 635), "传输与尺寸通过不等于十个主体都被准确保留；正文单独记录视觉复核。", 17, MUTED, anchor="mm")
    image.save(output)


def extended_2k_gallery(sglang: Path, vllm: Path, output: Path):
    image = Image.new("RGB", (1200, 675), BG)
    draw = ImageDraw.Draw(image)
    text(draw, (52, 29), "2K 原生生成与 2048 编辑：正式请求原图", 35, bold=True)
    text(draw, (53, 79), "单卡 L20 · VAE Tiling · 40 步 · 缩略图只做等比裁切，不做增强", 18, MUTED)
    cards = [
        (sglang, "native-1x1", "SGLang", "原生 2K · P50 140.3s", BLUE),
        (vllm, "native-1x1", "vLLM-Omni", "原生 2K · P50 162.4s", PURPLE),
        (sglang, "edit-ref1-2048", "SGLang", "单图编辑 · P50 197.0s", BLUE),
        (vllm, "edit-ref1-2048", "vLLM-Omni", "单图编辑 · P50 176.7s", PURPLE),
    ]
    for index, (root, case, engine, detail, color) in enumerate(cards):
        x = 44 + index * 286
        rounded(draw, (x, 130, x + 260, 574), radius=19)
        path = first_success(root, case)
        if path:
            thumb = fit(path, (232, 300))
            image.paste(thumb, (x + 14, 145))
            draw.rectangle((x + 14, 145, x + 246, 445), outline=GRID, width=1)
        else:
            text(draw, (x + 130, 292), "未取得成功图片", 17, RED, anchor="mm")
        text(draw, (x + 20, 486), engine, 20, color, bold=True)
        text(draw, (x + 20, 526), detail, 16, MUTED)
    text(draw, (600, 628), "所有图片均通过 PNG 解码、目标尺寸与 SHA-256 核对；视觉语义仍需人工验收。", 17, MUTED, anchor="mm")
    image.save(output)


def safety_pipeline(output: Path):
    image = Image.new("RGB", (1200, 675), BG)
    draw = ImageDraw.Draw(image)
    text(draw, (52, 34), "NSFW 不是一个开关，而是一条发布前治理链", 35, bold=True)
    text(draw, (53, 84), "本地部署后，输入、输出、真人授权和留痕责任都由服务运营方承担", 19, MUTED)
    stages = [
        ("01", "身份与权限", "实名账号、角色权限\n批量额度与速率限制", BLUE),
        ("02", "输入审核", "文本与参考图一起判断\n未成年人和真人滥用拒绝", PURPLE),
        ("03", "隔离生成", "任务与对象使用临时 ID\n输出先进入隔离区", AMBER),
        ("04", "输出审核", "多模态复审与人工升级\n通过后才展示或下载", GREEN),
        ("05", "标识与审计", "显式/隐式标识、版本\nPrompt 摘要与处置记录", "#315f9f"),
    ]
    for index, (number, title, body, color) in enumerate(stages):
        x = 35 + index * 230
        rounded(draw, (x, 160, x + 205, 500), radius=20)
        draw.rounded_rectangle((x + 20, 185, x + 74, 239), radius=15, fill=color)
        text(draw, (x + 47, 212), number, 18, "white", anchor="mm", bold=True)
        text(draw, (x + 20, 277), title, 22, INK, bold=True)
        for line, value in enumerate(body.splitlines()):
            text(draw, (x + 20, 327 + line * 35), value, 16, MUTED)
        if index < len(stages) - 1:
            draw.line((x + 205, 330, x + 225, 330), fill="#9aa8bd", width=4)
            draw.polygon([(x + 225, 330), (x + 214, 323), (x + 214, 337)], fill="#9aa8bd")
    text(draw, (600, 570), "默认拒绝：未成年人性内容、真人色情化/换脸、无授权私密内容", 19, RED, anchor="mm", bold=True)
    text(draw, (600, 618), "能力边界测试可以不生成露骨样例；更有价值的是验证阻断、审计与删除流程。", 17, MUTED, anchor="mm")
    image.save(output)


def home_gpu_guide(output: Path, sglang_peak_gb: float, vllm_peak_gb: float):
    image = Image.new("RGB", (1200, 675), BG)
    draw = ImageDraw.Draw(image)
    text(draw, (52, 33), "家庭部署：先按显存档位选目标，再谈速度", 35, bold=True)
    text(draw, (53, 83), f"L20 实测峰值：SGLang {sglang_peak_gb:.1f} GB；vLLM-Omni {vllm_peak_gb:.1f} GB", 19, MUTED)
    cards = [
        ("48 GB", "完整 BF16 起点", "先跑 1024 与 C1\n2K 必须验证 VAE 峰值\nTiling 仍是稳定性参数", GREEN),
        ("32 GB / 5090", "社区 W4A4 路线", "作者报告约 21.5 GB 常驻\nNVFP4 版本只支持 Blackwell\n质量、编辑和依赖仍须复测", PURPLE),
        ("16–24 GB / Mac", "INT8、GGUF、MLX", "权重文件不等于整条 Pipeline\n编码器、VAE 与 Offload 仍占内存\n优先从 ComfyUI 工作流验证", AMBER),
    ]
    for index, (capacity, title, body, color) in enumerate(cards):
        x = 55 + index * 375
        rounded(draw, (x, 150, x + 340, 515), radius=24)
        badge_width = max(120, min(280, draw.textbbox((0, 0), capacity, font=font(20, True))[2] + 40))
        draw.rounded_rectangle((x + 25, 180, x + 25 + badge_width, 230), radius=17, fill=color)
        text(draw, (x + 25 + badge_width / 2, 205), capacity, 20, "white", anchor="mm", bold=True)
        text(draw, (x + 25, 278), title, 24, INK, bold=True)
        for line, value in enumerate(body.splitlines()):
            text(draw, (x + 25, 332 + line * 42), value, 18, MUTED)
    text(draw, (600, 574), "官方仓库当前仍是 BF16；量化版本来自社区，必须固定仓库、Runtime 与校验样例", 17, BLUE, anchor="mm", bold=True)
    text(draw, (600, 615), "个人创作优先 ComfyUI；局域网 API 再评估服务化、并发与监控", 18, PURPLE, anchor="mm", bold=True)
    image.save(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-csv", type=Path, required=True)
    parser.add_argument(
        "--sglang-edits",
        type=Path,
        required=True,
        help="Merged SGLang edit-case result directory; cases may come from different validated profiles.",
    )
    parser.add_argument(
        "--vllm-edits",
        type=Path,
        required=True,
        help="Merged vLLM-Omni edit-case result directory; cases may come from different validated profiles.",
    )
    parser.add_argument("--sglang-tiling-root", type=Path, required=True)
    parser.add_argument("--vllm-tiling-root", type=Path, required=True)
    parser.add_argument("--sglang-peak-gb", type=float, required=True)
    parser.add_argument("--vllm-peak-gb", type=float, required=True)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = read_rows(args.matrix_csv)
    native_matrix(rows, OUT / "extended-native-matrix.png")
    editing_gallery(args.sglang_edits, args.vllm_edits, OUT / "editing-reference-gallery.png")
    extended_2k_gallery(args.sglang_tiling_root, args.vllm_tiling_root, OUT / "extended-2k-samples.png")
    safety_pipeline(OUT / "nsfw-governance.png")
    home_gpu_guide(OUT / "home-gpu-deployment.png", args.sglang_peak_gb, args.vllm_peak_gb)
    print(OUT)


if __name__ == "__main__":
    main()
