#!/usr/bin/env python3
"""Generate Qwen-Image-2.1 wide and square WeChat covers from real outputs."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


CHINESE = "/System/Library/Fonts/Hiragino Sans GB.ttc"
LATIN = "/System/Library/Fonts/HelveticaNeue.ttc"


def font(size: int, bold=False, latin=False):
    path = LATIN if latin else CHINESE
    return ImageFont.truetype(path, size, index=1 if bold else 0)


def gradient(size):
    width, height = size
    image = Image.new("RGB", size)
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            ratio = min(1.0, x / width * 0.72 + y / height * 0.28)
            start, end = (10, 27, 61), (31, 111, 226)
            pixels[x, y] = tuple(round(a + (b - a) * ratio) for a, b in zip(start, end))
    return image


def rounded_photo(path: Path, size, radius=28):
    with Image.open(path) as source:
        source.load()
        photo = ImageOps.fit(source.convert("RGB"), size, method=Image.Resampling.LANCZOS)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    photo.putalpha(mask)
    return photo


def wide(primary: Path, output: Path):
    image = gradient((900, 383))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((420, -190, 820, 210), fill=(106, 183, 255, 32))
    draw.text((55, 42), "AIK8S · 图像生成实测", font=font(18), fill=(173, 216, 255))
    draw.text((52, 90), "Qwen-Image-2.1", font=font(48, bold=True, latin=True), fill="white")
    draw.text((55, 158), "单卡 L20 · 双引擎实测", font=font(28, bold=True), fill=(235, 244, 255))
    draw.text((55, 215), "SGLang × vLLM-Omni", font=font(21, latin=True), fill=(194, 224, 255))
    draw.rounded_rectangle((55, 273, 432, 320), radius=22, fill=(9, 26, 62, 125), outline=(149, 211, 255, 130))
    draw.text((244, 296), "文字排版 · 透明 PNG · 批量工作台", font=font(17), fill="white", anchor="mm")
    draw.text((55, 345), "aik8s.run", font=font(15, latin=True), fill=(157, 210, 255))
    photo = rounded_photo(primary, (292, 292), 26)
    image.paste(photo, (566, 45), photo)
    draw.rounded_rectangle((560, 39, 864, 343), radius=31, outline=(180, 225, 255, 180), width=3)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, optimize=True)


def square(primary: Path, secondary: Path, output: Path):
    image = gradient((900, 900))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((480, -120, 970, 370), fill=(103, 190, 255, 35))
    draw.text((60, 62), "AIK8S · 图像生成实测", font=font(23), fill=(178, 219, 255))
    draw.text((56, 120), "Qwen-Image-2.1", font=font(59, bold=True, latin=True), fill="white")
    draw.text((60, 205), "单卡 L20 · SGLang × vLLM-Omni", font=font(29, bold=True), fill=(235, 245, 255))
    draw.rounded_rectangle((60, 274, 840, 320), radius=22, fill=(9, 26, 62, 125), outline=(149, 211, 255, 130))
    draw.text((450, 297), "真实样例 · 性能数据 · Grafana · 批量生成", font=font(19), fill="white", anchor="mm")
    first = rounded_photo(primary, (355, 355), 30)
    second = rounded_photo(secondary, (355, 355), 30)
    image.paste(first, (70, 365), first)
    image.paste(second, (475, 365), second)
    draw.rounded_rectangle((64, 359, 431, 726), radius=34, outline=(183, 226, 255, 180), width=3)
    draw.rounded_rectangle((469, 359, 836, 726), radius=34, outline=(183, 226, 255, 180), width=3)
    draw.text((248, 763), "产品摄影", font=font(23, bold=True), fill="white", anchor="mm")
    draw.text((653, 763), "写实街景", font=font(23, bold=True), fill="white", anchor="mm")
    draw.text((60, 850), "aik8s.run", font=font(18, latin=True), fill=(164, 214, 255))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, optimize=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--secondary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    wide(args.primary, args.output_dir / "cover.png")
    square(args.primary, args.secondary, args.output_dir / "cover-square.png")
    print(args.output_dir)


if __name__ == "__main__":
    main()
