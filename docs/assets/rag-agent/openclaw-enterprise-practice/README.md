# OCE Kubernetes 实战配图

| 文件 | 用途 | 来源 | 尺寸 |
| --- | --- | --- | --- |
| access-paths.png | 区分办公网管理入口和本机模型验证路径 | 依据本轮部署拓扑绘制，内部标识省略 | 1200 × 675 |
| acceptance.png | 说明安装、授权、版本部署和模型回复的验收关系 | 依据本轮验证记录绘制；5.37 秒为一次功能请求 | 1200 × 675 |
| console-deployment-succeeded.jpg | 展示真实当前版本与部署结果 | 浏览器直接截取 Console 的无内部标识区域 | 1240 × 490 |
| native-tool-calls.jpg | 原生聊天实际写入并读取演示文件 | 浏览器真实截图，仅遮挡底部内部模型别名 | 1720 × 1294 |
| native-chat-result.jpg | 实际对话回复与原生文件查看器 | 浏览器真实截图，仅遮挡底部内部模型别名 | 1720 × 1294 |
| console-runtime.jpg | 当前版本、Pod Ready 与重启次数 | 浏览器真实截图，遮挡 Revision、Configuration 和 Pod 标识 | 1720 × 1242 |
| console-gateway-log.jpg | 实际容器就绪日志 | 真实 Logs 区域裁剪，遮挡 Pod 标识 | 990 × 470 |
| oce-demo-7f3a91.md.txt | 本轮 Agent 实际生成的无敏感信息文件 | 从当前服务 Pod 独立读回，117 个 UTF-8 字节；额外后缀避免站点转换成 HTML | 原始文本 |
| demo-artifact-verification.json | 文件字节数、校验串及 SHA-256 | 独立读取记录，仅保留可公开的验证字段 | JSON |

两张图解由 `scripts/generate_oce_kubernetes_practice_visuals.py` 生成，复用前篇 OCE 的字体与基础绘图样式。图解不是产品界面。

Console 截图没有改写状态值。页面的 Live serving 显示 Not verified，外部模型功能验收结果在正文单独解释。原始截图、模型请求响应及内部部署包不提交公开仓库。

新增四张应用截图均来自已部署实例的实际操作。原生界面通过只监听本机回环地址的端口转发访问；它不代表办公网已开放原生聊天。图片保留工具调用、实际回复、文件内容和运行时状态，灰色矩形仅遮挡内部标识。演示文件的 SHA-256 为 `e440f725c09ac0bdfe857c0a1b53747779e329ebf0d6d7b6d49d5eecc32e49d6`。这些截图及文件验证没有覆盖持久卷故障恢复、权限隔离或性能压测。
