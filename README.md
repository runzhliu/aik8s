# AI & K8s 知识库

基于 Zensical 的 Markdown 文档站。`docs/` 下的文件夹会成为内容栏目，Markdown 文件会自动进入站点导航。

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

生产构建还会向每个 HTML 页面的 `<head>` 注入 Google AdSense：

```bash
make build-production
```

普通的 `make dev` 和 `make build` 不包含广告代码。生产部署工作流会自动执行注入，不需要手动运行该命令。

## 添加内容

在 `docs/` 中创建文件夹和 Markdown 文件即可。自动导航按文件名排序，需要固定顺序时可以使用 `01-`、`02-` 这样的前缀。

每个栏目建议添加一个 `index.md`：

```text
docs/
└── kubernetes/
    ├── index.md
    ├── 01-基础概念.md
    └── 02-集群部署.md
```

## 生产部署

向 `main` 分支推送后，GitHub Actions 会严格构建站点、注入生产 AdSense 代码，将静态文件上传到服务器的新版本目录，然后原子切换 `/srv/aik8s/current`。

完整的首次配置步骤见 [部署说明](deploy/README.md)。
