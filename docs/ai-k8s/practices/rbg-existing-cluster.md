---
title: RBG 多角色推理编排与 sr1 实战
description: 在 Kubernetes 1.30 集群部署 RoleBasedGroup，实测角色依赖、服务发现、角色级扩缩与自愈，并对比 RBG、AIBrix StormService 和 Higress
status: lab
last_reviewed: 2026-08-07
---

# RBG 多角色推理编排与 sr1 实战

RBG 的全称是 **RoleBasedGroup（RBG）**。它不是新的推理引擎，也不是另一个 AI Gateway，而是一组面向分布式、带状态、多角色 AI 工作负载的 Kubernetes API。它把 Router、Prefill、Decode、KV Store 等角色，以及角色内部的多 Pod Rank，作为一个逻辑服务协调创建、发现、扩缩、更新和恢复。

截至 2026 年 8 月，官方最新发布为 `v0.8.0-alpha.3`。本次在 sr1 的 Kubernetes 1.30.4 集群安装该版本，并用 CPU 占位进程验证控制面。结论是：RBG 很适合补齐原生 Deployment 对多角色生命周期表达不足的问题，但它不能替代 vLLM/SGLang/Dynamo、P/D Router、KV Connector、AIBrix Gateway 或 Higress。

参考：[RBG 仓库](https://github.com/sgl-project/rbg)、[RBG v0.8.0-alpha.3](https://github.com/sgl-project/rbg/releases/tag/v0.8.0-alpha.3)、[RBG 官方文档](https://rolebasedgroup.github.io/)

## 1. 它解决的是哪一层问题

一套 P/D 分离服务可能包含：

```text
Higress
  → 模型或 P/D Router
      → Prefill Pool
      → Decode Pool
          → KV Cache Transfer / Store
```

这里至少有四类不同职责：

| 层次 | 回答的问题 | 典型组件 |
| --- | --- | --- |
| 企业入口 | 哪个租户可以访问，域名、TLS、鉴权、限流和审计怎么做 | Higress |
| 推理请求路由 | 请求应该进入哪个模型副本，P 与 D 如何配对 | AIBrix Gateway、SGLang Router、Dynamo Router、llm-d EPP |
| 工作负载编排 | Router、P、D 各需要几组 Pod，先启动谁，如何发现、更新和恢复 | RBG、AIBrix StormService/RoleSet、LWS、KubeRay |
| 推理与数据路径 | 模型如何执行，KV Cache 如何产生、传输和复用 | vLLM、SGLang、TensorRT-LLM、NIXL、Mooncake、LMCache |

RBG 主要位于第三层。它可以创建运行 SGLang、vLLM、Dynamo 或 Mooncake 的 Pod，却不实现这些组件的数据路径。

## 2. RBG 的资源模型

本次安装建立了 10 个 CRD。理解日常操作时先抓住下面五个：

```text
RoleBasedGroup：一个完整逻辑服务
  ├─ 每个 Role 自动生成一个 RoleInstanceSet
  │    └─ 每份 Role 副本生成一个 RoleInstance
  │          └─ 一个或多个 Pod
  ├─ 每个 Role 自动生成一个 Headless Service
  └─ 可选 RoleBasedGroupScalingAdapter
       └─ 为某个 Role 暴露 Scale 子资源
```

| 资源 | 作用 | sr1 中的实例 |
| --- | --- | --- |
| `RoleBasedGroup` | 声明一个服务包含哪些 Role、依赖和副本数 | `mock-pd` |
| `RoleInstanceSet` | 管理一个 Role 的多份实例 | `mock-pd-prefill` |
| `RoleInstance` | 管理一份稳定实例及其 Pod 组 | `mock-pd-prefill-0` |
| `RoleBasedGroupScalingAdapter` | 把单个 Role 映射为 HPA/KEDA 可操作的 Scale 目标 | `mock-pd-decode` |
| `CoordinatedPolicy` | 声明跨 Role 的更新或伸缩协调策略 | 本次未验证 |
| `RoleBasedGroupSet` | 管理多份 RBG | 本次未验证 |
| `ClusterEngineRuntimeProfile` | 复用引擎运行时配置 | 本次未验证 |

一个 Role 还能选择不同的实例拓扑：

| Pattern | 一份 RoleInstance 包含什么 | 适用场景 |
| --- | --- | --- |
| `standalonePattern` | 一个 Pod | Router、单卡或单 Pod 多卡引擎 |
| `leaderWorkerPattern` | 一个 Leader 和多个 Worker | 一个模型副本跨多个 Pod/节点 |
| `customComponentsPattern` | 多种自定义 Component | 需要异构 Pod 组合的复杂 Runtime |

`Role` 是外层职责，`Pattern` 是一份该职责内部的 Pod 拓扑。例如 Prefill 是一个 Role，而一份 Prefill Engine 可以用 `leaderWorkerPattern` 跨四个节点。不要把 “Prefill/Decode” 和 “Leader/Worker” 当成同一维度。

## 3. RBG、AIBrix 和 Higress 对比

RBG 与整套 AIBrix、Higress 并不是同类产品。最有意义的直接对比是 **RBG 与 AIBrix StormService/RoleSet**。

| 维度 | RBG | AIBrix StormService/RoleSet | AIBrix 整体 | Higress |
| --- | --- | --- | --- | --- |
| 核心定位 | 通用多角色工作负载编排 API | AIBrix 内部多角色推理编排 | LLM 推理控制面和数据面 | 企业 API/AI Gateway |
| 是否拥有 Pod 生命周期 | 是 | 是 | 可以通过 StormService、RayClusterFleet 等拥有 | 否 |
| 是否处理用户请求 | 否 | CRD 本身不处理 | AIBrix Gateway 处理 | Higress Gateway 处理 |
| 模型感知选副本 | 无 | 由 AIBrix Gateway 配合完成 | 有 | 侧重 Provider/Route 治理，不等于 P/D 副本调度 |
| P/D 能力 | 表达 Router、P、D Role；数据路径由 Runtime 提供 | 表达 P/D Role，并与 AIBrix P/D 路由更紧密 | 路由、编排、伸缩和 KV 能力可组合 | 可把请求转给 P/D Router，但不管理 P/D Pod |
| 服务发现 | 每个 Role 自动创建 Headless Service，注入拓扑环境变量 | StormService/RoleSet 的服务和标签 | 结合 Gateway 的模型/Role 发现 | Upstream、Ingress、Gateway API 或注册中心 |
| 角色级弹性 | ScalingAdapter 接 HPA/KEDA 等 | AIBrix PodAutoscaler 可按 `roleName` 操作 | KPA、APA、HPA 和自定义指标链 | 主要伸缩 Gateway，自身不决定 P/D 池容量 |
| 生态倾向 | SGLang、Dynamo、Mooncake，也可承载 vLLM | AIBrix Gateway、vLLM 与 AIBrix CRD | vLLM 为主的完整平台能力 | 企业入口、多模型/云模型、Wasm 插件 |
| 当前项目风险 | 最新发布仍是 alpha | 与 AIBrix 版本和 Gateway 集成绑定 | 组件较多、兼容矩阵较大 | 不是分布式推理编排器 |

### 3.1 什么时候更适合 RBG

- 想用一个独立、引擎相对中立的 API 表达 Router/P/D/Store 多角色拓扑；
- Role 之间有明确启动依赖、稳定身份、联动恢复或协调更新要求；
- 同时要表达单 Pod Role 和多节点 Leader/Worker Role；
- 正在使用 SGLang、NVIDIA Dynamo 或 Mooncake 的官方集成方式；
- 希望把工作负载编排与上层 Gateway 解耦。

### 3.2 什么时候继续用 StormService

- 已经完整采用 AIBrix Gateway、PodAutoscaler、模型标签和 P/D 路由；
- 希望 Prefill/Decode 编排、请求配对和角色级伸缩都沿用一套 AIBrix 语义；
- 已经验证 StormService 的 Replica/Pool 模式，不希望再引入第二套相似 CRD；
- 运维团队更重视减少控制器数量，而不是 Runtime 中立性。

同一批 Pod 不能同时由 RBG 和 StormService 拥有。否则副本数、滚动更新、故障恢复和 Service 都会出现两个权威来源。

### 3.3 与 Higress 怎么组合

RBG 没有自己的通用外部 Gateway，因此不会产生“Higress 和 RBG 两层网关”的重复问题。常见链路是：

```text
Client
  → Higress：TLS、认证、租户配额、审计
  → SGLang/Dynamo/自研 Router Service
  → RBG 管理的 Prefill、Decode 和 KV 角色
```

如果还需要 AIBrix 的模型感知路由，可以设计：

```text
Client
  → Higress：企业入口
  → AIBrix Gateway：模型、Prefix/Session/P-D 感知选路
  → 由 RBG 管理的 Runtime Endpoint
```

但 AIBrix v0.7.0 没有在本次实验中证明能够原生创建或管理 RBG。实际接入至少需要稳定 Endpoint、AIBrix 模型/端口标签、Ready 语义和自定义集成测试。只有固定一个 Runtime Router 或一个完整模型副本时，Higress 直接转发通常更简单；不要为了组件齐全强行叠加第二层推理网关。

## 4. sr1 安装前检查

本次环境：

| 项目 | 实测值 | 结论 |
| --- | --- | --- |
| Kubernetes Server | 1.30.4 | 满足当前安装文档的 1.28+ 要求 |
| 节点架构 | amd64 | 官方控制器镜像可运行 |
| GPU | 未发现 `nvidia.com/gpu` Allocatable | 只验证 CPU 控制面 |
| CRD/ClusterRole 权限 | 可以创建 | 能安装 Helm Chart |
| RBG | `v0.8.0-alpha.3` | 固定版本，不追随 latest |
| Controller App Version | `0.8.0-47cfe17` | 与发布 Chart 的默认值一致 |

不要只依据仓库首页的兼容表。当前 `doc/install.md` 写的是 Kubernetes 1.28+，因此本次按更严格的条件判断。

## 5. 安装 RBG

安装参数保存在 [`helm-values.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/rbg-sr1/helm-values.yaml)。实验把 Controller 和 CRD Upgrade Job 固定到健康节点，并将控制器缩为一个副本：

```bash
helm upgrade --install rbgs \
  https://github.com/sgl-project/rbg/releases/download/v0.8.0-alpha.3/rbgs-0.8.0-alpha.3.tgz \
  --namespace rbgs-system \
  --create-namespace \
  -f examples/rbg-sr1/helm-values.yaml \
  --wait
```

最终状态：

```text
Deployment/rbgs-controller-manager  1/1 Ready
Image                              rolebasedgroup/rbgs-controller:v0.8.0-47cfe17
Node                               10.189.110.112
```

### 5.1 实际遇到的安装坑

第一次安装时，CRD Upgrade Job 落到了已禁止调度的 `10.189.110.111`。Chart 默认给该 Job 配置了 `operator: Exists` 的全污点容忍，因此它仍可被分配到异常节点。镜像成功拉取后，Pod 内访问 `10.96.0.1:443` 超时，CRD 安装无法继续。

处理方式不是更换镜像，而是把 Job 和 Controller 的 `nodeSelector` 指向确认健康的节点后重试。生产建议进一步：

- 不要把全污点容忍等同于“适合运行在任何节点”；
- 为安装 Hook 配置健康节点池、必要的亲和性和资源；
- 安装超时先查 Job 日志、节点和 API Service 网络，再判断是否为镜像问题；
- Controller 生产至少两个副本，并配置跨节点反亲和，本次单副本只为实验收敛变量。

## 6. CPU 多角色样例

[`cpu-role-demo.yaml`](https://github.com/runzhliu/aik8s/blob/main/examples/rbg-sr1/cpu-role-demo.yaml) 声明三种 Role：

```text
gateway × 1
  └─ prefill × 2，等待 gateway Ready
       └─ decode × 2，等待 prefill Ready
            └─ 开启 ScalingAdapter
```

三种 Pod 都运行 NGINX，占用很少 CPU/内存。这只是控制面 Mock：Role 名叫 Prefill/Decode 不代表 NGINX 做了推理。

```bash
kubectl apply -f examples/rbg-sr1/cpu-role-demo.yaml
kubectl wait --for=condition=Ready \
  rbg/mock-pd -n rbg-demo --timeout=5m
```

控制器生成：

```text
RoleBasedGroup/mock-pd                  Ready=True
├─ RoleInstanceSet/mock-pd-gateway      1/1
├─ RoleInstanceSet/mock-pd-prefill      2/2
├─ RoleInstanceSet/mock-pd-decode       2/2
└─ ScalingAdapter/mock-pd-decode        Bound
```

事件时间线证明依赖生效：Gateway Ready 后才创建 Prefill；两个 Prefill Ready 后才创建 Decode。初始协调期间出现过 `DependencyNotMet` 和目标 `RoleInstanceSet not found` Warning，最终收敛为 `AllRolesReady`。生产告警要给这类可恢复协调事件设置持续时间，不能见到单次 Warning 就直接呼叫值班人员。

## 7. 服务发现实测

RBG 为每个 Role 自动创建 Headless Service：

```text
s-mock-pd-gateway   ClusterIP=None
s-mock-pd-prefill   ClusterIP=None
s-mock-pd-decode    ClusterIP=None
```

从 Gateway Pod 访问 Prefill：

```bash
kubectl exec -n rbg-demo mock-pd-gateway-0 -- \
  wget -qO- http://s-mock-pd-prefill:80
```

实测返回 NGINX HTML。RBG 还注入了：

```text
RBG_GROUP_NAME=mock-pd
RBG_ROLE_NAME=gateway
RBG_ROLE_INDEX=0
RBG_ROLE_INSTANCE_NAME=mock-pd-gateway-0
RBG_COMPONENT_NAME=gateway
RBG_COMPONENT_INDEX=0
```

真实 Runtime 可以用稳定 DNS 与这些拓扑变量构造 Rank、注册和 Peer 发现。但 Headless Service 只是发现机制，不提供模型感知负载均衡、P/D 配对或 KV 一致性。

## 8. 角色级扩缩实测

Decode Role 开启 `scalingAdapter` 后，控制器自动创建同名适配器。通过标准 Scale 子资源把 Decode 从 2 扩到 3：

```bash
kubectl scale rolebasedgroupscalingadapter mock-pd-decode \
  -n rbg-demo --replicas=3
```

结果：

```text
ScalingAdapter/mock-pd-decode  Bound  replicas=3  readyReplicas=3
RoleInstanceSet/mock-pd-decode desired=3 ready=3
```

验证后再通过同一 Scale 子资源恢复为 2，最终状态与仓库清单一致。恢复前曾对原始 YAML 执行服务端 Dry Run：由于清单仍声明 `decode.replicas: 2`、ScalingAdapter 已控制为 3，Webhook 明确拒绝覆盖。这是有价值的保护，也说明生产必须确定副本字段的唯一写入者：启用外部伸缩后，不要让 GitOps 持续回写同一个 Role 的静态副本数。

这证明 HPA/KEDA 可以通过适配器改变某个 Role 的目标副本数，但没有证明 CPU、QPS、KV 或 TTFT/TPOT 指标策略是合理的。P/D 自动伸缩还要处理模型加载预热、P/D 比例、排队、请求排空和 Scale-to-Zero 冷启动。

## 9. 自愈实测

删除 `mock-pd-prefill-1` 后，原 Pod 消失，控制器以相同稳定名称重新创建，约 5 秒恢复 Ready：

```text
mock-pd-prefill-1  1/1 Running  AGE=5s
RoleInstanceSet/mock-pd-prefill desired=2 ready=2
RoleBasedGroup/mock-pd          Ready=True
```

这只证明普通 Pod 删除能够恢复。真实多机推理必须继续验证：

- 一个 Worker 故障时只重启 Worker，还是重建完整 RoleInstance；
- NCCL/RDMA 连接和残留进程能否清理；
- 正在生成的请求、Router Endpoint 与 KV Cache 如何失效；
- 重启退避是否会形成故障风暴；
- 同一故障是否触发 RBG、Runtime 和上层 Gateway 的重复恢复。

## 10. 企业 TrainingJob 跑 vLLM 与 RBG 是什么关系 { #trainingjob-vllm-vs-rbg }

很多企业已经用 VolcanoJob、PyTorchJob 或自研 TrainingJob 启动多个 Pod，再用它们运行 vLLM 多机多卡。这不是错误用法：Job Controller 提供成组启动和失败重试，企业脚本负责建立 Ray Cluster、发现 Rank，最后只把 Head Pod 的 vLLM API 暴露为在线 Service。

```text
TrainingJob / VolcanoJob
  ├─ Master Pod：Ray Head + vLLM API
  ├─ Worker Pod 1：加入 Ray Cluster
  ├─ Worker Pod 2：加入 Ray Cluster
  └─ Worker Pod N
```

这套架构可以长期运行，尤其适合已有成熟训练平台、固定模型拓扑和少量内部服务的公司。它的代价是在线服务语义通常散落在平台代码和启动脚本中：Head-only Service、整组 Readiness、滚动发布、请求排空、完整副本扩缩以及 NCCL/Ray 故障恢复都需要自己实现。

RBG 不是替换 vLLM 的执行层，而是把这组脚本约定提升为声明式的长期工作负载：

```text
RoleBasedGroup
  └─ Role: backend
       replicas: 2
       leaderWorkerPattern:
         size: 4

最终含义：
  ├─ 完整模型副本 A：1 Leader + 3 Worker
  └─ 完整模型副本 B：1 Leader + 3 Worker
```

这里两个数字不能混淆：

- `leaderWorkerPattern.size` 是**一份完整模型副本内部**的 Pod 数；
- `role.replicas` 是完整模型副本数，扩容 1 次会新增一整组 Leader/Worker；
- 上层 Gateway 只能选择完整副本的 Leader/API Endpoint，不能把不同组的 Worker 混在一起。

### 10.1 RBG 能解决多少 vLLM 多机多卡问题

| 问题 | RBG 是否解决 | 实际责任方 |
| --- | --- | --- |
| 创建一组 Leader/Worker Pod | 是 | `leaderWorkerPattern` |
| 稳定编号、Leader 地址和组大小 | 是 | Headless Service 与 `RBG_LWP_*` 环境变量 |
| 以完整模型副本扩缩 | 是 | Role Replica/ScalingAdapter |
| Worker 故障后整组或局部恢复 | 可配置 | RBG RestartPolicy，仍须验证 Runtime 清理 |
| 一次性获得所有 GPU | 需要组合 | Volcano 或 Scheduler Plugins 的 Gang Scheduling |
| TP/PP/DP/EP 如何切分 | 否 | vLLM |
| Ray Actor 和进程执行 | 否 | Ray/vLLM |
| NCCL/RDMA/多网卡选择 | 否 | vLLM、Ray、NCCL、CNI 与节点网络 |
| 权重下载和缓存 | 否 | 对象存储、P2P 分发、镜像或本地缓存 |
| 模型感知请求路由 | 否 | AIBrix、llm-d、Ray Serve 或 Runtime Router |
| P/D KV Cache 传输 | 否 | NIXL、Mooncake、LMCache 等 Connector |

因此，RBG 能解决的是**多机多卡服务的 Kubernetes 编排面**，不能把尚未跑通的 vLLM 分布式通信自动变得可用或更快。

### 10.2 RBG + Ray + vLLM

最容易复用现有企业方案的是保留 Ray，只把 Job Controller 换成 RBG：

```text
Leader Template
  1. ray start --head --port=6379
  2. 等待预期 Worker Ready
  3. vllm serve MODEL --distributed-executor-backend ray ...

Worker Template
  1. ray start --address=${RBG_LWP_LEADER_ADDRESS}:6379 --block
```

RBG 可通过 `leaderTemplatePatch` 与 `workerTemplatePatch` 给 Leader、Worker 设置不同入口脚本，并注入：

```text
RBG_LWP_LEADER_ADDRESS  Leader 的稳定 DNS
RBG_LWP_GROUP_SIZE      一份 RoleInstance 的 Pod 总数
RBG_LWP_WORKER_INDEX    当前 Pod 序号，Leader 为 0
```

例如两台机器、每台 8 卡，一个模型副本共使用 16 卡时，vLLM 官方给出的常见组合是：

```bash
vllm serve /models/example \
  --tensor-parallel-size 8 \
  --pipeline-parallel-size 2 \
  --distributed-executor-backend ray
```

TP 通常留在单机高速互联域，PP 跨两个节点。也可以把 TP 设置为全组 GPU 数，但必须按模型、网络和硬件实测。所有节点需要一致的镜像、模型路径、Python/vLLM/Ray/CUDA/NCCL 版本；多网卡环境还要明确 `VLLM_HOST_IP`、NCCL 与 Gloo 使用的接口。

参考：[vLLM Parallelism and Scaling](https://docs.vllm.ai/en/latest/serving/parallelism_scaling/)、[vLLM Multi-Node Serving](https://docs.vllm.ai/en/latest/examples/ray_serving/multi-node-serving/)

### 10.3 RBG + vLLM 原生 MultiProcessing

当前 vLLM 也提供多节点 MultiProcessing 模式。概念上映射为：

```text
RBG_LWP_GROUP_SIZE      → --nnodes
RBG_LWP_WORKER_INDEX    → --node-rank
RBG_LWP_LEADER_ADDRESS  → --master-addr
```

两节点示意：

```bash
# Leader
vllm serve /models/example \
  --tensor-parallel-size 8 \
  --pipeline-parallel-size 2 \
  --nnodes 2 --node-rank 0 \
  --master-addr "$RBG_LWP_LEADER_ADDRESS"

# Worker
vllm serve /models/example \
  --tensor-parallel-size 8 \
  --pipeline-parallel-size 2 \
  --nnodes 2 --node-rank 1 \
  --master-addr "$RBG_LWP_LEADER_ADDRESS" \
  --headless
```

生产入口脚本不能硬编码 `node-rank 1`，而要读取 `RBG_LWP_WORKER_INDEX`；还要等待 DNS、端口和所有 Rank 就绪。原生模式减少 Ray 组件，但企业必须重新验证启动屏障、日志聚合、故障恢复和可观测性，不能因为进程更少就认为运维一定更简单。

### 10.4 官方 vLLM 支持到什么程度

RBG v0.8 文档明确给出 vLLM `standalonePattern`，仓库还有 vLLM + Mooncake Transfer Engine 的 P/D 示例。因此“RBG 可以承载 vLLM”有官方依据。

但当前开箱即用的 `leaderWorkerPattern` 多节点样例主要使用 SGLang 或 Dynamo SGLang Runtime；仓库还不是一套可直接复制到任意企业网络的 vLLM Ray 多节点模板。落地时仍需编写 Leader/Worker 入口脚本，确定 vLLM/Ray 版本、模型分发、端口、网卡、Gang 和恢复策略。

参考：[RBG Ecosystem Integration](https://github.com/sgl-project/rbg/blob/v0.8.0-alpha.3/doc/features/ecosystem-integration.md)、[RBG vLLM + Mooncake Example](https://github.com/sgl-project/rbg/blob/v0.8.0-alpha.3/examples/inference/ecosystem/mooncake/mooncake-transfer-engine/vllm-pd-disagg-with-mooncake-te.yaml)

### 10.5 要不要从 TrainingJob 迁移

| 当前情况 | 建议 |
| --- | --- |
| 固定一个模型、一两个多机副本，现有 Job 已有 Gang、Service、整组恢复 | 保留现有方案，迁移收益有限 |
| 已经标准使用 Ray 和 KubeRay | 优先评估 RayCluster/RayClusterFleet，不必只为换 CRD 引入 RBG |
| 已全面采用 AIBrix Gateway 和角色级弹性 | 优先 StormService/RoleSet，避免两套工作负载控制器 |
| 多团队各写一套 Master/Worker 脚本 | RBG 可统一拓扑、发现、更新和恢复接口 |
| 开始引入 Router、Prefill、Decode、KV Store 多角色 | RBG 的价值明显增大 |
| 需要 Runtime 中立并组合 SGLang、Dynamo、Mooncake、vLLM | RBG 比绑定单一平台的内部 CRD 更适合作为候选 |

迁移时不要一次重写 vLLM 数据路径。先保持原来的镜像、Ray 和启动参数，只把 Pod 生成、DNS、状态和 Service 所有权迁到 RBG；用同一模型、输入长度和并发对照启动时间、TTFT、TPOT、Goodput、恢复时间，再决定是否扩大范围。

## 11. 从 Mock 走向真实推理

推荐按风险递增：

1. 保留 `standalonePattern`，先用单卡 SGLang/vLLM 聚合服务替换 NGINX；
2. 再加入 Router、Prefill、Decode，验证 OpenAI-Compatible 请求和 KV Connector；
3. 为 P/D 分别接入真实负载指标，只观测建议副本数，暂不自动执行；
4. 用 `leaderWorkerPattern` 建一份跨节点 Engine，验证 Rank 发现、Gang、拓扑和整体恢复；
5. 最后加入 Higress 或 AIBrix Gateway，压测额外一跳、SSE、重试、超时和故障语义。

RBG 官方仓库已经提供 SGLang 聚合/P-D、多节点 Leader/Worker，以及 Dynamo、Mooncake Transfer Engine/Store 示例。示例证明上游提供了集成入口，不等于目标 GPU、网络、Runtime 和模型组合已经生产验证。

参考：[RBG Inference Examples](https://github.com/sgl-project/rbg/tree/v0.8.0-alpha.3/examples/inference)、[Mooncake RBG Integration](https://kvcache-ai.github.io/Mooncake/deployment/kubernetes-deployment-guide/rbg-integration.html)

## 12. 这次实验没有证明什么

- 没有 GPU，因此未证明模型加载、推理正确性和吞吐；
- 没有真实 P/D Router 与 KV Connector，因此未证明 KV 传输；
- 没有测试 `leaderWorkerPattern`、Gang Scheduling 和硬件拓扑；
- 没有测试 HPA/KEDA 指标闭环、协调伸缩和 Scale-to-Zero；
- 没有测试滚动、原地升级、CRD 转换和版本回滚；
- 没有测试 RBG 与 AIBrix Gateway 的原生集成；
- Controller 只有一个副本，未验证控制面高可用；
- 没有让 Higress 接管该样例入口，现有 Higress/AIBrix 链路未修改。

## 13. 生产验收清单

- [x] RBG 版本固定，Chart、Controller 镜像和 Kubernetes 版本已记录；
- [x] Controller、CRD 和 Webhook 安装完成；
- [x] 角色启动依赖、Headless Service 和环境变量已验证；
- [x] Decode Role 完成 2→3→2 独立扩缩，并验证副本字段所有权冲突保护；
- [x] Prefill Pod 删除后恢复，RBG 回到 Ready；
- [ ] Controller 多副本和反亲和已验证；
- [ ] 真实引擎、模型、OpenAI API 与流式响应已验证；
- [ ] P/D Router、KV Connector、超时和失效语义已验证；
- [ ] 多节点 Rank、Gang、GPU/NIC 拓扑和整体恢复已验证；
- [ ] HPA/KEDA 指标、预热、排空和防抖已验证；
- [ ] 升级、回滚、CRD 转换、备份与灾难恢复已验证；
- [ ] Higress/AIBrix/RBG/Runtime 的路由、伸缩、重试和故障职责只有一个权威来源。

## 延伸阅读

- [RBG Installation](https://github.com/sgl-project/rbg/blob/v0.8.0-alpha.3/doc/install.md)
- [RBG Deploy Inference Service](https://github.com/sgl-project/rbg/blob/v0.8.0-alpha.3/doc/best-practice/zh/01-deploy-inference-service.md)
- [AIBrix 既有集群实战](aibrix-existing-cluster.md)
- [Higress AI Gateway 实战](../inference/higress-ai-gateway.md)
- [多机与分离式 LLM 推理](../inference/distributed-serving.md)
