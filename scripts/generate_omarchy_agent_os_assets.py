#!/usr/bin/env python3
"""Generate public-source Agent OS diagrams; these are not runtime screenshots."""
import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

from generate_chatgpt_dots_assets import (
    BLUE, ORANGE, LINE, MUTED, arrow, canvas, card, center, footer, text,
)


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/assets/rag-agent/omarchy-agent-os"


def product_map():
    im, d = canvas("Agent OS：先看它管理什么",
                   "四种产品范围并列比较；不是必须依次安装的技术栈。")
    specs = [
        ((48, 160, 582, 353), "Omarchy · 电脑与桌面",
         ["Linux / 窗口 / 配置 / 系统命令", "Agent 帮助使用和定制个人电脑"], BLUE),
        ((618, 160, 1152, 353), "BrowserOS · 浏览器工作区",
         ["网页 / 登录态 / 标签页 / 回放", "让 Agent 在浏览器中完成工作"], BLUE),
        ((48, 382, 582, 575), "Agno AgentOS · 服务运行时",
         ["Agent API / 会话 / 工作流", "把智能体提供给应用和团队使用"], ORANGE),
        ((618, 382, 1152, 575), "AIOS · Agent 资源管理",
         ["模型请求 / 上下文 / 工具 / 存储", "借鉴操作系统思想管理共享资源"], ORANGE),
    ]
    for box, title, lines, color in specs:
        card(d, box, title, lines, color)
    footer(d, "同名的 Builder Methods Agent OS 主要组织开发规范与需求规格。")
    im.save(OUT / "product-map.png", optimize=True)


def task_workflow():
    im, d = canvas("一次桌面修改，怎样做到可检查、可恢复",
                   "建议工作流程；差异确认与恢复需要 Harness、用户和备份机制配合。")
    top = [(48, 173, 368, 352), (440, 173, 760, 352), (832, 173, 1152, 352)]
    for box, title, lines in zip(top, ["1  描述目标", "2  读取环境", "3  确认差异"],
        [["改什么 / 保留什么", "明确实际工具权限"],
         ["版本 / 配置 / Skill", "检查路径和快捷键冲突"],
         ["列出目标文件和修改", "保留修改前的内容"]]):
        card(d, box, title, lines)
    for a, b in zip(top, top[1:]):
        arrow(d, (a[2] + 5, 261), (b[0] - 6, 261), BLUE)
    text(d, 48, 389, "执行后的结果要能验证", 24, ORANGE, True)
    bottom = [(48, 432, 368, 577), (440, 432, 760, 577), (832, 432, 1152, 577)]
    for box, title, lines in zip(bottom, ["6  保留或恢复", "5  实际验证", "4  实施修改"],
        [["保存证据，失败则撤销"], ["语法 / 重载 / 实际操作"], ["修改用户覆盖配置"]]):
        card(d, box, title, lines, ORANGE)
    arrow(d, (992, 357), (992, 426), ORANGE)
    for a, b in zip(bottom, bottom[1:]):
        x, y = a[2] + 5, 504
        d.line((b[0] - 6, y, x, y), fill=ORANGE, width=3)
        d.polygon([(x, y), (x + 10, y - 6), (x + 10, y + 6)], fill=ORANGE)
    footer(d, "Skill 提供环境知识；文件权限、工具授权与备份负责限制和恢复。")
    im.save(OUT / "task-workflow.png", optimize=True)


def enterprise():
    im, d = canvas("企业组合：工作入口、执行环境与状态分开",
                   "部署建议；Omarchy 是可选工作站，后台任务按所需能力选择运行环境。")
    upper = [(48, 169, 368, 357), (440, 169, 760, 357), (832, 169, 1152, 357)]
    for box, title, lines in zip(upper,
        ["员工工作入口", "任务服务与策略", "独立执行环境"],
        [["Omarchy / 现有桌面", "浏览器 / Web 门户", "使用个人身份提交"],
         ["API / 队列 / 任务状态", "身份、工具与模型权限", "明确重试和恢复条件"],
         ["命令行任务：容器", "桌面任务：虚拟机", "按任务隔离凭据"]]):
        card(d, box, title, lines)
    for a, b in zip(upper, upper[1:]):
        arrow(d, (a[2] + 5, 259), (b[0] - 6, 259), BLUE)
    # Only the service and workers write the shared records in this logical view.
    for x in (600, 992):
        arrow(d, (x, 361), (x, 426), ORANGE)
    d.rounded_rectangle((48, 432, 1152, 575), radius=15, fill="white", outline=LINE, width=2)
    center(d, (64, 449, 1136, 487), "持久状态、文件产物与执行证据", 26, ORANGE, True)
    center(d, (64, 503, 1136, 544), "数据库  ·  工作目录 / 对象存储  ·  调用追踪与结果验证", 24, MUTED)
    footer(d, "模型推理单独提供；Agent 桌面、业务运行时和 GPU 服务各有职责。")
    im.save(OUT / "enterprise-integration.png", optimize=True)


def official_desktop(source):
    with Image.open(source) as src:
        rgb = src.convert("RGB")
        rgb.thumbnail((1200, 675), Image.Resampling.LANCZOS)
        target = Image.new("RGB", (1200, 675), "#F7F9FC")
        target.paste(rgb, ((1200 - rgb.width) // 2, (675 - rgb.height) // 2))
        target.save(OUT / "official-quattro-desktop.png", optimize=True)


def manifest():
    images = [
        ("product-map.png", "比较四类产品管理对象", "官方项目文档的分类归纳", "diagram"),
        ("task-workflow.png", "解释桌面任务的检查与恢复", "本文提出的工作流程", "diagram"),
        ("enterprise-integration.png", "解释桌面与 Kubernetes 的职责", "本文提出的企业架构", "diagram"),
        ("official-quattro-desktop.png", "展示 Quattro 桌面形态",
         "https://github.com/omacom/omarchy/releases/tag/v4.0.0", "upstream-screenshot"),
    ]
    content = {
        "reviewed": "2026-10-16", "channel": "public-documentation",
        "size": [1200, 675],
        "screenshot_original": "https://github.com/user-attachments/assets/8ed81d7d-751f-4318-9e70-7ca175d22fd5",
        "screenshot_processing": "Aspect-preserving resize with padding; no content edits.",
        "generator": "scripts/generate_omarchy_agent_os_assets.py",
        "assets": [{"file": name, "purpose": purpose, "evidence": evidence, "kind": kind,
                    "sha256": hashlib.sha256((OUT / name).read_bytes()).hexdigest()}
                   for name, purpose, evidence, kind in images if (OUT / name).exists()],
    }
    (OUT / "sources.json").write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-screenshot", type=Path)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    product_map()
    task_workflow()
    enterprise()
    if args.official_screenshot:
        official_desktop(args.official_screenshot)
    manifest()
    print("Generated Agent OS diagrams and source manifest.")
