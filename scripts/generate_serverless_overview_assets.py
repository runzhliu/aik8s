from pathlib import Path
from xml.sax.saxutils import escape
p=Path('docs/assets/images/serverless-overview')
def text(x,y,s,size=23,color='#263631',weight='400'):
 return f'<text x="{x}" y="{y}" font-family="Hiragino Sans GB, PingFang SC, Arial, sans-serif" font-size="{size}" font-weight="{weight}" text-anchor="middle" fill="{color}">{escape(s)}</text>'
def box(x,y,w,h,a,b,shade='#f4f8f6'):
 return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{shade}" stroke="#adc8bc" stroke-width="1.5"/>'+text(x+w/2,y+42,a,25)+text(x+w/2,y+72,b,18,'#587068')
def head(title,subtitle):
 return '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675"><rect width="1200" height="675" fill="#fff"/><defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 Z" fill="#71857c"/></marker></defs>'+text(600,65,title,31)+text(600,102,subtitle,19,'#61756c')
def arrow(x1,y1,x2,y2):
 return f'<path d="M{x1} {y1} L{x2} {y2}" fill="none" stroke="#71857c" stroke-width="2" marker-end="url(#arrow)"/>'
s=head('Serverless 平台的基本组成','Serverless platform: responsibilities and runtime')
s+=box(70,165,235,100,'用户、应用、Agent','User / App / Agent')+box(365,165,300,100,'请求、消息、定时事件','Requests / Messages / Timers')+box(725,165,405,100,'入口与控制面','Entry and control plane')
s+=arrow(305,215,365,215)+arrow(665,215,725,215)
s+=text(928,300,'鉴权 · 路由 · 排队 · 扩缩容',20,'#587068')+text(928,329,'Auth · Routing · Queueing · Scaling',18,'#587068')
s+=arrow(750,265,750,380)
s+=box(725,380,405,100,'服务、函数、任务','Services / Functions / Jobs')+box(365,380,300,100,'Kubernetes 基础设施','Pods / Scheduling / Storage')+box(70,380,235,100,'计算与隔离运行时','CPU / GPU / Isolation')
s+=arrow(725,430,665,430)+arrow(365,430,305,430)
s+=text(600,558,'贯穿全链路：日志、指标、结果与审计',21,'#587068')+text(600,591,'Across the flow: logs, metrics, results and audit',18,'#587068')+'</svg>'
(p/'platform.svg').write_text(s)
s=head('从零唤醒 HTTP 服务','How an HTTP request wakes a zero-replica service')
steps=[('请求到达','Request arrives'),('入口接收','Entry receives'),('触发扩容','Scaling starts'),('启动并就绪','Pod becomes ready'),('返回结果','Response returned')]
for i,(a,b) in enumerate(steps):
 x=45+i*231;s+=box(x,245,205,120,a,b)
 if i<4:s+=arrow(x+205,305,x+231,305)
s+=text(600,443,'排队、调度、拉镜像与初始化都会影响等待时间',21,'#587068')+text(600,478,'Queueing, scheduling, image pull and initialization add to the wait.',18,'#587068')+text(600,556,'入口缓冲和客户端超时均有限',21,'#587068')+text(600,591,'Buffer capacity and client timeouts are finite.',18,'#587068')+'</svg>'
(p/'request-flow.svg').write_text(s)
