---
title: Higress AI Gateway：架构、安装与 AIBrix 接入实战
description: 在既有 Kubernetes 集群隔离安装 Higress，理解 Controller、Gateway、Console、AI Proxy 与可观测插件，并设计 Higress 和 AIBrix 的同集群及跨集群链路
status: lab
last_reviewed: 2026-08-06
---

# Higress AI Gateway：架构、安装与 AIBrix 接入实战

Higress 不只是一个把域名转发到 Service 的 Ingress Controller。它以 Envoy 为数据面，把传统 API Gateway 能力、Wasm 插件和面向大模型的协议代理、认证、Token 统计、限流及多模型治理放在同一个入口层。对于已经用 Higress 暴露业务 API、又准备引入 AIBrix、vLLM 或 SGLang 的团队，它更适合承担“统一入口和租户治理”，而不是替代推理平台内部的模型感知调度器。

本文包含一套在既有 Kubernetes 1.30 集群中的实际安装记录。集群原本已经运行 nginx Ingress 和 AIBrix Envoy Gateway，因此实验使用独立 Helm Release、Namespace、IngressClass 和 ClusterIP Service，没有接管已有域名或修改业务入口。

最终结果如下：

- Higress v2.2.3 的 Controller、Gateway 和 Console 全部 Ready；
- `IngressClass=higress-sr1` 与已有 `nginx` 隔离；
- 回显请求经过 Higress Gateway 后返回 `higress-sr1-ok`；
- Console 返回 HTTP 200；
- 实验只验证了普通 Ingress 数据面，尚未给真实模型配置 API Key、AI Proxy 或公网入口。

## 1. 先区分 Higress、AIBrix 和推理引擎

```text
客户端 / SDK / Agent
        │
        ▼
Higress
  域名、TLS、认证、租户、API Key、Token 配额、审计、协议转换
        │
        ▼
AIBrix / Inference Gateway / 自研 Router
  模型发现、队列、Prefix/KV、Session、P/D 和 Endpoint 选择
        │
        ▼
vLLM / SGLang / TensorRT-LLM
  Continuous Batching、KV Cache、模型并行和 Token 生成
```

三层都可能出现“路由”二字，但输入信号不同：

| 层 | 主要决策 | 不应成为它的唯一职责 |
| --- | --- | --- |
| Higress | 用户能访问哪个逻辑模型、调用哪个提供商、配额和安全策略 | 根据每个 vLLM Pod 的 KV 命中选择 Endpoint |
| AIBrix/推理路由 | 请求应该进入哪个模型池、角色或具体副本 | 对公网用户保存长期 API Key 和计费账户 |
| 推理引擎 | 如何批处理、分配 KV、执行 Prefill/Decode | 企业域名、TLS 证书和组织级授权 |

小规模平台可以让 Higress 直接代理一个或多个 vLLM Service。引入 AIBrix 后，应让 Higress 的 Upstream 指向 AIBrix Gateway，而不是绕过它直接随机访问 vLLM Pod。

## 2. Higress 的组件和资源

Helm 安装后最先看到三个 Deployment：

| 组件 | 职责 | 数据路径 |
| --- | --- | --- |
| `higress-controller` | 监听 Ingress、Service、插件和 Higress/Istio 资源，生成 xDS 配置 | 不承载用户请求 |
| `higress-gateway` | Envoy 数据面，执行路由、TLS、插件和流量策略 | 承载用户请求 |
| `higress-console` | Web 管理页面和管理 API | 管理面，不应直接暴露公网 |

还会出现以下对象：

- `IngressClass`：决定哪一个 Ingress Controller 处理某条 `Ingress`；
- `McpBridge`、`WasmPlugin`、`EnvoyFilter` 等 CRD：表达服务来源、插件和底层扩展；
- Istio Networking API：Higress 内部可用 `Gateway`、`VirtualService`、`DestinationRule` 等表达高级流量配置；
- Gateway API：新版本可以选择启用，但在已有 Envoy Gateway/AIBrix 的集群中应先明确 `GatewayClass` 所有权；
- ConfigMap/Secret：保存域名、HTTPS、控制器配置、Console 账户和控制面 CA。

Console 是配置入口之一，不是新的数据面。页面中的变更最终仍会转换为 Kubernetes 资源；生产环境应把关键配置纳入 GitOps，避免只有页面里才存在的不可审计状态。

## 3. 为什么在这套集群选择 v2.2.3

实验时 Higress 最新稳定版和 Helm Chart 都是 v2.2.3。该版本提供 `global.createIngressClass`，适合在已有 Ingress Controller 的集群中创建独立 IngressClass；Kubernetes v1.30 也满足该版本的基础 API 要求。

版本选择不能只看 Kubernetes：还要一起验证 Helm Chart、Gateway 镜像、Pilot/Controller、Console、Wasm 插件 ABI 和现有 Gateway API CRD。生产升级时应固定 Chart 版本和镜像 digest，不使用浮动标签。

参考：[Higress v2.2.3 Release](https://github.com/higress-group/higress/releases/tag/v2.2.3)、[Helm 部署文档](https://higress.cn/docs/latest/ops/deploy-by-helm/)

## 4. 安装前盘点

不要在生产集群中直接复制 Quickstart。先检查冲突面：

```bash
kubectl version
kubectl get ingressclass
kubectl get gatewayclass
kubectl get ingress -A
kubectl get gateway,httproute -A
kubectl get crd | grep -Ei 'higress|istio|gateway'
kubectl get deploy,svc -A | grep -Ei 'ingress|gateway|envoy'
```

本次盘点结果：

| 项目 | 实际状态 | 安装决策 |
| --- | --- | --- |
| Kubernetes | v1.30.4 | 使用 Higress v2.2.3 |
| Ingress Controller | 已有 nginx，Class 为 `nginx` | 新建 `higress-sr1`，不设为默认 Class |
| Gateway API | 已由 AIBrix/Envoy Gateway 使用 | Higress 实验关闭 Gateway API |
| AIBrix Gateway | 已运行 | 不修改已有 Gateway、HTTPRoute 和 EnvoyExtensionPolicy |
| LoadBalancer | 没有可用地址分配器 | Gateway 和 Console 都先用 ClusterIP |
| 外部 Registry | TLS 证书链不被节点信任 | 预先同步固定版本 amd64 镜像 |

## 5. 隔离安装配置

仓库中的 [`examples/higress-sr1/values.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/higress-sr1/values.yaml) 是这次实验的最小配置：

```yaml
global:
  ingressClass: higress-sr1
  createIngressClass: true
  watchNamespace: ""
  enableIstioAPI: false
  enableGatewayAPI: false
  enableAlphaGatewayAPI: false
  enableInferenceExtension: false
  enableRedis: false
  enablePluginServer: false

higress-core:
  gateway:
    replicas: 1
    service:
      type: ClusterIP
  controller:
    replicas: 1
    automaticHttps:
      enabled: false

higress-console:
  replicaCount: 1
  service:
    type: ClusterIP
  ingress:
    enabled: false
```

这里用独立 IngressClass 隔离，而没有把 `watchNamespace` 固定为业务 Namespace。实测发现，Controller 只监听 `higress-lab` 时，Namespace Controller 不会在 `higress-system` 生成 Gateway 必需的 `higress-ca-root-cert`，Gateway 因挂载不到 ConfigMap 一直停留在 `ContainerCreating`。恢复集群级 Namespace 监听后，Controller 取得 Leader Lease、发布根证书，Gateway 才能启动。

集群级监听不等于接管所有 Ingress。真正的路由归属由 `ingressClassName: higress-sr1` 决定；现有 `ingressClassName: nginx` 仍由 nginx Controller 处理。生产环境还应通过 RBAC、准入策略和 GitOps 限制谁能创建 Higress 资源。

## 6. 安装命令与离线镜像

在线环境可以按官方 Helm 仓库安装：

```bash
helm repo add higress.io https://higress.io/helm-charts
helm repo update

helm upgrade --install higress-sr1 higress.io/higress \
  --version 2.2.3 \
  -n higress-system --create-namespace \
  -f examples/higress-sr1/values.yaml \
  --set-string higress-console.admin.password='<ADMIN_PASSWORD>'
```

本次集群不能信任上游 Registry 的证书链，涉及四个镜像：

```text
higress/console:2.2.3
higress/higress:2.2.3
higress/pilot:2.2.3
higress/gateway:2.2.3
```

在能够访问上游的机器上同步 `linux/amd64` 镜像到企业 Registry，然后通过以下 values 覆盖，不要把企业 Registry 地址写进公共文档：

```bash
helm upgrade --install higress-sr1 higress.io/higress \
  --version 2.2.3 \
  -n higress-system --create-namespace \
  -f examples/higress-sr1/values.yaml \
  --set global.hub='<INTERNAL_REGISTRY>' \
  --set higress-console.image.repository='<INTERNAL_REGISTRY>/higress/console' \
  --set-string higress-console.admin.password='<ADMIN_PASSWORD>'
```

不要只同步 Gateway：Controller Deployment 同时使用 `higress` 和 `pilot`，Console 又有独立仓库。Apple Silicon 上准备镜像时必须明确目标架构，避免把 arm64 Manifest 推给 amd64 节点。

## 7. 安装验收

### 7.1 控制面和数据面

```bash
helm status higress-sr1 -n higress-system
kubectl -n higress-system get deploy,pod,svc
kubectl get ingressclass higress-sr1
kubectl -n higress-system get cm higress-ca-root-cert
```

本次结果为：

```text
higress-console      1/1 Ready
higress-controller   1/1 Ready（Pod 内两个容器 Ready）
higress-gateway      1/1 Ready
higress-ca-root-cert 已生成
```

如果 Gateway 一直 `ContainerCreating`，先 `describe pod`。若事件是 `configmap "higress-ca-root-cert" not found`，应检查 Controller 的 Namespace 监听范围和 discovery 容器日志，而不是反复拉 Gateway 镜像。

### 7.2 普通 Ingress 回源

测试清单见 [`echo-ingress.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/higress-sr1/echo-ingress.yaml)：

```bash
kubectl apply -f examples/higress-sr1/echo-ingress.yaml
kubectl -n higress-lab rollout status deployment/echo
```

从集群内通过 Gateway Service 请求，并显式带 Host：

```bash
kubectl -n higress-lab run higress-smoke --rm -i --restart=Never \
  --image=busybox:stable -- \
  wget -qO- --header='Host: echo.higress.lab' \
  http://higress-gateway.higress-system.svc/
```

实测响应：

```text
higress-sr1-ok
```

这个结果同时证明了 Gateway Listener、Ingress 转换、xDS 下发、Service 发现和后端网络，并不仅是 Pod 状态为 Running。

## 8. Console 访问与账户

实验没有为 Console 创建公网 Ingress。最稳定的临时访问方法是端口转发：

```bash
kubectl -n higress-system port-forward svc/higress-console 8080:8080
```

然后打开 `http://127.0.0.1:8080`。默认管理员用户名是 `admin`，密码应在安装时通过安全的 Helm values、Secret 管理系统或 CI 注入，不能提交到 Git。当前 Secret 字段包括 `adminUsername` 和 `adminPassword`，但不要把 Secret 解码输出写入终端日志或工单。

直接访问 Pod IP 只适合临时排障：Pod 重建后 IP 会变化。企业办公网需要长期访问时，优先为 Console 配置内网 Ingress/VIP、TLS、SSO 或至少来源 IP 白名单；不要把管理页面直接暴露公网。

## 9. Higress 如何代理大模型

Higress AI Proxy 可把多种上游模型服务统一到 OpenAI-Compatible API，并支持识别或转换 OpenAI、Claude 等协议。一个典型配置过程是：

1. 在 Secret 或外部密钥系统保存提供商 API Key；
2. 创建逻辑模型和 Upstream，不让客户端知道真实 Endpoint；
3. 在 Route 上启用 AI Proxy，配置模型映射和协议；
4. 再叠加认证、Token 限流、统计、安全和审计插件；
5. 用流式和非流式请求分别验收。

参考：[AI Gateway 概览](https://higress.io/en/ai-gateway)、[AI Proxy 插件](https://higress.io/en/docs/latest/plugins/ai/api-provider/ai-proxy/)

### 9.1 为什么逻辑模型名很重要

客户端可以始终请求 `chat-standard`，网关在内部映射到：

```text
chat-standard
  ├── 自托管 AIBrix Pool / vLLM
  ├── 云厂商模型 API
  └── 灾备模型或降级模型
```

这样模型版本、提供商和部署方式可以独立变化。但故障切换前必须确认上下文长度、工具调用、多模态、内容安全和输出质量等能力可互换，不能只因为 HTTP API 长得一样就自动切换。

### 9.2 Token 限流优于只看 QPS

LLM 请求成本差异很大。生产入口至少区分：

- 每租户每分钟输入/输出 Token；
- 最大上下文和最大输出 Token；
- 并发请求和活跃 SSE 连接；
- 每模型、每提供商预算；
- 超限后的拒绝、排队或降级策略。

传统 QPS 限流只能挡住大量短请求，挡不住少量超长上下文请求。

## 10. 可观测性

Higress Gateway 的访问日志和 Prometheus Endpoint 能回答入口层问题。AI Statistics 插件还能统计输入/输出 Token、首 Token 延迟和总响应时间，并按网关、路由、服务和模型分析。

参考：[AI Statistics 插件](https://higress.io/en/docs/latest/plugins/ai/api-o11y/ai-statistics/)

推荐保留以下标签，但控制基数：

| 标签/指标 | 用途 |
| --- | --- |
| route、logical_model | 找到哪条入口和哪个逻辑模型异常 |
| tenant/team | 配额、成本和低效资源治理 |
| status、error_type | 区分认证、限流、网关和模型错误 |
| input/output tokens | 容量、成本和异常请求识别 |
| TTFT、total latency | 交互体验和端到端 SLO |
| upstream/model version | 发布回归和故障切换定位 |

Request ID 和 Trace Context 要从 Higress 透传到 AIBrix 与 vLLM。Prompt、Response、Authorization、API Key 和 Tool 参数默认不进入普通访问日志；调试采样需要脱敏、授权和保存期限。

## 11. 成熟 Higress 平台引入 AIBrix，要不要混合

结论是：**建议分层串联，但只让需要 AIBrix 高级调度的模型经过第二层，不要把两个网关合并成一个控制面，也不要一次性迁移全部存量服务。**

企业已经用 Higress 稳定承载单机单卡或单机多卡 Deployment 时，现有域名、TLS、认证、租户、配额、审计和发布流程已经形成平台资产。为了引入 AIBrix 而替换入口，迁移风险远大于收益。AIBrix Gateway 应被视为 Higress 后面的“内部推理路由器”，而不是第二个对外 API Gateway：

```text
                                ┌─→ 现有单机单卡 Deployment Service
Client → Higress 统一入口 ──────┼─→ 现有单机多卡 Deployment Service
                                │
                                └─→ AIBrix 内部 Gateway
                                      ├─→ 多机多卡 Replica A
                                      ├─→ 多机多卡 Replica B
                                      ├─→ Prefill Role / Decode Role
                                      └─→ KV/Prefix/Session 感知 Endpoint
```

“多机多卡”本身不是必须增加 AIBrix Gateway 的理由。多机执行通常由 LeaderWorkerSet、StormService、KubeRay 或 Runtime 编排；如果只有一个固定模型副本，请求永远进入同一个 Leader Service，Higress 仍可直接代理。只有需要在多个模型副本、角色或 Endpoint 之间根据运行时状态做选择时，AIBrix Gateway 才体现价值。

这里的“模型感知选副本”不是选择模型参数或 GPU 数量，而是先从请求 Body/Header 识别逻辑模型，排除没有加载该模型或 Adapter 的 Endpoint，再在合格副本中按排队数、并发、Session、Prefix/KV 命中、Prefill/Decode 角色和健康状态选择目标。普通 Service 负载均衡只看到一组 Endpoint，并不天然理解这些模型运行时信号。只有一个整体副本时没有选择空间，这项能力自然没有明显收益。

以 DeepSeek-V4-Pro 为例，官方规格为 1.6T 总参数、49B 激活参数和 1M Context；vLLM 官方配方中的混合精度 Checkpoint 约 960GB，并给出 2 个 GB200 NVL4 Tray、共 8 张 GPU 的多节点 DP + EP 部署。这 8 张 GPU 是一个完整 Replica，而不是 8 个可以由网关独立选择的副本：

```text
Higress：识别企业逻辑模型 deepseek-v4-pro、执行认证和配额
  → AIBrix Gateway：在 Replica A 与 Replica B 之间选择
      ├── Replica A：2 Tray / 8 GPU，内部由 vLLM DP + EP 协同
      └── Replica B：2 Tray / 8 GPU，内部由 vLLM DP + EP 协同
```

如果当前只有 Replica A，Higress 直接访问它的 Leader/API Service 就能工作；当增加 Replica B，或者把 Prefill/Decode 拆成不同 Pool 后，AIBrix 才负责组间选择。AIBrix 不能把请求发送给 A1 的一半 GPU 和 B2 的另一半 GPU，完整副本的 Rank 组成由 StormService/RoleSet、LeaderWorkerSet、KubeRay 或 Runtime 控制。

参考：[DeepSeek-V4 官方发布](https://api-docs.deepseek.com/news/news260424/)、[vLLM DeepSeek-V4-Pro Recipe](https://github.com/vllm-project/recipes/blob/main/models/deepseek-ai/DeepSeek-V4-Pro.yaml)、[多机与分离式 LLM 推理](distributed-serving.md#deepseek-v4-multi-node-example)

| 场景 | 推荐链路 | 原因 |
| --- | --- | --- |
| 已稳定运行的单机单卡/多卡 Deployment | Higress → Service | 没有必要增加一次代理和一个故障域 |
| 单个固定多机多卡副本，只暴露 Leader Service | 初期可 Higress → Leader Service | 多机编排与请求选副本是两个问题 |
| 多个多机多卡副本，需要负载/Session 感知 | Higress → AIBrix → Replica | AIBrix 负责推理池内部 Endpoint 选择 |
| P/D 分离、KV/Prefix-aware、Role-aware | Higress → AIBrix → Role/Pod | 普通七层网关不掌握这些实时推理信号 |
| 仅供集群内部调用，没有统一 API 治理要求 | 可直接 AIBrix Gateway | 外层 Higress 的企业治理价值不明显 |
| 外部用户、多租户、多模型和云 API 混合 | Higress → AIBrix/云模型 Upstream | Higress 保持统一身份、协议、预算和审计 |

渐进迁移时按模型或 Route 分流：存量路径不动，先为一个新逻辑模型建立 Higress → AIBrix Canary，验证完成后再扩大范围。不要让 Higress 和 AIBrix 同时成为重试、鉴权、租户限流或模型映射的权威写入者。

## 12. 与 AIBrix 同集群串联实测

同集群时，Higress Upstream 应指向 AIBrix Envoy 数据面的稳定 Service DNS：

```text
Client
  → higress-gateway.higress-system.svc
  → envoy-<namespace>-<gateway>-<hash>.envoy-gateway-system.svc:80
  → AIBrix ext_proc Gateway Plugin
  → selected vLLM Pod
```

Higress 负责：

- 外部域名、TLS、认证和租户；
- OpenAI/Claude 协议和逻辑模型名；
- 入口 Token 配额、内容策略、审计；
- 提供商级故障切换。

AIBrix 负责：

- 发现模型 Endpoint；
- 根据负载、Prefix/KV、Session 和角色选 Pod；
- P/D、StormService 和模型工作负载扩缩；
- 推理池内部容量保护。

不要让 Higress 直接负载均衡 AIBrix 管理的所有 vLLM Service，否则 AIBrix 的模型感知选择会被绕过。

### 12.1 用稳定 Service 隐藏 Envoy Gateway 哈希名

Envoy Gateway 自动生成的 Service 名含哈希。实验创建一个 `aibrix-gateway-upstream` ClusterIP Service，用 owning-gateway 标签选择 AIBrix Envoy Pod，再让 Higress Ingress 指向这个稳定名称。完整清单见 [`higress-to-aibrix.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/higress-sr1/higress-to-aibrix.yaml)：

```text
aibrix.higress.lab
  → higress-gateway.higress-system.svc:80
  → aibrix-gateway-upstream.envoy-gateway-system.svc:80
  → Envoy targetPort 10080
  → AIBrix ext_proc
  → selected mock vLLM Pod:8000
```

```bash
kubectl apply -f examples/higress-sr1/higress-to-aibrix.yaml
kubectl -n envoy-gateway-system \
  get svc,endpointslice,ingress -l app.kubernetes.io/part-of=higress-aibrix-lab
```

这个别名 Service 是实验中的稳定入口。生产环境可以用 Envoy Gateway 定制的 Service、内部 VIP 或经平台管理的别名 Service，但必须监控 Selector 是否仍能选中 Endpoint，不能悄悄退化为零 Endpoint。

### 12.2 OpenAI-Compatible 请求证据

通过 Higress Gateway 发送请求，Body 中模型为 `llama2-7b`，路由策略为 `least-request`：

```bash
curl http://<HIGRESS_INTERNAL_ADDRESS>/v1/chat/completions \
  -H 'Host: aibrix.higress.lab' \
  -H 'Authorization: Bearer <TEST_API_KEY>' \
  -H 'Content-Type: application/json' \
  -H 'routing-strategy: least-request' \
  -d '{
    "model": "llama2-7b",
    "messages": [{"role": "user", "content": "reply pong"}],
    "max_tokens": 8
  }'
```

实测返回 HTTP 200、模型名 `llama2-7b` 和 10 个总 Token。Higress 访问日志记录：

```text
route_name=envoy-gateway-system/aibrix-via-higress
upstream_cluster=aibrix-gateway-upstream.envoy-gateway-system.svc.cluster.local
response_code=200
duration=57ms
upstream_service_time=56ms
```

AIBrix Gateway Plugin 同一时刻记录：

```text
model=llama2-7b
routing_strategy=least-request
target_pod=mock-llama2-7b-...
prompt_tokens=2 completion_tokens=8 total_tokens=10
routing_time_taken=363µs total_time_taken=54.7ms
```

这证明请求依次经过 Higress、AIBrix ext_proc 和被选中的 mock vLLM Pod。57ms/56ms 只是单次 CPU mock 观测，不是性能基准；生产是否接受额外一跳，必须用真实模型、SSE、并发和连接复用做对照压测。

### 12.3 实测发现的两个生产缺口

第一次请求中，AIBrix 返回的 `target-pod`、`target-pod-ip`、路由耗时等内部诊断头被 Higress 原样传给客户端。实验随后在 Ingress 增加 `higress.io/response-header-control-remove`，再次请求时这些头已经消失。Higress 官方支持在后端响应返回客户端前按 Route 删除指定 Header，参考 [Ingress Annotation 高阶流量治理](https://higress.cn/en/docs/latest/user/annotation-use-case/#response-header-control)。

这个边界还必须处理请求方向。AIBrix v0.7.0 会读取 `user`、`external-filter`、`routing-strategy`、`config-profile` 和 `x-session-id` 等 Header；如果公网用户能自行设置，就可能伪造身份、选择内部配置或操纵负载策略。实验清单使用两类 Annotation：

```yaml
higress.io/request-header-control-remove: "user,external-filter,config-profile,x-session-id,target-pod,target-pod-ip,request-id"
higress.io/request-header-control-update: "routing-strategy least-request"
higress.io/response-header-control-remove: "target-pod,target-pod-ip,routing-strategy,req-cost-time,req-arrive-time,resp-start-time,x-went-into-req-headers"
```

复测时客户端故意发送 `routing-strategy: random`、伪造的 `user`、`config-profile`、`external-filter` 和 `x-session-id`，请求仍返回 HTTP 200；AIBrix 日志最终记录 `routing_strategy=least-request`，证明外部值已被平台策略覆盖。生产中的可信 `user` 和租户级 Session ID 应由 Higress 在认证后重新注入，而不是直接信任同名客户端 Header。

第二个缺口是两层本地 Request ID 不一致。AIBrix v0.7.0 源码在没有追踪上下文时生成 UUID，但会读取 W3C `traceparent` 并把其中的 Trace ID 用作内部 Request ID。因此不需要强求 Higress 与 AIBrix 的本地 Request ID 相同，应统一跨层 Trace Context：

```text
traceparent: 00-0123456789abcdef0123456789abcdef-0123456789abcdef-01
                 └──────────── Trace ID ────────────┘
```

实测 AIBrix `request_start`、`request_end` 和返回的 `request-id` 都变成 `0123456789abcdef0123456789abcdef`。Higress 默认 Access Log 仍记录自身 `x-request-id`，生产应开启 Higress OpenTelemetry Tracing，并在日志中增加 Trace ID/`traceparent` 字段，让日志和 Trace 都能用同一 Trace ID 查询。Higress 支持在 `higress-config` 中配置 OpenTelemetry Collector，参考 [Higress Tracing 配置](https://higress.cn/docs/latest/user/configmap/#tracing-配置说明)。

Trace Context 只是关联键，不是身份凭据。边界网关应生成或校验其格式，不能因为客户端提供了某个 Trace ID 就授予权限、去重计费或信任其唯一性。

| 缺口 | 直接风险 | 优先级 | sr1 状态 |
| --- | --- | --- | --- |
| 内部响应头外泄 | 暴露 Pod/IP、拓扑、调度策略和耗时 | 外部上线前 P0 | 已删除并复测 |
| 客户端伪造 AIBrix 控制头 | 绕过平台路由/身份策略、制造负载偏斜 | 外部上线前 P0 | 已清除/覆盖并复测 |
| Request ID/Trace 不可关联 | 故障、审计、重试与成本无法端到端定位 | 规模化前 P1；强审计场景 P0 | `traceparent` 已验证，Collector/日志字段待接入 |

## 13. 与 AIBrix 跨集群串联

Higress 和 AIBrix 可以部署在不同集群，但不能把 AIBrix 的 `*.svc.cluster.local` 直接注册给 Higress。AIBrix 集群要先暴露一个稳定的内部入口：

1. 内网 LoadBalancer/VIP；
2. 解析到 VIP 的企业 DNS；
3. 服务注册中心地址；
4. 多集群 Service API 或受控东西向网关。

然后 Higress 把该地址作为 Upstream。必须验证：

- 两个集群之间的路由、ACL、MTU、DNS 和 TLS；
- SSE 长连接、Idle Timeout、连接池和客户端取消；
- AIBrix Gateway 多副本和入口健康检查；
- 一个集群失联时的熔断和容量回退；
- Trace、租户身份和 Request ID 跨集群透传；
- 数据地域和 Prompt 合规边界。

不能注册单个 Envoy Pod IP，它会随重建变化。跨集群也不意味着一定需要服务网格：稳定 VIP 加 mTLS 往往更容易运维。

## 14. 两层网关最容易犯的错误

### 重复重试

客户端、Higress、AIBrix 和 Runtime 如果各重试一次，最坏请求数会成倍增长。流式响应已经输出 Token 后通常不能安全重试；Tool Call 还可能产生重复副作用。只允许一层成为自动重试的权威执行者，并限制总预算。

### 重复限流

Higress 的租户 Token 配额与 AIBrix 的模型池容量保护不是同一个概念。前者回答“这个用户能不能用”，后者回答“这个池现在接不接得下”。分别定义指标和错误码，不要让两层都返回无法区分的 429。

### 超时不一致

从外到内的总超时应逐层收敛，同时单独定义连接、首 Token、流式 Idle 和总请求超时。外层先断开时，要把取消传播到推理引擎，避免 GPU 继续生成无人消费的 Token。

### 暴露内部信息

AIBrix 的目标 Pod、内部模型标签和调试头不应默认返回公网。Higress 应移除内部诊断头，只保留对用户稳定的错误契约。

## 15. 生产化清单

- [ ] Chart、四个核心镜像和 Wasm 插件全部固定版本或 digest。
- [ ] `higress-sr1` 不是默认 IngressClass，未接管已有 nginx 路由。
- [ ] Gateway 至少两个副本，并使用反亲和或拓扑分布约束。
- [ ] 通过内网 LB/VIP 暴露数据面，不依赖 Pod IP。
- [ ] Console 仅内网可达，接入 SSO/RBAC，管理员密码托管在 Secret 系统。
- [ ] TLS 证书自动续期、失败告警和回滚均已演练。
- [ ] API Key 不在 Ingress Annotation、Git、日志或 ConfigMap 明文保存。
- [ ] 流式请求的 Buffer、Idle Timeout、Drain 和取消传播已用真实客户端验证。
- [ ] Token、并发、上下文、Body 大小和费用都有租户级上限。
- [ ] Prompt、响应和 Tool 参数默认不写普通日志。
- [ ] Higress 与 AIBrix 的重试、限流、错误码和路由职责只有一个权威来源。
- [ ] AIBrix 的 Pod/IP/路由诊断头已在 Higress 边界删除。
- [ ] Higress、AIBrix 和 Runtime 使用可关联的 Request ID 或 Trace Context。
- [ ] Gateway 数据面故障不影响 Controller，Controller 故障不切断已有连接。
- [ ] 配置进入 GitOps，Console 临时修改可以被发现并回收。
- [ ] 升级前验证旧 CRD、插件 ABI、配置转换和回滚路径。

## 16. 本次实验还没有证明什么

普通回显和 CPU mock 串联成功只证明两层网关控制流正常。下一阶段仍需在隔离 Namespace 中补充：

- AI Proxy 到一个 CPU mock OpenAI-Compatible Endpoint；
- API Key、模型映射和协议转换；
- 非流式与 SSE 流式请求；
- Token 统计、TTFT 和 Prometheus 抓取；
- 租户 Token 限流和错误语义；
- AIBrix 故障、超时、取消和扩缩容期间的入口行为；
- 内网 VIP、TLS、SSO 与多副本高可用。

控制面 Ready 和普通 HTTP 200 不能替代真实模型数据面的性能、安全与故障测试。

## 延伸阅读

- [Higress 官方文档](https://higress.io/en/)
- [Higress Helm 部署](https://higress.cn/docs/latest/ops/deploy-by-helm/)
- [Higress AI Gateway](https://higress.io/en/ai-gateway)
- [Higress AI Proxy](https://higress.io/en/docs/latest/plugins/ai/api-provider/ai-proxy/)
- [Higress AI Statistics](https://higress.io/en/docs/latest/plugins/ai/api-o11y/ai-statistics/)
- [AIBrix 既有集群实战](../practices/aibrix-existing-cluster.md)
- [AI Gateway 与智能路由](gateway-routing.md)
