# 微信公众号草稿导入

这里保存面向微信公众号重新编排的文章。仓库脚本通过微信公众号官方 API 上传封面和正文图片，并把文章直接写入草稿箱；它不会自动发布或群发。

## 首次配置

在公众号后台获取 AppID 和 AppSecret，并确认调用机器的出口 IP 已加入公众号 IP 白名单。凭据只保存在本地忽略目录中：

```bash
mkdir -p .deploy-secrets
$EDITOR .deploy-secrets/wechat.env
```

文件内容：

```dotenv
WECHAT_APP_ID=<公众号 AppID>
WECHAT_APP_SECRET=<公众号 AppSecret>
# 可选的默认“阅读原文”地址；也可以在 make 命令中逐篇覆盖
WECHAT_SOURCE_URL=https://aik8s.run/path/to/article/
```

不要把真实 AppSecret 提交到 Git，也不要粘贴到聊天记录中。

公众号图文作者在发布脚本中固定为 `runzhliu`，不再从环境变量覆盖，避免不同机器或旧配置
把作者写回公众号名称。

## 本地预览

```bash
make wechat-preview
open .wechat-output/deepseek-v4-flash-h20.html
```

也可以启动 Doocs Markdown Editor 做人工排版检查：

```bash
make wechat-editor
```

## 写入草稿箱

先准备与文章匹配的封面，再显式传入文章、封面和“阅读原文”地址：

```bash
make wechat-draft \
  WECHAT_ARTICLE=articles/wechat/gpu-notebook-storage.md \
  WECHAT_COVER=articles/wechat/assets/gpu-notebook-storage-cover.png \
  WECHAT_SOURCE_URL=https://aik8s.run/ai-k8s/practices/gpu-notebook-platform-evolution/
```

命令依次完成：

1. 将 Markdown 转换成带内联样式的微信正文 HTML；
2. 上传正文中的本地或远程图片；
3. 上传指定封面为永久素材；
4. 调用草稿接口创建一篇图文草稿。

`wechat-draft` 不会自动重新生成封面，避免用默认参数覆盖已经设计好的文章头图。需要生成默认封面时单独执行 `make wechat-cover`，自定义封面则直接运行 `scripts/generate_wechat_cover.py` 并传入标题参数。

## 双封面规范

每篇微信公众号文章应同时准备两个独立排版的封面：

- 横向主封面：`900×383`，文件名建议为 `<slug>-cover.png`，通过 `WECHAT_COVER` 上传到图文草稿；
- 方形分享封面：`900×900`，文件名建议为 `<slug>-cover-square.png`，用于方形分享位、头像流或后续渠道复用。

两个版本应使用相同的主张、配色和视觉母题，但要分别安排文字和主体安全区；不得把横版简单拉伸或盲裁成方形。生成后分别检查尺寸、文件大小、手机端字号、文字重叠和数据准确性。草稿 API 当前只接收一个主封面，方形版本作为同篇文章的配套素材保存。

参考资料统一使用“标题：明文 URL”，不强求正文超链接。例如：

```text
SGLang Cookbook：https://docs.sglang.io/
```

这样即使微信草稿 API 清洗正文外链，读者仍能看到和复制完整地址。“阅读原文”继续指向公开版页面。

```bash
.venv/wechat/bin/python scripts/publish_wechat.py inspect \
  --media-id <draft-media-id> \
  --env-file .deploy-secrets/wechat.env
```

如果回读结果为 `anchors: 0`，说明该账号或当前草稿接口清洗掉了正文外链；明文 URL 和“阅读原文”的公开落地页仍应保留。

成功后终端会输出草稿的 `media_id`。如遇 `invalid ip`，检查公众号 IP 白名单；如遇接口权限错误，检查公众号类型、认证状态和接口权限。

可以用变量覆盖默认文章或封面：

```bash
make wechat-draft \
  WECHAT_ARTICLE=articles/wechat/another-article.md \
  WECHAT_COVER=articles/wechat/assets/another-cover.png \
  WECHAT_SOURCE_URL=https://aik8s.run/path/to/article/
```
