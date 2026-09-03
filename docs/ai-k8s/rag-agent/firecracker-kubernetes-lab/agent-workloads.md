# Kata + Firecracker 上的 Agent 工作负载

本实验将 OpenClaw、DSH、Hermes 和 Codex 作为普通 Kubernetes Pod 运行，并通过
`runtimeClassName: kata-fc-lab` 选择运行时。因此，每个 Pod 外层都有一个
Kata/Firecracker microVM 隔离边界。随后，Agent 的 CubeSandbox 集成再通过
Adapter API 申请一个独立沙箱：

```text
Kubernetes Pod
  -> Kata runtime-rs
  -> Firecracker microVM（Agent 运行时）
  -> Agent 的 CubeSandbox 插件或 MCP 客户端
  -> CubeSandbox Adapter
  -> CubeSandbox 沙箱（工具执行）
```

这里有意验证的是两种系统的组合，而不是相互替代。Firecracker 提供 Pod 隔离边界，
CubeSandbox 则提供面向 Agent 的执行 API 和沙箱生命周期。

## 测试结果

| 应用 | 版本 | 验证路径 | 结果 |
| --- | --- | --- | --- |
| OpenClaw | 2026.8.2 | 插件发现、模型对话、`cube_exec`、`cube_status`、`cube_release` | 通过；3 次工具调用成功，0 次失败 |
| DSH | 0.1.2-alpha.4 | 无界面 Agent 运行和 CubeSandbox 插件工具 | 通过；返回执行标记并释放沙箱 |
| Hermes | 0.21.0 | 插件诊断、单次模型运行、CubeSandbox 生命周期 | 通过；检测到插件，返回执行标记，审计链完整 |
| Codex | 0.150.1 | Adapter 客户端和官方 MCP stdio 握手 | 部分通过；发现全部 17 个 MCP 工具，生命周期冒烟测试通过；未运行模型对话 |

没有为 Codex 人为制造成功结果。它的自定义模型提供方目前要求 Responses 协议，
而实验环境中的网关只提供 Chat Completions。因此改为独立验证 Adapter 和 MCP 集成。

![脱敏后的 Agent 测试结果矩阵](assets/evidence/agents-light.jpg)

## 可复现的部署结构

[`manifests/kata-fc-agents.yaml`](manifests/kata-fc-agents.yaml) 包含脱敏后的
Pod 定义。应用前，需要由环境侧提供以下对象，且不要将其真实值提交到仓库：

- `Secret/firecracker-agent-model`：包含所选 Agent 需要的模型端点和凭据环境变量；
- `Secret/cube-adapter-auth`：包含键 `token`；
- 从对应插件版本生成的四个 `firecracker-*-plugin` ConfigMap；
- 可访问的 CubeSandbox Adapter 服务，以及已进入节点本地镜像仓库或获准镜像仓库的
  四个固定版本工作负载镜像。

清单通过 Secret 引用传入凭据，移除 Linux capability，禁止权限提升，使用运行时
默认 seccomp 配置，并为每个应用分配独立的 `emptyDir` 工作区。

```bash
kubectl apply -f manifests/kata-fc-agents.yaml
kubectl wait -n agent-runtime --for=condition=Ready \
  pod/kata-fc-openclaw pod/kata-fc-dsh pod/kata-fc-hermes pod/kata-fc-codex \
  --timeout=300s
kubectl get pod -n agent-runtime -l app.kubernetes.io/part-of=firecracker-agent-lab -o wide
```

需要从内外两侧同时验证边界：`kubectl exec` 应返回 Kata Guest 内核信息；Worker
节点上则应为每个 Pod 看到一个 Firecracker VMM。

## 兼容性发现

被测 Kata TAP 网络无法访问集群常规 ClusterIP，但可以直接访问 Pod 地址。隔离
Worker 也无法访问模型端点，因此测试期间临时使用了受访问控制的 SSH 反向转发，并在
测试后移除。这些属于网络集成问题，而不是 Firecracker 故障。生产环境应修复 CNI/
Service 路由，并采用经过认证的内部出站路径，不应长期保留转发通道。

将 Agent 的整个状态目录挂载到 `emptyDir`，还在两个镜像中触发了 `fchmod`
兼容性问题。测试因此将应用状态保留在容器根文件系统中，只挂载工作区或已知兼容的
状态路径。把这些挂载改为持久化之前，需要重新验证所有权变更行为。

## 浅色模式应用截图

以下四张图片来自相同 CubeSandbox 应用集成的真实浅色模式产品截图，已复制到这个
独立发布包中。Firecracker 本次新增的结果由上方脱敏测量图和审计结果体现；这些 UI
截图并不冒充 Firecracker 控制台画面。

### OpenClaw

![OpenClaw 使用 CubeSandbox](assets/apps/openclaw-cubesandbox-light.jpg)

### DSH

![DSH 使用 CubeSandbox](assets/apps/dsh-cubesandbox-light.png)

### Hermes

![Hermes 使用 CubeSandbox](assets/apps/hermes-cubesandbox-light.png)

### Codex

![Codex 使用 CubeSandbox](assets/apps/codex-cubesandbox-light.png)

## 清理检查

每次 Agent 任务结束后，必须同时以应用输出和 Adapter 释放审计记录作为清理依据。
全部测试结束时，Adapter 报告的活跃租约数为 0。仅看到成功文本响应，不能证明沙箱
已经完成清理。
