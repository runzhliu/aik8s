#!/usr/bin/env python3
"""Prepare display copies from measured model outputs and genuine Grafana screenshots."""
from pathlib import Path
from PIL import Image
import shutil
root=Path(__file__).resolve().parents[1];src=root/'docs/assets/practices/minimax-h3-image-h20';dest=root/'articles/wechat/assets/minimax-h3-image-h20';dest.mkdir(parents=True,exist_ok=True)
for n in ('concurrency-en','edit-concurrency-en','resolution-performance'):
 shutil.copyfile(src/(n+'.png'),dest/(n+'.png'))
def canvas(items,name):
 out=Image.new('RGB',(1200,675),'white')
 for file,box in items:
  im=Image.open(src/file).convert('RGB');im.thumbnail((box[2]-box[0],box[3]-box[1]));out.paste(im,(box[0]+(box[2]-box[0]-im.width)//2,box[1]+(box[3]-box[1]-im.height)//2))
 out.save(dest/name,optimize=True)
canvas([('portrait.webp',(45,30,595,645)),('landscape.webp',(605,30,1155,645))],'samples.png')
canvas([('smoke-t2i.webp',(45,30,595,645)),('smoke-4k.webp',(605,30,1155,645))],'product-2k-4k.png')
canvas([('edit-comparison.webp',(0,0,1200,675))],'edit-comparison.png')
canvas([('edit-8-input.webp',(0,30,590,645)),('edit-8.webp',(610,30,1200,645))],'eight-ref.png')
im=Image.open(src/'grafana-load.png').convert('RGB').crop((315,115,1369,720)); im=im.resize((1176,675),Image.Resampling.LANCZOS); out=Image.new('RGB',(1200,675),'white'); out.paste(im,((1200-im.width)//2,(675-im.height)//2)); out.save(dest/'grafana.png',optimize=True)
canvas([('smoke-t2i.webp',(45,30,595,645)),('sglang-smoke.webp',(605,30,1155,645))],'engines-smoke.png')
im=Image.open(src/'sglang-grafana-visual.png').convert('RGB').crop((315,115,1369,720));im=im.resize((1176,675),Image.Resampling.LANCZOS);out=Image.new('RGB',(1200,675),'white');out.paste(im,((1200-im.width)//2,(675-im.height)//2));out.save(dest/'sglang-grafana.png',optimize=True)
