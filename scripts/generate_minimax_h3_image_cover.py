#!/usr/bin/env python3
"""Adapt the approved MiniMax M3 cover to H3 Image's single-GPU test."""
from pathlib import Path
from PIL import Image, ImageDraw
from generate_minimax_m3_brand_covers import BG, INK, MUTED, RED, ORANGE, LINE, rail, text, center
out=Path(__file__).resolve().parents[1]/'articles/wechat/assets/minimax-h3-image-h20/cover'
out.mkdir(parents=True,exist_ok=True)
im=Image.new('RGB',(900,383),BG); d=ImageDraw.Draw(im);rail(d,383,12)
text(d,(45,36),'AI-K8S 技术工程',18,RED)
text(d,(45,95),'MiniMax-H3-Image',43,RED)
text(d,(45,173),'单卡 H20-3e 实测',35)
text(d,(45,258),'vLLM-Omni + SGLang · 2K / 4K',22,RED)
text(d,(45,320),'真实出图 · 压测 · 部署建议',20,MUTED)
d.rounded_rectangle((661,103,800,218),radius=10,fill='white',outline=LINE,width=2)
center(d,(661,103,800,218),'H20-3e',20,RED)
center(d,(625,275,840,315),'1 GPU · 6 steps',22,ORANGE)
im.save(out/'cover.png',optimize=True)
im=Image.new('RGB',(900,900),BG);d=ImageDraw.Draw(im);rail(d,900,14)
text(d,(62,66),'AI-K8S 技术工程',25,RED)
text(d,(62,177),'MiniMax-H3-Image',60,RED)
text(d,(62,310),'单卡 H20-3e',64)
text(d,(62,420),'出图与压测实战',42)
d.rounded_rectangle((65,532,235,602),radius=10,fill='white',outline=LINE,width=2)
center(d,(65,532,235,602),'H20-3e',24,RED)
text(d,(62,748),'vLLM-Omni + SGLang · 2K / 4K',29,RED)
im.save(out/'cover-square.png',optimize=True)
