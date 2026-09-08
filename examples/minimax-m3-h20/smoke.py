"""Small real-request acceptance suite; save all requests, responses and fixtures."""
import base64, hashlib, io, json, os, pathlib, re, time, urllib.error, urllib.request
import av
import numpy as np
from PIL import Image, ImageDraw, ImageFont
base=os.environ['BASE_URL'].rstrip('/');model=os.environ['MODEL'];out=pathlib.Path(os.environ['RESULTS_DIR']);out.mkdir(parents=True,exist_ok=True)
assert not (out/'smoke-summary.json').exists(),'Use a fresh output directory'
results=[]
def save(name,obj): (out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2))
def chat(messages,mode='disabled',**kw):return {'model':model,'messages':messages,'temperature':0,'max_tokens':512,'chat_template_kwargs':{'thinking_mode':mode},**kw}
def req(case,payload=None,path='/v1/chat/completions',validate=None,expect=200):
 start=time.monotonic();save(case+'-request.json',payload)
 request=urllib.request.Request(base+path,data=None if payload is None else json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer EMPTY'})
 try:
  try:
   with urllib.request.urlopen(request,timeout=180) as r:status=r.status;raw=r.read().decode()
  except urllib.error.HTTPError as e:status=e.code;raw=e.read().decode()
  (out/(case+'-response.txt')).write_text(raw)
  body=json.loads(raw);ok=status in (expect if isinstance(expect,tuple) else (expect,)) and (validate(body) if validate else True)
  result={'case':case,'status':'PASS' if ok else 'FAIL','http_status':status,'elapsed_s':time.monotonic()-start}
 except Exception as e:body={};result={'case':case,'status':'FAIL','error':str(e),'elapsed_s':time.monotonic()-start}
 results.append(result);print(json.dumps(result),flush=True);save('progress.json',results);return body
def content(x):return x['choices'][0]['message'].get('content') or ''
def number(x,n):return re.search(r'(?<!\d)'+str(n)+r'(?!\d)',content(x)) is not None
req('models',path='/v1/models',validate=lambda x:any(m['id']==model for m in x['data']))
math=[{'role':'user','content':'一个仓库有 240 件货物，先发走 15%，又入库 36 件，现在有多少件？只给结论并简要说明。'}]
req('math-disabled',chat(math),validate=lambda x:number(x,240) and '<mm:think>' not in content(x))
req('math-enabled',chat([{'role':'user','content':'计算 17 加 28，并简述计算过程。'}],mode='enabled',max_tokens=1024),validate=lambda x:number(x,45) and bool(x['choices'][0]['message'].get('reasoning_content') or x['choices'][0]['message'].get('reasoning')) and '<mm:think>' not in content(x))
req('math-adaptive',chat([{'role':'user','content':'2 加 3 是多少？'}],mode='adaptive'),validate=lambda x:number(x,5))
messages=[{'role':'user','content':'本次测试代号是 jade628，请记住。'},{'role':'assistant','content':'已记住本次测试代号。'},{'role':'user','content':'请说一句中文问候语。'},{'role':'assistant','content':'你好，祝你今天顺利。'},{'role':'user','content':'本次测试代号是什么？'}]
req('multi-turn',chat(messages),validate=lambda x:'jade628' in content(x))
# Keep raw SSE and require explicit terminator plus a final finish_reason.
payload=chat([{'role':'user','content':'只回答：北京是中国的首都。'}],stream=True,stream_options={'include_usage':True});save('stream-request.json',payload);chunks=[];beg=time.monotonic()
try:
 with urllib.request.urlopen(urllib.request.Request(base+'/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'}),timeout=180) as r:
  for raw in r:
   line=raw.decode();chunks.append(line)
 (out/'stream-response.sse').write_text(''.join(chunks));events=[json.loads(x[6:]) for x in chunks if x.startswith('data: ') and x.strip()!='data: [DONE]'];text=''.join(c.get('delta',{}).get('content') or '' for x in events for c in x.get('choices',[]));ok=any(x.strip()=='data: [DONE]' for x in chunks) and '北京' in text and any(c.get('finish_reason') for x in events for c in x.get('choices',[]));results.append({'case':'stream','status':'PASS' if ok else 'FAIL','elapsed_s':time.monotonic()-beg})
except Exception as e:results.append({'case':'stream','status':'FAIL','error':str(e)})
tools=[{'type':'function','function':{'name':'get_weather','description':'查询城市当前天气，返回摄氏温度','parameters':{'type':'object','properties':{'city':{'type':'string'}},'required':['city'],'additionalProperties':False}}}]
message=[{'role':'user','content':'请调用 get_weather 查询广州天气，获取结果后用中文回答。'}]
def valid_tool(x):
 calls=x['choices'][0]['message'].get('tool_calls',[])
 return bool(calls) and calls[0]['function']['name']=='get_weather' and any(s in str(json.loads(calls[0]['function']['arguments']).get('city','')).lower() for s in ['广州','guangzhou'])
x=req('tool-call',chat(message,tools=tools,tool_choice='auto'),validate=valid_tool)
if results[-1]['status']=='PASS':
 m=x['choices'][0]['message'];calls=m['tool_calls'];follow=message+[m]+[{'role':'tool','tool_call_id':c['id'],'content':json.dumps({'city':'广州','temperature_c':24,'condition':'晴'},ensure_ascii=False)} for c in calls]
 req('tool-result',chat(follow,tools=tools,tool_choice='none'),validate=lambda x:number(x,24))
# Deterministic image fixture; never a screenshot of another user's data.
im=Image.new('RGB',(640,384),'white');draw=ImageDraw.Draw(im);font=ImageFont.load_default(size=38)
for i,(label,value) in enumerate([('Q1',120),('Q2',90),('Q3',150)]):
 y=45+i*105;draw.text((20,y),f'{label}: {value}',fill='black',font=font);draw.rectangle((230,y,230+value*2,y+55),fill=['#c33','#3a6','#36c'][i])
im.save(out/'quarter-chart.png');url='data:image/png;base64,'+base64.b64encode((out/'quarter-chart.png').read_bytes()).decode()
req('image-ocr',chat([{'role':'user','content':[{'type':'text','text':'读出图中 Q1、Q2、Q3 的数值，指出哪个季度比上季度下降。'},{'type':'image_url','image_url':{'url':url}}]}]),validate=lambda x:all(number(x,v) for v in [120,90,150]) and any(s in content(x) for s in ['Q2','第二季度','二季度']))
# Keep the video and checksums outside the model Pod.
with av.open(str(out/'color-order.mp4'),'w') as v:
 stream=v.add_stream('mpeg4',rate=8);stream.width=256;stream.height=256;stream.pix_fmt='yuv420p'
 for i in range(32):
  rgb=[(255,0,0),(0,255,0),(0,0,255)][min(i//11,2)];arr=np.empty((256,256,3),dtype=np.uint8);arr[:]=rgb;frame=av.VideoFrame.from_ndarray(arr,format='rgb24')
  for packet in stream.encode(frame):v.mux(packet)
 for packet in stream.encode():v.mux(packet)
video='data:video/mp4;base64,'+base64.b64encode((out/'color-order.mp4').read_bytes()).decode()
def color_order(x):
 s=content(x).lower();positions=[min([i for i in [s.find(a),s.find(b)] if i>=0],default=-1) for a,b in [('红','red'),('绿','green'),('蓝','blue')]]
 return all(i>=0 for i in positions) and positions==sorted(positions)
req('video-order',chat([{'role':'user','content':[{'type':'text','text':'按出现顺序列出视频中背景的三种颜色。'},{'type':'video_url','video_url':{'url':video}}]}]),validate=color_order)
req('invalid-max-tokens',chat(math,max_tokens=-1),expect=(400,422))
req('recovery',chat([{'role':'user','content':'计算 6 乘 7，只给出答案。'}]),validate=lambda x:number(x,42))
fixtures=[{'file':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in out.iterdir() if p.suffix in ['.png','.mp4']];save('fixtures.json',fixtures)
summary={'status':'PASS' if all(r['status']=='PASS' for r in results) else 'CHECK_FAILURES','model':model,'cases':results,'fixtures':fixtures};save('smoke-summary.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)
