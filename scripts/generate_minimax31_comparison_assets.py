#!/usr/bin/env python3
"""M3-series bilingual figures from sanitized M3.1 deployment measurements."""
import argparse
import json
import math
from pathlib import Path
import statistics

from PIL import Image, ImageDraw, ImageFont
from generate_glm53_day1_assets import font, BG, INK, MUTED, LINE, BLUE, ORANGE

ROOT = Path(__file__).resolve().parents[1]
ENGINES = [('sglang', 'SGLang', BLUE), ('vllm', 'vLLM', ORANGE)]


def text(d, x, y, value, size=23, color=INK, bold=False):
    f = font(size, bold=bold, latin=value.isascii())
    if bold and value.isascii():
        f = ImageFont.truetype('/System/Library/Fonts/HelveticaNeue.ttc', size, index=1)
    b = d.textbbox((0, 0), value, font=f)
    assert x + b[2] - b[0] < 1185, value
    d.text((x-b[0], y-b[1]), value, font=f, fill=color)


def centered(d, x, y, value, size=23, color=INK, bold=False):
    f = font(size, bold=bold, latin=value.isascii())
    if bold and value.isascii():
        f = ImageFont.truetype('/System/Library/Fonts/HelveticaNeue.ttc', size, index=1)
    b = d.textbbox((0, 0), value, font=f)
    d.text((x-(b[0]+b[2])/2, y-b[1]), value, font=f, fill=color)


def frame(title, subtitle, note):
    im = Image.new('RGB', (1200, 675), BG); d = ImageDraw.Draw(im)
    text(d, 48, 38, title, 33, bold=True)
    text(d, 50, 98, subtitle, 21, MUTED)
    for x, (_, label, color) in zip([855, 1014], ENGINES):
        d.rounded_rectangle((x, 37, x+135, 78), 20, fill='white', outline=LINE)
        d.rounded_rectangle((x+13, 52, x+32, 63), 3, fill=color)
        text(d, x+42, 49, label, 21, color)
    d.rounded_rectangle((48, 607, 1152, 656), 14, fill='white', outline=LINE)
    text(d, 64, 622, note, 19, MUTED)
    return im, d


def grouped(out, name, title, subtitle, note, groups, unit, decimals=0):
    im, d = frame(title, subtitle, note)
    max_value = max(v['max'] for _, pair in groups for v in pair.values() if v is not None)
    raw_tick = max_value * 1.12 / 5
    magnitude = 10 ** math.floor(math.log10(raw_tick or 1))
    tick = next(x*magnitude for x in [1, 2, 2.5, 5, 10] if x*magnitude >= raw_tick)
    maximum = math.ceil(max_value * 1.12 / tick) * tick
    left, right, top, bottom = 104, 1152, 204, 512
    text(d, left, 163, unit, 22, MUTED)
    for i in range(int(round(maximum/tick))+1):
        value = i*tick; y = bottom-value/maximum*(bottom-top)
        d.line((left, y, right, y), fill=LINE)
        text(d, 50, y-8, f'{value:g}', 18, MUTED)
    step = (right-left)/len(groups)
    for i, (label, pair) in enumerate(groups):
        mid = left+(i+.5)*step
        for j, (key, _, color) in enumerate(ENGINES):
            x = mid+(j-.5)*84; v = pair.get(key)
            if v is None:
                centered(d, x, bottom-34, 'N/A', 22, '#D64949'); continue
            y = bottom-v['median']/maximum*(bottom-top)
            d.rounded_rectangle((x-28, y, x+28, bottom), 7, fill=color)
            lo = bottom-v['min']/maximum*(bottom-top); hi = bottom-v['max']/maximum*(bottom-top)
            d.line((x, lo, x, hi), fill=INK, width=2)
            for yy in [lo, hi]: d.line((x-5, yy, x+5, yy), fill=INK, width=2)
            centered(d, x, hi-34, f"{v['median']:.{decimals}f}", 24, color, True)
        for row, line in enumerate(label.split('\n')):
            centered(d, mid, 532+row*27, line, 22 if row == 0 else 19, MUTED)
    im.save(out/name, optimize=True)


def core_groups(data, cases, metric, scale=1):
    pairs = []
    for label, case in cases:
        values = {}
        for engine, _, _ in ENGINES:
            row = next(x for x in data[engine]['core'] if x['case'] == case)
            if engine == 'sglang' and row.get('executed_rounds', 3) < 3:
                return None
            raw = row.get(metric)
            values[engine] = {k: v/scale for k, v in raw.items()} if raw else None
        pairs.append((label, values))
    return pairs


def render(data, out):
    out.mkdir(parents=True, exist_ok=True)
    for en in [False, True]:
        suffix = 'en' if en else 'zh'
        subtitle = ('8×H20-3e · TP8 · different nodes · 3-round medians and ranges' if en else
                    '8×H20-3e · TP8 · 同卡型不同节点 · 各工况三轮中位数与范围')
        short = core_groups(data, [('C'+str(c), 'short-c'+str(c)) for c in [1,4,8,16,32]], 'output_throughput')
        if short:
            grouped(out, f'comparison-short-{suffix}.png',
                    '128 → 128: output throughput' if en else '128 → 128：输出吞吐对比', subtitle,
                    'Fixed input and output lengths. These are measured configurations, not engine-only effects.' if en else
                    '固定输入与输出长度；比较本轮具体部署配置，节点和实现差异均需纳入解释。',
                    short, 'Output Token/s' if en else '输出 Token/s')
        workloads = core_groups(data, [('4K → 256\nC8','rag4k-c8'),('8K → 1K\nC8','agent8k-c8'),('16K → 256\nC8','rag16k-c8')], 'p95_ttft_ms', 1000)
        if workloads:
            grouped(out, f'comparison-prefill-{suffix}.png',
                    'Long inputs: P95 first-token latency' if en else '长输入：P95 首 Token 等待', subtitle,
                    'P95 is computed within each round, then summarized across the three rounds.' if en else
                    'P95 先在轮内计算，再汇总三轮；更低的首 Token 等待更适合交互请求。',
                    workloads, 'P95 TTFT · s', 2)
        decode = core_groups(data, [('C'+str(c), 'decode2k-c'+str(c)) for c in [1,4,8]], 'p95_tpot_ms')
        if decode:
            grouped(out, f'comparison-decode-{suffix}.png',
                    '128 → 2K: P95 time per output token' if en else '128 → 2K：P95 每输出 Token 耗时', subtitle,
                    'P95 of per-request average TPOT, not the percentile of individual token gaps.' if en else
                    'P95 为请求级平均 TPOT 的分位数，不是逐 Token 间隔的分位数。',
                    decode, 'P95 TPOT · ms', 2)
        if len(data['sglang']['long_context']) == 7:
            groups = []
            for context, label in [(65536,'64K'),(131072,'128K'),(262144,'256K'),(524288,'512K'),(1048576,'1M')]:
                pair = {}
                for engine, _, _ in ENGINES:
                    rows = [x for x in data[engine]['long_context'] if x['target_context'] == context and x['status'] == 'PASS']
                    values = [x['ttft_s'] for x in rows]
                    pair[engine] = {'median':statistics.median(values),'min':min(values),'max':max(values)} if values else None
                groups.append((label, pair))
            grouped(out, f'comparison-long-{suffix}.png',
                    'Long-context recall: first-token latency' if en else '长上下文召回：首 Token 等待',
                    '8×H20-3e · TP8 · max context 1,048,576 · max sequences 1' if en else
                    '8×H20-3e · TP8 · 服务上下文 1,048,576 · 最大序列 1',
                    '64K–512K: one probe each. 1M: median/range of three seeds; see actual token counts.' if en else
                    '64K–512K 各一个样例；1M 为三组种子的中位数与范围，实际输入计数见正文。',
                    groups, 'TTFT · s', 1)
    print('Figures rendered:', ', '.join(x.name for x in sorted(out.glob('comparison-*.png'))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, default=ROOT/'docs/assets/practices/minimax-m31-flash-day0/comparison-results.json')
    parser.add_argument('--output', type=Path, default=ROOT/'docs/assets/practices/minimax-m31-flash-day0')
    args = parser.parse_args(); render(json.loads(args.data.read_text()), args.output)
