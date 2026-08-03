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

生产构建还会注入 Google AdSense 和 Cloudflare Web Analytics；普通本地构建不加载这些第三方脚本：

```bash
make build-production
```

生产部署工作流会自动执行注入，不需要手动运行该命令。Cloudflare Web Analytics Token 是公开出现在浏览器 HTML 中的站点标识，不是 Cloudflare API Token 或账号凭据。

AdSense 授权销售方记录保存在 `docs/ads.txt`，构建后发布到站点根路径 `/ads.txt`。发布商 ID 变更时需要同时更新该文件和生产注入配置。

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

## 生产部署

向 `main` 分支推送后，GitHub Actions 会严格构建站点、注入生产 AdSense 代码，将静态文件上传到服务器的新版本目录，然后原子切换 `/srv/aik8s/current`。

完整的首次配置步骤见 [部署说明](deploy/README.md)。
