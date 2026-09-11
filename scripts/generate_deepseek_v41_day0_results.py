#!/usr/bin/env python3
"""Draw the recorded DS V4.1 results, including failed and unexecuted rounds."""
import json
from pathlib import Path
import generate_minimax_m3_visuals_v2 as v
from generate_glm53_day1_assets import BLUE, ORANGE, INK, MUTED, LINE
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/assets/practices/deepseek-v41-flash-h20-day0'
v.OUT=OUT
r=json.loads((OUT/'benchmark-summary.json').read_text())
rows={(x['engine'],x['stage'],x['case']):x for x in r['summary']}
def values(case,metric):
 return {e:{k:rows[e,'core',case][metric+'_round_'+k] for k in ['median','min','max']} for e in ['sglang','vllm']}
v.grouped('short-throughput.png','短请求吞吐', 'V4.1-Flash · 8×H20-3e · 1,024 输入 / 128 输出 · Token/s',
 [(f'C{c}',values(f'short-c{c}','output_tok_s')) for c in [1,8,32]],750,[0,150,300,450,600,750],1,
 '三轮中位数，线段为范围；C32：SGLang 192/192，vLLM 191/192 成功')
v.grouped('prefill-ttft.png','长输入首字等待', 'V4.1-Flash · 8×H20-3e · 128 输出 · 成功请求 TTFT P95（秒）',
 [(label,values(case,'ttft_p95_s')) for label,case in [('8K · C8','prefill-c8'),('8K · C32','prefill-c32'),('24K · C8','long-c8'),('24K · C32','long-c32')]],190,[0,40,80,120,160],1,
 '三轮 P95 的中位数与范围；vLLM 8K/C32 有 2/192 失败，未计入延迟')
v.grouped('decode-tpot.png','长输出的生成延迟', 'V4.1-Flash · 8×H20-3e · 1,024 输入 / 512 输出 · TPOT P95（毫秒）',
 [(f'C{c}',values(f'decode-c{c}','request_tpot_p95_ms')) for c in [1,8,32]],42,[0,10,20,30,40],2,
 '成功请求的平均 TPOT 分位数；三轮中位数与范围；vLLM C32 有 1/192 失败')
im,d=v.header('三类负载的请求成功数','成功数 / 已执行请求数 · SGLang 与 vLLM 分阶段统计',False)
for x,title,color,e in [(48,'SGLang',BLUE,'sglang'),(620,'vLLM',ORANGE,'vllm')]:
 d.rounded_rectangle((x,163,x+532,545),18,fill='white',outline=LINE,width=2)
 v.txt(d,x+26,190,title,31,fill=color,bold=True)
 for j,(stage,label) in enumerate([('core','核心'),('history','历史长度'),('slo','限速')]):
  z=next(a for a in r['counts'] if a['engine']==e and a['stage']==stage)
  v.txt(d,x+26,257+j*70,label,24)
  v.txt(d,x+186,252+j*70,f"{z['completed']:,} / {z['requests']:,}",30,fill=color,bold=True,latin=True)
 v.txt(d,x+26,482,'限速 9 轮已执行' if e=='sglang' else '限速 3/9 轮已执行，其余未测',22,fill=MUTED)
v.footer(d,'不含预热与校准；限速测试分别执行 9 轮与 3 轮')
im.save(OUT/'request-completeness.png',optimize=True)
# Three independent panels prevent different-unit scales from implying a ratio.
im,d=v.header('历史 V4：只能作为参考','相似短文本模板 · C1 / 256 输出 · 环境和缓存不同，不能归因代际加速',False)
entries=[('V4 历史',146.7792526,157.26048,6.2491587)]
for e in ['sglang','vllm']:
 h=next(x for x in r['history_template'] if x['engine']==e)
 entries.append(('V4.1 '+('SGLang' if e=='sglang' else 'vLLM'),h['throughput_round_median'],h['ttft_p95_ms_round_median'],h['tpot_p95_ms_round_median']))
for j,(title,unit,maximum,dec) in enumerate([('输出吞吐','Token/s',170,1),('TTFT P95','毫秒',260,1),('TPOT P95','毫秒',24,2)]):
 x=48+j*376;d.rounded_rectangle((x,168,x+352,554),18,fill='white',outline=LINE,width=2)
 v.txt(d,x+22,189,title,25,bold=True);v.txt(d,x+22,228,unit,21,fill=MUTED)
 for i,(name,*nums) in enumerate(entries):
  y=287+i*83;val=nums[j];color=['#667085',BLUE,ORANGE][i]
  v.txt(d,x+22,y,name,20,fill=color);v.txt(d,x+231,y,f'{val:.{dec}f}',24,fill=color,bold=True,latin=True)
  d.rounded_rectangle((x+22,y+33,x+22+val/maximum*301,y+49),5,fill=color)
v.footer(d,'V4 单轮 35 请求；V4.1 各三轮，共 36 / 81 请求；分位数为各轮中位数')
im.save(OUT/'history-reference.png',optimize=True)
(OUT/'figure-values.json').write_text(json.dumps(v.EVIDENCE,ensure_ascii=False,indent=2))
print('Saved five 1200×675 result figures')
