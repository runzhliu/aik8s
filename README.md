# AI/LLM on Kubernetes 基础设施知识库

[简体中文](README.md) | [English](README.en.md)

Hi~你好👋, 这里是 runzhliu 的工作笔记，我是一名在 AI/LLM/大数据/Kubernetes 领域工作了十年的工程师，同时我也是一个记录狂人🤔，特别爱记笔记，这个站点是我基于这几年在 AI/LLM Infras 的工作经历总结的一些笔记，同时也经过一些大模型的润色发布的，希望和大家一起交流和学习，一起在大模型时代做一点🤏小事，无论是内容本身还是工作，欢迎大家找我交流😄👏!(runzhliu@163.com)

面向平台工程师、SRE、训练、模型服务与 Agent 平台团队的工程文档。

内容围绕 Kubernetes、GPU/LLM 基础设施和 Agent 工程展开：既有架构与源码分析，也有部署、性能测试、故障排查和迁移记录。模型实测尽量保留版本、硬件、请求条件、原始结果与监控截图；社区方案、线上指标观察和本地实验分别说明依据与适用范围。

线上站点：[简体中文](https://aik8s.run/) · [English](https://aik8s.run/en/)

## 从哪里开始

| 你关注的方向 | 内容与阅读入口 |
| --- | --- |
| Kubernetes 稳定性与规模化 | [多集群稳定性](docs/ai-k8s/practices/kubernetes-fleet-reliability.md)、[万节点优化](docs/ai-k8s/practices/large-scale-kubernetes-optimization.md)、[调度器优化](docs/ai-k8s/practices/large-scale-kubernetes-scheduler-optimization.md)、[API Server 负载均衡](docs/ai-k8s/practices/kube-apiserver-load-balancing.md) |
| GPU 平台与资源调度 | [GPU 节点软件栈](docs/ai-k8s/cluster/gpu-node-stack.md)、[设备管理与 DRA](docs/ai-k8s/accelerators/device-management.md)、[队列与多租户](docs/ai-k8s/queue-multitenancy.md)、[Koordinator 混部](docs/ai-k8s/scheduling/koordinator-colocation.md) |
| LLM 推理与模型测试 | [推理平台总览](docs/ai-k8s/llm-inference.md)、[引擎选型](docs/ai-k8s/inference/engines.md)、[KV Cache](docs/ai-k8s/inference/kv-cache-overview.md)、[实战与排障目录](docs/ai-k8s/practices/index.md) |
| 训练、存储与恢复 | [分布式训练与 Checkpoint 恢复](docs/ai-k8s/training/distributed-training-frameworks-recovery.md)、[SFT 入门](docs/ai-k8s/training/sft-concepts.md)、[模型制品与分发](docs/ai-k8s/data/model-artifacts.md) |
| Agent 的执行、记忆与评估 | [Harness](docs/ai-k8s/rag-agent/agent-harness-technology-overview.md)、[Memory](docs/ai-k8s/rag-agent/agent-memory-technology-overview.md)、[评估方法](docs/ai-k8s/rag-agent/agent-evaluation-overview.md)、[长任务中断续跑](docs/ai-k8s/rag-agent/agent-long-running-durable-execution.md) |
| 沙箱与企业 Agent 平台 | [沙箱选型](docs/ai-k8s/rag-agent/agent-sandbox-selection.md)、[Firecracker 与 CubeSandbox](docs/ai-k8s/rag-agent/firecracker-cubesandbox-enterprise-selection.md)、[OpenSandbox 实战](docs/ai-k8s/rag-agent/opensandbox-kubernetes-practice.md)、[OpenClaw Enterprise 实战](docs/ai-k8s/rag-agent/openclaw-enterprise-kubernetes-practice.md) |
| 网络与可观测性 | [Contiv 到 Kube-OVN 迁移](docs/ai-k8s/practices/contiv-to-kubeovn-underlay.md)、[OpenTelemetry 入门](docs/ai-k8s/opentelemetry-kubernetes-fundamentals.md)、[Kubernetes 组件与 Grafana 实战](docs/ai-k8s/practices/opentelemetry-kubernetes-components-grafana.md)、[大规模监控与时序数据库](docs/ai-k8s/practices/large-scale-kubernetes-monitoring-tsdb.md) |

完整目录见[技术地图](docs/ai-k8s/index.md)，建设方案可从[生产参考架构](docs/ai-k8s/guides/reference-architectures.md)和[集群组件清单](docs/cases/ai-cluster-component-checklist.md)开始。

## 实战与技术分析

| 文章 | 主要内容 |
| --- | --- |
| [DeepInfer 深度解析](docs/ai-k8s/inference/deepinfer-architecture-analysis.md) | 源码架构、性能口径、硬件限制与生产接入边界 |
| [Agent RL：veRL 与 Miles](docs/ai-k8s/rag-agent/agent-rl-verl-miles-overview.md) | 工具调用、交互轨迹、奖励设计与训练框架 |
| [OpenSandbox Kubernetes 实战](docs/ai-k8s/rag-agent/opensandbox-kubernetes-practice.md) | 官方 Console、任务执行、自动回收及 CubeSandbox 对比 |
| [Contiv 到 Kube-OVN 单节点迁移](docs/ai-k8s/practices/contiv-to-kubeovn-underlay.md) | 保留物理 VLAN，验证 IPAM、双向通信与监控 |
| [DeepSeek 1017 Day0](docs/ai-k8s/practices/deepseek-v41-flash-1017-day0.md) | 八卡 H20 的 vLLM 部署、性能测试与百万 Token 实测 |
| [DeepSeek：PRO 5000 与 H20 线上观察](docs/ai-k8s/practices/deepseek-v41-pro5000-h20-observation.md) | 根据生产指标讨论硬件差异和日常性能，不对生产服务追加压测 |
| [Qwen-Image-2.1 单卡 L20 双引擎实测](docs/ai-k8s/practices/qwen-image21-l20-benchmark.md) | 图像生成、图片编辑、原生画幅与显存边界 |
| [Koordinator Webhook 证书竞态排查](docs/ai-k8s/practices/koordinator-webhook-multireplica-cert-race.md) | 特殊接入环境中的多副本证书问题、修复过程与前后指标 |

## 关注微信公众号

更多 AI/LLM on Kubernetes 实战、部署记录与性能分析会同步到微信公众号 **AI-K8S技术工程**。使用微信扫描二维码，或在“微信搜一搜”中搜索 `AI-K8S技术工程`：

<p align="center">
  <img src="docs/assets/wechat-official-account-promo.png" alt="扫描二维码或通过微信搜一搜关注公众号 AI-K8S技术工程" width="900">
</p>

## 阅读、订阅与反馈

- 中英文文章一一对应，可在站点语言菜单中切换；文章显示创建与更新日期。
- 站点提供搜索、文章时间线及主题筛选；正文图片和 Mermaid 流程图支持点击放大查看。
- RSS：[中文](https://aik8s.run/rss.xml) · [English](https://aik8s.run/en/rss.xml)；Atom：[中文](https://aik8s.run/atom.xml) · [English](https://aik8s.run/en/atom.xml)。`/feed.xml` 与 `/en/feed.xml` 为订阅别名。
- 订阅仅包含文章，配图目录、README 说明和栏目首页不作为文章推送。
- 文章支持复制链接和分享；评论由 [Giscus](https://github.com/giscus/giscus) 接入本仓库的 GitHub Discussions。内容纠错也欢迎提交 Issue 或 Pull Request。

## 本地预览

站点使用 Markdown 与 Zensical，导航和主题配置在 `zensical.toml`。`make dev` 使用 Docker 运行固定版本的 Zensical；完整双语构建还需要本机的 Python 3.11 或更高版本：

```bash
make dev
```

打开 <http://localhost:8000>，此开发命令只预览中文源文件并自动刷新。完整双语预览使用 `make build` 后运行 `python3 -m http.server 8000 --directory site`，英文入口为 <http://localhost:8000/en/>。

也可以使用 Python 虚拟环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/zensical serve
```

上述两种 `serve` 方式都只预览中文。若不使用 Docker 构建双语站点，激活安装好依赖的虚拟环境后执行：

```bash
source .venv/bin/activate
python scripts/build_bilingual.py
python -m http.server 8000 --directory site
```

## 双语构建与发布

```bash
make build
```

此命令先核对中英文覆盖与同步状态，再严格构建中文和英文版本。构建结果保存在 `site/` 和 `site/en/`，该目录不会提交到 Git。英文使用独立导航、搜索、订阅和页面语言元数据，语言菜单直接切到对应文章。

普通双语构建已经生成文章日期、RSS/Atom、文章时间线、带更新时间的 Sitemap、页面分享、社交元数据和 TechArticle/BreadcrumbList 结构化数据。以下命令在此基础上额外注入生产使用的广告与统计脚本：

```bash
make build-production
```

文章标题下显示创建与更新日期，按北京时间展示。创建日期取文件首次进入 Git
历史的时间（追踪文件重命名），更新日期沿用页面元数据的口径，取最近一次文件提交
与 `last_reviewed` 中较晚的时间。日期在双语构建的 `build_distribution.py` 步骤生成，
不会因单纯重新构建站点而变化；本地执行 `make build` 即可查看。

向 `main` 分支推送后，GitHub Actions 会检查双语一致性、内部链接、图片、浏览器交互与资源体积，并将构建产物发布到 `site-production` GitHub Release。服务器通过 HTTPS 主动拉取并校验制品，安装到新版本目录，再原子切换 `/srv/aik8s/current`；激活后的健康检查失败时回滚。

当前部署流程见 [Server-pull deployment](ops/aik8s-pull-deploy/README.md)；工作流定义在 [.github/workflows/deploy.yml](.github/workflows/deploy.yml)。

## 添加内容

公开文档默认提供完整中英文版本：中文源文件在 `docs/`，英文在 `translations/en/`，两者保持相同相对路径。新增、更新或移动中文页面时，同步维护英文页、`translations/navigation.en.json` 与 `translations/manifest.json`，不能仅提供英文摘要或中文回退页。详细流程见 [双语维护说明](translations/README.md)。

目录名和文件名会形成公开 URL，建议只使用小写英文字母、数字和连字符；中文展示名称放在一级标题或 `zensical.toml` 的 `nav` 配置中。原有中文 URL 保持不变，英文 URL 添加 `/en/` 前缀。

测试与压测计划仅保存在本地 `.local/test-plans/`，不提交 GitHub，也不放入站点目录。公开内容保留已完成的实测结果、已验证的修复过程和可复现材料；已有报告中夹带的待执行方案也应先移到本地。部分历史实测报告沿用含 `plan` 的 URL，仅为保持既有链接可用。

每个栏目建议添加一个 `index.md`：

```text
docs/
└── kubernetes/
    ├── index.md
    ├── basic-concepts.md
    └── cluster-deployment.md
```

新增或移动页面后，还需要在 `zensical.toml` 中更新站点导航。提交前建议执行：

```bash
python3 scripts/bilingual.py
make build
git diff --check
```

仓库说明同样维护 [英文 README](README.en.md)，修改时同步两个版本；审核后运行 `python3 scripts/record_translation.py --readme` 更新同步记录。

## 项目结构

```text
.
├── docs/                  # Markdown 文档与静态资源
│   ├── ai-k8s/            # AI/LLM on Kubernetes 核心专题
│   ├── cases/             # 工程清单与案例入口
│   ├── k3s-upgrade/       # 集群升级案例
│   └── assets/            # 文章图片、图表与实测截图
├── examples/              # 公开示例、脚本与实验结果
├── articles/wechat/       # 公众号稿件与配图
├── overrides/             # 站点模板
├── ops/aik8s-pull-deploy/  # 当前服务器主动拉取部署流程
├── deploy/                # 部署配置示例与历史说明
├── scripts/               # 双语构建、内容检查与发布工具
├── translations/          # 英文文档、导航与双语同步记录
├── zensical.toml          # 站点导航和主题配置
├── requirements.txt       # 本地 Python 构建依赖
└── Makefile               # 本地预览和构建入口
```
