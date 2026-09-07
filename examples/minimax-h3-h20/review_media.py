#!/usr/bin/env python3
"""Extract an evidence contact sheet and audio metrics without rewriting originals."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import array
from PIL import Image,ImageDraw,ImageFont
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('video',type=Path)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
info=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',str(a.video)]))
v=next(x for x in info['streams'] if x['codec_type']=='video');n=int(v['nb_read_frames'])
frames=[round((n-1)*fraction) for fraction in [0,.2,.4,.6,.8,1]]
sheet=Image.new('RGB',(1200,780),'#f4f7fa');d=ImageDraw.Draw(sheet)
font=ImageFont.load_default(size=18)
for i,frame in enumerate(frames):
 path=a.output/f'frame-{frame:04d}.png'
 subprocess.run(['ffmpeg','-v','error','-i',str(a.video),'-vf',f'select=eq(n\\,{frame})','-frames:v','1',str(path)],check=True)
 image=Image.open(path).convert('RGB');image.thumbnail((580,327))
 x=10+(i%2)*600;y=10+(i//2)*260
 # Use fixed 16:9 thumbnail inside each labeled cell.
 image=image.resize((420,236));sheet.paste(image,(x,y));d.text((x+430,y+20),f'frame {frame}\n{frame/24:.3f}s',font=font,fill='#172e45')
sheet.save(a.output/'contact-sheet.png')
raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(a.video),'-map','0:a:0','-f','f32le','-ac','2','-ar','32000','-'])
samples=array.array('f');samples.frombytes(raw)
finite=all(math.isfinite(x) for x in samples);rms=math.sqrt(sum(x*x for x in samples)/len(samples));peak=max(abs(x) for x in samples)
metrics=dict(video_file=a.video.name,frames=n,width=v['width'],height=v['height'],audio_finite=finite,
             audio_rms=rms,audio_peak=peak,audio_rms_dbfs=20*math.log10(rms) if rms else None,
             caveat='Decoded audio signal checks do not establish semantic sound quality or audiovisual synchronization.')
(a.output/'review.json').write_text(json.dumps(metrics,indent=2)+'\n')
subprocess.run(['ffmpeg','-v','error','-i',str(a.video),'-map','0:a:0',str(a.output/'audio.wav')],check=True)
print(json.dumps(metrics,indent=2))
