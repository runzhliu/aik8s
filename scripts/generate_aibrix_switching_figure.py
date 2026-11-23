"""Plot the measured ModelClaim 14B handoff from the public CSV records."""
import csv
import math
from datetime import datetime
from pathlib import Path

from PIL import Image
from generate_dsv41_vllm032_research_assets import GRID, INK, MUTED, NEW, S, header, line, rect, text

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'docs/assets/practices/aibrix-modelclaim-l20'
COLORS = {'Active': '#619F8D', 'Sleeping': '#BFC7C3', 'Activating': '#E6EAE8', 'Pending': 'white'}


def rows(name):
    with (DATA / name).open() as source:
        return list(csv.DictReader(source))


def ts(row):
    return datetime.fromisoformat(row['utc']).timestamp()


def draw(english):
    stages = rows('switch-stages.csv')
    events = rows('switch-states.csv')
    start, end = ts(stages[0]), ts(stages[-1])
    duration = end - start
    device = [r for r in rows('switch-device.csv') if start <= ts(r) <= end]
    title = 'Two 14B engines take turns on one L20' if english else '一张 L20 上，两个 14B 模型轮流接手'
    subtitle = 'Device memory sampled on the Pod and claim phases observed from Kubernetes' if english else '上方是实验 Pod 内采样的整卡显存，下方是控制器报告的模型状态'
    im, d = header(title, not english, subtitle)
    left, right, top, bottom = 178, 1144, 193, 396

    def x(t):
        return left + (right-left)*(min(end,max(start,t))-start)/duration

    def y(gib):
        return bottom - (bottom-top)*gib/45

    text(d, 56, 154, 'Used GPU memory  /  GiB' if english else '整卡已用显存  /  GiB', 22, INK)
    for amount in [0,10,20,30,40]:
        line(d,left,y(amount),right,y(amount),GRID)
        text(d,left-12,y(amount)-8,str(amount),18,MUTED,'right')
    for before, after in zip(device,device[1:]):
        line(d,x(ts(before)),y(int(before['used_mib'])/1024),
             x(ts(after)),y(int(after['used_mib'])/1024),NEW,3)
    for t in range(0,math.ceil(duration),60):
        text(d,x(start+t),bottom+12,f'{t//60}',17,MUTED,'center')
    text(d,right,bottom+38,'Minutes since A was serving' if english else '自 A 提供服务起 / 分钟',17,MUTED,'right')
    for short,yy,name in [('A',478,'Qwen3-14B'),('B',527,'R1-Distill-14B')]:
        text(d,left-14,yy+1,name,20,INK,'right')
        line(d,left,yy+12,right,yy+12,'#D0D6D2',1)
        for i,row in enumerate(events):
            u=max(start,ts(row));v=min(end,ts(events[i+1]) if i+1<len(events) else end)
            phase=row[short]
            if v<=u or phase not in COLORS or phase=='Pending':continue
            rect(d,x(u),yy,max(0.5,x(v)-x(u)),24,COLORS[phase])
    labels=(['Serving','Starting','Asleep','Unplaced'] if english else ['可接请求','引擎启动中','休眠','尚未放置'])
    for xx,phase,txt in zip([180,378,625,812],['Active','Activating','Sleeping','Pending'],labels):
        if phase=='Pending':line(d,xx,603,xx+24,603,'#BCC5BF',2)
        else:rect(d,xx,596,24,14,COLORS[phase])
        text(d,xx+34,592,txt,19,MUTED)
    text(d,58,642,'During a wake the claim can still report Sleeping until it becomes routable.' if english else '唤醒过程中，Claim 可能持续显示休眠，直到引擎重新可路由。',16,MUTED)
    suffix = '-en' if english else ''
    im.resize((1200,675), Image.Resampling.LANCZOS).save(DATA / f'switching-14b{suffix}.png', optimize=True)


if __name__ == '__main__':
    for en in (False,True):
        draw(en)
