# OCE Kubernetes 实战配图

| 文件 | 用途 | 来源 | 尺寸 |
| --- | --- | --- | --- |
| access-paths.png | 区分办公网管理入口和本机模型验证路径 | 依据本轮部署拓扑绘制，内部标识省略 | 1200 × 675 |
| acceptance.png | 说明安装、授权、版本部署和模型回复的验收关系 | 依据本轮验证记录绘制；5.37 秒为一次功能请求 | 1200 × 675 |
| console-deployment-succeeded.jpg | 展示真实当前版本与部署结果 | 浏览器直接截取 Console 的无内部标识区域 | 1240 × 490 |

两张图解由 `scripts/generate_oce_kubernetes_practice_visuals.py` 生成，复用前篇 OCE 的字体与基础绘图样式。图解不是产品界面。

Console 截图没有改写状态值。页面的 Live serving 显示 Not verified，外部模型功能验收结果在正文单独解释。原始截图、模型请求响应及内部部署包不提交公开仓库。
