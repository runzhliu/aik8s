#!/usr/bin/env python3
"""Deterministic H3 article cover and experiment diagram, no synthetic evidence."""
from pathlib import Path
import math
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'articles/wechat/assets/minimax-h3-h20'
OUT.mkdir(parents=True,exist_ok=True)
FONT='/System/Library/Fonts/Hiragino Sans GB.ttc'
INK='#172e45';MUTED='#60758a';BLUE='#1776a0';TEAL='#278c8f';LINE='#d9e4ed';BG='#f5f9fc'
def font(size):return ImageFont.truetype(FONT,size)
def text(d,xy,t,size=24,color=INK):
 f=font(size);b=d.textbbox((0,0),t,font=f);d.text((xy[0]-b[0],xy[1]-b[1]),t,font=f,fill=color)
def center(d,box,t,size=24,color=INK):
 f=font(size);b=d.textbbox((0,0),t,font=f);d.text(((box[0]+box[2]-b[2]-b[0])/2,(box[1]+box[3]-b[3]-b[1])/2),t,font=f,fill=color)
def cover():
 im=Image.new('RGB',(900,383),BG);d=ImageDraw.Draw(im)
 d.rectangle((0,0,12,383),fill=BLUE)
 text(d,(48,40),'AI-K8S 技术工程',17,BLUE)
 text(d,(48,100),'MiniMax H3',55)
 text(d,(48,178),'上 H20-3e',42)
 text(d,(49,258),'音视频生成 · 双引擎验证',23,MUTED)
 text(d,(49,326),'SGLang Diffusion  /  vLLM-Omni',17,BLUE)
 d.rounded_rectangle((605,63,851,302),radius=20,fill='white',outline=LINE,width=2)
 for n in range(4):
  x=626+n*53;d.rounded_rectangle((x,88,x+42,155),radius=7,fill='#e6f2f8',outline='#a6cddd')
  center(d,(x,88,x+42,155),'H20',13,BLUE)
 d.line((633,181,825,181),fill=LINE,width=2)
 for x in range(629,829,6):
  h=8+int(16*abs(math.sin((x-629)*0.065)));d.line((x,224-h,x,224+h),fill=TEAL,width=3)
 center(d,(620,264,836,291),'VIDEO + AUDIO',16,TEAL)
 im.save(OUT/'cover.png')
def workflow():
 im=Image.new('RGB',(1200,675),BG);d=ImageDraw.Draw(im)
 text(d,(55,44),'一次生成，验收画面与声音',39)
 text(d,(56,106),'固定模型与采样参数，独立及同机并行时段分别记录',22,MUTED)
 items=[('共享模型源','只读核对'),('NVMe / CFS','校验后加载'),('4 × H20-3e','SGLang / vLLM'),('原始 MP4','保留并回传')]
 for i,(title,sub) in enumerate(items):
  x=55+i*280;d.rounded_rectangle((x,204,x+250,355),radius=16,fill='white',outline=LINE,width=2)
  center(d,(x,226,x+250,281),title,28,BLUE);center(d,(x,284,x+250,329),sub,20,MUTED)
  if i<3:
   d.line((x+256,279,x+273,279),fill=BLUE,width=3);d.polygon([(x+274,279),(x+265,274),(x+265,284)],fill=BLUE)
 d.rounded_rectangle((55,412,1145,568),radius=16,fill='#e9f4f6')
 text(d,(80,437),'媒体验收目标',24,TEAL)
 text(d,(80,484),'视频：H.264 · 24 fps',25)
 text(d,(620,484),'音频：AAC · 32 kHz · 双声道',25)
 text(d,(57,608),'结果留存：请求 JSON、原始音视频、媒体检测、日志、显存与功耗、文件校验和',19,MUTED)
 im.save(OUT/'workflow.png')
def square():
 im=Image.new('RGB',(900,900),BG);d=ImageDraw.Draw(im)
 d.rectangle((0,0,14,900),fill=BLUE)
 text(d,(65,65),'AI-K8S 技术工程',25,BLUE)
 text(d,(65,170),'MiniMax H3',78)
 text(d,(65,287),'四张 H20-3e',65)
 text(d,(65,405),'5 秒视频，要等多久？',43)
 for n in range(4):
  x=65+n*193;d.rounded_rectangle((x,520,x+165,655),radius=15,fill='white',outline=LINE,width=2)
  center(d,(x,520,x+165,655),'H20-3e',28,BLUE)
 text(d,(65,720),'SGLang Diffusion / vLLM-Omni',30,TEAL)
 text(d,(65,787),'实测数据 · 参考输入 · 视频留存',27,MUTED)
 im.save(OUT/'cover-square.png')
cover();square();workflow()
print(OUT)
