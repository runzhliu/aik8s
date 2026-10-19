"""Deterministic NVCRE concept figures; no measured performance data."""
import json
from pathlib import Path
from shutil import copyfile

from PIL import Image, ImageDraw, ImageFont
from generate_glm53_day1_assets import font as baseline_font, BG, INK, MUTED, LINE, BLUE, BLUE_LIGHT, ORANGE

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'docs/assets/nvcre'
WECHAT = ROOT / 'articles/wechat/assets/nvcre/v1'
COVERS = ROOT / 'articles/wechat/assets/nvcre/brand-cover'


def font(size, *, bold=False, latin=False):
    # Helvetica Neue TTC face 1 was verified to be Bold; face 0 is Regular.
    if latin and bold:
        return ImageFont.truetype('/System/Library/Fonts/HelveticaNeue.ttc',size,index=1)
    return baseline_font(size,bold=bold,latin=latin)


def text(d, x, y, value, size=24, color=INK, bold=False, latin=False):
    f = font(size, bold=bold, latin=latin)
    b = d.textbbox((0, 0), value, font=f)
    assert x + b[2] - b[0] <= d._image.width - 32, value
    assert y + b[3] - b[1] <= d._image.height - 22, value
    d.text((x-b[0], y-b[1]), value, font=f, fill=color)


def center(d, box, value, size=24, color=INK, bold=False, latin=False):
    f = font(size, bold=bold, latin=latin)
    b = d.textbbox((0, 0), value, font=f)
    assert b[2] - b[0] <= box[2] - box[0] - 20, value
    d.text(((box[0]+box[2]-b[2]-b[0])/2,
            (box[1]+box[3]-b[3]-b[1])/2), value, font=f, fill=color)


def canvas(title, subtitle):
    im = Image.new('RGB', (1200, 675), BG)
    d = ImageDraw.Draw(im)
    text(d, 48, 38, title, 34, bold=True)
    text(d, 48, 97, subtitle, 21, MUTED)
    return im, d


def card(d, box, title, lines, accent=BLUE, title_size=26, latin=False):
    d.rounded_rectangle(box, radius=15, fill='white', outline=LINE, width=2)
    x, y, right, bottom = box
    center(d, (x+8, y+20, right-8, y+56), title, title_size, accent, True, latin)
    for i, line in enumerate(lines):
        assert y+74+i*36+25 < bottom-12, line
        center(d, (x+8, y+74+i*36, right-8, y+106+i*36), line, 23, MUTED)


def arrow(d, start, end, color=MUTED):
    d.line((start, end), fill=color, width=3)
    x, y = end
    if start[1] == y:
        d.polygon([(x,y), (x-10,y-6), (x-10,y+6)], fill=color)
    elif start[0] == x:
        d.polygon([(x,y), (x-6,y-10), (x+6,y-10)], fill=color)
    else:
        raise ValueError('Use orthogonal arrows')


def footer(d, value):
    d.rounded_rectangle((48,600,1152,646), radius=12, fill=BLUE_LIGHT)
    center(d, (58,600,1142,646), value, 22, BLUE)


def save(im, name):
    im.save(PUBLIC / name, optimize=True)
    copyfile(PUBLIC / name, WECHAT / name)


def execution():
    im,d = canvas('把节点范围、负载与测量结果连起来',
                  'NVCRE v0.7.0 执行关系示意；实际负载由 Kubeflow Trainer v2 启动。')
    boxes = [(48,160,294,327),(334,160,580,327),(620,160,866,327),(906,160,1152,327)]
    for box, title, lines in zip(boxes,
        ['Certification','Workflow','NVCRE Job','TrainJob'],
        [['选择节点与类别','定义验收条件'],['分组与迭代','组织执行顺序'],['管理一次执行','记录健康与失败'],['启动真实负载','使用 GPU 与网络']]):
        card(d, box, title, lines, latin=True, title_size=26)
    for a,b in zip(boxes, boxes[1:]):
        arrow(d,(a[2]+3,244),(b[0]-4,244))
    d.line((1029,331,1029,392),fill=MUTED,width=3)
    d.line((213,392,1029,392),fill=MUTED,width=3)
    for x in (213,600,987):
        arrow(d,(x,392),(x,408))
    text(d, 48, 359, '读取运行日志与状态', 24, bold=True)
    card(d,(48,412,378,576),'训练有效时间',['GoodputMeasurement','恢复 / 保存 / 丢失工作'], title_size=26)
    card(d,(435,412,765,576),'集合通信带宽',['BandwidthMeasurement','消息大小 / 带宽 / 路径'], title_size=26)
    card(d,(822,412,1152,576),'报告与节点归因',['最终状态 / 原始日志','通过 / 失败 / 未覆盖'], ORANGE)
    footer(d,'LogProfile 定义解析规则；WorkloadRun 是简化入口，仍生成 TrainJob。')
    save(im,'execution-chain.png')


def scope():
    im,d = canvas('先验证最小链路，再扩大测试范围',
                  '生产接入建议；各阶段通过以后再推进，不是已执行的实验结果。')
    boxes = [(48,164,294,353),(334,164,580,353),(620,164,866,353),(906,164,1152,353)]
    for box,title,lines in zip(boxes,['01 依赖核查','02 单机验证','03 双机通信','04 训练回归'],
       [['版本 / CRD / 权限','标签与模板'],['预留设备','卡数与 PCIe 路径'],['网卡与实际路径','带宽与数值正确性'],['稳态与检查点','恢复与本地基线']]):
        card(d,box,title,lines,title_size=25)
    for a,b in zip(boxes,boxes[1:]):
        arrow(d,(a[2]+3,261),(b[0]-4,261))
    d.rounded_rectangle((48,400,1152,558),radius=16,fill='white',outline=LINE,width=2)
    text(d,78,424,'每一步都要保留',26,BLUE,True)
    text(d,78,474,'实际执行范围 · 模板与镜像版本 · 原始日志 · 退出码 · 测量结果',24)
    text(d,78,519,'测试并发、排队总期限、额外诊断成本需要分别控制。',23,MUTED)
    footer(d,'GPU 利用率为零，不等于设备尚未分配；测试前先核对实际资源占用。')
    save(im,'validation-scope.png')


def retention():
    im,d = canvas('历史曲线和最终成绩，要分别保存',
                  'NVCRE v0.7.0 会清理部分临时 Gauge；测量 CR 保存最终状态。')
    boxes=[(48,160,378,355),(435,160,765,355),(822,160,1152,355)]
    card(d,boxes[0],'测量进行中',['日志解析与指标采集','记录实验起止时间','关联 Workflow / Job'])
    card(d,boxes[1],'测量结束',['最终测量状态冻结','部分指标序列清理','瞬时查询可能无数据'],ORANGE)
    card(d,boxes[2],'结果归档',['导出 CR 与报告','保存原始日志','历史区间图与截图'])
    for a,b in zip(boxes,boxes[1:]):
        arrow(d,(a[2]+3,258),(b[0]-4,258))
    d.rounded_rectangle((48,410,1152,563),radius=16,fill='white',outline=LINE,width=2)
    text(d,78,434,'两种依据，分别回答问题',26,BLUE,True)
    text(d,78,483,'历史曲线：测试期间发生了什么？',24)
    text(d,78,526,'最终报告：哪些测试完成，结果与覆盖范围是什么？',24)
    footer(d,'先归档，再删除测试对象；短测试可能落在两次 Scrape 之间。')
    save(im,'result-retention.png')


def production():
    im,d = canvas('把验收接到节点上线与变更流程中',
                  '生产接入建议；NVCRE 负责运行负载和输出报告，平台负责放行与隔离。')
    boxes = [(48,161,294,366),(334,161,580,366),(620,161,866,366),(906,161,1152,366)]
    for box,title,lines in zip(boxes,
        ['预留测试节点','运行真实负载','对照本站基线','执行平台决策'],
        [['新节点 / 维修后','升级前后','限定卡数与期限'],
         ['单机与跨机通信','诊断 / 训练','固定版本与拓扑'],
         ['性能与正确性','失败范围与原因','保存日志和报告'],
         ['通过后入业务池','异常时继续定位','复测后再放行']]):
        card(d,box,title,lines,title_size=25)
    for a,b in zip(boxes,boxes[1:]):
        arrow(d,(a[2]+3,264),(b[0]-4,264))
    d.rounded_rectangle((48,407,1152,565),radius=15,fill='white',outline=LINE,width=2)
    text(d,78,434,'日常监控持续运行',26,BLUE,True)
    text(d,78,480,'GPU、网络与任务指标发现异常；验收负载安排在预留节点或维护窗口。',23)
    text(d,78,523,'升级回归比较同条件结果；性能异常通过分组复测缩小嫌疑范围。',23,MUTED)
    footer(d,'验收会占用 GPU 与网络；NVCRE 自身不执行封禁、驱逐或硬件维修。')
    save(im,'production-lifecycle.png')


def covers():
    bg, ink, muted, accent, line, soft = '#F7FAF1','#25311F','#69775C','#527D00','#D6E3BE','#EAF3D9'
    for square in [False,True]:
        im = Image.new('RGB',(900,900 if square else 383),bg)
        d = ImageDraw.Draw(im)
        d.rectangle((0,0,14 if square else 12,im.height), fill='#76B900')
        if not square:
            text(d,45,36,'AI-K8S 技术工程',18,accent)
            text(d,45,95,'NVIDIA NVCRE',47,accent,True,True)
            text(d,45,173,'怎样验收 GPU 集群？',33,ink)
            text(d,45,258,'通信 · 训练 · 故障定位',25,accent)
            text(d,45,320,'架构原理 · 部署前提 · 生产接入',20,muted)
            for idx,label in enumerate(['通信','训练','诊断']):
                y=104+idx*67
                d.rounded_rectangle((668,y,844,y+52),radius=8,fill='white',outline=line,width=2)
                center(d,(668,y,844,y+52),label,23,accent)
            name='cover.png'
        else:
            text(d,62,66,'AI-K8S 技术工程',25,accent)
            text(d,62,177,'NVIDIA NVCRE',67,accent,True,True)
            text(d,62,310,'验收 GPU 集群',59,ink)
            text(d,62,420,'真实负载与生产接入',42,ink)
            for idx,label in enumerate(['通信带宽','训练有效时间','故障定位']):
                x=65+idx*263
                d.rounded_rectangle((x,550,x+244,696),radius=12,fill='white',outline=line,width=2)
                center(d,(x,550,x+244,696),label,26,accent)
            text(d,62,778,'架构原理 · 部署前提 · 运维建议',30,accent)
            name='cover-square.png'
        im.save(COVERS/name,optimize=True)
    (COVERS/'palette.json').write_text(json.dumps({
        'layout_reference':'articles/wechat/assets/minimax-m3-h20/brand-cover/',
        'brand_accent':'#76B900',
        'palette_scope':'NVIDIA green with darker editorial text; no official logo reproduction',
        'main':'900x383','sharing':'900x900','source':'scripts/generate_nvcre_article_assets.py',
    },ensure_ascii=False,indent=2)+'\n')


if __name__ == '__main__':
    for path in (PUBLIC,WECHAT,COVERS):
        path.mkdir(parents=True,exist_ok=True)
    execution()
    scope()
    retention()
    production()
    covers()
    print('Generated 4 concept figures and 2 independently composed covers.')
