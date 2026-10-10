#!/usr/bin/env python3
"""Deterministic diagrams; the evidence figure only frames a real screenshot.

Conceptual quantities are illustrative, not benchmark results. Fonts and colors
follow the established MiniMax M3 article system. No screenshot data is changed.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps
from generate_glm53_day1_assets import font, BG, INK, MUTED, LINE, BLUE, ORANGE

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'docs/assets/practices'
MANIFEST = []


def text(draw, x, y, label, size=24, color=INK, bold=False):
    f = font(size, bold=bold, latin=label.isascii())
    b = draw.textbbox((0, 0), label, font=f)
    assert x + b[2] - b[0] < 1189, label
    draw.text((x - b[0], y - b[1]), label, font=f, fill=color)


def centered(draw, box, label, size=24, color=INK, bold=False):
    f = font(size, bold=bold, latin=label.isascii())
    b = draw.textbbox((0, 0), label, font=f)
    assert b[2] - b[0] <= box[2] - box[0], label
    assert b[3] - b[1] <= box[3] - box[1], label
    draw.text(((box[0]+box[2]-b[2]-b[0])/2,
               (box[1]+box[3]-b[3]-b[1])/2), label, font=f, fill=color)


def canvas(title, subtitle, note):
    im = Image.new('RGB', (1200, 675), BG)
    d = ImageDraw.Draw(im)
    text(d, 48, 36, title, 34, bold=True)
    text(d, 50, 97, subtitle, 21, MUTED)
    d.rounded_rectangle((48, 605, 1152, 656), 15, fill='white', outline=LINE)
    centered(d, (58, 610, 1142, 651), note, 21, MUTED)
    return im, d


def card(d, box, title, lines, color=BLUE, size=24):
    d.rounded_rectangle(box, 16, fill='white', outline=LINE, width=2)
    d.rounded_rectangle((box[0]+14, box[1]+20, box[0]+20, box[3]-20), 3, fill=color)
    text(d, box[0]+32, box[1]+23, title, 25, color, bold=True)
    for i, line in enumerate(lines):
        f = font(size, latin=line.isascii())
        b = d.textbbox((0, 0), line, font=f)
        assert b[2]-b[0] <= box[2]-box[0]-52, line
        assert box[1]+76+i*35+size <= box[3]-14, line
        text(d, box[0]+32, box[1]+76+i*35, line, size, MUTED)


def arrow(d, points, color=MUTED):
    d.line(points, fill=color, width=3, joint='curve')
    x,y=points[-1]; px,py=points[-2]
    a=math.atan2(y-py,x-px)
    d.polygon([(x,y),(x-11*math.cos(a)-5*math.sin(a),y-11*math.sin(a)+5*math.cos(a)),
               (x-11*math.cos(a)+5*math.sin(a),y-11*math.sin(a)-5*math.cos(a))],fill=color)


def save(im, folder, filename, kind='conceptual'):
    out = BASE / folder / filename
    out.parent.mkdir(parents=True,exist_ok=True)
    im.save(out,optimize=True)
    MANIFEST.append({'path':str(out.relative_to(ROOT)), 'kind':kind,
                     'size':list(im.size),'sha256':hashlib.sha256(out.read_bytes()).hexdigest()})


def scheduling_path():
    im,d=canvas('Pod 启动慢：先找出卡在哪一段',
                '上游调度框架 · 调度周期串行，绑定周期可并发 · 节点执行另计',
                '排队、尝试耗时、绑定与 Ready 延迟分别统计，避免把镜像拉取当作调度慢')
    card(d,(48,160,260,363),'调度队列',['active','backoff','unschedulable'],size=21)
    arrow(d,[(269,254),(300,254)])
    d.rounded_rectangle((310,148,850,377),16,fill='white',outline=LINE,width=2)
    centered(d,(330,170,830,207),'串行决策：一个 Pod 选择节点',25,BLUE,True)
    for x,label,desc in [(330,'Filter','可行性'),(502,'Score','放置质量'),(674,'Reserve','保留资源')]:
        d.rounded_rectangle((x,242,x+150,337),12,fill='#EAF1FF',outline=LINE)
        centered(d,(x+6,253,x+144,289),label,25,BLUE,True)
        centered(d,(x+6,296,x+144,327),desc,22,MUTED)
    centered(d,(330,344,830,370),'含 Permit 准入判断',18,MUTED)
    arrow(d,[(484,290),(497,290)])
    arrow(d,[(656,290),(669,290)])
    arrow(d,[(856,254),(882,254)])
    card(d,(892,160,1152,363),'绑定周期',['WaitOnPermit','PreBind / Bind','PostBind / 并发推进'],ORANGE,size=21)
    centered(d,(48,397,850,445),'节点工作可并行 ≠ 多个完整调度周期并行',25,INK,True)
    arrow(d,[(1022,372),(1022,456)],ORANGE)
    card(d,(48,466,1152,584),'节点执行：kubelet → Ready',
         ['镜像、卷、网络、设备分配与应用初始化，会继续影响最终启动时间'],size=23)
    save(im,'large-scale-kubernetes-scheduler','scheduling-path.png')


def search_quality():
    im,d=canvas('调低搜索比例，为什么不一定更快',
                '示意：10,000 节点 · 搜索阈值 10% · 统计找到的可行节点，不是固定扫描比例',
                '减少候选会影响放置质量：吞吐、碎片、拓扑和业务性能需要共同验收')
    card(d,(48,154,582,480),'可行节点很多',
         ['例如普通 CPU Pod','找到约 1,000 个可行节点后','可以提前结束搜索','更多节点不必进入打分'],size=24)
    card(d,(610,154,1152,480),'可行节点很稀疏',
         ['例如只有 30 个节点满足 GPU 条件','达不到可行节点阈值','仍可能搜索全部节点','调低比例不能创造可用资源'],ORANGE,size=23)
    d.rounded_rectangle((48,507,1152,581),14,fill='#EAF1FF',outline=LINE)
    centered(d,(68,518,1132,569),'节点池 / 约束治理 → 减少无关候选；插件索引 → 进一步压缩计算',25,BLUE)
    save(im,'large-scale-kubernetes-scheduler','search-and-quality.png')


def local_central():
    im,d=canvas('多集群监控：本地守住告警，中心保留历史',
                '职责示意 · 关键告警不完全依赖中心 · 两侧分别设置容量与故障边界',
                '缓冲有限：按实际队列增长预算中断时间，并验证恢复后的积压清理速度')
    card(d,(48,156,412,355),'每个 Kubernetes 集群',
         ['服务发现与指标采集','本地关键规则与告警','远程写入队列 / 磁盘缓冲'],size=23)
    card(d,(494,156,1152,355),'中心时序存储',
         ['长期保留、租户限额与存储扩展','复制、去重、备份与故障恢复','接收写入和查询资源分别预算'],ORANGE,size=23)
    arrow(d,[(424,255),(482,255)],BLUE)
    centered(d,(420,208,485,242),'写入',20,BLUE)
    card(d,(48,422,412,581),'本地 Alertmanager',
         ['API / etcd / 节点故障','中心失联时仍能发出告警'],size=23)
    card(d,(494,422,1152,581),'中心查询与报表',
         ['跨集群排障、容量趋势、长期分析','限制重查询，避免挤占关键规则'],ORANGE,size=23)
    arrow(d,[(230,365),(230,410)])
    arrow(d,[(824,365),(824,410)])
    save(im,'large-scale-kubernetes-monitoring','local-and-central.png')


def selection_path():
    im,d=canvas('时序数据库选型：先明确要扩展什么',
                '节点数不是迁移阈值 · 采集、存储、全局查询与租户治理分别评估',
                '共同验收：同一序列画像、相同复制与保留期、查询负载和故障恢复')
    card(d,(48,153,582,342),'本地采集、告警和短期排障',
         ['Prometheus 或 VMSingle 完整栈','先测单机资源与恢复时间','不要为了节点数盲目分布式化'],size=23)
    card(d,(610,153,1152,342),'保留 Prometheus，扩展历史',
         ['Prometheus + Thanos','对象存储、统一查询与去重','近期数据与历史块分开验收'],ORANGE,size=23)
    card(d,(48,379,582,581),'拆开采集与中心存储',
         ['本地采集 + VictoriaMetrics','按需求选择单机或存储集群','明确复制、缓冲与查询语义'],size=23)
    card(d,(610,379,1152,581),'中心多租户与配额治理',
         ['Mimir 或其他隔离设计','明确版本、对象存储和依赖','把运维成本纳入总成本'],ORANGE,size=23)
    save(im,'large-scale-kubernetes-monitoring','selection-path.png')


def evidence(source):
    raw=Image.open(source).convert('RGB')
    assert raw.size==(1500,1050),raw.size
    # Only the resource-count panel. Private workload namespaces and unrelated
    # capacity panels are excluded. The chart and every numerical value remain.
    crop=raw.crop((887,102,1484,550))
    im,d=canvas('实际对象趋势：看板与查询链路已跑通',
                '12 节点实验集群 · VictoriaMetrics K8s Stack · 30 秒采集 · 真实看板节选',
                '截图保留对象数量与趋势；这项验证不代表万节点容量或数据库性能对比')
    fitted=ImageOps.contain(crop,(1104,446),Image.Resampling.LANCZOS)
    im.paste(fitted,((1200-fitted.width)//2,145))
    save(im,'large-scale-kubernetes-monitoring','resource-count-evidence.png','real-screenshot-crop')
    MANIFEST[-1]['crop']=[887,102,1484,550]
    MANIFEST[-1]['source_sha256']=hashlib.sha256(Path(source).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--grafana-screenshot',type=Path,required=True)
    args=parser.parse_args()
    scheduling_path();search_quality();local_central();selection_path();evidence(args.grafana_screenshot)
    out=BASE/'large-scale-kubernetes-monitoring'/'visual-manifest.json'
    out.write_text(json.dumps(MANIFEST,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'figures':len(MANIFEST),'manifest':str(out.relative_to(ROOT))},ensure_ascii=False))


if __name__=='__main__':
    main()
