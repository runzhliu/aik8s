#!/usr/bin/env python3
"""Compose the Sleep covers with the confirmed MiniMax M3 light layout."""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'articles/wechat/assets/vllm-sleep-l20/brand-cover'
BG, INK, MUTED = '#FFF8F2', '#382B25', '#8A7364'
ACCENT, LINE, SOFT = '#B95016', '#EDCCB8', '#FFF0E2'
FONT = '/System/Library/Fonts/Hiragino Sans GB.ttc'
LATIN = '/System/Library/Fonts/HelveticaNeue.ttc'


def text(draw, xy, value, size, color=INK, latin=False):
    font = ImageFont.truetype(LATIN if latin else FONT, size, index=1 if latin else 0)
    box = draw.textbbox((0, 0), value, font=font)
    assert xy[0] + box[2] - box[0] <= draw._image.width - 32
    assert xy[1] + box[3] - box[1] <= draw._image.height - 24
    draw.text((xy[0] - box[0], xy[1] - box[1]), value, font=font, fill=color)


def center(draw, box, value, size, color=INK, latin=False):
    font = ImageFont.truetype(LATIN if latin else FONT, size, index=1 if latin else 0)
    bounds = draw.textbbox((0, 0), value, font=font)
    assert bounds[2] - bounds[0] <= box[2] - box[0] - 12
    assert bounds[3] - bounds[1] <= box[3] - box[1] - 8
    draw.text(((box[0] + box[2] - bounds[2] - bounds[0]) / 2,
               (box[1] + box[3] - bounds[3] - bounds[1]) / 2),
              value, font=font, fill=color)


def rail(draw, height, width):
    start, end = (226, 93, 36), (255, 169, 78)
    for y in range(height):
        t = y / (height - 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip(start, end))
        draw.line((0, y, width, y), fill=color)


def tile(draw, box, label, size, active=False):
    draw.rounded_rectangle(box, radius=9, fill=SOFT if active else 'white', outline=LINE, width=2)
    center(draw, box, label, size, ACCENT if active else MUTED)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (900, 383), BG)
    draw = ImageDraw.Draw(image)
    rail(draw, 383, 12)
    text(draw, (45, 36), 'AI-K8S 技术工程', 18, ACCENT)
    text(draw, (45, 95), 'vLLM Sleep', 54, ACCENT, latin=True)
    text(draw, (45, 173), '单卡双模型，按需唤醒', 33)
    text(draw, (45, 258), 'L20 · Sleep / Wake', 26, ACCENT, latin=True)
    text(draw, (45, 320), '显存交接 · 恢复实测 · DRA 思考', 20, MUTED)
    tile(draw, (638, 106, 837, 184), '一张 L20', 27, active=True)
    draw.line((684, 184, 684, 220), fill=LINE, width=3)
    draw.line((790, 184, 790, 220), fill=LINE, width=3)
    tile(draw, (626, 220, 731, 278), '模型 A', 21, active=True)
    tile(draw, (747, 220, 852, 278), '模型 B', 21)
    center(draw, (618, 291, 860, 326), '轮流运行 · 按需恢复', 19, MUTED)
    image.save(OUT / 'cover.png', optimize=True)

    image = Image.new('RGB', (900, 900), BG)
    draw = ImageDraw.Draw(image)
    rail(draw, 900, 14)
    text(draw, (62, 66), 'AI-K8S 技术工程', 25, ACCENT)
    text(draw, (62, 177), 'vLLM Sleep', 75, ACCENT, latin=True)
    text(draw, (62, 310), '单卡双模型', 64)
    text(draw, (62, 420), '显存交接与按需唤醒', 42)
    tile(draw, (65, 532, 835, 612), '一张 L20 · 两个常驻引擎', 31, active=True)
    draw.line((252, 612, 252, 646), fill=LINE, width=3)
    draw.line((648, 612, 648, 646), fill=LINE, width=3)
    tile(draw, (65, 646, 439, 718), '模型 A', 29, active=True)
    tile(draw, (461, 646, 835, 718), '模型 B', 29)
    text(draw, (62, 778), 'L20 · 恢复实测 · DRA 思考', 30, ACCENT)
    image.save(OUT / 'cover-square.png', optimize=True)

    (OUT / 'palette.json').write_text(json.dumps({
        'layout_reference': 'articles/wechat/assets/minimax-m3-h20/brand-cover/',
        'layout': 'Light background, left title, simple right-side device tiles; independently composed square variant',
        'palette_scope': 'Editorial orange for the vLLM series, not a claim of official corporate brand colors',
        'editorial_palette': {'background': BG, 'ink': INK, 'muted': MUTED, 'accent': ACCENT, 'line': LINE},
        'source': 'scripts/generate_vllm_sleep_brand_covers.py',
        'main_cover': 'cover.png', 'sharing_cover': 'cover-square.png',
    }, ensure_ascii=False, indent=2) + '\n')
    print(OUT)


if __name__ == '__main__':
    main()
