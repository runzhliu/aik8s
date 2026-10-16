# Adapter v0.6 文章素材

本文素材用于 `docs/ai-k8s/rag-agent/cubesandbox-agent-adapter-v06.md`。

| 文件 | 用途 | 来源 | 日期与格式 |
| --- | --- | --- | --- |
| `00-multi-cluster-architecture.svg` / `.png` | 解释一个入口连接两个执行集群 | 本目录可编辑 SVG，浏览器渲染；架构示意 | 2026-10-16，1200×675 |
| `01-openclaw-features-light.png` | 原生 Profile、执行、续租、Job 和释放 | Adapter v0.6.0 客户端实测 | 2026-10-15，1440×1150 |
| `02-dsh-features-light.png` | 额外 Web 端复测的调用与结果 | Adapter v0.6.0 客户端实测 | 2026-10-15，1440×1150 |
| `03-opencode-features-light.png` | MCP 调用、日志游标与 EOF | Adapter v0.6.0 客户端实测 | 2026-10-15，1440×1150 |
| `04-hermes-features-light.png` | 原生工具结果与两边释放 | Adapter v0.6.0 客户端实测 | 2026-10-15，1440×1150 |
| `05-console-profiles-light.png` | 演示租户的策略目录 | Adapter 控制台本地验收 | 2026-10-14，1376×268 |
| `06-console-audit-light.png` | 演示租户审计查询与执行链 | Adapter 控制台本地验收 | 2026-10-14，1376×942 |

截图原样复用已脱敏的公开文件，不修改应用文字。OpenCode、Hermes 的完整租约和 Job 引用已在源图中遮挡。原生界面保留完整纵横比，可在文章中点击查看原图。

源码与实测记录固定在 [Adapter v0.6.0](https://github.com/aik8s/cubesandbox-agent-adapter/tree/v0.6.0/docs/assets/production-features)，四张客户端图位于 `clients/`；控制台源文件为 `01-console-profiles-light.png` 和 `03-console-audit-light.png`。
