"""Concept diagrams for durable agent execution; not benchmark measurements."""
from pathlib import Path
from PIL import Image, ImageDraw
from generate_glm53_day1_assets import (
    font, BG, INK, MUTED, LINE, BLUE, ORANGE, BLUE_LIGHT, ORANGE_LIGHT,
)

OUT = Path(__file__).resolve().parents[1] / 'docs/assets/rag-agent/agent-durable-execution'
OUT.mkdir(parents=True, exist_ok=True)


def text(draw, x, y, value, size=24, color=INK, bold=False):
    face = font(size, bold=bold)
    bounds = draw.textbbox((0, 0), value, font=face)
    width, height = bounds[2]-bounds[0], bounds[3]-bounds[1]
    assert x + width <= 1160, value
    assert y + height <= 646, value
    draw.text((x-bounds[0], y-bounds[1]), value, font=face, fill=color)


def center(draw, box, value, size=24, color=INK, bold=False):
    face = font(size, bold=bold)
    b = draw.textbbox((0, 0), value, font=face)
    assert b[2]-b[0] <= box[2]-box[0]-14, value
    assert b[3]-b[1] <= box[3]-box[1], value
    x = (box[0]+box[2]-b[2]+b[0])/2
    y = (box[1]+box[3]-b[3]+b[1])/2
    text(draw, x, y, value, size, color, bold)


def canvas(title, subtitle):
    im = Image.new('RGB', (1200, 675), BG)
    draw = ImageDraw.Draw(im)
    text(draw, 48, 38, title, 34, bold=True)
    text(draw, 48, 96, subtitle, 21, MUTED)
    return im, draw


def card(draw, box, title, lines, accent=BLUE, background='white'):
    draw.rounded_rectangle(box, radius=16, fill=background, outline=LINE, width=2)
    x, y, right, bottom = box
    draw.rounded_rectangle((x+16,y+20,x+21,bottom-20), radius=2, fill=accent)
    text(draw, x+36, y+24, title, 25, accent, True)
    for idx, line in enumerate(lines):
        face = font(22)
        b = draw.textbbox((0,0), line, font=face)
        assert x+36+b[2]-b[0] <= right-18, line
        assert y+70+idx*37+b[3]-b[1] <= bottom-16, line
        text(draw, x+36, y+70+idx*37, line, 22, MUTED)


def arrow(draw, start, end, color=MUTED, width=3):
    draw.line((start,end), fill=color, width=width)
    x, y = end
    if start[0] == end[0]:
        direction=1 if end[1]>start[1] else -1
        draw.polygon([(x,y),(x-7,y-direction*11),(x+7,y-direction*11)],fill=color)
    else:
        direction=1 if end[0]>start[0] else -1
        draw.polygon([(x,y),(x-direction*11,y-7),(x-direction*11,y+7)],fill=color)


def boundary():
    im,d = canvas('一小时任务中断后，从可靠的步骤边界继续',
                  '示意场景：32 分钟已保存代码；37 分钟 Worker 中断。时间不是实测数据。')
    card(d,(48,158,376,357),'已提交的检查点',
         ['目标与分析已保存','代码版本已保存','对应时刻：第 32 分钟'])
    card(d,(436,158,764,357),'正在执行的测试',
         ['可能仍在外部运行','也可能已完成或失败','中断时刻：第 37 分钟'],ORANGE,ORANGE_LIGHT)
    card(d,(824,158,1152,357),'尚未开始的工作',
         ['审查与必要修复','最终验收和交付','不能直接标记完成'])
    arrow(d,(378,258),(432,258))
    arrow(d,(766,258),(820,258))
    arrow(d,(600,358),(600,396),ORANGE)
    d.rounded_rectangle((48,403,1152,562),16,fill='white',outline=LINE,width=2)
    text(d,78,426,'恢复顺序',25,BLUE,True)
    text(d,78,471,'读取检查点  →  查询原测试任务  →  取回结果或安全重跑  →  继续审查',23)
    text(d,78,516,'复用已确认的成果；对结果未知的工具操作先核实，再决定下一步。',22,MUTED)
    d.rounded_rectangle((48,600,1152,646),12,fill=BLUE_LIGHT)
    center(d,(58,601,1142,644),'保存聊天有助于理解历史；检查点与工具回执决定能否安全继续。',22,BLUE)
    im.save(OUT/'recovery-boundary.png',optimize=True)


def architecture():
    im,d = canvas('Worker 可以更换，任务状态必须保留下来',
                  'Kubernetes 架构建议：任务身份、进度、工作区和外部作业分别管理。')
    boxes = [(48,158,366,342),(442,158,760,342),(836,158,1152,342),
             (48,402,366,570),(442,402,760,570),(836,402,1152,570)]
    card(d,boxes[0],'Task API',['创建、查询与取消','稳定的任务 Run ID','页面重连后仍可查'])
    card(d,boxes[1],'持久执行引擎',['步骤与等待条件','队列、租约与重试','从保存状态调度'])
    card(d,boxes[2],'Agent Worker',['模型与工具调用','重建当前上下文','Pod 可替换或回收'])
    card(d,boxes[3],'工作区与制品',['代码、环境与文件','版本和制品哈希'],BLUE,BLUE_LIGHT)
    card(d,boxes[4],'持久数据库',['检查点、回执、预算','执行所有权与版本'],BLUE,BLUE_LIGHT)
    card(d,boxes[5],'外部工具执行面',['作业 ID 与状态查询','幂等、核实与清理'],ORANGE,ORANGE_LIGHT)
    arrow(d,(368,246),(438,246))
    arrow(d,(762,246),(832,246))
    arrow(d,(601,344),(601,398))
    arrow(d,(994,344),(994,398),ORANGE)
    arrow(d,(207,344),(207,398))
    d.rounded_rectangle((48,600,1152,646),12,fill=BLUE_LIGHT)
    center(d,(58,601,1142,644),'Pod 重启解决进程可用性；持久状态、幂等与核实解决任务恢复。',22,BLUE)
    im.save(OUT/'kubernetes-architecture.png',optimize=True)


if __name__ == '__main__':
    boundary()
    architecture()
    print('Created two 1200×675 concept diagrams.')
