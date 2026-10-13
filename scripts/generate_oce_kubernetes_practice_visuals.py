#!/usr/bin/env python3
"""Draw sanitized OCE trial topology and acceptance boundaries from observed results."""

from pathlib import Path
from generate_openclaw_enterprise_visuals import canvas, card, arrow, label, BLUE, TEAL, MUTED

OUT = Path(__file__).resolve().parents[1] / 'docs/assets/rag-agent/openclaw-enterprise-practice'


def topology():
    im, d = canvas('OCE 试点：管理入口与模型验证分别走通',
                   '两套集群只承担跨集群入口；OCE 控制面和 Agent 均运行在同一套运行集群')
    label(d, 60, 146, '办公网管理入口', size=19, bold=True)
    entries = [
        ('办公网浏览器', ['HTTPS / Console', '已有登录会话', '查看版本与日志']),
        ('接入集群 Ingress', ['终结浏览器 TLS', '转发到运行集群', '使用内部 Host 路由']),
        ('运行集群入口', ['Ingress 与专用代理', '重建允许的请求头', '保留登录凭据']),
        ('OCE API', ['鉴权与资源管理', 'Console 静态页面', 'Worker 异步部署']),
    ]
    for x, (title, lines) in zip([60, 348, 636, 924], entries):
        card(d, (x, 182, x+216, 340), title, lines, BLUE, title_size=20)
    for left, right in [(276,348),(564,636),(852,924)]:
        arrow(d, [(left+5,260),(right-5,260)])
    label(d, 60, 376, '实际模型验证：仅本机监听的独立路径', size=19, bold=True)
    entries = [
        ('本机校验脚本', ['127.0.0.1 端口转发', '无凭据请求必须拒绝', '本地 Gateway 密码']),
        ('Agent Gateway', ['Embedded OpenClaw', '加载指定配置快照', '通过 Secret 使用模型凭据']),
        ('内部模型 API', ['接收新的随机校验串', '返回实际模型回复', '本轮已验证调用成功']),
    ]
    for x, (title, lines) in zip([60,432,804], entries):
        card(d, (x,414,x+336,572), title, lines, TEAL, title_size=22)
    arrow(d, [(401,491),(427,491)])
    arrow(d, [(773,491),(799,491)])
    label(d,60,609,'原生聊天页面没有接入办公网；Console 的 Succeeded 表示部署记录，不等于模型验收。',size=17,color=MUTED)
    im.save(OUT/'access-paths.png',optimize=True)


def acceptance():
    im,d=canvas('从安装成功到模型实际回复', '本轮验收逐层检查；配置了模型、Pod Ready 和部署成功各自证明不同的事情')
    entries=[
        ('1  数据库与安装',['PostgreSQL TLS 校验','迁移 / Bootstrap 完成','RBD 持久卷绑定']),
        ('2  租户与授权',['认领预建租户空间','Secret 按资源授权','限定 Worker 权限']),
        ('3  运行时启动',['Revision 配置快照','Succeeded 记录','Pod 1/1 Ready']),
        ('4  实际模型验证',['未认证请求：401','新随机校验串被返回','单次观测：5.37 秒']),
    ]
    for x,(title,lines) in zip([60,348,636,924],entries):
        card(d,(x,185,x+216,345),title,lines,BLUE,title_size=20)
    for left,right in [(276,348),(564,636),(852,924)]:
        arrow(d,[(left+5,264),(right-5,264)])
    card(d,(60,413,564,573),'本轮已走通',['办公网 HTTPS Console 登录与版本查看','Embedded OpenClaw 调用内部模型','独立服务身份和指定 Secret 的使用授权'],TEAL)
    card(d,(636,413,1140,573),'后续需独立验证',['原生聊天 UI 与私有网关路由','工作区 / 工具 / 渠道与多用户权限','高可用、恢复和长时间运行'],BLUE)
    label(d,60,610,'5.37 秒来自一个功能验证请求，包含 Agent 处理时间，不作为吞吐或延迟基准。',size=17,color=MUTED)
    im.save(OUT/'acceptance.png',optimize=True)


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    topology()
    acceptance()
    print('Generated 2 sanitized OCE practice figures.')
