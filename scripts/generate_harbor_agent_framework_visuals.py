#!/usr/bin/env python3
"""Generate 16:9 visuals for the Harbor Agent evaluation framework article."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


W, H = 1200, 675
OUT = Path("docs/assets/rag-agent/harbor-agent-evaluation-framework")
BG = "#F6F8FC"
INK = "#172033"
MUTED = "#68748B"
LINE = "#D7DEEA"
BLUE = "#2F6BFF"
VIOLET = "#7B61E8"
TEAL = "#0B9B8A"
ORANGE = "#E98122"
RED = "#D94B57"
WHITE = "#FFFFFF"


def font(size: int, bold: bool = False):
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc" if bold else "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size, index=1 if bold and path.endswith(".ttc") else 0)
            except OSError:
                continue
    return ImageFont.load_default()


F_TITLE = font(35, True)
F_SUB = font(17)
F_H = font(22, True)
F_BODY = font(17)
F_SMALL = font(14)
F_TINY = font(12)


def canvas(title: str, subtitle: str):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((42, 34, 1158, 641), radius=24, fill=WHITE, outline="#E5E9F2", width=2)
    d.rounded_rectangle((70, 69, 78, 126), radius=4, fill=BLUE)
    d.text((96, 66), title, fill=INK, font=F_TITLE)
    d.text((96, 113), subtitle, fill=MUTED, font=F_SUB)
    return im, d


def wrapped(d, xy, text, width, fill=MUTED, f=F_BODY, line_gap=7):
    x, y = xy
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for ch in paragraph:
            candidate = current + ch
            if d.textlength(candidate, font=f) <= width:
                current = candidate
            else:
                lines.append(current)
                current = ch
        if current:
            lines.append(current)
    for line in lines:
        d.text((x, y), line, fill=fill, font=f)
        y += f.size + line_gap
    return y


def card(d, box, title, body, accent=BLUE, tag=None, title_size=None):
    x1, y1, x2, y2 = box
    d.rounded_rectangle(box, radius=16, fill="#FBFCFF", outline=LINE, width=2)
    d.rounded_rectangle((x1, y1, x1 + 7, y2), radius=4, fill=accent)
    if tag:
        tw = d.textlength(tag, font=F_TINY) + 18
        d.rounded_rectangle((x2 - tw - 14, y1 + 14, x2 - 14, y1 + 38), radius=10, fill=accent)
        d.text((x2 - tw - 5, y1 + 18), tag, fill=WHITE, font=F_TINY)
    tf = font(title_size, True) if title_size else F_H
    d.text((x1 + 22, y1 + 18), title, fill=accent, font=tf)
    wrapped(d, (x1 + 22, y1 + 54), body, x2 - x1 - 44, f=F_SMALL, line_gap=5)


def arrow(d, start, end, color="#8994AA", width=4):
    d.line((start, end), fill=color, width=width)
    x2, y2 = end
    x1, y1 = start
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 > x1 else -1
        pts = [(x2, y2), (x2 - direction * 13, y2 - 8), (x2 - direction * 13, y2 + 8)]
    else:
        direction = 1 if y2 > y1 else -1
        pts = [(x2, y2), (x2 - 8, y2 - direction * 13), (x2 + 8, y2 - direction * 13)]
    d.polygon(pts, fill=color)


def architecture():
    im, d = canvas(
        "Harbor 是 Agent 外层评测框架",
        "Job 展开成 Trial；每个 Trial 绑定任务、Agent、模型、隔离环境与独立验证器",
    )
    card(d, (72, 181, 264, 326), "Job / 配置", "数据集、并发、重复次数、Agent、模型、超时与环境提供方", BLUE, "输入")
    card(d, (337, 165, 614, 342), "Trial Orchestrator", "解析任务契约，创建沙箱，驱动 Agent，收集制品，再调用 Verifier 评分", VIOLET, "一题一次运行")
    card(d, (687, 165, 1128, 268), "Agent Adapter + Model", "Claude Code、Codex CLI、OpenHands、自定义 Agent；模型只是完整运行组合的一部分", BLUE)
    card(d, (687, 292, 902, 410), "Agent Sandbox", "容器、文件、终端、服务、网络策略与资源限制", TEAL)
    card(d, (926, 292, 1128, 410), "Verifier", "测试环境状态并输出 reward.txt / reward.json", ORANGE)
    card(d, (337, 446, 1128, 565), "可审计结果", "result.json · trajectory.json · verifier 日志 · recording.cast · artifacts · Token / 时间 / 错误分类", TEAL, "输出")
    arrow(d, (264, 252), (337, 252))
    arrow(d, (614, 215), (687, 215))
    arrow(d, (614, 305), (687, 351))
    arrow(d, (902, 351), (926, 351))
    arrow(d, (1030, 410), (1030, 446))
    arrow(d, (470, 342), (470, 446))
    d.rounded_rectangle((72, 468, 278, 548), radius=14, fill="#EEF3FF", outline="#CEDAFF", width=2)
    d.text((92, 482), "真正被评分的对象", fill=BLUE, font=font(17, True))
    d.text((92, 516), "Agent × Model × Environment", fill=INK, font=F_SMALL)
    d.text((72, 590), "关键边界：Harbor 不替代 Agent Loop；它负责把不同 Agent 放进同一套可执行、可验证的实验契约中。", fill=INK, font=F_SMALL)
    im.save(OUT / "architecture.png", quality=95)


def task_contract():
    im, d = canvas(
        "Task 不是一道文本题，而是一份可执行契约",
        "自然语言说明负责表达目标，环境与 Verifier 负责把“完成”变成可复验事实",
    )
    xs = [70, 292, 514, 736, 958]
    items = [
        ("instruction.md", "目标、约束与交付物；只写 Agent 应该看到的信息", BLUE),
        ("task.toml", "Schema、超时、资源、网络、制品和 Verifier 运行方式", VIOLET),
        ("environment/", "Dockerfile 或 Compose；固定工具、依赖、初始文件和服务", TEAL),
        ("tests/", "独立检查最终状态；优先机器可判定，避免只评最终措辞", ORANGE),
        ("solution/", "可选 Oracle 解法；证明任务可解并校验评分器", RED),
    ]
    for x, (title, body, color) in zip(xs, items):
        card(d, (x, 184, x + 190, 349), title, body, color, title_size=18)
    for x in xs[:-1]:
        arrow(d, (x + 190, 266), (x + 214, 266), width=3)
    d.rounded_rectangle((100, 408, 1100, 542), radius=20, fill="#F7F9FD", outline=LINE, width=2)
    d.text((126, 432), "Verifier 输出", fill=INK, font=F_H)
    d.rounded_rectangle((308, 426, 568, 510), radius=14, fill="#EEFAF7", outline="#BDE5DD", width=2)
    d.text((329, 442), "reward.txt", fill=TEAL, font=font(20, True))
    d.text((329, 478), "单一浮点奖励", fill=MUTED, font=F_SMALL)
    d.rounded_rectangle((605, 426, 966, 510), radius=14, fill="#FFF6EA", outline="#F4D5AC", width=2)
    d.text((628, 442), "reward.json", fill=ORANGE, font=font(20, True))
    d.text((628, 478), "多维数字奖励：正确性、安全、效率……", fill=MUTED, font=F_SMALL)
    d.text((96, 578), "推荐做法：隐藏测试或独立 Verifier 环境、固定镜像 Digest、Oracle 冒烟、负向样例与防投机检查。", fill=INK, font=F_SMALL)
    im.save(OUT / "task-contract.png", quality=95)


def kubernetes_architecture():
    im, d = canvas(
        "在 Kubernetes 上把每个 Trial 当作一次性受控作业",
        "控制面负责编排与排队，工作负载面负责隔离执行，证据面负责长期保存与复盘",
    )
    card(d, (70, 176, 322, 326), "Harbor 控制面", "Job 配置、数据集解析、Trial 状态机、并发和超时", BLUE)
    card(d, (70, 365, 322, 515), "队列与容量", "Kueue / Volcano、ResourceQuota、PriorityClass、专用节点池", VIOLET)
    card(d, (395, 176, 806, 515), "Trial Namespace / Kubernetes Job", "一个 Trial 对应一个短生命周期 Job\n\nAgent 容器 + 任务环境 + 可选 sidecar\n\nRuntimeClass · NetworkPolicy · 最小权限 ServiceAccount\n\nCPU / 内存 / GPU 限额 · activeDeadlineSeconds", TEAL, "执行边界")
    card(d, (879, 176, 1130, 326), "制品与元数据", "对象存储保存轨迹、日志与输出；数据库保存版本、状态和分数", ORANGE)
    card(d, (879, 365, 1130, 515), "观测与治理", "Prometheus、OpenTelemetry、成本、审计、Secrets 与数据脱敏", RED)
    arrow(d, (322, 251), (395, 251))
    arrow(d, (322, 440), (395, 440))
    arrow(d, (806, 251), (879, 251))
    arrow(d, (806, 440), (879, 440))
    d.rounded_rectangle((106, 558, 1094, 608), radius=14, fill="#EEF3FF", outline="#CEDAFF", width=2)
    d.text((134, 572), "默认拒绝出网 · 短期凭据 · 不可信代码使用 gVisor / Kata · TTL 清理 · Infra Error 与任务失败分开", fill=BLUE, font=F_SMALL)
    im.save(OUT / "kubernetes-production.png", quality=95)


def framework_map():
    im, d = canvas(
        "Harbor 与常见 Agent 工具的边界",
        "这些项目有交集，但它们解决的是不同层次的问题；生产系统通常需要组合使用",
    )
    columns = [
        (76, "应用编排", "LangGraph", "定义节点、状态、路由和长流程", BLUE),
        (295, "Agent Runtime", "Claude Code / Codex / OpenHands", "执行 Agent Loop、工具调用与上下文管理", VIOLET),
        (514, "评测与优化", "Harbor / Inspect AI", "运行任务、隔离环境、验证结果与生成 Rollout", TEAL),
        (733, "专项基准", "SWE-bench", "针对真实代码修复的任务与评分协议", ORANGE),
        (952, "观测平台", "Langfuse", "记录生产与实验 Trace、成本、数据集和评审", RED),
    ]
    for x, layer, name, body, color in columns:
        d.rounded_rectangle((x, 178, x + 182, 488), radius=18, fill="#FBFCFF", outline=LINE, width=2)
        d.rounded_rectangle((x, 178, x + 182, 228), radius=18, fill=color)
        d.rectangle((x, 208, x + 182, 228), fill=color)
        d.text((x + 18, 193), layer, fill=WHITE, font=font(17, True))
        wrapped(d, (x + 18, 260), name, 146, fill=INK, f=font(19, True), line_gap=5)
        wrapped(d, (x + 18, 342), body, 146, fill=MUTED, f=F_SMALL, line_gap=7)
    d.rounded_rectangle((124, 540, 1076, 598), radius=16, fill="#F4F7FC", outline=LINE, width=2)
    d.text((158, 557), "组合关系：LangGraph 构建应用 → Agent Runtime 执行 → Harbor 离线评测 → Langfuse 观察实验与生产", fill=INK, font=F_SMALL)
    im.save(OUT / "framework-map.png", quality=95)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    architecture()
    task_contract()
    kubernetes_architecture()
    framework_map()
    print(f"generated 4 visuals in {OUT}")


if __name__ == "__main__":
    main()
