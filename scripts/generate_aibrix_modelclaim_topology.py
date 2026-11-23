"""Render the single-Pod L20 topology recorded in the ModelClaim lab."""
from pathlib import Path

from PIL import Image
from generate_dsv41_vllm032_research_assets import INK, MUTED, S, header, line, text

DEST = Path(__file__).resolve().parents[1] / "docs/assets/practices/aibrix-modelclaim-l20"
GREEN = "#407A69"
EDGE = "#9BAAA4"


def outline(draw, x, y, w, h, fill, edge):
    draw.rounded_rectangle((x*S, y*S, (x+w)*S, (y+h)*S), radius=8*S,
                           fill=fill, outline=edge, width=2*S)


def arrow_down(draw, x, y, tip):
    line(draw, x, y, x, tip, GREEN, 2)
    draw.polygon([(x*S, tip*S), ((x-6)*S, (tip-9)*S), ((x+6)*S, (tip-9)*S)], fill=GREEN)


def render(english):
    title = "Two model servers run inside one GPU Pod" if english else "一个 GPU Pod 如何运行两个模型"
    sub = "Kubernetes allocates the GPU once. AIBrix starts a vLLM service for each claim." if english else "Kubernetes 分配一次 GPU，AIBrix 为每份 Claim 启动独立的 vLLM 服务。"
    canvas, draw = header(title, not english, sub)
    centers = (330, 870)
    for x, name in zip(centers, ("Qwen3-0.6B", "Qwen2.5-0.5B-Instruct")):
        text(draw, x, 153, name, 28, INK, "center")
        text(draw, x, 195, "ModelClaim", 21, MUTED, "center")
        arrow_down(draw, x, 229, 262)

    outline(draw, 61, 265, 1078, 341, "#F7FAF9", EDGE)
    text(draw, 91, 286, "Pool Pod  /  aibrix-runtime" if english else "池 Pod  /  aibrix-runtime 容器", 25)
    text(draw, 1106, 289, "nvidia.com/gpu: 1", 22, MUTED, "right")

    for x, process, port in zip(centers, (28, 29), (20000, 20001)):
        outline(draw, x-225, 348, 450, 97, "white", EDGE)
        text(draw, x, 366, "vLLM API server" if english else "vLLM 服务进程", 26, INK, "center")
        text(draw, x, 406, f"PID {process}   ·   TCP {port}", 22, MUTED, "center")
        arrow_down(draw, x, 445, 494)
    outline(draw, 105, 498, 990, 78, "#E9F2EE", GREEN)
    text(draw, 600, 520, "Same NVIDIA L20   /   one GPU UUID" if english else "同一张 NVIDIA L20   /   一个 GPU UUID", 29, GREEN, "center")
    text(draw, 62, 633, "Both engines serve requests concurrently while awake." if english else "两个引擎同时处于 Active，并可同时接收各自模型的请求。", 21, MUTED)
    suffix = "-en" if english else ""
    canvas.resize((1200, 675), Image.Resampling.LANCZOS).save(DEST / f"pod-topology{suffix}.png", optimize=True)


if __name__ == "__main__":
    for english in (False, True):
        render(english)
