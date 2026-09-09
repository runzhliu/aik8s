# APF 隔离案例配图与证据

| 资产 | 目的 | 来源与制作方式 |
| --- | --- | --- |
| grafana-case.png | 展示席位、执行、拒绝、排队和等待之间的关系 | 实际 Grafana 专用看板截图；固定真实实验时间范围，不展示地址栏 |
| grafana-case-mobile.png | 手机查看六个监控面板 | 同一真实看板，430 像素宽度自动重排为单列后截图 |
| client-outcomes.png | 比较批量账号和对照账号的请求结果 | results.json；确定性绘图 |
| client-outcomes-mobile.png | 手机版结果图 | 相同数据，独立重排 |
| results.json / requests.csv / metrics.json | 支持核对图表与数值 | 实验客户端日志和 Prometheus API；去除内网地址、集群名与凭据 |

技术图沿用项目浅色风格与中文字体。截图保留真实图形和坐标，不将合成图冒充 Grafana。截图只允许裁去无关空白，不修改指标曲线。
