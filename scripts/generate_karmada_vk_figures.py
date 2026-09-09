#!/usr/bin/env python3
"""Editable SVG teaching diagrams; no measured performance data.

Visual plan:
- architecture.svg, 1200x960: contrast object ownership and execution paths;
  sources: official Karmada architecture and Virtual Kubelet architecture.
- capacity.svg, 1200x760: contrast placement with final admission and show a
  hypothetical GPU fragmentation example; source: article's engineering analysis.
Destination: public documentation. Blue/teal, Chinese system fonts, light theme.
Browser QA measures SVG text bounding boxes against explicit available widths.
"""
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / 'docs/assets/cluster/karmada-vs-virtual-kubelet'
BLUE, TEAL, TEXT, MUTED = '#2455a6', '#087e82', '#172b49', '#596b82'

class Figure:
    def __init__(self, height, title, subtitle, width=1200):
        self.height = height
        self.parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
                      f'<title id="title">{escape(title)}</title><desc id="desc">{escape(subtitle)}</desc>',
                      '<defs><marker id="arrow" markerWidth="9" markerHeight="9" refX="7" refY="4.5" orient="auto"><path d="M0 0L9 4.5L0 9" fill="none" stroke="#687b93" stroke-width="1.5"/></marker></defs>',
                      f'<rect width="{width}" height="{height}" fill="#f6f8fc"/>',
                      '<g font-family="-apple-system,BlinkMacSystemFont, &quot;PingFang SC&quot;, &quot;Hiragino Sans GB&quot;,sans-serif">']
        self.text(44, 55, title, 32, TEXT, weight=700, width=width-88)
        self.text(44, 95, subtitle, 23, MUTED, width=width-88)

    def text(self, x, y, value, size=23, color=TEXT, weight=400, width=1000, center=False):
        anchor = 'middle' if center else 'start'
        self.parts.append(f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" data-max-width="{width}">{escape(value)}</text>')

    def rect(self, x, y, w, h, color='#fff', stroke='#d9e1ed'):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{color}" stroke="{stroke}"/>')

    def box(self, x, y, w, h, title, detail, accent=BLUE):
        self.rect(x, y, w, h)
        self.text(x+w/2, y+39, title, 24, accent, 650, w-32, True)
        self.text(x+w/2, y+74, detail, 20, MUTED, 400, w-32, True)

    def arrow(self, x1, y1, x2, y2):
        self.parts.append(f'<path d="M{x1} {y1} L{x2} {y2}" fill="none" stroke="#687b93" stroke-width="2" marker-end="url(#arrow)"/>')

    def save(self, name):
        self.parts += ['</g></svg>']
        (OUT/name).write_text('\n'.join(self.parts), encoding='utf-8')

def architecture():
    f=Figure(960,'应用跨集群编排，与外部计算接入','架构示意 · 箭头表示控制与执行路径，不表示跨集群网络已经连通')
    for x,color,title,sub in [(40,BLUE,'Karmada','放置对象：资源模板及其副本'),(620,TEAL,'Virtual Kubelet','适配对象：已绑定虚拟节点的 Pod')]:
        f.rect(x,130,540,734,'#edf3fd' if x==40 else '#eaf6f5')
        f.text(x+30,174,title,29,color,700,480)
        f.text(x+30,206,sub,21,MUTED,width=480)
    f.box(70,232,480,100,'Karmada API','Deployment 模板：6 个副本')
    f.box(70,378,480,100,'策略 / Binding / Work','集群级调度、差异覆盖与分发')
    f.box(70,524,480,100,'成员集群中的 Deployment','各成员本地控制器创建 Pod')
    for a,b in [(332,371),(478,517)]:f.arrow(310,a,310,b)
    for target in [182.5,437.5]:
        f.parts.append(f'<path d="M310 624 V652 H{target} V679" fill="none" stroke="#687b93" stroke-width="2" marker-end="url(#arrow)"/>')
    f.box(70,686,225,100,'集群 A：4 副本','本地节点调度',BLUE)
    f.box(325,686,225,100,'集群 B：2 副本','本地节点调度',BLUE)
    f.text(310,831,'示例策略：Divided，权重 2:1',21,MUTED,width=480,center=True)
    f.box(650,232,480,100,'普通 Kubernetes API','Deployment：6 个副本',TEAL)
    f.box(650,378,480,100,'本地控制器 / kube-scheduler','创建 Pod，并选择虚拟节点',TEAL)
    f.box(650,524,480,100,'VK / Provider','转换创建请求、回报状态与容量',TEAL)
    f.box(650,686,480,100,'外部执行后端','容器云 / 远端 Kubernetes / 其他',TEAL)
    for a,b in [(332,371),(478,517),(624,679)]:f.arrow(890,a,890,b)
    f.text(890,831,'具体语义取决于 Provider 实现',21,MUTED,width=480,center=True)
    f.text(44,910,'两种方式可以组合；需明确副本、数据、身份和故障恢复的责任方。',23,TEXT,width=1112)
    f.save('architecture.svg')

def capacity():
    f=Figure(760,'获得放置结果，还需要通过执行层准入','工程分析示意 · 容量总量、资源拓扑与实际可运行数量需要分别验证')
    f.text(44,153,'Karmada 路径',24,BLUE,700,width=1100)
    f.text(44,333,'Virtual Kubelet 路径',24,TEAL,700,width=1100)
    for y,titles,details,color in [(181,['选定成员集群','成员调度 / 队列','真实节点执行'],['策略与资源估算','检查具体 Pod 约束','CPU / GPU / 卷 / 网络'],BLUE),(361,['选定虚拟节点','Provider / 后端准入','真实执行资源'],['上报容量与节点标签','配额、能力与可用布局','实例启动后才产生能力'],TEAL)]:
        for i in range(3):f.box(44+i*385,y,340,100,titles[i],details[i],color)
        f.arrow(387,y+50,417,y+50);f.arrow(772,y+50,802,y+50)
    f.rect(44,514,1112,187)
    f.text(70,556,'假设算例：两台机器各空闲 4 GPU，单个 Pod 要求同机 8 GPU',25,TEXT,650,width=1060)
    f.text(70,601,'资源总和 = 8 GPU；满足这个 Pod 的物理节点数 = 0。',23,BLUE,width=1060)
    f.text(70,646,'资源估算或 Provider 准入应识别这种碎片，不能只向上暴露加总后的卡数。',22,MUTED,width=1060)
    f.text(44,735,'图中的执行约束是验证要求，不代表所有 Provider 使用相同的容量模型。',19,MUTED,width=1112)
    f.save('capacity.svg')

def mobile():
    f=Figure(1390,'Karmada 与 Virtual Kubelet','架构示意 · 对象归属与执行路径',720)
    for y,color,title,steps in [
        (158,BLUE,'Karmada：跨集群放置',[
            ('Karmada API','Deployment 模板：6 个副本'),
            ('策略 / Binding / Work','选择集群并分发资源'),
            ('成员 Deployment 控制器','在各成员集群创建 Pod'),
            ('成员调度器 → 真实节点','示例：A 为 4 副本，B 为 2 副本')]),
        (745,TEAL,'VK：外部计算适配',[
            ('普通 Kubernetes API','Deployment：6 个副本'),
            ('本地控制器 / 调度器','创建 Pod，选择虚拟节点'),
            ('VK / Provider','在外部创建执行实例、回报状态'),
            ('外部执行后端','功能与限制取决于 Provider')])]:
        f.text(44,y,title,29,color,700,632)
        for i,(a,b) in enumerate(steps):
            top=y+27+i*127
            f.rect(44,top,632,100)
            f.text(360,top+39,a,28,color,650,584,True)
            f.text(360,top+75,b,25,MUTED,400,584,True)
            if i<3:f.arrow(360,top+101,360,top+120)
    f.text(44,1355,'两者可以组合；需明确控制与恢复责任。',25,TEXT,width=632)
    f.save('architecture-mobile.svg')
    f=Figure(1320,'放置成功之后，还要检查准入','工程分析 · 上报额度与物理布局不同',720)
    for y,color,title,steps in [(158,BLUE,'Karmada',['选定成员集群','成员调度 / 队列检查','真实节点执行']),
                               (590,TEAL,'Virtual Kubelet',['选定虚拟节点','Provider / 后端准入','真实执行资源'])]:
        f.text(44,y,title,29,color,700,632)
        for i,label in enumerate(steps):
            top=y+28+i*116
            f.rect(44,top,632,86)
            f.text(360,top+53,label,30,color,650,584,True)
            if i<2:f.arrow(360,top+87,360,top+109)
    f.rect(44,1020,632,244)
    for i,line in enumerate(['假设两台机器各空闲 4 GPU，','一个 Pod 要求同机 8 GPU。','合计 8 GPU，但没有满足的节点。','需要校验真实拓扑和可执行布局。']):
        f.text(70,1069+i*49,line,27,BLUE if i==2 else TEXT,650 if i==2 else 400,580)
    f.text(44,1300,'假设算例，不代表所有 Provider 的容量模型。',23,MUTED,width=632)
    f.save('capacity-mobile.svg')

if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    architecture();capacity();mobile()
    print('Generated two diagrams with desktop and mobile layouts')
