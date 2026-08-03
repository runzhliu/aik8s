# 生产部署说明

生产环境使用 GitHub Actions 构建 Zensical 站点，通过 SSH 和 rsync 上传静态文件，再由 Caddy 对外提供 HTTPS 服务。

生产工作流会在构建后向所有 HTML 页面注入 AdSense 客户端和 Cloudflare Web Analytics Beacon。本地预览和普通本地构建不会加载广告或统计脚本。

Cloudflare Web Analytics Token 会随 Beacon 出现在公开 HTML 中，它只标识统计站点，不具备 Cloudflare Dashboard、GraphQL API 或账号权限。不要把它与 Cloudflare API Token、Global API Key 或部署密钥混用。

## 1. 准备域名

将站点域名的 A/AAAA 记录指向生产服务器，并确认服务器防火墙开放 TCP 80 和 443。

## 2. 创建部署用户和目录

以下命令以 Debian/Ubuntu 为例，在服务器上执行：

```bash
sudo useradd --create-home --shell /bin/bash docs-deploy
sudo install -d -m 755 -o docs-deploy -g docs-deploy /srv/aik8s
sudo install -d -m 755 -o docs-deploy -g docs-deploy /srv/aik8s/releases
sudo install -d -m 700 -o docs-deploy -g docs-deploy /home/docs-deploy/.ssh
```

部署用户不需要 sudo 权限。

## 3. 创建部署密钥

在可信的本地设备上创建一对专用密钥：

```bash
ssh-keygen -t ed25519 -C aik8s-github-actions -f ./aik8s-deploy-key
```

将 `aik8s-deploy-key.pub` 的内容追加到服务器：

```text
/home/docs-deploy/.ssh/authorized_keys
```

确保该文件属于 `docs-deploy`，目录权限为 `700`，文件权限为 `600`。私钥内容只保存到 GitHub Secret，切勿提交到仓库。

## 4. 安装并配置 Caddy

使用 Caddy 官方软件源安装 Caddy，将 [Caddyfile.example](Caddyfile.example) 复制到服务器的 `/etc/caddy/Caddyfile`：

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddy 只读取 `/srv/aik8s/current`，发布新内容时不需要重启或重新加载 Caddy。

## 5. 配置 GitHub Environment

在 GitHub 仓库中打开 `Settings → Environments`，创建 `production` Environment。

添加 Environment variables：

| 名称 | 示例 | 说明 |
| --- | --- | --- |
| `PROD_HOST` | `aik8s.run` | 服务器域名或 IP |
| `PROD_PORT` | `62222` | SSH 端口 |
| `PROD_USER` | `docs-deploy` | 无 sudo 权限的部署用户 |

添加 Environment secrets：

| 名称 | 内容 |
| --- | --- |
| `PROD_SSH_KEY` | `aik8s-deploy-key` 私钥的完整内容 |
| `PROD_KNOWN_HOSTS` | 经过人工核对的服务器 SSH host key |

可使用以下命令取得 host key 候选值，但必须通过另一个可信渠道核对指纹后再保存：

```bash
ssh-keyscan -p 62222 aik8s.run
```

建议将 Environment 的部署分支限制为 `main`。如果 GitHub 套餐支持，也可以启用人工审批。

## 6. 首次发布

完成上述配置后，推送到 `main`，或在 GitHub Actions 页面手动运行 `Deploy documentation` 工作流。

工作流会发布到：

```text
/srv/aik8s/releases/<git-commit-sha>/
```

发布成功后，`/srv/aik8s/current` 会指向该版本。

## 回滚

列出服务器上的历史版本：

```bash
ls -1 /srv/aik8s/releases
```

确认目标版本后，以 `docs-deploy` 用户执行：

```bash
ln -sfn /srv/aik8s/releases/<previous-commit-sha> /srv/aik8s/.current-next
mv -Tf /srv/aik8s/.current-next /srv/aik8s/current
```

切换软链接后立即生效，无需重新构建或重启 Caddy。
