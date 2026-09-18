#!/usr/bin/env python3
"""Generate deterministic 16:9 figures for the kube-apiserver LB guide."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/assets/practices/kube-apiserver-load-balancing"
W, H = 1200, 675

BG = "#F6F8FC"
PANEL = "#FFFFFF"
INK = "#172033"
MUTED = "#667085"
LINE = "#D8DFEA"
BLUE = "#2457E6"
TEAL = "#07867D"
PURPLE = "#7654D8"
ORANGE = "#D97812"
RED = "#C43D4D"
FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_PATH, size=size, index=1 if bold else 0)


def label(draw, xy, value, size, color=INK, bold=False, anchor=None):
    draw.text(xy, value, font=font(size, bold), fill=color, anchor=anchor)


def rounded(draw, bounds, fill=PANEL, outline=LINE, radius=18, width=2):
    draw.rounded_rectangle(bounds, radius=radius, fill=fill, outline=outline, width=width)


def arrow(draw, start, end, color=MUTED, width=4):
    draw.line([start, end], fill=color, width=width)
    x1, y1 = start
    x2, y2 = end
    if abs(x2 - x1) >= abs(y2 - y1):
        dx = -13 if x2 > x1 else 13
        pts = [(x2, y2), (x2 + dx, y2 - 8), (x2 + dx, y2 + 8)]
    else:
        dy = -13 if y2 > y1 else 13
        pts = [(x2, y2), (x2 - 8, y2 + dy), (x2 + 8, y2 + dy)]
    draw.polygon(pts, fill=color)


def canvas(title, subtitle):
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    label(draw, (52, 38), title, 31, INK, True)
    label(draw, (52, 83), subtitle, 18, MUTED)
    return img, draw


def card(draw, bounds, title, lines, accent=BLUE):
    x1, y1, x2, y2 = bounds
    rounded(draw, bounds)
    draw.rounded_rectangle((x1 + 14, y1 + 14, x1 + 22, y2 - 14), 4, fill=accent)
    label(draw, (x1 + 40, y1 + 23), title, 20, accent, True)
    for i, line in enumerate(lines):
        label(draw, (x1 + 40, y1 + 58 + i * 25), line, 16, MUTED)


def compact_card(draw, bounds, title, lines, accent=BLUE):
    """Card for narrow columns; keep all copy clear of connectors."""
    x1, y1, x2, y2 = bounds
    rounded(draw, bounds, radius=16)
    draw.rounded_rectangle((x1 + 12, y1 + 12, x1 + 20, y2 - 12), 4, fill=accent)
    label(draw, (x1 + 30, y1 + 18), title, 18, accent, True)
    for i, line in enumerate(lines):
        label(draw, (x1 + 30, y1 + 51 + i * 23), line, 14, MUTED)


def pill(draw, center, value, color):
    x, y = center
    bbox = draw.textbbox((0, 0), value, font=font(15, True))
    tw = bbox[2] - bbox[0]
    draw.rounded_rectangle((x - tw / 2 - 12, y - 15, x + tw / 2 + 12, y + 15), 12, fill="#FFFFFF", outline=color, width=2)
    label(draw, (x, y), value, 15, color, True, "mm")


def connection_granularity():
    img, d = canvas(
        "同样是负载均衡，均衡单位决定最终效果",
        "四层在建连时选后端；七层解析 HTTP 请求后，可以把同一客户端的请求分配到不同 API Server",
    )
    rounded(d, (44, 126, 578, 615), fill="#FFFFFF")
    rounded(d, (622, 126, 1156, 615), fill="#FFFFFF")
    label(d, (72, 151), "L4：连接级均衡", 24, BLUE, True)
    label(d, (650, 151), "L7：请求级均衡", 24, PURPLE, True)

    compact_card(d, (72, 202, 238, 360), "客户端", ["1 条 TCP/TLS", "多个 H2 Stream", "长 Watch"], BLUE)
    compact_card(d, (280, 216, 394, 346), "四层 LB", ["只看连接", "建连选后端"], ORANGE)
    arrow(d, (238, 281), (280, 281), BLUE, 5)
    compact_card(d, (424, 190, 552, 286), "API 1", ["全部 Stream"], RED)
    compact_card(d, (424, 314, 552, 410), "API 2", ["无新增连接"], TEAL)
    compact_card(d, (424, 438, 552, 534), "API 3", ["无新增连接"], PURPLE)
    arrow(d, (394, 281), (424, 238), RED, 5)
    label(d, (72, 548), "已有连接不重建，扩容后也不会自动洗牌", 17, RED, True)
    label(d, (72, 578), "适合结构简单、连接倾斜可控的高可用入口", 16, MUTED)

    compact_card(d, (650, 202, 814, 360), "客户端", ["1 条下游连接", "多类 API 请求", "长流 + 写入"], BLUE)
    compact_card(d, (856, 216, 970, 346), "七层网关", ["解析 HTTP", "逐请求选择"], PURPLE)
    arrow(d, (814, 281), (856, 281), PURPLE, 5)
    compact_card(d, (1010, 190, 1132, 286), "API 1", ["请求 A / D"], BLUE)
    compact_card(d, (1010, 314, 1132, 410), "API 2", ["请求 B / E"], TEAL)
    compact_card(d, (1010, 438, 1132, 534), "API 3", ["请求 C / F"], PURPLE)
    # Split only in the whitespace between gateway and backends. No connector
    # is allowed to cross a card's title or body copy.
    d.line((970, 281, 990, 281), fill=PURPLE, width=4)
    d.line((990, 238, 990, 486), fill=PURPLE, width=4)
    arrow(d, (990, 238), (1010, 238), BLUE, 4)
    arrow(d, (990, 362), (1010, 362), TEAL, 4)
    arrow(d, (990, 486), (1010, 486), PURPLE, 4)
    label(d, (650, 548), "能够路由、限流和摘除后端，但网关进入信任边界", 17, PURPLE, True)
    label(d, (650, 578), "适合规模大、请求治理需求明确的控制面", 16, MUTED)
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / "connection-vs-request-balancing.png", quality=95)


def tls_boundaries():
    img, d = canvas(
        "TLS 在哪里终结，决定谁负责证明用户身份",
        "Passthrough 保留端到端客户端证书；Terminate + Re-encrypt 需要网关认证用户并受控地向上游传递身份",
    )
    label(d, (52, 133), "方案 A  TLS Passthrough", 23, BLUE, True)
    card(d, (52, 176, 270, 306), "kubectl / client-go", ["持有用户证书或 Token", "TLS 直接到 API Server"], BLUE)
    card(d, (390, 176, 610, 306), "L4 入口", ["不解密 HTTP", "不理解 verb / resource"], ORANGE)
    card(d, (730, 176, 1148, 306), "kube-apiserver", ["验证原始用户证书或 Token", "执行认证、授权、准入与审计"], TEAL)
    arrow(d, (270, 241), (390, 241), BLUE, 5)
    arrow(d, (610, 241), (730, 241), BLUE, 5)
    pill(d, (500, 334), "一条端到端 TLS 会话", BLUE)

    label(d, (52, 382), "方案 B  TLS Terminate + Re-encrypt", 23, PURPLE, True)
    card(d, (52, 425, 270, 565), "kubectl / client-go", ["先向网关证明身份", "下游 TLS 在网关结束"], BLUE)
    card(d, (390, 425, 610, 565), "L7 API Gateway", ["认证原始用户", "携带 Token 或 Impersonation", "使用专用身份访问上游"], PURPLE)
    card(d, (730, 425, 1148, 565), "kube-apiserver", ["验证网关 mTLS 身份", "校验 Impersonate 权限", "按原始用户授权并记录审计"], TEAL)
    arrow(d, (270, 495), (390, 495), BLUE, 5)
    arrow(d, (610, 495), (730, 495), PURPLE, 5)
    pill(d, (331, 594), "下游 TLS", BLUE)
    pill(d, (670, 594), "上游 mTLS", PURPLE)
    label(d, (1148, 628), "不要把明文上游当成默认生产方案", 16, RED, True, "ra")
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / "tls-termination-boundaries.png", quality=95)


def rollout_evidence():
    img, d = canvas(
        "API Server 入口优化要用恢复过程验收",
        "稳定时三台 CPU 接近并不够；必须观察发布、故障、长 Watch 和重连风暴中的连接迁移与尾延迟",
    )
    stages = [
        ("1  建基线", "分实例 QPS / P99\n连接数 / Watch / 429", BLUE),
        ("2  注入变化", "滚动升级一台\n摘除一台 / 恢复一台", ORANGE),
        ("3  验证流式流量", "WATCH / logs -f\nexec / attach / port-forward", PURPLE),
        ("4  验证恢复", "Ready 后再接流量\n连接重新收敛到预算", TEAL),
    ]
    for i, (title, detail, color) in enumerate(stages):
        x = 52 + i * 286
        rounded(d, (x, 150, x + 254, 306), fill=PANEL)
        d.rounded_rectangle((x + 18, 168, x + 226, 204), 13, fill=color)
        label(d, (x + 122, 186), title, 18, "#FFFFFF", True, "mm")
        for j, line in enumerate(detail.split("\n")):
            label(d, (x + 24, 226 + j * 29), line, 16, MUTED)
        if i < 3:
            arrow(d, (x + 254, 228), (x + 286, 228), LINE, 4)

    rounded(d, (52, 354, 1148, 616), fill="#FFFFFF")
    label(d, (78, 380), "生产门禁", 22, INK, True)
    gates = [
        ("均衡", "单实例请求率、inflight、连接和 CPU 不越过既定偏差", BLUE),
        ("可用", "readyz 失败立即摘流；恢复后等缓存同步完成再接流量", TEAL),
        ("语义", "写请求不盲目重试；Watch 按 resourceVersion 正确续传", PURPLE),
        ("安全", "客户端身份、Impersonation、审计链和证书轮换全部可追溯", ORANGE),
        ("回退", "保留旁路入口；网关异常时能回到已验证的 L4 路径", RED),
    ]
    for i, (name, detail, color) in enumerate(gates):
        y = 426 + i * 35
        d.rounded_rectangle((78, y, 164, y + 27), 10, fill=color)
        label(d, (121, y + 14), name, 15, "#FFFFFF", True, "mm")
        label(d, (186, y + 4), detail, 16, MUTED)
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / "rollout-and-evidence-gates.png", quality=95)


def scale_out_rebalance():
    img, d = canvas(
        "API Server 扩容后，重新均衡要主动管理连接生命周期",
        "生产 Runbook · 新实例先预热，再接流量；已有 HTTP/2 连接通过 GOAWAY 或逐台排空迁移",
    )
    steps = [
        ("1  建立基线", ["记录各实例 QPS", "连接 / CPU / P99"], BLUE),
        ("2  启动新实例", ["核对配置与证书", "readyz 连续通过"], TEAL),
        ("3  加入服务池", ["先低权重接流", "观察错误与尾延迟"], PURPLE),
        ("4  迁移旧连接", ["GOAWAY 自然轮换", "或旧实例逐台排空"], ORANGE),
        ("5  收敛验收", ["请求与压力回预算", "无 LIST / 429 风暴"], RED),
    ]
    xs = [44, 270, 496, 722, 948]
    for i, (title, lines, color) in enumerate(steps):
        x = xs[i]
        rounded(d, (x, 142, x + 202, 306), fill=PANEL)
        d.rounded_rectangle((x + 16, 160, x + 186, 196), 13, fill=color)
        label(d, (x + 101, 178), title, 17, "#FFFFFF", True, "mm")
        for j, line in enumerate(lines):
            label(d, (x + 22, 222 + j * 31), line, 16, MUTED)
        if i < len(steps) - 1:
            arrow(d, (x + 202, 224), (xs[i + 1], 224), LINE, 4)

    rounded(d, (44, 352, 585, 626), fill="#FFFFFF")
    label(d, (70, 378), "L4 TCP 入口", 23, BLUE, True)
    l4_rows = [
        ("加入", "新实例只获得新建 TCP 连接"),
        ("迁移", "已有连接要等 GOAWAY、断开或重启"),
        ("排空", "旧后端逐台 Drain，不能同时洗牌"),
        ("验收", "连接均衡后还要核对请求与 CPU"),
    ]
    for i, (name, detail) in enumerate(l4_rows):
        y = 426 + i * 43
        d.rounded_rectangle((70, y, 138, y + 29), 10, fill=BLUE if i != 1 else ORANGE)
        label(d, (104, y + 15), name, 15, "#FFFFFF", True, "mm")
        label(d, (158, y + 5), detail, 16, MUTED)

    rounded(d, (615, 352, 1156, 626), fill="#FFFFFF")
    label(d, (641, 378), "L7 请求级入口", 23, PURPLE, True)
    l7_rows = [
        ("加入", "按 0 → 10% → 50% → 100% 放量"),
        ("迁移", "新请求立刻参与分配"),
        ("长流", "现有 Watch 仍等断线后重建"),
        ("验收", "检查身份、重试、路由和后端连接池"),
    ]
    for i, (name, detail) in enumerate(l7_rows):
        y = 426 + i * 43
        d.rounded_rectangle((641, y, 709, y + 29), 10, fill=PURPLE if i != 2 else ORANGE)
        label(d, (675, y + 15), name, 15, "#FFFFFF", True, "mm")
        label(d, (729, y + 5), detail, 16, MUTED)
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / "scale-out-rebalance-runbook.png", quality=95)


def main():
    connection_granularity()
    tls_boundaries()
    rollout_evidence()
    scale_out_rebalance()
    print(f"generated assets in {OUT}")


if __name__ == "__main__":
    main()
