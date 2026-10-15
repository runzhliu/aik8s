#!/usr/bin/env python3
"""HiRoute capability diagrams; public-source analysis, not runtime evidence."""
from pathlib import Path

from generate_chatgpt_dots_assets import BLUE, ORANGE, arrow, canvas, card, footer, text


OUT = Path(__file__).resolve().parents[1] / "docs/assets/rag-agent/hiroute"
BOXES_TOP = [(48, 176, 294, 337), (334, 176, 580, 337),
             (620, 176, 866, 337), (906, 176, 1152, 337)]
BOXES_BOTTOM = [(48, 412, 294, 574), (334, 412, 580, 574),
                (620, 412, 866, 574), (906, 412, 1152, 574)]


def lane(d, boxes, titles, lines, color):
    for box, title, content in zip(boxes, titles, lines):
        card(d, box, title, content, color)
    for left, right in zip(boxes, boxes[1:]):
        y = (left[1] + left[3]) // 2
        arrow(d, (left[2] + 3, y), (right[0] - 4, y), color)


def routing_layers():
    im, d = canvas("HiRoute：任务委派与模型选择是两层工作",
                   "公开能力关系示意；两种路由可独立启用，不代表已部署系统。")
    text(d, 48, 139, "任务路由：这项工作交给谁", 24, BLUE, True)
    lane(d, BOXES_TOP,
         ["主 Agent", "Worker 计划", "选定执行 Agent", "任务结果"],
         [["明确目标和目录", "发起独立任务"],
          ["指定一个执行器", "固定计划与权限"],
          ["运行原生工具", "实现、检查与交付"],
          ["进度、文件、状态", "由主 Agent 汇总"]], BLUE)
    text(d, 48, 373, "模型路由：这一阶段用什么能力", 24, ORANGE, True)
    lane(d, BOXES_BOTTOM,
         ["原生 Agent", "本地 Gateway", "模型组与候选", "企业网关 / API"],
         [["构造模型请求", "接收工具与回答"],
          ["按计划作出选择", "检查能力与权限"],
          ["省钱组 / 主力组", "有限、有序接力"],
          ["访问选定模型", "返回实际推理结果"]], ORANGE)
    footer(d, "Higress 可承接企业入口治理；模型服务负责实际推理。")
    im.save(OUT / "routing-layers.png", optimize=True)


def context_hold():
    im, d = canvas("ContextHold：一轮内保持连续，边界处再判断",
                   "逻辑示意；重新判断可以仍选原模型，不是每次都切换。")
    text(d, 48, 139, "同一轮：识别连续历史，复用有效决策", 24, BLUE, True)
    lane(d, BOXES_TOP,
         ["本轮决策", "模型请求", "工具执行", "模型继续"],
         [["选择模型组", "保存有效决策"],
          ["当前合格模型", "生成回答或工具调用"],
          ["原生 Agent 处理", "返回新的工具结果"],
          ["同轮且决策可复用", "沿用已有选择"]], BLUE)
    text(d, 48, 373, "新消息，或历史重建后原决策无法复用", 24, ORANGE, True)
    lane(d, BOXES_BOTTOM,
         ["进入新决策边界", "重新判断", "原模型或新模型", "继续执行"],
         [["使用当前任务输入", "核对历史与计划"],
          ["类别、复杂度", "适用的阶段反馈"],
          ["限于选中的模型组", "候选必须满足能力"],
          ["沿当前上下文推进", "再积累可复用前缀"]], ORANGE)
    footer(d, "路由复用不等于缓存必然命中，也不会跨模型迁移 KV Cache。")
    im.save(OUT / "context-hold.png", optimize=True)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    routing_layers()
    context_hold()
    print("Generated 2 HiRoute conceptual diagrams at 1200 x 675.")
