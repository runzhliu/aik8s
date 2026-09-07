#!/usr/bin/env python3
"""Build paired evidence contact sheets from verified, retained MP4 files."""
import argparse, hashlib, json, subprocess, os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

FONT='/System/Library/Fonts/Hiragino Sans GB.ttc'
BG='#f5f9fc';INK='#172e45';MUTED='#60758a'
def text(d,x,y,value,size=24,color=INK):
    f=ImageFont.truetype(FONT,size);b=d.textbbox((0,0),value,font=f)
    d.text((x-b[0],y-b[1]),value,font=f,fill=color)
def frame(video,index,target):
    subprocess.run([os.environ.get('FFMPEG','ffmpeg'),'-v','error','-y','-i',str(video),'-vf',f'select=eq(n\\,{index})','-frames:v','1',str(target)],check=True)
    return target
def paste(im,path,x,y):
    pic=Image.open(path).convert('RGB');pic.thumbnail((350,200));im.paste(pic,(x+(350-pic.width)//2,y+(200-pic.height)//2))
def generate(item,out,work):
    work.mkdir(parents=True,exist_ok=True)
    im=Image.new('RGB',(1200,1110),BG);d=ImageDraw.Draw(im)
    text(d,50,35,item['title'],36)
    text(d,50,96,'实际输出抽帧 · 4 × H20-3e · 1344 × 768 · 50 个采样点',22,MUTED)
    text(d,50,147,'输入素材',27)
    for i,src in enumerate(item['inputs']):
        p=Path(src['path']);
        if p.suffix=='.mp4':p=frame(p,60,work/f'input-{i}.png')
        paste(im,p,50+i*375,197);text(d,50+i*375,407,src['label'],21,MUTED)
    text(d,800,205,'相同提示词与参考素材',23)
    text(d,800,250,f"固定种子 {item['seed']}",24)
    text(d,800,295,item['input_note'],21,MUTED)
    report=[];cases=[]
    for i,row in enumerate(item['outputs']):
        video=Path(row['video']);meta=json.loads(video.with_suffix('.json').read_text());cases.append(meta['case'])
        assert meta['status']=='PASS' and meta['case']['seed']==item['seed']
        digest=hashlib.sha256(video.read_bytes()).hexdigest();assert digest==meta['file_sha256']
        # Result metadata was produced by full ffprobe/ffmpeg acceptance; bind it to the verified MP4 hash.
        probe=next(v for v in meta['media']['streams'] if v['codec_type']=='video')
        n=int(probe['nb_read_frames']);assert n==124
        y=458+i*275;text(d,50,y,f"{row['engine']} · 首个正式样本 · {meta['e2e_s']:.3f} 秒",26,'#1776a0' if i==0 else '#278c8f')
        indices=[0,(n-1)//2,n-1]
        for k,idx in enumerate(indices):
            p=frame(video,idx,work/f'output-{i}-{idx}.png');paste(im,p,50+k*375,y+43)
            text(d,50+k*375,y+247,f'帧 {idx} / {idx/24:.3f} 秒',20,MUTED)
        report.append(dict(engine=row['engine'],sample=video.stem,sha256=digest,frames=indices,e2e_s=meta['e2e_s']))
    assert cases[0]==cases[1],'Compared inputs must be identical'
    text(d,50,1020,item['version_note'],20,MUTED)
    text(d,50,1064,'同种子不保证跨引擎像素一致；抽帧不评价完整运动、声音语义或口型。',20,MUTED)
    out.mkdir(parents=True,exist_ok=True);im.save(out/(item['id']+'.png'))
    (out/(item['id']+'.json')).write_text(json.dumps(dict(title=item['title'],seed=item['seed'],samples=report),ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--work',type=Path,required=True);a=p.parse_args()
    for item in json.loads(a.manifest.read_text()):generate(item,a.output,a.work/item['id'])
