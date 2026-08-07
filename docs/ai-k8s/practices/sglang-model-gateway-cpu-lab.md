---
title: SGLang Model Gateway CPU 实战
description: 在没有 GPU 的 Kubernetes 1.30 集群部署 SGLang Router 和两个 OpenAI-Compatible Mock Worker，实测动态发现、轮询、摘除恢复与 Prometheus 指标
status: lab
last_reviewed: 2026-08-07
---

# SGLang Model Gateway CPU 实战

没有 GPU 也能先验证 SGLang 的一部分集群能力，但必须把结论限定在 **Model Gateway/Router 控制链**。本次在 sr1 Kubernetes 1.30.4 集群部署 SGLang Router v0.2.4 和两个 CPU OpenAI-Compatible Mock Worker，实际跑通了 Kubernetes 动态发现、OpenAI API 转发、Round Robin、Pod 摘除与恢复、请求 ID 和 Prometheus 指标。

本次没有加载模型，因此不能据此宣称 SGLang Runtime、Radix Cache、GPU 性能、多机并行或 P/D KV 传输已经跑通。

## 1. 最终结果

| 验证项 | 实测结果 | 能说明什么 |
| --- | --- | --- |
| Router 与 Worker 启动 | 1 个 Router、2 个 Mock Worker 全部 Ready | 镜像、参数、探针和基础网络可用 |
| Kubernetes 动态发现 | 日志依次出现两个 `Adding pod` 和 `Activated worker` | Label Selector、Pod IP 和最小 RBAC 有效 |
| OpenAI-Compatible API | `/health`、`/v1/models`、`/v1/chat/completions` 返回 200 | 请求能经过 Router 到达 Worker |
| Round Robin | 连续 6 次请求在两个 Pod 间严格交替 | 路由策略实际生效，不只是参数存在 |
| 缩容与摘除 | 2→1 后日志出现 `Removing pod`、`Removed worker` | Router 能跟随 Pod 删除更新后端集合 |
| 单副本连续服务 | 缩容后连续 3 次请求均由剩余 Pod 返回 200 | 已摘除的 Pod 没有继续接收请求 |
| 恢复 | 1→2 后新 Pod 自动注册，两次请求再次落到不同 Pod | 新 Endpoint 能自动加入路由集合 |
| Prometheus | 有决策、请求、健康、熔断结果和 Add/Remove Worker 指标 | 可接入监控，但要先校验指标语义 |

## 2. 先区分 Runtime 和 Router 版本

截至 2026 年 8 月 7 日，SGLang 主项目最新发布是 v0.5.16，但 Docker Hub 上可直接获取的官方 `lmsysorg/sglang-router` 容器最新标签是 v0.2.4。这不是把 Runtime 降级成 v0.2.4，而是 **SGLang Runtime 与 Model Gateway/Router 使用独立版本和发布节奏**。

本次固定组合为：

| 项目 | 版本或状态 |
| --- | --- |
| Kubernetes Server | v1.30.4 |
| 节点架构 | amd64 |
| SGLang Router | v0.2.4 |
| SGLang Runtime | 未部署 |
| Worker | CPU OpenAI-Compatible Mock v0.7.0 |
| GPU | 集群未报告可分配 `nvidia.com/gpu` |

Router v0.2.4 官方镜像当前只有 amd64 架构，ARM 集群要先确认是否自行构建或上游已经补充对应镜像。生产上线不能只写“使用最新版 SGLang”，应分别记录 Runtime、Router、Worker 协议和镜像 Digest。

参考：[SGLang v0.5.16](https://github.com/sgl-project/sglang/releases/tag/v0.5.16)、[SGLang Router 镜像标签](https://hub.docker.com/r/lmsysorg/sglang-router/tags)、[SGLang Model Gateway](https://docs.sglang.io/docs/advanced_features/sgl_model_gateway)

## 3. 实验架构

```text
本机 curl
  → kubectl port-forward（只用于验收）
  → Service/sglang-router:30000
  → SGLang Router v0.2.4
      ├─ watch Pods: sglang.ai/worker=true
      ├─ round_robin
      ├─ health check / circuit breaker
      └─ :29000 Prometheus metrics
           ├─ Pod A :8000，CPU Mock
           └─ Pod B :8000，CPU Mock
```

资源分成两个 Namespace：

- `sglang-system`：Router、ServiceAccount 和 Service；
- `sglang-demo`：两个 CPU Worker、发现 Role/RoleBinding 和内部 Service。

Role 只有 `get/list/watch pods`，并通过跨 Namespace RoleBinding 授予 `sglang-system:sglang-router`。不需要 ClusterRole，也不应为了方便给 Router `cluster-admin`。

完整清单见 [`examples/sglang-sr1/sglang-cpu-gateway.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/sglang-sr1/sglang-cpu-gateway.yaml)。

## 4. 部署与检查

```bash
kubectl apply -f examples/sglang-sr1/sglang-cpu-gateway.yaml
kubectl rollout status deployment/sglang-cpu-mock \
  -n sglang-demo --timeout=180s
kubectl rollout status deployment/sglang-router \
  -n sglang-system --timeout=180s
```

实测 Worker 分布在不同节点，Router 也独立运行：

```text
sglang-router                              1/1 Running
sglang-cpu-mock-59bd99996c-5k8zm          1/1 Running
sglang-cpu-mock-59bd99996c-twtxx          1/1 Running
```

验证最小权限：

```bash
kubectl auth can-i list pods \
  --as=system:serviceaccount:sglang-system:sglang-router \
  -n sglang-demo
```

返回 `yes`。Router 日志给出的发现证据是：

```text
Starting K8s service discovery | selector: 'sglang.ai/worker=true'
Adding pod: sglang-cpu-mock-... | type: Some(Regular) | url: http://10.x.x.x:8000
Activated worker http://10.x.x.x:8000 (marked as healthy)
```

Pod 必须同时满足 Label Selector 和 Ready 条件。这里直接发现 Pod IP，不经过 Worker Service 负载均衡，否则 Router 无法知道实际选中了哪个副本。

## 5. API 与 Round Robin 实测

测试时只临时转发本机端口：

```bash
kubectl port-forward --address 127.0.0.1 \
  -n sglang-system service/sglang-router \
  33000:30000 32900:29000
```

健康检查返回：

```text
HTTP/1.1 200 OK
OK
```

模型列表返回 `unknown`：

```json
{"object":"list","data":[{"id":"unknown","object":"model","owned_by":"local"}]}
```

这是 Mock 没有实现完整 SGLang `/server_info`、`/model_info` 元数据协议的结果，不是生产模型名的推荐写法。

Chat 请求：

```bash
curl -sS http://127.0.0.1:33000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "unknown",
    "messages": [{"role": "user", "content": "round robin test"}],
    "max_tokens": 4,
    "stream": false
  }'
```

连续 6 次响应中携带的 Mock Pod 名依次为：

```text
mdjhj → 5k8zm → mdjhj → 5k8zm → mdjhj → 5k8zm
```

这条证据比“两个 Pod 都 Ready”更强：它证明请求经过 Router，且 `round_robin` 在两个独立 Endpoint 上实际执行。

## 6. 摘除与恢复实验

先把 Worker 从 2 个缩到 1 个：

```bash
kubectl scale deployment/sglang-cpu-mock \
  -n sglang-demo --replicas=1
```

Router 观察到 Pod 删除：

```text
Removing pod: sglang-cpu-mock-... | url: http://10.x.x.x:8000
Removed worker http://10.x.x.x:8000
```

随后连续 3 次 Chat 请求均由剩余 Pod `5k8zm` 返回 200。恢复到 2 个副本：

```bash
kubectl scale deployment/sglang-cpu-mock \
  -n sglang-demo --replicas=2
```

日志再次出现新 Pod 的 `Adding pod` 与 `Activated worker`；恢复后的两次请求分别落到新、旧两个 Pod。

这验证的是 **Kubernetes 期望状态变化后的发现与摘除**。它还没有覆盖节点瞬断、半开连接、正在流式输出时进程死亡、健康端点假阳性和长请求重试。生产故障演练仍要增加这些变量。

## 7. Prometheus 指标实测

Router 在 29000 端口暴露 Prometheus 文本指标。完成轮询、滚动更新和缩放后，关键值包括：

```text
sgl_router_http_responses_total{status_code="200"} 13
sgl_router_requests_total{route="/v1/chat/completions"} 12
sgl_router_job_success_total{job_type="AddWorker"} 5
sgl_router_job_success_total{job_type="RemoveWorker"} 3
sgl_router_policy_decisions_total{policy="round_robin",worker="http://10.x.x.x:8000"} ...
sgl_router_processed_requests_total{worker="http://10.x.x.x:8000"} ...
sgl_router_worker_health{worker="http://10.x.x.x:8000"} 1
sgl_router_cb_outcomes_total{worker="http://10.x.x.x:8000",outcome="success"} ...
```

Add/Remove 计数包含实验过程中的 Router/Worker 滚动更新，不等于一次缩放的纯计数。告警和 Dashboard 更适合组合：

- 当前 Pod 清单与 `sgl_router_worker_health`；
- 每个 Worker 的 `processed_requests_total`；
- `policy_decisions_total` 与预期策略；
- HTTP 429/5xx、熔断状态和请求时延；
- Kubernetes Ready、重启、驱逐和 Endpoint 变化。

### 7.1 一个真实的指标缺口

本次实测中，两个 Worker 的 `worker_health=1`，请求也持续 200，但：

```text
sgl_router_active_workers 0
```

因此在 Router v0.2.4 上不能单独用这个 Gauge 判断“无可用 Worker”。上线前应在目标版本复测并向上游确认指标语义或缺陷；在修复前，以逐 Worker 健康、请求决策、实际成功率和 Kubernetes Endpoint 做交叉判断。

## 8. CPU Mock 暴露出的协议边界

### 8.1 `openai` 后端不能与动态发现组合

为了让通用 Flask Mock 完全按 HTTP/1.1 工作，曾尝试加入：

```text
--backend openai
```

Router v0.2.4 启动时直接拒绝该组合：

```text
Configuration error: OpenAI mode does not support service discovery
```

因此本实验保留默认 `sglang` 后端和 Kubernetes Service Discovery。若目标是代理任意静态 OpenAI-Compatible Endpoint，可以使用 `--backend openai` 配合静态 Worker URL；如果目标是随 Pod 扩缩自动发现，则应使用真实 SGLang Runtime，或先确认新版本已经改变此限制。

### 8.2 通用 Mock 不等于 SGLang Worker

默认后端在注册时会探测 SGLang 连接能力。Flask/Werkzeug Mock 不支持 HTTP/2，日志会出现一次 505 探测错误，Router 随后回退后仍能以 HTTP/1.1 完成 Chat 请求。这只能证明回退路径，不能作为生产协议组合。

Mock 返回的 Token Usage 也是随机占位值，不能拿来计算吞吐、成本、TTFT 或 TPOT。

### 8.3 为什么示例没有 API Key

Router 的 `--api-key` 用于访问 Worker。通用 Mock 与默认 SGLang 后端组合时没有正确继承这套认证约定，因此 CPU Worker 保持无认证，只能在隔离 Namespace 内使用，并且不能暴露到办公网或公网。

生产推荐：

```text
Client
  → Higress：TLS、OIDC/API Key、租户授权、限流、审计
  → SGLang Router：模型池选择、Prefix/负载/P-D 路由
  → SGLang Runtime：受限集群网络、可选 Worker mTLS/API Key
```

## 9. 没有 GPU 时还可以测什么

| 能在 CPU/Mock 先测 | 本次状态 | 不能由 CPU Mock 证明 |
| --- | --- | --- |
| Router 启动、探针、Service 和资源限制 | 已测 | CUDA/ROCm Kernel 可用性 |
| Kubernetes Label 动态发现与最小 RBAC | 已测 | 模型真正加载成功 |
| Round Robin | 已测 | Prefix Cache 带来的真实收益 |
| Worker Add/Remove 与基础连续服务 | 已测 | GPU OOM、NCCL 故障和节点高速网络 |
| Prometheus 暴露、请求 ID、HTTP 状态 | 已测 | TTFT、TPOT、吞吐和显存容量 |
| `random`、`power_of_two`、并发上限、队列、重试、熔断 | 可继续测 | 策略在真实长短请求混合下的最优性 |
| P/D Label Selector 和 Router 启动参数 | 可做语法/控制面测试 | Prefill 生成 KV、Bootstrap、KV 传输和 Decode 续算 |
| CORS、超时、429 与故障码 | 可继续测 | 流式 Token 中断后的真实恢复语义 |

`cache_aware` 即使能在 Mock 上做策略单元测试，也没有真实 Radix/Prefix Cache 命中证据。不能因为相同 Prompt 被固定到同一 Pod，就宣称缓存命中率或 TTFT 已改善。

## 10. 切换到 GPU Runtime 的步骤

1. 用通过兼容测试的 SGLang Runtime 镜像替换 CPU Mock；
2. 固定模型、量化、CUDA、PyTorch、通信库、Router 与 Runtime 版本；
3. 设置 `nvidia.com/gpu`、共享内存、模型缓存 PVC/HostPath 和启动探针；
4. 让 Pod 保留 Router Selector，并确认 `/health`、模型元数据和 API Key 协议；
5. 先用单 Pod 单/多卡建立正确性和性能基线；
6. 再用 RBG、LeaderWorkerSet 或 KubeRay 表达一个跨节点模型副本；
7. 最后验证 Cache-aware、P/D、KV 传输、取消、滚动发布和 Autoscaling。

P/D 模式下 Prefill 和 Decode 都是真正运行模型的 GPU Worker。Router 可以通过 `--prefill-selector`、`--decode-selector` 发现两类 Pod，但必须用真实 Runtime 验证 Bootstrap 信息与 KV 数据路径。只看到两类 Pod 被注册，不代表 Decode 能接着 Prefill 的 KV 继续生成。

## 11. 与 Higress、RBG 和 AIBrix 怎么组合

| 组件 | 在这条链路中的职责 |
| --- | --- |
| Higress | 域名、TLS、认证、租户配额、协议治理、审计和统一入口 |
| SGLang Router/Model Gateway | SGLang Worker 发现、请求级副本选择、Prefix/负载策略和 P/D 配对 |
| RBG/LWS/KubeRay | Router、Prefill、Decode 或多节点 Rank 的 Pod 生命周期和拓扑 |
| SGLang Runtime | 模型执行、Batch、Radix Cache、并行与 KV 数据路径 |
| AIBrix | 另一套 LLM Gateway、模型路由、编排、Autoscaling、LoRA 和 KV 能力组合 |

一种清晰组合是：

```text
Higress
  → SGLang Router Service
  → RBG 管理的 SGLang Prefill/Decode Worker
```

如果已经采用 AIBrix Gateway，就不要再让 SGLang Router 和 AIBrix 同时对同一个模型池做模型感知选副本。可以按模型分路：存量 vLLM 模型走 AIBrix，原生 SGLang/P-D 模型走 SGLang Router；也可以统一选一套内部 Router。无论怎么选，重试、超时、限流、熔断和 Autoscaling 都只能有明确的策略 Owner。

## 12. 生产前验收清单

- [x] Router 和两个 CPU Mock Worker Ready；
- [x] ServiceAccount 只拥有目标 Namespace 的 Pod 读取权限；
- [x] 两个 Pod IP 被自动发现和激活；
- [x] OpenAI Chat 请求返回 200；
- [x] 六次请求证明 Round Robin；
- [x] 2→1 摘除后剩余副本连续服务；
- [x] 1→2 恢复后新副本自动加入；
- [x] Prometheus 指标包含 Worker、策略和 HTTP 维度；
- [ ] 换成真实 SGLang Runtime 并加载目标模型；
- [ ] 验证流式、取消、重试预算、熔断和长请求故障；
- [ ] 用真实 Prefix Cache 负载比较策略收益；
- [ ] 用真实 Prefill/Decode Worker 证明 KV 传输；
- [ ] 接入 Higress 认证、NetworkPolicy、Secret 和 mTLS；
- [ ] 在目标 Router 版本复核 `active_workers` 指标。

## 13. 清理

实验资源完全隔离，可以按 Namespace 清理：

```bash
kubectl delete namespace sglang-demo sglang-system
```

本次为了保留后续 GPU 替换入口，没有执行清理；最终状态仍是 1 个 Router 和 2 个 CPU Mock Worker Ready。

## 延伸阅读

- [SGLang Model Gateway](https://docs.sglang.io/docs/advanced_features/sgl_model_gateway)
- [SGLang Router Source](https://github.com/sgl-project/sglang/tree/main/sgl-model-gateway)
- [SGLang Documentation](https://docs.sglang.io/)
- [RBG 多角色推理编排与 sr1 实战](rbg-existing-cluster.md)
- [AI Gateway、推理路由与流量治理](../inference/gateway-routing.md)
- [分布式与 P/D 分离推理](../inference/distributed-serving.md)
