---
title: 在既有 Kubernetes 集群落地 AIBrix：路由、P/D、自动扩缩容与可观测性实测
description: 在 Kubernetes 1.30 集群安装 AIBrix v0.7.0，用 CPU mock 跑通模型路由、P/D、StormService、自动扩缩容、Prometheus 指标和 Higress 两层网关串联
status: lab
last_reviewed: 2026-08-06
---

# 在既有 Kubernetes 集群落地 AIBrix：路由、P/D、自动扩缩容与可观测性实测

这次实验不是在干净的 Kind 集群中执行 Quickstart，而是在一套已经运行数据库、虚拟机、存储和其他控制器的 Kubernetes 集群中增量安装 AIBrix。目标是回答六个问题：

1. 现有 Kubernetes 版本适合安装哪个 AIBrix 版本；
2. 外部 Registry 不稳定时，如何先把依赖镜像完整准备好；
3. 没有可分配 GPU 时，能否先验证 AIBrix 控制面与模型感知路由；
4. 能否用 CPU demo 观察 StormService/RoleSet 与 KVCache 两套资源抽象；
5. 没有 GPU 时，KPA、APA、原生 HPA 和 Prometheus 自定义指标能测到哪一层；
6. 业务入口使用 Higress 时，Higress 和 AIBrix Gateway 应如何分工。

最终验证结果：AIBrix v0.7.0 的六个控制面 Deployment、Envoy Gateway 控制面和数据面全部 Ready；两个 mock vLLM 副本运行在不同节点；普通模型路由、按角色过滤、Session Affinity、P/D 控制流和错误语义均获得了实际响应证据。补装 Metrics Server 后，KPA、APA、资源 HPA 和 Prometheus 自定义指标 HPA 都触发了真实扩容；最小 Prometheus Operator、Prometheus 与 Adapter 也已经采集并暴露 vLLM 指标。后续还在同一集群跑通 Higress → AIBrix → mock vLLM，并验证了边界响应头清洗。

```text
测试客户端
  → Envoy Gateway
  → AIBrix ext_proc Gateway Plugin
  → 按 model + routing-strategy 选择 Pod
  → mock vLLM 副本
  → OpenAI-Compatible 响应
```

本文把公司内部 Registry、域名和地址写成 `<...>` 占位符。不要把实验 API Key、内网地址或浮动标签直接复制到生产。

## 1. 先盘点集群，不要直接运行 Quickstart

首先收集版本、节点资源和现有 CRD：

```bash
kubectl config current-context
kubectl version
kubectl get nodes -o wide
kubectl get nodes \
  -o custom-columns='NAME:.metadata.name,GPU:.status.allocatable.nvidia\.com/gpu'
kubectl get crd | grep -E 'gateway|envoy|ray|aibrix'
kubectl get deploy,ds -A | grep -Ei 'gateway|envoy|ray|gpu|device-plugin'
kubectl get storageclass
```

这次目标集群的关键事实如下：

| 项目 | 实际状态 | 对安装的影响 |
| --- | --- | --- |
| Kubernetes Server | v1.30.4 | 可运行 AIBrix v0.7.0 固定的 Envoy Gateway v1.2 系列 |
| Container Runtime | containerd 1.7.x | 无特殊限制，但节点必须能访问镜像 Registry |
| Gateway API | 未安装 | 需要先安装 AIBrix dependency 清单 |
| Envoy Gateway | 未安装 | AIBrix 模型感知路由依赖它，不能只安装 AIBrix Controller |
| KubeRay CRD | 未安装 | 官方 dependency 会安装；AIBrix 不使用 Ray 时可不部署 Ray 工作负载 |
| `nvidia.com/gpu` | 所有节点均未发布 | 不能声称真实 GPU 推理已跑通，先使用 CPU mock Runtime 验证控制面 |
| LoadBalancer Controller | 未给 Envoy Service 分配地址 | Gateway Listener 可工作，但外部入口需要 ClusterIP、内网 LB/VIP 或端口转发 |
| Metrics API | 初始不存在，实验中补装 | 资源 HPA 与 APA 的 CPU/内存数据来源 |
| Prometheus Operator CRD | 初始不存在，实验中补装最小栈 | 提供 ServiceMonitor、PrometheusRule 等声明式监控资源 |
| Custom Metrics API | 初始不存在，实验中补装 Adapter | 让原生 HPA 使用 `gpu_cache_usage_perc` 等 vLLM 指标 |

“节点物理上可能有 GPU”和“Kubernetes 已经能分配 GPU”是两回事。只有节点 `status.allocatable` 出现 `nvidia.com/gpu` 或目标 DRA ResourceClaim 能被分配，才可以继续部署真实 GPU vLLM。

## 2. 为什么选择 AIBrix v0.7.0

安装时查询到的最新稳定版本为 v0.7.0，发布日期为 2026-06-18。官方发布提供三份独立资产：

- `aibrix-dependency-v0.7.0.yaml`：Gateway API、Envoy Gateway 和 KubeRay CRD 等依赖；
- `aibrix-core-crds-v0.7.0.yaml`：AIBrix 自身 CRD；
- `aibrix-core-v0.7.0.yaml`：Controller、Gateway Plugin、Metadata、Redis 和默认 Gateway 资源。

该版本固定 Envoy Gateway v1.2.8。Envoy Gateway v1.2 的兼容矩阵覆盖 Kubernetes 1.28—1.31，因此 Kubernetes 1.30 在兼容范围内。不过 v1.2 已经结束上游维护，生产环境不能擅自只把 Envoy Gateway 升到较新版本：AIBrix 使用 `EnvoyExtensionPolicy`、`EnvoyPatchPolicy` 和自定义 Envoy 镜像，必须把 AIBrix、Envoy Gateway、Gateway API CRD 和 Envoy Proxy 作为一组做回归测试。

参考：[AIBrix Installation](https://aibrix.readthedocs.io/latest/getting_started/installation/installation.html)、[AIBrix Releases](https://github.com/vllm-project/aibrix/releases)、[Envoy Gateway Compatibility Matrix](https://gateway.envoyproxy.io/news/releases/matrix/)

## 3. 先准备完整镜像，而不是等 Pod 逐个失败

官方 v0.7.0 默认安装至少涉及以下镜像：

| 组件 | 上游镜像 |
| --- | --- |
| AIBrix Controller | `aibrix/controller-manager:v0.7.0` |
| Gateway Plugin | `aibrix/gateway-plugins:v0.7.0` |
| Metadata/GPU Optimizer | `aibrix/metadata-service:v0.7.0` |
| KubeRay Operator | `aibrix/kuberay-operator:v1.2.1-patch-20250726` |
| Envoy Gateway | `envoyproxy/gateway:v1.2.8` |
| Envoy 数据面 | `envoyproxy/envoy:v1.33.2` |
| 初始化与状态存储 | `busybox:stable`、`redis:latest` |
| 无 GPU 验证 Runtime | `aibrix/vllm-mock:nightly` |

如果集群无法稳定访问 Docker Hub，应在安装前统一镜像。集群节点是 amd64，而执行镜像准备的电脑可能是 Apple Silicon，因此必须显式拉取 `linux/amd64`：

```bash
docker pull --platform linux/amd64 aibrix/controller-manager:v0.7.0
docker pull --platform linux/amd64 aibrix/gateway-plugins:v0.7.0
docker pull --platform linux/amd64 aibrix/metadata-service:v0.7.0
docker pull --platform linux/amd64 aibrix/kuberay-operator:v1.2.1-patch-20250726
docker pull --platform linux/amd64 envoyproxy/gateway:v1.2.8
docker pull --platform linux/amd64 envoyproxy/envoy:v1.33.2
docker pull --platform linux/amd64 busybox:stable
docker pull --platform linux/amd64 redis:latest
docker pull --platform linux/amd64 aibrix/vllm-mock:nightly
```

然后逐个重打标签并推送：

```bash
docker tag aibrix/controller-manager:v0.7.0 \
  <INTERNAL_REGISTRY>/aibrix-controller-manager:v0.7.0
docker push <INTERNAL_REGISTRY>/aibrix-controller-manager:v0.7.0
```

其余镜像使用相同流程。推送完成后再替换两份安装清单中的所有 `image:`，并重新扫描确认没有遗漏：

```bash
grep -n 'image:' aibrix-dependency-v0.7.0.yaml
grep -n 'image:' aibrix-core-v0.7.0.yaml
```

这里有三个容易踩坑的地方：

1. 只替换 AIBrix Deployment 镜像还不够，`EnvoyProxy` 自定义资源中还声明了动态创建数据面的 Envoy 和 shutdown-manager 镜像；
2. Certgen Job 与 Envoy Gateway Deployment 共用 Envoy Gateway 镜像；
3. 官方清单使用 `redis:latest` 和 mock `nightly`，实验可以保持一致，生产应在验证后锁定 digest，避免重建时得到不同内容。

## 4. 严格按依赖顺序安装

先下载固定版本发布资产：

```bash
curl -fLO https://github.com/vllm-project/aibrix/releases/download/v0.7.0/aibrix-dependency-v0.7.0.yaml
curl -fLO https://github.com/vllm-project/aibrix/releases/download/v0.7.0/aibrix-core-crds-v0.7.0.yaml
curl -fLO https://github.com/vllm-project/aibrix/releases/download/v0.7.0/aibrix-core-v0.7.0.yaml
```

完成镜像替换后，按以下顺序执行：

```bash
kubectl apply --server-side -f aibrix-dependency-v0.7.0.yaml

kubectl -n envoy-gateway-system \
  rollout status deployment/envoy-gateway --timeout=180s
kubectl -n envoy-gateway-system \
  wait --for=condition=complete job/eg-gateway-helm-certgen --timeout=180s

kubectl apply --server-side -f aibrix-core-crds-v0.7.0.yaml
kubectl wait --for=condition=Established \
  crd/stormservices.orchestration.aibrix.ai \
  crd/modeladapters.model.aibrix.ai \
  crd/podautoscalers.autoscaling.aibrix.ai \
  --timeout=120s

kubectl apply -f aibrix-core-v0.7.0.yaml
kubectl -n aibrix-system rollout status deployment --timeout=300s
```

如果把三份清单同时执行 `--dry-run=server`，后面的对象可能报 Namespace 或 CRD 不存在。原因是 dry-run 不会真正持久化前一份清单，不代表 API 不兼容。可靠做法是先实际安装依赖和 CRD，确认 `Established=True`，再预检或安装 Core。

## 5. 安装后应该看到什么

AIBrix v0.7.0 默认控制面包括：

```text
aibrix-system
  aibrix-controller-manager
  aibrix-gateway-plugins
  aibrix-gpu-optimizer
  aibrix-kuberay-operator
  aibrix-metadata-service
  aibrix-redis-master

envoy-gateway-system
  envoy-gateway
  envoy-<namespace>-<gateway>-<hash>
```

检查时不要只看 Pod：

```bash
kubectl -n aibrix-system get deploy,pod,svc
kubectl get gatewayclass aibrix-eg -o yaml
kubectl -n aibrix-system \
  get gateways.gateway.networking.k8s.io,httproutes.gateway.networking.k8s.io
kubectl -n envoy-gateway-system get deploy,pod,svc
```

集群同时存在其他名为 `Gateway` 的 CRD 时，`kubectl get gateway` 可能解析到错误的 API Group。排障时使用完整资源名 `gateways.gateway.networking.k8s.io`，避免把 Gateway API 对象和云资源 CRD 混淆。

## 6. 没有 GPU，也能先证明 AIBrix 路由是通的

这次使用两个 CPU mock vLLM 副本，Manifest 见 [`examples/aibrix-sr1/mock-llama2-7b.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/mock-llama2-7b.yaml)。核心约束是：

```yaml
metadata:
  labels:
    model.aibrix.ai/name: llama2-7b
    model.aibrix.ai/port: "8000"
spec:
  template:
    metadata:
      labels:
        model.aibrix.ai/name: llama2-7b
        model.aibrix.ai/port: "8000"
```

Service 名称、请求体中的 `model` 和 `model.aibrix.ai/name` 应保持一致。端口标签要写在 Pod Template 上；只写 Deployment 顶层时，AIBrix 会回退到 8000 并产生 warning。

```bash
kubectl apply -f examples/aibrix-sr1/mock-llama2-7b.yaml
kubectl -n aibrix-demo rollout status deployment/mock-llama2-7b
kubectl -n aibrix-demo get pods,svc,endpoints -o wide
kubectl -n aibrix-system get httproutes.gateway.networking.k8s.io
```

Controller 会为发现的模型生成对应 HTTPRoute。测试时临时转发 Envoy 数据面 Service：

```bash
kubectl -n envoy-gateway-system get svc
kubectl -n envoy-gateway-system port-forward \
  svc/<AIBRIX_ENVOY_SERVICE> 28999:80
```

另一个终端发送请求：

```bash
curl -i http://127.0.0.1:28999/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer test-key-1234567890' \
  -H 'routing-strategy: least-request' \
  --data '{
    "model": "llama2-7b",
    "messages": [{"role": "user", "content": "Say this is an AIBrix test"}],
    "temperature": 0.1
  }'
```

这次实测返回：

```text
HTTP/1.1 200 OK
routing-strategy: least-request
target-pod: mock-llama2-7b-...
target-pod-ip: <pod-ip>:8000
request-id: <uuid>
```

Gateway Plugin 日志同时记录模型名、目标 Pod、路由耗时、输入/输出 Token 和总耗时，形成了完整证据链。

### 6.1 不要只测一种路由策略

同一组 CPU mock 后端实测了以下请求头。除错误用例外，请求均返回 HTTP 200：

| `routing-strategy` | 实测结果 | CPU 环境能证明什么 |
| --- | --- | --- |
| `random` | 成功 | 策略被插件接受并完成后端选择 |
| `least-request` | 成功 | 能走最少请求数的选择路径 |
| `power-of-two` | 成功 | 能从候选集中执行二选一 |
| `least-latency` | 成功 | 能读取并参与延迟统计路径 |
| `throughput` | 成功 | 能进入吞吐感知策略 |
| `prefix-cache` | 成功 | Prefix 路由代码路径可用；mock 不能证明真实 KV 命中 |
| `external-filter` | `role=prefill/decode` 精确选中对应 Role | 元数据过滤与 StormService Role 标签生效 |
| `session-affinity` | 重放响应中的 `x-session-id` 后落到同一个 Pod | 会话粘滞闭环生效 |
| `pd` | 同时记录 Prefill 与 Decode 目标 | P/D 编排控制流生效 |

`prefix-cache` 连续请求前两次命中同一 Pod、第三次切换了 Pod。这不是错误，也不能据此计算 Prefix 命中率：mock Runtime 没有真实 KV Block、模型上下文和缓存事件。要证明 Prefix 路由收益，必须换成真实推理引擎，并同时观测命中、TTFT、输入 Token 和缓存容量。

### 6.2 P/D 路由要看两段目标和插件日志

对 `aibrix-role-demo` 发送 `routing-strategy: pd` 后，响应同时包含 Decode 目标和 `prefill-target-pod`。Gateway Plugin 日志依次记录：

```text
selected prefill/decode pair
prefill request start/end
prefill_time_taken
kv_transfer_time_taken
ttft
decode_time_taken
```

这能证明请求经历了 Prefill、模拟 KV 传递和 Decode 控制流，但 `kv_transfer_time_taken` 只是 mock 协议的阶段耗时，不代表 GPU KV Tensor 已经通过 NIXL、RDMA 或 TCP 真实传输。

失败语义也应纳入验收：不存在的模型、请求体缺少模型都返回 HTTP 400，并带 `x-error-no-model-backends`；非法路由策略返回 HTTP 400 和 `x-error-routing: true`。生产网关可据此区分“容量暂不可用”和“客户端请求错误”，不能把所有 4xx/5xx 都做重试。

## 7. AIBrix 能否按角色部署 Prefill、Decode 和 KV Cache

可以，但需要区分两套资源模型：

- `StormService → RoleSet → Pod` 描述推理服务内部的角色，例如 Prefill 和 Decode；
- `KVCache` CRD 描述独立的缓存层，包括元数据、成员发现和真正保存 KV Block 的缓存节点。

它们可以组合使用，但 KV Cache 不是简单地在 `StormService` 中增加一个 `cache` 角色。

### 7.1 Prefill 和 Decode 都是推理 Pod

AIBrix 的 `StormService` 可以在一个服务单元中定义多个 Role。典型 P/D 分离服务包含：

```yaml
apiVersion: orchestration.aibrix.ai/v1alpha1
kind: StormService
spec:
  replicas: 1
  template:
    spec:
      roles:
        - name: prefill
          replicas: 1
          template: <vLLM Prefill PodTemplate>
        - name: decode
          replicas: 1
          template: <vLLM Decode PodTemplate>
```

Prefill Pod 负责处理 Prompt 并生成初始 KV，Decode Pod 接收 KV 后继续逐 Token 生成；两类 Pod 都运行模型、通常都需要 GPU。AIBrix v0.7.0 的 vLLM 1P1D 示例使用 NIXL Connector 在两类推理进程之间传输 KV，它并不要求部署一个长期保存 KV 的独立缓存集群。

这和 Ray 多机不是同一层概念：普通 RayCluster 中的 Head/Worker 会共同执行同一个 Engine 的 Prefill 与 Decode，并不分别扮演 P/D 角色。如果模型本身还要跨节点，可以让 Prefill Engine、Decode Engine 各自在一组多机资源中运行，但这会同时引入组内模型并行和组间 KV 传输。完整数据路径见 [vLLM Ray 多机与 P/D 分离是什么关系](../inference/distributed-serving.md#vllm-ray-vs-pd)。

`StormService.spec.replicas > 1` 时，每个 RoleSet 可以作为一个完整服务副本按组扩缩；`spec.replicas = 1` 时，各 Role 形成共享池。AIBrix v0.7.0 已提供共享池角色级自动扩缩示例：分别创建指向同一 StormService 的 `PodAutoscaler`，再用 `subTargetSelector.roleName` 选择 Prefill 或 Decode，并增加 `autoscaling.aibrix.ai/storm-service-mode: pool` 注解。生产环境仍要用真实指标验证扩缩、预热、P/D 容量比例和缩容中的请求排空，不能只看 CRD 能否表达。

如果服务内部本来就使用 Ray，也可以改用 `RayClusterFleet`：每个 RayCluster 是一个完整副本，Ray 负责集群内部进程调度，AIBrix 只把请求送到 Head/API Pod。两条路线的边界需要单独说清楚。

### 7.2 两条 AIBrix 编排路线：RayClusterFleet 与 StormService/RoleSet { #rayclusterfleet-vs-stormservice }

`StormService` 和 `RoleSet` 不是两个平级方案。真正的二选一是 **RayClusterFleet 与 StormService**；RoleSet 是 StormService 管理的下一层资源：

```text
Ray 路线
RayClusterFleet（类似 Deployment）
  └─ RayClusterReplicaSet（类似 ReplicaSet）
       └─ RayCluster × N（每个都是完整推理副本）
            ├─ Ray Head / vLLM API
            └─ Ray Worker × M

Role 路线
StormService（整个推理服务）
  └─ RoleSet × N（完整副本或共享池）
       ├─ Role: prefill → Pod / 多 Pod Group
       ├─ Role: decode  → Pod / 多 Pod Group
       └─ Role: 其他自定义角色
```

| 维度 | RayClusterFleet | StormService / RoleSet |
| --- | --- | --- |
| 核心抽象 | 一份应用实例就是一个完整 RayCluster | 一份服务由一个或多个具名 Role 组成 |
| 内部编排 | Ray 负责分布式进程、Actor/Task 和资源调度，KubeRay 负责 Head/Worker Pod | AIBrix Controller 直接管理 Role、Pod、索引、状态和更新顺序；Runtime 自己完成分布式进程通信 |
| 依赖 | 需要 KubeRay，并在镜像中准备 Ray | 不依赖 KubeRay；AIBrix v0.7.0 安装文档明确允许只使用 StormService |
| 典型拓扑 | 固定的 Ray Head + 一个或多个 Worker Group | Prefill/Decode、同构 Worker、代理等任意角色；单个 Role 还可用 `podGroupSize > 1` 表达多机实例 |
| 对外 Endpoint | 只暴露 Ray Head 上的 vLLM API，Worker 不能进入 Gateway Endpoint | 共置模式暴露服务 Role；P/D 模式由 AIBrix 按 Role 和 RoleSet 选择 Prefill/Decode |
| 扩缩单位 | `spec.replicas` 增减完整 RayCluster，即完整模型副本 | Replica 模式增减完整 RoleSet；Pool 模式可按 `roleName` 分别增减 Prefill/Decode Pod |
| 更新 | Deployment 风格 RollingUpdate/Recreate、Revision 和回滚，更新单位是 RayCluster | StormService 支持 Rolling/InPlace；RoleSet 支持 Parallel、Sequential、Interleave，并可声明 `upgradeOrder` |
| 状态与故障边界 | KubeRay 修复 Cluster 内 Head/Worker，Fleet 统计完整 RayCluster 副本状态 | RoleSet 聚合每个 Role 的 Ready 状态；Stateful Role 保留稳定 Slot，Stateless Role 可互换替换 |
| 调度能力 | 主要依赖 Kubernetes/KubeRay；需要另行验证整组 GPU 的 Gang 和拓扑约束 | RoleSet 可引用 Volcano、Coscheduling 或 Godel PodGroup 策略，但集群仍须安装相应调度器 |
| 最适合 | 已经使用 Ray，或 vLLM 以 Ray Backend 启动；希望复用 Ray Dashboard、任务和集群模型 | P/D 分离、角色异构/独立扩缩、希望去掉 Ray，或希望平台直接理解角色边界 |

三种配置最容易说明扩缩语义：

1. `RayClusterFleet.replicas=2`，每个 RayCluster 含 1 Head + 1 Worker：得到两个完整模型副本，AIBrix 只在两个 Head Endpoint 之间选路；
2. `StormService.replicas=2`，每个 RoleSet 含 2 Prefill + 1 Decode：得到两个相互隔离的 P/D 完整副本，扩容一次会增加整套 RoleSet；
3. `StormService.replicas=1`，RoleSet 内 Prefill=4、Decode=8：得到一个共享 P/D Pool，可以为两个 Role 分别创建 `PodAutoscaler`，通过 `subTargetSelector.roleName` 独立扩缩。

因此，**模型跨节点不等于必须选 RayClusterFleet**。如果团队已经用 Ray 跑 vLLM，RayClusterFleet 的改造最小；如果目标是 AIBrix 原生 P/D、角色级弹性或不想引入 Ray，优先 StormService。

参考：[AIBrix Installation](https://aibrix.readthedocs.io/latest/getting_started/installation/installation.html)、[AIBrix Multi-Node Inference](https://aibrix.readthedocs.io/latest/features/multi-node-inference.html)、[AIBrix StormService](https://aibrix.readthedocs.io/latest/designs/aibrix-stormservice.html)、[StormService Role-Level Autoscaling](https://aibrix.readthedocs.io/latest/features/autoscaling/metric-based-autoscaling.html#stormservice-role-level-autoscaling)

### 7.3 用裸 Kubernetes 启动多个 8-GPU Pod，能否替代它们

可以做出相同的**推理数据面**，但不会自动得到相同的**运维控制面**。几个申请 `nvidia.com/gpu: 8` 的 Pod 可以各自跑完整模型，也可以组成一个跨 Pod 模型，甚至可以手工分成 Prefill 和 Decode 池。但 `sleep infinity` 后再 `kubectl exec` 启动进程只适合调试：Pod 重建后命令丢失，Kubernetes 也不知道哪些 Pod 属于同一个完整副本。

| 目标 | 最小可行做法 | 与 AIBrix 抽象的差距 |
| --- | --- | --- |
| 模型可装入单个 8-GPU Pod，多副本 | `Deployment + Service`，每个 Pod 启动一个 vLLM，`replicas=N` | 对普通共置模型已经足够；缺少 Fleet 级 Revision/回滚和角色语义 |
| 一个模型跨多个 8-GPU Pod | `StatefulSet + Headless Service + Leader Service`，通过稳定序号确定 Rank | 要自己处理整组启停、就绪、Gang Scheduling、组故障和 Leader-only Endpoint |
| 手工 Ray 集群 | Head Pod 执行 `ray start --head`，Worker Pod 执行 `ray start --address=...`，再在 Head 启动 vLLM | 可得到 Ray 运行时，但没有 KubeRay 的 RayCluster 协调，更没有 Fleet 的多完整副本管理 |
| 手工 P/D 分离 | Prefill 和 Decode 各一组 Workload/Service，配置 NIXL/KV Connector 和 P/D Router | 标签本身不会传 KV；需自己处理配对、独立扩缩、请求排空和故障降级 |

对于跨 Pod 的静态实验，最小骨架可以是：

```yaml
apiVersion: v1
kind: Service
metadata:
  name: vllm-headless
spec:
  clusterIP: None
  selector:
    app: vllm-multinode
  ports:
    - {name: control, port: 29500}
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: vllm
spec:
  serviceName: vllm-headless
  podManagementPolicy: Parallel
  replicas: 2
  selector:
    matchLabels: {app: vllm-multinode}
  template:
    metadata:
      labels: {app: vllm-multinode}
    spec:
      containers:
        - name: vllm
          image: <预装模型、vLLM 和通信依赖的镜像>
          command: ["/opt/aik8s/start-vllm-rank.sh"]
          env:
            - {name: WORLD_SIZE, value: "2"}
            - {name: MASTER_ADDR, value: vllm-0.vllm-headless}
          resources:
            requests:
              nvidia.com/gpu: 8
            limits:
              nvidia.com/gpu: 8
```

`start-vllm-rank.sh` 需从 Pod 名的序号推导 `node-rank`，为 Rank 0 启动 API/Leader，为其他 Rank 启动 Headless Worker。若选 Ray，则改为启动 Ray Head/Worker，并在 Head 上启动 vLLM。对外 Service 只能选 Rank 0，例如通过 `statefulset.kubernetes.io/pod-name: vllm-0` 筛选；Readiness 必须在所有 Rank 入组且模型可服务后才成功。

要接近生产可用，还需要自己补齐：

- 不再使用 `sleep + exec`，把启动逻辑固化到镜像 EntryPoint 或版本化 ConfigMap；
- 为完整副本设计 Group ID、Rank、稳定 DNS、Leader-only Service 和整组 Readiness；
- 引入 Volcano/Coscheduling 等 Gang Scheduling，避免只抢到部分 GPU Pod 后长期占位；
- 配置 GPU/RDMA 资源、拓扑亲和性、NCCL/NIXL 网络和一致的模型路径；
- 实现整组重启、滚动更新、缩容排空、自动扩缩、故障摘除和可观测性。

选型上，**单 Pod 8 卡、每个 Pod 就是一个完整副本**时，原生 Deployment 往往最简单，再让 AIBrix 按 `model.aibrix.ai/name` 和 `model.aibrix.ai/port` 发现就够了。**一个副本需要跨多个 8-GPU Pod** 时，至少使用 LWS、RayClusterFleet 或 StormService/RoleSet 之一；如果坚持只用原生 Workload，实际上就是由自己承担一个小型 Operator 的设计和运维工作。

参考：[vLLM Multi-Node Serving](https://docs.vllm.ai/en/latest/examples/ray_serving/multi-node-serving/)、[vLLM on LeaderWorkerSet](https://docs.vllm.ai/en/latest/deployment/frameworks/lws/)、[vLLM Parallelism and Scaling](https://docs.vllm.ai/en/latest/serving/parallelism_scaling/)

#### 自己实践 P/D 和 KV Cache，核心还是 vLLM 数据路径

对本文当前这套技术栈来说，答案是**是**：真正执行模型、生成 KV Tensor 并通过 Connector 移动 KV 的仍是 vLLM。AIBrix 不是另一个推理引擎，它把同一套数据路径纳入 Kubernetes 的服务发现、角色编排、请求路由和扩缩容。

| 分层 | 自己组装 | 加入 AIBrix 后 |
| --- | --- | --- |
| 推理引擎 | vLLM Prefill/Decode 进程 | 还是 vLLM，也可换成 AIBrix 支持的其他引擎 |
| KV 传输 | vLLM `NixlConnector` 等 Connector | 仍是匹配版本的 Connector 和 NIXL/UCX 数据面 |
| P/D 配对和路由 | vLLM 示例 Proxy 或自己编写 Router | AIBrix Gateway 按 RoleSet、负载和缓存信号选 Prefill/Decode |
| Workload 编排 | Deployment/StatefulSet、Service 和启动脚本 | StormService/RoleSet 或 RayClusterFleet |
| KV 存储 | vLLM 本地 HBM/CPU，或 LMCache 等独立 Backend | AIBrix Offloading Connector + L1 DRAM，可选 `KVCache` CR 管理的 L2 Backend |
| 物理数据面 | TCP，或 NIXL + UCX/RDMA | 不变；AIBrix CRD 不会把慢网络自动变成 RDMA |

需要特别区分三个目标：

1. **P/D 直传**：同一次请求先进 Prefill，计算出的 KV 再传给 Decode。它不需要一个长期保存 KV 的独立缓存集群。
2. **KV Offload**：把本应留在 GPU HBM 的 KV 放到本机 CPU DRAM、SSD 或远端存储，主要目标是扩大容量或腾出 HBM。
3. **跨引擎共享 KV**：不同 vLLM 副本通过共享 L2 Backend 复用相同前缀。这才需要元数据、Cache Engine、容量治理和命中/回源逻辑。

一条可验证、也容易定位问题的实验顺序是：

1. **单个共置 vLLM 基线**：固定模型、镜像、TP、上下文长度和请求集，记录 TTFT、TPOT、Throughput 和 HBM。
2. **裸 vLLM 1P1D**：部署一个 Prefill Pod 和一个 Decode Pod，两端使用完全匹配的 vLLM/NIXL/UCX 镜像和 `--kv-transfer-config`，先用 TCP，再换 RDMA。
3. **加入最小 Proxy**：先使用 vLLM 官方 `disagg_proxy_demo.py`，让它调用 Prefill、传递 `kv_transfer_params`、再调用 Decode。这一步证明 P/D 数据面，与 AIBrix 无关。
4. **把 Proxy 换成 AIBrix Gateway**：同样的两个引擎放进 StormService/RoleSet，请求使用 `routing-strategy: pd`。对比请求配对、故障摘除和角色独立扩缩。
5. **再做 L1 KV Offload**：只把 KV 卸载到本机 CPU DRAM，验证 HBM 释放量、PCIe 开销和端到端延迟。
6. **最后加共享 L2 KVCache**：使用 AIBrix `KVCache` CR 创建 InfiniStore/Vineyard 等 Backend，并在真实 vLLM 中启用对应 Offloading Connector。用重复长 System Prompt 验证跨副本命中，再测 Backend 中断时能否回源重算。

裸 vLLM P/D 的命令形态大致如下，应放入 Pod 的 `command/args` 而不是人工 `exec`：

```bash
# Prefill
vllm serve <MODEL> --port 8100 \
  --kv-transfer-config \
  '{"kv_connector":"NixlConnector","kv_role":"kv_producer"}'

# Decode
vllm serve <MODEL> --port 8200 \
  --kv-transfer-config \
  '{"kv_connector":"NixlConnector","kv_role":"kv_consumer"}'

# 实验用 P/D Router
python examples/disaggregated/disaggregated_serving/disagg_proxy_demo.py \
  --model <MODEL> --prefill prefill:8100 --decode decode:8200 --port 8000
```

这个片段用来说明组件边界，不应脱离镜像版本直接复制到生产。vLLM 的 Connector 参数和 P/D 协议还在迭代；AIBrix 官方示例的特定镜像也可能要求两端使用 `kv_role=kv_both`。必须将 **AIBrix、vLLM、AIBrix KVCache Connector、NIXL、UCX/CUDA/PyTorch** 作为一个经过验证的版本组合锁定，不能分别追求最新。

验收时不只看 Pod `Running` 或请求能返回，至少还要证明：Prefill 真的只做 Prompt 阶段、Decode 真的接收了远端 KV，同一长前缀的第二次请求有可观测命中，以及关闭 Connector/缓存 Backend 后能观察到预期的性能回退或重算。

参考：[vLLM Disaggregated Serving](https://docs.vllm.ai/en/stable/examples/disaggregated/disaggregated_serving/)、[vLLM NixlConnector Usage Guide](https://docs.vllm.ai/en/stable/features/nixl_connector_usage/)、[vLLM KV Offloading Usage Guide](https://docs.vllm.ai/en/latest/features/kv_offloading_usage/)、[AIBrix Prefill-Decode Disaggregation](https://aibrix.readthedocs.io/latest/features/pd-disaggregation.html)、[AIBrix KVCache Offloading Framework](https://aibrix.readthedocs.io/latest/designs/aibrix-kvcache-offloading-framework.html)

### 7.4 独立 KV Cache 集群不只有一个“管理 Pod”

如果要把 KV 从 GPU HBM 或单机内存进一步卸载到共享 L2 缓存，AIBrix 使用独立的 `KVCache` CR。以 InfiniStore Backend 为例，它通常包含：

| 组件 | 运行模型 | 保存实际 KV Block | 职责 |
| --- | --- | --- | --- |
| AIBrix Controller | 否 | 否 | 把 `KVCache` CR 协调成 Deployment、Service 等资源 |
| Metadata Redis/Etcd | 否 | 否 | 保存成员、索引、位置等元数据，不保存大块 KV Tensor |
| Watcher | 否 | 否 | 注册和发现缓存成员，维护缓存集群拓扑 |
| Cache Engine Pod | 否 | 是 | 在 CPU 内存或远端介质中真正保存、读取 KV Block |
| Prefill Pod | 是 | 生成 KV | 执行 Prompt 计算，通过 Connector 写入或传输 KV |
| Decode Pod | 是 | 消费并扩展 KV | 读取已有 KV 并继续执行 Token 生成 |

对应的资源形态大致如下：

```yaml
apiVersion: orchestration.aibrix.ai/v1alpha1
kind: KVCache
spec:
  mode: distributed
  metadata:
    redis:
      runtime:
        replicas: 1
        image: <redis-image>
  watcher:
    image: <kvcache-watcher-image>
  cache:
    replicas: 3
    image: <cache-engine-image>
    resources:
      requests:
        cpu: "10"
        memory: 120Gi
        <rdma-resource>: "1"
```

推理 Pod 通过 AIBrix Offloading Connector 与缓存层通信。数据路径可以概括为：

```text
客户端
  → AIBrix Gateway
  → Prefill / Decode 推理 Pod（StormService / RoleSet）
       ↕ AIBrix Offloading Connector
     L1：推理节点 CPU DRAM
       ↕
     L2：分布式 KVCache
       ├─ Redis / Etcd：元数据和位置索引
       ├─ Watcher：成员注册与发现
       └─ Cache Engine Pod × N：保存实际 KV Block
```

本次安装生成的 `aibrix-redis-master` 是 AIBrix 平台控制面使用的 Redis，不能因为它已经存在，就认为分布式 KV 数据面已经部署；`KVCache` CR 还会按 Backend 和配置创建自己的元数据及缓存工作负载。

### 7.5 三种模式怎么选

| 模式 | 组成 | 适用场景 | 主要代价 |
| --- | --- | --- | --- |
| 本地 KV | 推理引擎 HBM，可选单机 L1 DRAM | 先跑通、低复杂度、复用率不高 | 容量受单机限制，副本间不能共享 |
| P/D 直传 | Prefill Role + Decode Role + NIXL/RDMA 等传输 | Prompt 和生成阶段资源特征差异明显 | 网络、连接器和故障恢复更复杂 |
| 独立 L2 KVCache | 推理池 + Metadata + Watcher + Cache Engine | 长共享前缀、跨副本命中、需要扩大缓存容量 | 占用大量 CPU 内存/网络，需要一致性、容量和降级治理 |

不能把“部署了 KVCache”直接等同于“吞吐一定提升”。只有共享 System Prompt、长前缀或多轮上下文带来的命中收益，大于查询和传输成本时，L2 缓存才值得。缓存故障也应允许回源重新计算，不能让推理正确性依赖缓存永久可用。

### 7.6 在无 GPU 的 sr1 中把两套抽象都部署出来

仓库提供两个独立示例：

- [`stormservice-role-demo.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/stormservice-role-demo.yaml)：创建一个 StormService，其中包含 Prefill、Decode 两个 CPU mock Role；
- [`kvcache-vineyard-demo.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/kvcache-vineyard-demo.yaml)：创建一个集中式 Vineyard KVCache，其中包含 Etcd 元数据和 Vineyard Cache Engine。

离线集群先把示例中的公开镜像映射到集群可访问的 Registry，再执行：

```bash
kubectl apply -f examples/aibrix-sr1/stormservice-role-demo.yaml
kubectl apply -f examples/aibrix-sr1/kvcache-vineyard-demo.yaml

kubectl -n aibrix-demo get stormservice,roleset,kvcache
kubectl -n aibrix-demo get deploy,pod,svc,endpoints -o wide
```

本次 StormService 实测结果为：

```text
StormService/aibrix-role-demo  Ready=True
└─ RoleSet/aibrix-role-demo-roleset-...  Ready=True
   ├─ Pod/...-prefill-...  Running  node=<node-a>
   └─ Pod/...-decode-...   Running  node=<node-b>
```

`status.roleStatuses` 显示 Prefill 和 Decode 均为 `replicas=1, readyReplicas=1`。通过 AIBrix Gateway 请求模型 `aibrix-role-demo` 返回 HTTP 200，响应头记录：

```text
routing-strategy: least-request
target-pod: aibrix-role-demo-roleset-...-decode-...
target-pod-ip: <pod-ip>:8000
```

随后把 `StormService.spec.replicas` 从 1 调到 2，Controller 创建了两个 RoleSet、四个 Pod，每个 RoleSet 都包含一个 Prefill 和一个 Decode。连续四次 P/D 请求会在两个 RoleSet 间轮转，但每次 Prefill 与 Decode 始终来自同一个 RoleSet，说明成组副本边界没有被打散。恢复为 1 后，多余 RoleSet 被删除，状态回到：

```text
readyReplicas=1
roleStatuses[prefill].readyReplicas=1
roleStatuses[decode].readyReplicas=1
```

这项测试比“CRD 能创建”更有价值：它验证了 RoleSet 生命周期、成组扩容、P/D 配对与缩容回收。真实 GPU 场景还应继续测试扩容期间的模型加载、连接预热、正在生成请求的优雅终止和 KV 失效。

这里遇到一个很典型的坑：不要为 StormService 手工创建同名普通 ClusterIP Service。Controller 会自动创建同名 Headless Service；如果普通 Service 先存在，Controller 尝试把 `clusterIP` 改成 `None` 时会因为字段不可变而持续失败，RoleSet 也不会生成。删除冲突 Service 后，StormService 立即恢复为 Ready。

KVCache 实测生成的资源为：

```text
KVCache/vineyard-demo
├─ Pod/vineyard-demo-etcd-0       role=metadata
├─ Deployment/vineyard-demo
│  └─ Pod/vineyard-demo-...       role=cache
├─ Service/vineyard-demo-etcd-service:2379
└─ Service/vineyard-demo-rpc:9600
```

两个工作负载的 OwnerReference 都指向 `KVCache/vineyard-demo`。日志确认 Etcd 单节点选主完成、Vineyard 成功连接元数据服务，并监听 `/var/run/vineyard.sock` 和 `0.0.0.0:9600`；由于节点没有 RDMA，Vineyard 明确回退到 TCP。

这两个 demo 证明了 CRD、Controller、OwnerReference、角色状态和基础缓存进程可以工作，但不能证明真实 P/D 或 KV 卸载性能：Prefill/Decode 使用的是相同 CPU mock，没有 NIXL/LMCache Connector；Vineyard 没有接入真实 vLLM；节点也没有向 Kubernetes 发布 GPU/RDMA。下一阶段应先完成单 GPU vLLM 基线，再依次验证 P/D 直传、缓存命中率和分布式 InfiniStore，而不是把 demo 的 `Running` 当成生产数据路径已经跑通。

参考：[AIBrix StormService](https://aibrix.readthedocs.io/latest/designs/aibrix-stormservice.html)、[AIBrix KVCache Offloading Framework](https://aibrix.readthedocs.io/latest/designs/aibrix-kvcache-offloading-framework.html)

## 8. 把 KPA、APA、HPA 和自定义指标真正跑一遍

四条链路依赖不同，不能笼统地说“装了 Prometheus 就能自动扩缩容”：

```text
资源 HPA
  kubelet → Metrics Server → metrics.k8s.io → 原生 HPA

AIBrix APA（resource metric）
  kubelet → Metrics Server → metrics.k8s.io → AIBrix Controller → Scale

AIBrix KPA / APA（pod metric）
  推理 Pod /metrics → AIBrix Controller 直接抓取 → Scale

自定义指标 HPA
  推理 Pod /metrics → Prometheus → Prometheus Adapter
  → custom.metrics.k8s.io → 原生 HPA
```

Prometheus Operator 负责管理 Prometheus、ServiceMonitor 和 PrometheusRule；它本身既不提供资源 Metrics API，也不提供 Custom Metrics API。

### 8.1 Kubernetes 1.30 应安装哪个 Metrics Server

sr1 是 Kubernetes 1.30.4。实验时 Metrics Server 最新版已经是 v0.9.0，但官方兼容矩阵要求：0.9.x 对应 Kubernetes 1.34+，0.8.x 对应 1.31+，0.7.x 支持 1.27+。因此这里选择 v0.7.2，而不是机械安装最新版本：

```bash
kubectl apply -f \
  https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.7.2/components.yaml

kubectl get apiservice v1beta1.metrics.k8s.io
kubectl top nodes
```

安装后 `v1beta1.metrics.k8s.io Available=True`，11 个节点能返回 CPU/内存；另一个节点的 Kubelet 10250 端口拒绝连接，所以仍显示 `<unknown>`。

这里还暴露了一个更严重的历史问题：多数节点的 Kubelet Serving Certificate 已经过期。为了先完成实验，Metrics Server 临时增加了：

```text
--kubelet-insecure-tls
```

它只关闭 Metrics Server 到 Kubelet 的证书校验，不会关闭 Kubernetes API TLS，但仍不应成为长期配置。生产修复应是轮换 Kubelet 证书、校验证书 SAN 和自动续期，再删除该参数；否则节点身份验证被降级，中间人风险被隐藏。

参考：[Metrics Server compatibility matrix](https://github.com/kubernetes-sigs/metrics-server#compatibility-matrix)

### 8.2 AIBrix v0.7.0 的 APA 还缺一条 RBAC

原生 HPA 安装 Metrics Server 后直接成功，但 AIBrix APA 一直读取到 0。Controller 日志给出了真实原因：

```text
pods.metrics.k8s.io is forbidden:
User "system:serviceaccount:aibrix-system:aibrix-controller-manager"
cannot get resource "pods" in API group "metrics.k8s.io"
```

也就是说 CRD 状态仍可能显示 Ready，但算法实际上在用 0 做计算。通过独立 ClusterRole 最小化补充 `get/list pods.metrics.k8s.io` 后，APA 才读到实际 CPU 并完成扩容。清单见 [`controller-metrics-rbac.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/controller-metrics-rbac.yaml)。独立 Role 比直接修改发布清单中的大 ClusterRole 更容易审计和升级。

### 8.3 三种策略的 CPU 实测结果

仓库中的实验清单包括：

- [`podautoscaler-cpu-demo.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/podautoscaler-cpu-demo.yaml)：直接抓取 mock `/metrics`；
- [`podautoscaler-hpa-cpu-demo.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/podautoscaler-hpa-cpu-demo.yaml)：资源 HPA；
- [`podautoscaler-apa-cpu-demo.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/podautoscaler-apa-cpu-demo.yaml)：APA 读取 Metrics API。

| 策略 | 数据来源 | 实测结果 | 关键发现 |
| --- | --- | --- | --- |
| KPA | mock Pod `/metrics` | StormService 1→2，又回到 1 | Controller 能直接抓指标；mock 波动、按副本归一和 0 冷却会振荡 |
| HPA | `metrics.k8s.io` CPU | Deployment 1→2 | AIBrix 正确生成有 OwnerReference 的 `autoscaling/v2` HPA |
| APA | `metrics.k8s.io` CPU | 补 RBAC 后 Deployment 1→2 | AIBrix 自己读取 Metrics API；默认安装权限不足会静默得到 0 |

HPA 实测指标为 `cpu: 1000%/20%`，事件是 `SuccessfulRescale`。APA 状态最终为 `desiredScale=2, actualScale=2`。这些 CPU burner 只用于证明控制器和指标链路，完成后都已删除，避免持续占用集群。

KPA 的快速 1→2→1 不是生产策略的理想行为，反而说明冷却窗口、稳定窗口、目标值和真实时序数据必须一起设计。推理扩容还要考虑模型加载分钟级延迟，不能照搬 Web 服务的秒级 HPA 参数。

### 8.4 用最小 Prometheus 栈采集 vLLM 指标

本次使用 `kube-prometheus-stack 88.1.5`，但关闭 Grafana、Alertmanager、node-exporter、kube-state-metrics 和默认规则，只保留 Prometheus Operator 与一个 Prometheus；不申请 PVC，数据保留 2 小时。配置见 [`prometheus-minimal-values.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/prometheus-minimal-values.yaml)：

```bash
helm upgrade --install aibrix-monitoring \
  prometheus-community/kube-prometheus-stack \
  --version 88.1.5 \
  -n monitoring --create-namespace \
  -f examples/aibrix-sr1/prometheus-minimal-values.yaml

kubectl apply -f examples/aibrix-sr1/mock-vllm-servicemonitor.yaml
```

离线环境需要把 Operator、Webhook Certgen、Prometheus 和 Config Reloader 四个镜像预先放入集群可访问的 Registry，再通过 values 覆盖镜像地址。不要忘记 Config Reloader：它由 Operator 动态写入 Prometheus Pod，单看 Helm 渲染出的 Deployment 很容易漏掉。

Prometheus 最终只选择带 `monitoring.aik8s.run/instance=aibrix` 的 Monitor。两个 mock vLLM Target 均为 `health=up`，以下查询返回两个 Pod 的当前值：

```promql
vllm:gpu_cache_usage_perc{model_name="llama2-7b"}
```

### 8.5 让原生 HPA 使用 vLLM 自定义指标

Prometheus Adapter 负责把 PromQL 映射为 Kubernetes Custom Metrics API。配置见 [`prometheus-adapter-values.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/prometheus-adapter-values.yaml)：

```bash
helm upgrade --install aibrix-prometheus-adapter \
  prometheus-community/prometheus-adapter \
  --version 5.3.0 \
  -n monitoring \
  -f examples/aibrix-sr1/prometheus-adapter-values.yaml

kubectl get apiservice v1beta1.custom.metrics.k8s.io
kubectl get --raw \
  '/apis/custom.metrics.k8s.io/v1beta1/namespaces/aibrix-demo/pods/%2A/gpu_cache_usage_perc'
```

APIService 最终为 `Available=True`，并发现 `pods/gpu_cache_usage_perc`。应用 [`podautoscaler-hpa-vllm-metric-demo.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/aibrix-sr1/podautoscaler-hpa-vllm-metric-demo.yaml) 后，AIBrix 创建原生 HPA，实测显示：

```text
gpu_cache_usage_perc: 61500m / 10
SuccessfulRescale: New size: 3
AIBrix desiredScale=3, actualScale=3
```

mock vLLM 从 2 扩到 3，测试后删除 PodAutoscaler 并恢复到 2。生产规则不能照抄 `targetValue: 10`；应根据真实 GPU KV 容量、等待队列、请求率、TTFT/TPOT SLO、扩容成本和模型加载时间联合定标，也不能把单个瞬时 Gauge 直接当唯一扩容信号。

## 9. 为什么 Gateway 是 Accepted，但 Programmed=False

Envoy Gateway 默认为数据面创建 `type: LoadBalancer` 的 Service。如果集群没有云 LoadBalancer Controller 或 MetalLB，Service 会长期显示：

```text
TYPE           EXTERNAL-IP
LoadBalancer   <pending>
```

这时 Gateway Condition 通常是：

- `Accepted=True`：GatewayClass 和配置已被控制器接受；
- Listener `Programmed=True`：监听器配置已经发送给 Envoy；
- Gateway `Programmed=False / AddressNotAssigned`：没有外部地址。

它不代表 Envoy 或 AIBrix 路由失败。本次通过 ClusterIP 后面的端口转发已经获得 HTTP 200。生产入口应根据网络拓扑选择 ClusterIP、内部 LoadBalancer/VIP 或受控的跨集群地址，不要把 `<pending>` 误诊为模型后端故障。

## 10. Higress 与 AIBrix 应如何分工

不建议用 Higress 直接替换 AIBrix 固定的 Envoy Gateway。AIBrix 的 Gateway Plugin 通过 Envoy `ext_proc`、`EnvoyExtensionPolicy` 和 `EnvoyPatchPolicy` 获得模型、队列、Prefix/KV 与 P/D 感知能力。更清晰的职责划分是：

```text
客户端
  → Higress：域名、TLS、认证、租户、限流、审计
  → AIBrix Envoy Gateway：模型发现、LLM 路由、P/D、KV/Prefix 策略
  → vLLM / SGLang / TensorRT-LLM
```

### 10.1 Higress 与 AIBrix 在同一集群

Higress 的 Upstream 指向 AIBrix Envoy 数据面 Service，而不是某个 vLLM Service：

```text
envoy-<namespace>-<gateway>-<hash>.envoy-gateway-system.svc.cluster.local:80
```

入口需要保留：

- `/v1/*` 路径和请求体；
- `Authorization`；
- `routing-strategy` 等受控路由头；
- SSE/流式响应、长请求超时和取消传播。

企业已经有成熟 Higress 时，不建议把所有存量模型都切到 AIBrix。现有单机单卡/多卡 Deployment 继续由 Higress 直连；只有需要多副本模型感知、P/D、KV/Prefix 或 Role-aware 路由的模型，才按 Route 渐进转入内部 AIBrix Gateway。单个固定多机多卡副本如果始终只访问一个 Leader Service，也不因“多机”自动获得第二层网关的必要性。

例如 DeepSeek-V4-Pro 的 vLLM 官方多节点配方可以把 2 个 GB200 NVL4 Tray、共 8 张 GPU 组成一个 DP + EP Replica。只有这一组时，Higress 可以直连它的 Leader/API Service；当部署第二个同构 8-GPU Replica，或增加独立 Prefill/Decode Pool 后，AIBrix 才在完整组之间做模型感知选择。组内 Rank 的生命周期和通信仍由 StormService/RoleSet、LeaderWorkerSet、KubeRay 或 Runtime 负责，Gateway 不能把不同 Replica 的 Worker 随意拼接。详见 [多机与分离式 LLM 推理](../inference/distributed-serving.md#deepseek-v4-multi-node-example)。

### 10.2 Higress 与 AIBrix 在不同集群

跨集群同样可行，但不能使用 `*.svc.cluster.local`。AIBrix 集群需要提供一个稳定且可路由的内部地址：

1. 内网 LoadBalancer/VIP，优先；
2. 解析到该 VIP 的内部 DNS；
3. 企业服务注册中心中的稳定服务；
4. 仅实验时使用端口转发，不用于生产。

Higress 把这个地址注册为静态、DNS 或注册中心 Upstream。网络必须允许 Higress 数据面到 AIBrix Gateway 监听端口，并配置健康检查、连接池、流式超时和容量保护。不要使用单个 Envoy Pod IP：Pod 重建和滚动发布会让地址失效。

两层网关还要避免重复策略：重试只由一层负责或明确预算；限流区分租户入口与模型容量；Higress 生成的 Request ID 应透传到 AIBrix；AIBrix 的 `target-pod` 等内部诊断头不应默认暴露给公网。

后续已在同一集群使用独立 `higress-system` Namespace、`higress-sr1` IngressClass 和 ClusterIP Service 安装 Higress v2.2.3，并通过稳定别名 Service 跑通 Higress → AIBrix → CPU mock vLLM。请求返回 HTTP 200，AIBrix `least-request` 选择了具体模型 Pod，Plugin 日志记录输入/输出 Token；Higress 日志同时记录了目标 Upstream。首次响应暴露 AIBrix 内部 Pod/IP 头，补充 Route 级响应头删除后复测通过。继续用伪造 Header 复测时，Higress 成功清除身份/配置控制头，并把客户端的 `random` 覆盖为平台 `least-request`；合法 `traceparent` 也让 AIBrix 日志和响应使用同一 Trace ID。未修改已有 nginx、AIBrix Gateway 或业务路由。完整清单、证据和选型边界见 [Higress AI Gateway 实战](../inference/higress-ai-gateway.md)。

## 11. 换成真实 GPU vLLM 前还缺什么

mock 请求成功只证明以下链路：

- AIBrix Controller、Webhook 和 CRD 正常；
- Envoy Gateway 与 AIBrix Gateway Plugin 正常；
- 模型发现、HTTPRoute 生成和路由策略正常；
- OpenAI-Compatible 请求能够到达目标后端。

它不证明 GPU、模型加载、NCCL、RDMA、KV Cache 或多机 P/D 已就绪。真实模型上线前至少完成：

- 安装并验证 NVIDIA Device Plugin/GPU Operator，节点出现 `nvidia.com/gpu`；
- 确认 Driver、CUDA、Container Toolkit 与 vLLM 镜像兼容；
- 准备模型 PVC、对象存储或节点缓存；
- 先跑单 Pod、单 GPU 的 vLLM 健康检查和性能基线；
- 再让 Service 名、served model name 和 AIBrix 模型标签一致；
- 多机 TP/PP 或 P/D 场景补充高速网络、拓扑、StormService/RoleSet 和故障测试；
- 把真实 TTFT、TPOT、队列、KV 命中和 GPU 指标接入监控。

### 11.1 还有哪些能力没测，CPU 能测到哪一层

| 能力 | CPU 是否可测 | 当前状态 | 下一步 |
| --- | --- | --- | --- |
| Gateway 多策略、错误语义、Session | 可以完整测控制流 | 已测 | 用真实流量补充质量和性能对比 |
| StormService/RoleSet 生命周期 | 可以 | 已测 1→2→1 和 P/D 配对 | 加入 Pod 故障、滚动升级、优雅下线 |
| KPA、APA、HPA | 可以 | 三种策略均已触发扩容 | 用真实时序和冷却参数做稳定性测试 |
| Prometheus 与自定义指标 HPA | 可以 | 已采集并扩容 | 增加队列、TTFT/TPOT、请求率组合策略 |
| RayClusterFleet/ReplicaSet | 控制面和 CPU Ray 任务可测 | CRD/Operator 已安装，尚未创建 Fleet | 准备固定 Ray 镜像，测扩缩与 Head 故障 |
| ModelAdapter / LoRA | CR 生命周期可测，效果需兼容 Runtime | 尚未测 | 用小模型与 CPU 兼容 vLLM 验证加载/卸载，再上 GPU |
| Batch API / BrixBench | 可以 | 尚未测 | 对 mock Endpoint 做并发、取消、失败重试和报告 |
| Semantic Router | 控制面可用 CPU | 尚未测 | 需要可访问的 Embedding 模型和至少两个语义后端 |
| 真实 P/D KV 传输 | 不足 | 只验证 mock 控制流 | GPU + NIXL/LMCache + 高速网络 |
| KVCache 性能与命中收益 | 不足 | Vineyard 进程与 CR 生命周期已测 | 真实 Connector、共享前缀和容量/故障实验 |
| 多 GPU、多机、异构与 GPU 故障 | 不可以 | 节点未发布 GPU | Device Plugin/GPU Operator、拓扑、NCCL/RDMA 与故障注入 |

因此下一阶段最值得优先做的不是再创建更多 `Running` 的 CR，而是先跑通单 GPU 真实 vLLM 基线；否则 LoRA、P/D、KVCache、异构调度和 GPU 故障检测都只能验证 Kubernetes 控制对象，无法证明数据面价值。CPU 环境仍适合继续补 Ray、Batch、BrixBench、Semantic Router 和故障生命周期，它们应明确标注“控制面已测”还是“真实模型数据面已测”。

## 12. 这次实验暴露的实战经验

1. **版本要按组合选。** AIBrix、Envoy Gateway、Gateway API 和 Envoy Proxy 是一个兼容单元；
2. **离线镜像要一次盘全。** 动态生成的 Envoy 数据面镜像最容易漏掉；
3. **先验证控制面，再占用 GPU。** mock Runtime 能快速区分网关问题和模型问题；
4. **看响应头和日志证明路由。** 只有 HTTP 200 不足以证明请求经过 AIBrix；
5. **完整 API Group 能避免 CRD 歧义。** 大型企业集群常有多个同名 Kind；
6. **LoadBalancer Pending 不等于 Listener 不工作。** 要分别看 Service、Gateway 和 Listener Condition；
7. **Higress 与 AIBrix 是两层职责。** 前者做统一入口，后者做 LLM 感知数据面；
8. **StormService 拥有同名 Headless Service。** 不要提前创建同名普通 ClusterIP Service；
9. **跨集群入口必须稳定。** 使用 VIP/DNS/服务注册，不能依赖 Pod IP；
10. **三类 Metrics API 要分清。** Metrics Server、Prometheus Operator、Prometheus Adapter 解决的是不同问题；
11. **Ready 不代表指标有效。** APA 在 RBAC Forbidden 时仍可能保持 Ready，必须同时看 Controller 日志和实际 Scale；
12. **离线监控镜像要考虑动态 Sidecar。** Config Reloader 不一定直接出现在 Helm 的静态 Deployment 镜像清单中；
13. **扩容参数不能照搬 Web 服务。** LLM 模型加载、KV 预热和 GPU 成本决定了更长的稳定窗口与更谨慎的缩容。

## 13. 验收清单

- [x] Kubernetes 与固定 Envoy Gateway 版本在兼容矩阵内；
- [x] 外部依赖镜像已按节点架构准备到集群可访问的 Registry；
- [x] Envoy Gateway Controller 与 Certgen 成功；
- [x] AIBrix 六个默认 Deployment 全部 Ready；
- [x] GatewayClass `Accepted=True`；
- [x] 三条 HTTPRoute 均为 `Accepted=True`、`ResolvedRefs=True`；
- [x] 两个 mock 模型 Pod Ready，Service 有两个 Endpoint；
- [x] Gateway 请求返回 HTTP 200；
- [x] 响应头与 Gateway Plugin 日志能定位目标 Pod；
- [x] StormService 自动生成 RoleSet，Prefill/Decode Role 均为 Ready；
- [x] CPU mock 模型通过 AIBrix Gateway 路由到 Role Pod；
- [x] 集中式 KVCache 自动生成 Etcd、Vineyard 和对应 Service；
- [x] `random`、`least-request`、`power-of-two`、延迟、吞吐、Prefix、Session 与过滤路由可用；
- [x] P/D 请求能选择同一 RoleSet 中的 Prefill 与 Decode；
- [x] StormService 完成 1→2→1 成组扩缩；
- [x] Metrics Server APIService 可用，11 个节点返回资源指标；
- [x] AIBrix KPA、APA 与资源 HPA 都触发过真实扩容；
- [x] Prometheus Operator 与单实例 Prometheus Ready，两个 vLLM Target 均为 Up；
- [x] Prometheus Adapter 暴露 `pods/gpu_cache_usage_perc`；
- [x] 自定义 vLLM 指标 HPA 把 mock Deployment 从 2 扩到 3，并已恢复；
- [x] 同集群 Higress → AIBrix → mock vLLM 返回 HTTP 200，并完成内部诊断响应头清洗；
- [x] Higress 清除伪造身份/配置头并强制平台路由策略，AIBrix 通过 `traceparent` 采用统一 Trace ID；
- [ ] 为 Gateway 配置生产可用的内部 VIP 或同集群 ClusterIP 入口；
- [ ] Kubernetes 发布 GPU 资源并跑通真实 vLLM；
- [ ] 修复 Kubelet Serving Certificate 过期并移除 `--kubelet-insecure-tls`；
- [ ] 修复节点 Kubelet 10250 拒绝连接导致的 Metrics `<unknown>`；
- [ ] 验证 RayClusterFleet、ModelAdapter/LoRA、Batch、BrixBench 与 Semantic Router；
- [ ] 接入 OpenTelemetry Collector，把 Higress/AIBrix Trace ID 写入统一日志，并验证超时、流式、认证和故障语义。

## 延伸阅读

- [AIBrix Installation](https://aibrix.readthedocs.io/latest/getting_started/installation/installation.html)
- [AIBrix Gateway Routing](https://aibrix.readthedocs.io/latest/features/gateway-plugins.html)
- [Envoy Gateway Compatibility Matrix](https://gateway.envoyproxy.io/news/releases/matrix/)
- [AI Gateway 与智能路由](../inference/gateway-routing.md)
- [多机与分离式 LLM 推理](../inference/distributed-serving.md)
- [RBG 多角色推理编排与 sr1 实战](rbg-existing-cluster.md)
