#!/usr/bin/env python3
"""Render M3-style figures from the sanitized, measured M3.1 result export."""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from generate_glm53_day1_assets import font, BG, INK, MUTED, LINE, ORANGE

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/assets/practices/minimax-m31-flash-day0'
DATA = json.loads((OUT / 'vllm-results.json').read_text())


def text(d, x, y, value, size=23, color=INK, bold=False):
    f = font(size, bold=bold, latin=value.isascii())
    if bold and value.isascii():
        f = ImageFont.truetype('/System/Library/Fonts/HelveticaNeue.ttc', size, index=1)
    b = d.textbbox((0, 0), value, font=f)
    assert x + b[2] - b[0] < 1190, value
    d.text((x-b[0], y-b[1]), value, font=f, fill=color)


def frame(title, subtitle, note):
    im = Image.new('RGB', (1200, 675), BG); d = ImageDraw.Draw(im)
    text(d, 48, 36, title, 33, bold=True)
    text(d, 50, 96, subtitle, 21, MUTED)
    d.rounded_rectangle((48, 607, 1152, 657), 14, fill='white', outline=LINE)
    text(d, 65, 622, note, 19, MUTED)
    return im, d


def short(en):
    im, d = frame(
        '128 → 128: throughput and latency as concurrency rises' if en else '128 → 128：提高并发，吞吐与等待怎样变化',
        '8×H20-3e · vLLM · TP8 · median of 3 rounds · fixed token lengths' if en else '8×H20-3e · vLLM · TP8 · 每格三轮中位数 · 固定输入与输出长度',
        'Bars: output tok/s. Lines: round-level P95 TTFT, in ms. No dual axes.' if en else '左图为输出 Token/s；右图为每轮 P95 首 Token 延迟，单位 ms。')
    rows = [x for x in DATA['core'] if x['case'].startswith('short-')]
    for left, right, title, key, maximum, ticks in [
        (48, 584, 'Output tok/s' if en else '输出吞吐 · Token/s', 'output_throughput', 1800, [0, 600, 1200, 1800]),
        (610, 1152, 'P95 TTFT · ms', 'p95_ttft_ms', 600, [0, 200, 400, 600])]:
        d.rounded_rectangle((left, 146, right, 584), 18, fill='white', outline=LINE)
        text(d, left+22, 164, title, 24, bold=True)
        x0, x1, y0, y1 = left+68, right-28, 249, 516
        for t in ticks:
            y = y1-t/maximum*(y1-y0); d.line((x0, y, x1, y), fill=LINE)
            text(d, left+12, y-8, str(t), 17, MUTED)
        points = []
        for i, row in enumerate(rows):
            x = x0+(i+.5)*(x1-x0)/5; item = row[key]
            y = y1-item['median']/maximum*(y1-y0)
            if key == 'output_throughput':
                d.rounded_rectangle((x-23, y, x+23, y1), 6, fill=ORANGE)
            points.append((x, y))
            text(d, x-23, y-33, f"{item['median']:.0f}", 23, ORANGE, True)
            low, high = [y1-item[k]/maximum*(y1-y0) for k in ['min', 'max']]
            d.line((x, low, x, high), fill=INK, width=2)
            for yy in [low, high]: d.line((x-5, yy, x+5, yy), fill=INK, width=2)
            text(d, x-17, 542, 'C'+str(row['concurrency']), 20, MUTED)
        if key == 'p95_ttft_ms':
            d.line(points, fill=ORANGE, width=3)
            for x, y in points: d.ellipse((x-5, y-5, x+5, y+5), fill=ORANGE)
    im.save(OUT / ('short-en.png' if en else 'short-zh.png'))


def shapes(en):
    im, d = frame(
        'C8: longer inputs change the bottleneck' if en else '同样 C8，长输入改变了等待时间',
        '8×H20-3e · vLLM · 3 rounds per case · P95 metrics computed within each round' if en else '8×H20-3e · vLLM · 每格三轮 · P95 先在轮内计算，再取三轮中位数',
        'Synthetic fixed-length workload; these are serving measurements, not task scores.' if en else '固定长度合成负载；衡量服务性能，任务完成率需用真实工作流另测。')
    columns = [(70, 'Input → output' if en else '输入 → 输出'), (390, 'Output tok/s'), (660, 'P95 TTFT'), (914, 'P95 TPOT')]
    for x, v in columns: text(d, x, 169, v, 23, MUTED)
    for i, case in enumerate(['short-c8', 'rag4k-c8', 'agent8k-c8', 'rag16k-c8', 'decode2k-c8']):
        row = next(x for x in DATA['core'] if x['case'] == case); y = 225+i*69
        d.rounded_rectangle((48, y-15, 1152, y+43), 9, fill='white', outline=LINE)
        text(d, 70, y, f"{row['input_tokens']:,} → {row['output_tokens']:,}", 25)
        text(d, 390, y, f"{row['output_throughput']['median']:.1f}", 25, ORANGE, True)
        text(d, 660, y, f"{row['p95_ttft_ms']['median']/1000:.2f} s", 25)
        text(d, 914, y, f"{row['p95_tpot_ms']['median']:.2f} ms", 25)
    im.save(OUT / ('shapes-en.png' if en else 'shapes-zh.png'))


def long(en):
    im, d = frame(
        '1M input: all three seeds recovered all three codes' if en else '百万 Token 输入：三组种子，三处目标全部找回',
        'vLLM · max context 1,048,576 · max sequences 1 · prefix caching off' if en else 'vLLM · 服务上下文 1,048,576 · 最大序列 1 · 关闭前缀缓存',
        'Exact-match codes near 10% / 50% / 90%. Recall probes, not a reasoning benchmark.' if en else '在输入约 10% / 50% / 90% 处放置随机代码；结果为精确召回。')
    for x, value in [(72, 'Seed'), (256, 'Actual input' if en else '实际输入 Token'), (590, 'TTFT'), (805, 'E2E'), (1001, 'Recall' if en else '召回')]:
        text(d, x, 176, value, 23, MUTED)
    rows = [x for x in DATA['long_context'] if x['prompt_tokens'] > 1000000]
    for i, row in enumerate(rows):
        y = 259+i*96; d.rounded_rectangle((48, y-24, 1152, y+47), 12, fill='white', outline=LINE)
        for x, value, color in [(72, str(row['seed']), INK), (256, f"{row['prompt_tokens']:,}", ORANGE), (590, f"{row['ttft_s']:.2f} s", INK), (805, f"{row['elapsed_s']:.2f} s", INK), (1001, '3 / 3', '#168B76')]:
            text(d, x, y, value, 28, color, True)
    text(d, 72, 557, 'Usage reported by the server; complete SSE and exact JSON checked.' if en else '使用服务端 Usage 计数；同时检查完整流结束与 JSON 精确匹配。', 22, MUTED)
    im.save(OUT / ('long-en.png' if en else 'long-zh.png'))


if __name__ == '__main__':
    for english in [False, True]: short(english); shapes(english); long(english)
    print('Rendered six bilingual figures from measured result export')
