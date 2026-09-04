#!/usr/bin/env python3
"""Generate light-mode Firecracker Kubernetes WeChat covers and topology."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "articles/wechat/assets/firecracker-kubernetes"
LANDSCAPE_OUTPUT = ROOT / "articles/wechat/assets/firecracker-kubernetes-cover.png"
SQUARE_OUTPUT = ROOT / "articles/wechat/assets/firecracker-kubernetes-cover-square.png"

CHINESE = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
LATIN = Path("/System/Library/Fonts/HelveticaNeue.ttc")

INK = (16, 29, 48)
MUTED = (77, 96, 121)
BLUE = (37, 99, 235)
CYAN = (7, 165, 188)
ORANGE = (239, 99, 42)
VIOLET = (111, 75, 202)
GREEN = (24, 148, 99)
PAPER = (247, 250, 253)
WHITE = (255, 255, 255)
LINE = (211, 222, 236)
PALE_BLUE = (229, 239, 255)
PALE_CYAN = (226, 247, 249)
PALE_ORANGE = (255, 239, 230)


def font(path: Path, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    if not path.exists():
        raise FileNotFoundError(f"font not found: {path}")
    return ImageFont.truetype(str(path), size=size, index=index)


def text_width(draw: ImageDraw.ImageDraw, value: str, face: ImageFont.FreeTypeFont) -> int:
    box = draw.textbbox((0, 0), value, font=face)
    return box[2] - box[0]


def centered_text(
    draw: ImageDraw.ImageDraw,
    center_x: float,
    y: float,
    value: str,
    face: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
) -> None:
    draw.text((center_x - text_width(draw, value, face) / 2, y), value, font=face, fill=fill)


def add_grid(draw: ImageDraw.ImageDraw, width: int, height: int, step: int) -> None:
    for x in range(0, width, step):
        draw.line((x, 0, x, height), fill=(229, 236, 245), width=1)
    for y in range(0, height, step):
        draw.line((0, y, width, y), fill=(229, 236, 245), width=1)


def pill(draw: ImageDraw.ImageDraw, xy: tuple[int, int], label: str, *, size: int) -> None:
    face = font(LATIN, size, 1)
    box = draw.textbbox((0, 0), label, font=face)
    width = box[2] - box[0] + 34
    height = box[3] - box[1] + 18
    left, top = xy
    draw.rounded_rectangle(
        (left, top, left + width, top + height),
        radius=height // 2,
        fill=PALE_ORANGE,
        outline=(247, 177, 137),
    )
    draw.text((left + 17, top + 9 - box[1]), label, font=face, fill=ORANGE)


def spark(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float) -> None:
    points = [
        (x + round(30 * scale), y),
        (x + round(2 * scale), y + round(62 * scale)),
        (x + round(31 * scale), y + round(57 * scale)),
        (x + round(16 * scale), y + round(110 * scale)),
        (x + round(71 * scale), y + round(38 * scale)),
        (x + round(41 * scale), y + round(43 * scale)),
    ]
    draw.polygon(points, fill=ORANGE)


def microvm_stack(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[int, int, int, int],
    *,
    scale: float,
) -> None:
    left, top, right, bottom = bounds
    draw.rounded_rectangle(bounds, radius=round(24 * scale), fill=PAPER, outline=LINE, width=2)
    spark(draw, left + round(24 * scale), top + round(17 * scale), 0.35 * scale)
    draw.text(
        (left + round(59 * scale), top + round(20 * scale)),
        "FIRECRACKER",
        font=font(LATIN, round(13 * scale), 1),
        fill=ORANGE,
    )
    layers = [
        ("Kubernetes Pod", PALE_BLUE, BLUE),
        ("Kata runtime-rs", PALE_CYAN, CYAN),
        ("Firecracker VMM", PALE_ORANGE, ORANGE),
        ("Linux microVM", WHITE, VIOLET),
    ]
    y = top + round(62 * scale)
    for label, fill, outline in layers:
        height = round(38 * scale)
        draw.rounded_rectangle(
            (left + round(22 * scale), y, right - round(22 * scale), y + height),
            radius=round(8 * scale),
            fill=fill,
            outline=outline,
            width=max(1, round(2 * scale)),
        )
        centered_text(
            draw,
            (left + right) / 2,
            y + round(8 * scale),
            label,
            font(LATIN, round(13 * scale), 1),
            INK,
        )
        y += round(48 * scale)
    centered_text(
        draw,
        (left + right) / 2,
        bottom - round(30 * scale),
        "RuntimeClass · KVM",
        font(LATIN, round(12 * scale), 1),
        MUTED,
    )


def compose_landscape() -> Path:
    image = Image.new("RGB", (900, 383), PAPER)
    draw = ImageDraw.Draw(image)
    add_grid(draw, 900, 383, 42)
    draw.rounded_rectangle((30, 24, 870, 359), radius=26, fill=WHITE, outline=LINE, width=2)
    draw.rectangle((30, 24, 42, 359), fill=ORANGE)
    draw.text((72, 47), "Firecracker 1.16.1 · Kata 4.1.0", font=font(LATIN, 15, 1), fill=ORANGE)
    draw.text((68, 86), "Firecracker × Kubernetes", font=font(LATIN, 35, 1), fill=INK)
    draw.text((70, 137), "从 VMM 到 RuntimeClass 实测", font=font(CHINESE, 28), fill=INK)
    pill(draw, (70, 205), "Snapshot · 10 Pods · Jailer", size=15)
    draw.text((70, 269), "RuntimeClass 主线 · VMM 分层实测", font=font(CHINESE, 16), fill=MUTED)
    draw.text((70, 319), "AIK8S.RUN", font=font(LATIN, 13, 1), fill=CYAN)
    microvm_stack(draw, (600, 47, 830, 331), scale=0.86)
    image.save(LANDSCAPE_OUTPUT, format="PNG", optimize=True)
    return LANDSCAPE_OUTPUT


def compose_square() -> Path:
    image = Image.new("RGB", (900, 900), PAPER)
    draw = ImageDraw.Draw(image)
    add_grid(draw, 900, 900, 56)
    draw.rounded_rectangle((52, 46, 848, 854), radius=42, fill=WHITE, outline=LINE, width=2)
    draw.rectangle((52, 46, 848, 58), fill=ORANGE)
    draw.text((90, 92), "Firecracker 1.16.1 · Kata 4.1.0", font=font(LATIN, 21, 1), fill=ORANGE)
    draw.text((86, 151), "Firecracker", font=font(LATIN, 66, 1), fill=INK)
    draw.text((90, 237), "跑进 Kubernetes", font=font(CHINESE, 49), fill=INK)
    microvm_stack(draw, (255, 350, 645, 700), scale=1.17)
    pill(draw, (90, 759), "Snapshot · 10 Pods · Jailer", size=20)
    draw.text((671, 816), "AIK8S.RUN", font=font(LATIN, 13, 1), fill=CYAN)
    image.save(SQUARE_OUTPUT, format="PNG", optimize=True)
    return SQUARE_OUTPUT


def figure(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (1200, 675), PAPER)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((42, 38, 1158, 637), radius=28, fill=WHITE, outline=LINE, width=2)
    draw.rectangle((42, 38, 54, 637), fill=ORANGE)
    draw.text((90, 72), title, font=font(CHINESE, 36), fill=INK)
    draw.text((92, 126), subtitle, font=font(CHINESE, 19), fill=MUTED)
    return image, draw


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: tuple[int, int, int]) -> None:
    draw.line((*start, *end), fill=color, width=4)
    draw.polygon([(end[0], end[1]), (end[0] - 14, end[1] - 9), (end[0] - 14, end[1] + 9)], fill=color)


def save_paths() -> Path:
    image, draw = figure(
        "RuntimeClass 才是 Kubernetes 调度主线",
        "原生 Firecracker 与 Launcher Pod 是辅助验证，不是部署必经步骤",
    )

    draw.rounded_rectangle((82, 190, 680, 532), radius=24, fill=(248, 250, 252), outline=LINE, width=2)
    draw.text((110, 213), "辅助验证 · 按需使用", font=font(CHINESE, 20), fill=MUTED)

    helpers = [
        (108, 256, "原生 Firecracker", "VMM API · 快照 · jailer", PALE_ORANGE, ORANGE, "底层研究"),
        (108, 380, "实验 Launcher Pod", "KVM 准入 · cgroup · 清理", PALE_BLUE, BLUE, "可选调试夹具"),
    ]
    for x, y, title, detail, fill, outline, tag in helpers:
        draw.rounded_rectangle((x, y, x + 544, y + 100), radius=18, fill=fill, outline=outline, width=2)
        draw.text((x + 22, y + 18), title, font=font(CHINESE, 21), fill=INK)
        draw.text((x + 22, y + 57), detail, font=font(CHINESE, 16), fill=MUTED)
        draw.rounded_rectangle((x + 389, y + 27, x + 521, y + 71), radius=18, fill=outline)
        centered_text(draw, x + 455, y + 38, tag, font(CHINESE, 14), WHITE)

    draw.rounded_rectangle((718, 190, 1118, 532), radius=24, fill=PALE_CYAN, outline=CYAN, width=3)
    draw.text((748, 216), "社区主线", font=font(CHINESE, 18), fill=CYAN)
    draw.text((748, 253), "Kata RuntimeClass", font=font(LATIN, 26, 1), fill=INK)
    main_steps = [
        "业务 Pod + runtimeClassName",
        "kube-scheduler 选择 KVM 节点",
        "Kubelet → containerd → Kata shim",
        "Firecracker 创建 Pod Sandbox",
    ]
    for index, step in enumerate(main_steps):
        y = 309 + index * 48
        draw.ellipse((751, y + 5, 763, y + 17), fill=CYAN)
        draw.text((780, y), step, font=font(CHINESE, 16), fill=MUTED)

    draw.rounded_rectangle((82, 558, 1058, 606), radius=11, fill=(239, 244, 250))
    centered_text(
        draw,
        570,
        570,
        "结论：Kubernetes 调度 Pod，运行时创建 microVM；Launcher 不是前置组件",
        font(CHINESE, 17),
        MUTED,
    )
    output = ASSET_DIR / "three-paths.png"
    image.save(output, format="PNG", optimize=True)
    return output


def save_runtimeclass_flow() -> Path:
    image, draw = figure(
        "一个 Pod 怎样变成 Firecracker microVM",
        "Kubernetes 只调度 Pod；节点运行时负责创建并清理 microVM",
    )

    cards = [
        (82, 187, 1, "提交业务 Pod", ("runtimeClassName:", "kata-fc-lab"), PALE_BLUE, BLUE),
        (432, 187, 2, "RuntimeClass 合并约束", ("Selector · Toleration", "Overhead"), PALE_BLUE, BLUE),
        (782, 187, 3, "kube-scheduler", ("选择已准备 KVM / Kata", "的节点"), PALE_BLUE, BLUE),
        (782, 373, 4, "Kubelet → containerd", ("CRI 选择", "kata-fc Handler"), PALE_ORANGE, ORANGE),
        (432, 373, 5, "Kata shim", ("准备 Sandbox", "Rootfs · CNI 网络"), PALE_ORANGE, ORANGE),
        (82, 373, 6, "Firecracker microVM", ("Guest → kata-agent", "容器 Ready"), PALE_ORANGE, ORANGE),
    ]
    for x, y, number, title, details, fill, outline in cards:
        draw.rounded_rectangle((x, y, x + 286, y + 116), radius=18, fill=fill, outline=outline, width=2)
        draw.ellipse((x + 19, y + 18, x + 55, y + 54), fill=outline)
        centered_text(draw, x + 37, y + 25, str(number), font(LATIN, 16, 1), WHITE)
        draw.text((x + 68, y + 18), title, font=font(CHINESE, 19), fill=INK)
        for index, detail in enumerate(details):
            draw.text((x + 22, y + 64 + index * 25), detail, font=font(CHINESE, 17), fill=MUTED)

    arrow(draw, (368, 245), (432, 245), BLUE)
    arrow(draw, (718, 245), (782, 245), BLUE)

    draw.line((925, 303, 925, 373), fill=ORANGE, width=4)
    draw.polygon([(925, 373), (916, 359), (934, 359)], fill=ORANGE)

    draw.line((782, 431, 718, 431), fill=ORANGE, width=4)
    draw.polygon([(718, 431), (732, 422), (732, 440)], fill=ORANGE)
    draw.line((432, 431, 368, 431), fill=ORANGE, width=4)
    draw.polygon([(368, 431), (382, 422), (382, 440)], fill=ORANGE)

    draw.rounded_rectangle((82, 531, 1118, 607), radius=13, fill=(239, 244, 250))
    draw.text((108, 548), "删除 Pod", font=font(CHINESE, 17), fill=ORANGE)
    draw.text(
        (215, 548),
        "Kubelet → containerd → Kata shim → 关闭 VMM → 回收快照与网络",
        font=font(CHINESE, 17),
        fill=INK,
    )
    draw.text((215, 577), "Launcher Pod 不参与这条正式运行时链路", font=font(CHINESE, 15), fill=MUTED)

    output = ASSET_DIR / "runtimeclass-scheduling-flow.png"
    image.save(output, format="PNG", optimize=True)
    return output


def save_cubesandbox_comparison() -> Path:
    image, draw = figure(
        "Firecracker/Kata 与 CubeSandbox：保护的不是同一个对象",
        "前者隔离 Agent Runtime，后者隔离 Agent 发起的工具与代码执行",
    )
    columns = [
        (
            84,
            "外层：Kata + Firecracker",
            BLUE,
            PALE_BLUE,
            [
                ("隔离对象", "Agent Pod / Runtime"),
                ("入口", "RuntimeClass"),
                ("生命周期", "Kubernetes Pod"),
                ("快照语义", "VM / Runtime 制品"),
                ("主要价值", "保护节点与工作负载边界"),
            ],
        ),
        (
            626,
            "内层：CubeSandbox",
            ORANGE,
            PALE_ORANGE,
            [
                ("隔离对象", "Shell / 文件 / 代码任务"),
                ("入口", "API / Plugin / MCP"),
                ("生命周期", "Lease / TTL / Release"),
                ("快照语义", "Pause / Rollback / Clone"),
                ("主要价值", "统一策略、凭据与审计"),
            ],
        ),
    ]
    for x, title, color, fill, rows in columns:
        draw.rounded_rectangle((x, 190, x + 490, 489), radius=22, fill=fill, outline=color, width=2)
        draw.text((x + 28, 214), title, font=font(CHINESE, 23), fill=color)
        for index, (key, value) in enumerate(rows):
            y = 266 + index * 43
            draw.text((x + 30, y), key, font=font(CHINESE, 16), fill=MUTED)
            draw.text((x + 155, y), value, font=font(CHINESE, 17), fill=INK)
            if index < len(rows) - 1:
                draw.line((x + 28, y + 32, x + 462, y + 32), fill=LINE, width=1)
    draw.rounded_rectangle((84, 527, 1116, 607), radius=15, fill=(239, 244, 250))
    draw.text((111, 545), "高风险双层路径", font=font(CHINESE, 17), fill=VIOLET)
    draw.text(
        (287, 545),
        "Kata/Firecracker 中的 Agent  →  Adapter  →  CubeSandbox 工具沙箱",
        font=font(CHINESE, 17),
        fill=INK,
    )
    draw.text((287, 575), "只有两个独立信任边界都必要时才值得叠加", font=font(CHINESE, 15), fill=MUTED)
    output = ASSET_DIR / "firecracker-vs-cubesandbox.png"
    image.save(output, format="PNG", optimize=True)
    return output


def save_launcher_kubevirt_comparison() -> Path:
    image, draw = figure(
        "Launcher Pod 不是“轻量版 KubeVirt”",
        "相似点只有调度外形；VM API、控制器与生命周期能力完全不同",
    )
    columns = [
        (
            84,
            "实验 Launcher Pod",
            BLUE,
            PALE_BLUE,
            [
                ("K8s 对象", "普通特权 Pod"),
                ("控制器", "无 VM 控制器"),
                ("Guest 可见性", "K8s 视角是黑盒"),
                ("网络 / 存储", "脚本与宿主机路径自管"),
                ("生命周期", "Entrypoint / Trap / Pod 删除"),
                ("适用场景", "节点准入与 VMM 实验"),
            ],
        ),
        (
            626,
            "KubeVirt",
            VIOLET,
            (241, 237, 253),
            [
                ("K8s 对象", "VirtualMachine / VMI"),
                ("控制器", "virt-controller / virt-handler"),
                ("Guest 可见性", "状态、事件与 VM API"),
                ("网络 / 存储", "CNI / Multus / PVC / CDI"),
                ("生命周期", "启停、重启、迁移、快照"),
                ("适用场景", "通用与持久化 VM"),
            ],
        ),
    ]
    for x, title, color, fill, rows in columns:
        draw.rounded_rectangle((x, 183, x + 490, 531), radius=22, fill=fill, outline=color, width=2)
        draw.text((x + 28, 207), title, font=font(CHINESE, 23), fill=color)
        for index, (key, value) in enumerate(rows):
            y = 257 + index * 43
            draw.text((x + 30, y), key, font=font(CHINESE, 16), fill=MUTED)
            draw.text((x + 155, y), value, font=font(CHINESE, 16), fill=INK)
            if index < len(rows) - 1:
                draw.line((x + 28, y + 32, x + 462, y + 32), fill=LINE, width=1)
    draw.rounded_rectangle((84, 558, 1116, 607), radius=11, fill=(239, 244, 250))
    centered_text(
        draw,
        600,
        570,
        "共同点：都可借 Kubernetes 调度到 KVM 节点；区别：一个是实验模式，一个是 VM 平台",
        font(CHINESE, 17),
        MUTED,
    )
    output = ASSET_DIR / "launcher-vs-kubevirt.png"
    image.save(output, format="PNG", optimize=True)
    return output


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    outputs = [
        compose_landscape(),
        compose_square(),
        save_paths(),
        save_runtimeclass_flow(),
        save_cubesandbox_comparison(),
        save_launcher_kubevirt_comparison(),
    ]
    for output in outputs:
        print(f"generated: {output}")


if __name__ == "__main__":
    main()
