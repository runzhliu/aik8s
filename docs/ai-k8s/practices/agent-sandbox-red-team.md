---
title: Agent Sandbox 攻防实验
description: 用文件、凭据、网络、资源耗尽和持久化测试验证 Agent 隔离边界
status: lab
last_reviewed: 2026-08-04
---

# Agent Sandbox 攻防实验

实验目标是验证不可信 Agent 代码最多能影响什么，而不是证明“容器很安全”。所有攻击样例只能在授权、隔离且无生产凭据的环境执行。

## 1. 威胁用例

| 类别 | 测试问题 | 通过标准 |
| --- | --- | --- |
| 文件 | 能否读取宿主机、其他 Workspace 或 Secret | 只能访问显式工作区 |
| 身份 | 能否取得 SA Token、云元数据或工具密钥 | 默认无长期凭据 |
| 网络 | 能否扫描内网、访问控制面或数据服务 | 仅允许声明的 Egress |
| 内核 | 能否使用危险 Syscall、设备和特权能力 | Runtime/Policy 拒绝 |
| 资源 | Fork Bomb、磁盘填满、GPU/网络滥用 | Quota、Limit、超时生效 |
| 持久化 | 任务结束后能否留下进程、文件或路由 | Sandbox 可验证销毁 |
| 工具 | Prompt 能否越权调用高危 API | Tool Gateway 二次授权 |

## 2. 对比运行时

在相同 Pod API 和策略下比较普通容器、强化容器、gVisor、Kata/微虚机和专用 Sandbox Runtime。记录启动时间、密度、系统调用兼容、网络、GPU 支持、销毁残留和逃逸面。

## 3. Prompt Injection 链

```text
不可信网页/文档
  → Prompt Injection
  → Agent 生成工具调用
  → Tool Gateway 鉴权与参数校验
  → Sandbox 执行
  → 输出过滤与审计
```

Sandbox 只能限制执行后果，不能替代工具授权、数据权限和人工确认。

## 4. 自动化证据

每个测试保存 Sandbox ID、镜像 Digest、RuntimeClass、NetworkPolicy、身份、系统调用/网络审计、退出原因和清理结果。升级内核、Runtime 或策略后自动回归。

## 5. 停止条件

一旦发现可以访问真实凭据、生产网络或宿主设备，立即停止实验、撤销凭据并按安全事件处理。不要继续尝试扩大影响范围。

延伸阅读：[Agent Sandbox 选型](../rag-agent/agent-sandbox-selection.md)、[Agent 与工具执行](../agentic-workloads.md)、[安全治理](../security-governance.md)
