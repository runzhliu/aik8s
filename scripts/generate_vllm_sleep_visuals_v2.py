#!/usr/bin/env python3
"""M3-style figures from measured aggregates and unchanged real screenshots.

The input directory contains real Grafana panel captures. This script adds
article framing, scales uniformly, and crops only irrelevant chat chrome.
It neither synthesizes dashboard evidence nor regenerates the existing cover.
"""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from generate_minimax_m3_visuals_v2 import (
    BLUE, INK, LINE, MUTED, ORANGE, center, footer, header, txt,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'docs/assets/practices/vllm-sleep-l20/benchmark-summary.json'
OUT = DATA.parent / 'v2'
WECHAT = ROOT / 'articles/wechat/assets/vllm-sleep-l20/v2'


def canvas(title, subtitle, legend=True):
    image, draw = header(title, subtitle, False)
    if legend:
        for x, label, color, background in [
            (864, 'A · 27B', BLUE, '#EAF1FF'),
            (1020, 'B · 1.7B', ORANGE, '#FFF1E8'),
        ]:
            draw.rounded_rectangle((x, 32, x + 136, 76), 22, fill=background)
            draw.rounded_rectangle((x + 13, 49, x + 33, 60), 3, fill=color)
            txt(draw, x + 43, 46, label, 21, latin=True)
    return image, draw


def restart_chart(data):
    image, draw = canvas(
        '重启与唤醒：首 Token 等待',
        '单张 L20 · 重启 2 次 / Level 1 5 次 / Level 2 3 次 · 中位数与范围',
    )
    left, top, right, bottom, maximum = 90, 191, 1150, 510, 65
    for value in [0, 15, 30, 45, 60]:
        y = bottom - value / maximum * (bottom - top)
        draw.line((left, y, right, y), fill=LINE)
        center(draw, (32, y - 13, 75, y + 13), str(value), 20, fill=MUTED)
    evidence = []
    for i, label in enumerate(['进程重启', 'Level 1', 'Level 2']):
        middle = left + (i + .5) * (right - left) / 3
        for j, (model, color) in enumerate([('A', BLUE), ('B', ORANGE)]):
            source = data['models'][model]
            value = source['restart_warm'] if i == 0 else source['sleep'][str(i)]['to_first_token_s']
            assert value['n'] == [2, 5, 3][i]
            assert 0 <= value['min'] <= value['median'] <= value['max'] <= maximum
            x = middle + (j - .5) * 90
            y = bottom - value['median'] / maximum * (bottom - top)
            draw.rounded_rectangle((x - 30, y, x + 30, bottom), 7, fill=color)
            lo = bottom - value['min'] / maximum * (bottom - top)
            hi = bottom - value['max'] / maximum * (bottom - top)
            draw.line((x, hi, x, lo), fill=INK, width=2)
            for endpoint in [lo, hi]:
                draw.line((x - 6, endpoint, x + 6, endpoint), fill=INK, width=2)
            center(draw, (x - 44, hi - 37, x + 44, hi - 6), f"{value['median']:.2f}", 25, fill=color, bold=True)
            evidence.append({'figure': 'restart-vs-wake.png', 'model': model, 'mode': label, **value})
        center(draw, (middle - 150, 527, middle + 150, 564), label, 23)
    footer(draw, '秒，越低越好 · 重启为同 Pod 缓存条件 · 两个模型使用相同纵轴')
    image.save(OUT / 'restart-vs-wake.png', optimize=True)
    return evidence


def paste_capture(image, draw, source, box, heading=None):
    draw.rounded_rectangle(box, 18, fill='white', outline=LINE, width=2)
    original = Image.open(source).convert('RGB')
    heading_height = 44 if heading else 0
    if heading:
        txt(draw, box[0] + 24, box[1] + 22, heading, 24, bold=True)
    fitted = ImageOps.contain(original, (box[2] - box[0] - 24, box[3] - box[1] - 24 - heading_height), Image.Resampling.LANCZOS)
    position = (box[0] + (box[2] - box[0] - fitted.width) // 2,
                box[1] + heading_height + (box[3] - box[1] - heading_height - fitted.height) // 2)
    image.paste(fitted, position)
    return {'sha256': hashlib.sha256(Path(source).read_bytes()).hexdigest(), 'dimensions': list(original.size)}


def evidence_figures(screenshots):
    manifest = []
    for name, title, subtitle, note in [
        ('switch', '休眠交出显存：约 33 → 1 GiB',
         '单张 L20 · A 为 27B FP8，B 为 1.7B BF16 · 两套引擎交替运行',
         '交出约 32 GiB 显存 · 进程仍在 · 极短的切换低谷可能落在两次采样之间'),
        ('timing', '恢复前后：C4 输出吞吐保持接近',
         '短提示词 / 输出 128 Token · 每配置 8 请求 × 2 轮 · C4',
         '实线为恢复前，虚线为恢复后 · 曲线为最近完成一轮的吞吐读数'),
    ]:
        image, draw = canvas(title, subtitle, legend=name != 'switch')
        metadata = paste_capture(image, draw, screenshots / f'{name}.png', (48, 146, 1152, 584))
        footer(draw, note)
        filename = f'grafana-{name}.png'
        image.save(OUT / filename, optimize=True)
        manifest.append({'figure': filename, 'source': f'{name}.png', **metadata})

    image, draw = canvas(
        '首 Token 与逐 Token：恢复前后的延迟',
        '单张 L20 · C4 · 短提示词 / 输出 128 Token · 一分钟滑动均值',
    )
    for slug, heading, box in [('ttft', 'TTFT · 首 Token 延迟', (48, 146, 588, 584)), ('tpot', 'TPOT · 每输出 Token 时间', (612, 146, 1152, 584))]:
        metadata = paste_capture(image, draw, screenshots / f'{slug}.png', box, heading)
        manifest.append({'figure': 'grafana-latency.png', 'source': f'{slug}.png', **metadata})
    footer(draw, 'TTFT：首 Token 延迟 · TPOT：每输出 Token 时间 · 一分钟滑动均值')
    image.save(OUT / 'grafana-latency.png', optimize=True)
    return manifest


def chat_figure(source):
    image, draw = canvas(
        '真实交互：Qwen3-1.7B 的生成样例',
        '单张 L20 · 独立交互验证 · 不计入正式 170 条请求', False,
    )
    draw.rounded_rectangle((48, 146, 1152, 584), 18, fill='white', outline=LINE, width=2)
    original = Image.open(source).convert('RGB')
    assert original.size == (1200, 675), 'Review crop bounds when the source screenshot changes'
    cropped = original.crop((132, 40, 1145, 302))
    scaled = ImageOps.contain(cropped, (1072, 360), Image.Resampling.LANCZOS)
    image.paste(scaled, (64 + (1072 - scaled.width) // 2, 190))
    txt(draw, 80, 522, '提示词：用三点解释 Pod 与 Deployment 的关系', 21, fill=MUTED)
    footer(draw, '真实聊天截图局部 · 模型名、提示词与回答保持原样')
    image.save(OUT / 'openwebui-chat-light.png', optimize=True)
    return {'figure': 'openwebui-chat-light.png', 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'crop': [132, 40, 1145, 302]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshots-dir', type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(DATA.read_text())
    assert data['status'] == 'PASS'
    OUT.mkdir(parents=True, exist_ok=True)
    WECHAT.mkdir(parents=True, exist_ok=True)
    measurements = restart_chart(data)
    evidence = evidence_figures(args.screenshots_dir)
    evidence.append(chat_figure(DATA.parent / 'openwebui-chat-light.png'))
    manifest = {'style': 'MiniMax M3 v2', 'dimensions': [1200, 675], 'measurement_sha256': hashlib.sha256(DATA.read_bytes()).hexdigest(), 'measurements': measurements, 'captures': evidence}
    (OUT / 'visual-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    for path in OUT.glob('*.png'):
        shutil.copyfile(path, WECHAT / path.name)
    print('Generated five M3-style figures; existing covers unchanged.')


if __name__ == '__main__':
    main()
