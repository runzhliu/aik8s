# AI/LLM on Kubernetes 基础设施知识库

面向平台工程师、SRE、训练和模型服务团队的 AI/LLM on Kubernetes 工程文档。

内容覆盖 GPU 与异构加速器、调度队列、RDMA、数据与模型分发、分布式训练、LLM 推理、RAG、Agent Sandbox、GPU Notebook、可观测性、安全、成本和生产运维。文档重点说明组件边界、选型条件、关键指标、故障路径和上线检查，而不只是罗列工具名称。

线上站点：[https://aik8s.run/](https://aik8s.run/)

## 技术栈

- Markdown 保存文档内容；
- Zensical 构建静态站点；
- `zensical.toml` 管理导航、主题和站点配置；
- GitHub Actions 在 `main` 分支更新后完成构建与部署。

## 本地预览

项目默认使用 Docker，因此不需要在本机安装 Python 依赖：

```bash
make dev
```

打开 <http://localhost:8000>。修改 `docs/` 下的文件后，页面会自动刷新。

也可以使用 Python 虚拟环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/zensical serve
```

## 验证构建

```bash
make build
```

构建结果保存在 `site/`，该目录不会提交到 Git。

## 添加内容

在 `docs/` 中创建文件夹和 Markdown 文件即可。目录名和文件名会形成公开 URL，建议只使用小写英文字母、数字和连字符；中文展示名称放在一级标题或 `zensical.toml` 的 `nav` 配置中。

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
make build
git diff --check
```

## 项目结构

```text
.
├── docs/                  # Markdown 文档与静态资源
│   ├── ai-k8s/            # AI/LLM on Kubernetes 核心专题
│   └── k3s-upgrade/       # 实际案例
├── deploy/                # 服务器部署配置与说明
├── scripts/               # 构建辅助脚本
├── zensical.toml          # 站点导航和主题配置
├── requirements.txt       # 本地 Python 构建依赖
└── Makefile               # 本地预览和构建入口
```

## 生产部署

向 `main` 分支推送后，GitHub Actions 会严格构建站点，将静态文件上传到服务器的新版本目录，然后原子切换 `/srv/aik8s/current`。构建或部署失败时不会切换当前线上版本。

完整的首次配置步骤见 [部署说明](deploy/README.md)。
