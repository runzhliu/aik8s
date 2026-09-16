#!/usr/bin/env python3
"""Build public 16:9 screenshots for the LangChain/LangGraph/Langfuse demo."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "docs/assets/langchain-langgraph-langfuse-demo"
RAW_DIR = ROOT / ".local/langgraph-langfuse-demo/assets"
WIDTH, HEIGHT = 1200, 675
INK = (23, 32, 51)
MUTED = (100, 116, 139)
PANEL = (248, 250, 252)
LINE = (219, 227, 239)
FONT_PATH = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size=size, index=1 if bold else 0)


def make_demo_overview() -> Path:
    source = Image.open(RAW_DIR / "demo-full-raw.png").convert("RGB")
    # Keep the whole execution panel. A narrow background rail on both sides
    # preserves 16:9 without cutting off the bottom of the four node cards.
    crop = source.crop((0, 0, 1440, 850))
    framed = Image.new("RGB", (1512, 850), (246, 248, 252))
    framed.paste(crop, (36, 0))
    output = framed.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    path = ASSET_DIR / "demo-overview.png"
    output.save(path, optimize=True)
    return path


def make_trace_tree() -> Path:
    source = Image.open(RAW_DIR / "langfuse-trace-v2-raw.png").convert("RGB")
    # Crop out the public-sharing header. It was added after the measured run and
    # would make that administrative operation look like request latency.
    output = source.crop((30, 210, 1310, 930))
    draw = ImageDraw.Draw(output)

    # Keep the real call tree on the left and replace environment-specific chips
    # above the input/output pane with a neutral public caption.
    draw.rectangle((440, 0, 1280, 108), fill=PANEL)
    draw.line((440, 108, 1280, 108), fill=LINE, width=2)
    draw.text((468, 20), "Langfuse Trace：从图节点展开到 LangChain 子链", font=font(27, True), fill=INK)
    draw.text((468, 66), "真实运行截图 · 左侧为调用树，右侧为节点输入与输出", font=font(18), fill=MUTED)

    output = output.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    path = ASSET_DIR / "langfuse-trace-tree.png"
    output.save(path, optimize=True)
    return path


def main() -> None:
    for path in (make_demo_overview(), make_trace_tree()):
        print(path)


if __name__ == "__main__":
    main()
