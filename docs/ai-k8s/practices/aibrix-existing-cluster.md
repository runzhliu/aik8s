---
title: 在既有 Kubernetes 集群落地 AIBrix：版本、离线镜像、路由验证与 Higress 边界
description: 在 Kubernetes 1.30 集群安装 AIBrix v0.7.0，镜像依赖到内网 Registry，用 mock vLLM 跑通模型感知路由，并设计同集群与跨集群 Higress 接入
status: lab
last_reviewed: 2026-08-05
---

# 在既有 Kubernetes 集群落地 AIBrix：版本、离线镜像、路由验证与 Higress 边界

这次实验不是在干净的 Kind 集群中执行 Quickstart，而是在一套已经运行数据库、虚拟机、存储和其他控制器的 Kubernetes 集群中增量安装 AIBrix。目标是先回答五个问题：

1. 现有 Kubernetes 版本适合安装哪个 AIBrix 版本；
2. 外部 Registry 不稳定时，如何先把依赖镜像完整准备好；
3. 没有可分配 GPU 时，能否先验证 AIBrix 控制面与模型感知路由；
4. 能否用 CPU demo 观察 StormService/RoleSet 与 KVCache 两套资源抽象；
5. 业务入口使用 Higress 时，Higress 和 AIBrix Gateway 应如何分工。

最终验证结果：AIBrix v0.7.0 的六个控制面 Deployment、Envoy Gateway 控制面和数据面全部 Ready；两个 mock vLLM 副本运行在不同节点；通过 AIBrix Gateway 请求 `/v1/chat/completions` 返回 HTTP 200，响应头包含 `routing-strategy`、`target-pod`、`target-pod-ip` 和 `request-id`。这证明请求经过了 AIBrix 的模型发现与路由，而不是直接访问普通 Kubernetes Service。

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

`StormService.spec.replicas > 1` 时，每个 RoleSet 可以作为一个完整服务副本按组扩缩；`spec.replicas = 1` 时，各 Role 形成共享池。v0.7.0 对共享池的自动扩缩仍有限制，生产设计不能只看 CRD 能否表达，还要验证 Controller 实际支持的扩缩语义。

### 7.2 独立 KV Cache 集群不只有一个“管理 Pod”

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

### 7.3 三种模式怎么选

| 模式 | 组成 | 适用场景 | 主要代价 |
| --- | --- | --- | --- |
| 本地 KV | 推理引擎 HBM，可选单机 L1 DRAM | 先跑通、低复杂度、复用率不高 | 容量受单机限制，副本间不能共享 |
| P/D 直传 | Prefill Role + Decode Role + NIXL/RDMA 等传输 | Prompt 和生成阶段资源特征差异明显 | 网络、连接器和故障恢复更复杂 |
| 独立 L2 KVCache | 推理池 + Metadata + Watcher + Cache Engine | 长共享前缀、跨副本命中、需要扩大缓存容量 | 占用大量 CPU 内存/网络，需要一致性、容量和降级治理 |

不能把“部署了 KVCache”直接等同于“吞吐一定提升”。只有共享 System Prompt、长前缀或多轮上下文带来的命中收益，大于查询和传输成本时，L2 缓存才值得。缓存故障也应允许回源重新计算，不能让推理正确性依赖缓存永久可用。

### 7.4 在无 GPU 的 sr1 中把两套抽象都部署出来

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

## 8. 为什么 Gateway 是 Accepted，但 Programmed=False

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

## 9. Higress 与 AIBrix 应如何分工

不建议用 Higress 直接替换 AIBrix 固定的 Envoy Gateway。AIBrix 的 Gateway Plugin 通过 Envoy `ext_proc`、`EnvoyExtensionPolicy` 和 `EnvoyPatchPolicy` 获得模型、队列、Prefix/KV 与 P/D 感知能力。更清晰的职责划分是：

```text
客户端
  → Higress：域名、TLS、认证、租户、限流、审计
  → AIBrix Envoy Gateway：模型发现、LLM 路由、P/D、KV/Prefix 策略
  → vLLM / SGLang / TensorRT-LLM
```

### 9.1 Higress 与 AIBrix 在同一集群

Higress 的 Upstream 指向 AIBrix Envoy 数据面 Service，而不是某个 vLLM Service：

```text
envoy-<namespace>-<gateway>-<hash>.envoy-gateway-system.svc.cluster.local:80
```

入口需要保留：

- `/v1/*` 路径和请求体；
- `Authorization`；
- `routing-strategy` 等受控路由头；
- SSE/流式响应、长请求超时和取消传播。

### 9.2 Higress 与 AIBrix 在不同集群

跨集群同样可行，但不能使用 `*.svc.cluster.local`。AIBrix 集群需要提供一个稳定且可路由的内部地址：

1. 内网 LoadBalancer/VIP，优先；
2. 解析到该 VIP 的内部 DNS；
3. 企业服务注册中心中的稳定服务；
4. 仅实验时使用端口转发，不用于生产。

Higress 把这个地址注册为静态、DNS 或注册中心 Upstream。网络必须允许 Higress 数据面到 AIBrix Gateway 监听端口，并配置健康检查、连接池、流式超时和容量保护。不要使用单个 Envoy Pod IP：Pod 重建和滚动发布会让地址失效。

两层网关还要避免重复策略：重试只由一层负责或明确预算；限流区分租户入口与模型容量；Higress 生成的 Request ID 应透传到 AIBrix；AIBrix 的 `target-pod` 等内部诊断头不应默认暴露给公网。

本次实验没有修改任何实际 Higress 资源。先独立验证 AIBrix，再在隔离环境验证网关串联，可以降低误改现有入口的风险。

## 10. 换成真实 GPU vLLM 前还缺什么

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

## 11. 这次实验暴露的实战经验

1. **版本要按组合选。** AIBrix、Envoy Gateway、Gateway API 和 Envoy Proxy 是一个兼容单元；
2. **离线镜像要一次盘全。** 动态生成的 Envoy 数据面镜像最容易漏掉；
3. **先验证控制面，再占用 GPU。** mock Runtime 能快速区分网关问题和模型问题；
4. **看响应头和日志证明路由。** 只有 HTTP 200 不足以证明请求经过 AIBrix；
5. **完整 API Group 能避免 CRD 歧义。** 大型企业集群常有多个同名 Kind；
6. **LoadBalancer Pending 不等于 Listener 不工作。** 要分别看 Service、Gateway 和 Listener Condition；
7. **Higress 与 AIBrix 是两层职责。** 前者做统一入口，后者做 LLM 感知数据面；
8. **StormService 拥有同名 Headless Service。** 不要提前创建同名普通 ClusterIP Service；
9. **跨集群入口必须稳定。** 使用 VIP/DNS/服务注册，不能依赖 Pod IP。

## 12. 验收清单

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
- [ ] 为 Gateway 配置生产可用的内部 VIP 或同集群 ClusterIP 入口；
- [ ] Kubernetes 发布 GPU 资源并跑通真实 vLLM；
- [ ] 在隔离环境验证 Higress → AIBrix 的超时、流式、认证和故障语义。

## 延伸阅读

- [AIBrix Installation](https://aibrix.readthedocs.io/latest/getting_started/installation/installation.html)
- [AIBrix Gateway Routing](https://aibrix.readthedocs.io/latest/features/gateway-plugins.html)
- [Envoy Gateway Compatibility Matrix](https://gateway.envoyproxy.io/news/releases/matrix/)
- [AI Gateway 与智能路由](../inference/gateway-routing.md)
- [多机与分离式 LLM 推理](../inference/distributed-serving.md)
