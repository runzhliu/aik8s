---
title: RBG 多角色推理编排：从 CPU 控制面到生产 GPU 实测
description: 在 Kubernetes 1.30 集群部署 RoleBasedGroup，实测角色依赖、服务发现、扩缩、自愈、Ray 两机推理和 NIXL P/D 分离，并以相同镜像与模型对比 RBG 和 AIBrix
status: lab
last_reviewed: 2026-08-08
---

# RBG 多角色推理编排：从 CPU 控制面到生产 GPU 实测

RBG 的全称是 **RoleBasedGroup（RBG）**。它不是新的推理引擎，也不是另一个 AI Gateway，而是一组面向分布式、带状态、多角色 AI 工作负载的 Kubernetes API。它把 Router、Prefill、Decode、KV Store 等角色，以及角色内部的多 Pod Rank，作为一个逻辑服务协调创建、发现、扩缩、更新和恢复。

截至 2026 年 8 月，官方最新发布为 `v0.8.0-alpha.3`。本次先在 sr1 的 Kubernetes 1.30.4 集群用 CPU 占位进程验证控制面，再在一套生产 GPU 集群以与现有 AIBrix 服务相同的镜像、模型和运行参数，依次跑通单卡 vLLM、两节点 Ray/vLLM 和两节点 NIXL P/D。结论是：RBG 很适合补齐原生 Deployment 对多角色生命周期表达不足的问题，但它不能替代 vLLM/SGLang/Dynamo、P/D Router、KV Connector、AIBrix Gateway 或 Higress。

!!! warning "生产信息已经脱敏"
    本文不记录公司内部集群名、节点地址、Registry、Ceph monitor、模型卷真实路径、域名、Pod IP 或 Secret。生产清单没有提交到公开仓库，文中的 `<...>` 需要按自己的环境替换。

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

### 3.4 使用 RBG 后，SGLang 是否还需要 Router

如果 SGLang 采用 Prefill/Decode 分离，答案是：**仍然需要一个理解 P/D 协议的 Router，但不一定必须是 SGLang Router**。RBG 负责 Router、Prefill、Decode Pod 的生命周期、启动依赖、稳定发现、更新和扩缩，不接收用户推理请求，也不负责为一次请求选择 P/D 实例。RBG 为 Prefill Role 创建的 Headless Service 只是服务发现入口，不能代替请求配对和数据面协调。

推荐的数据链路是：

```text
Client
  → Higress / API Gateway（可选：TLS、认证、租户限流）
  → SGLang Model Gateway（原 SGLang Router）
       ├─ 选择一个 Prefill Engine
       └─ 选择一个 Decode Engine
              ↑
       Prefill ── Mooncake/NIXL 等 KV Transfer ──→ Decode

RBG Controller
  ├─ 管理 Router Role
  ├─ 管理 Prefill Role
  └─ 管理 Decode Role
```

在 P/D 模式下，不应把普通 OpenAI-Compatible 流量直接发送到 Prefill Service。Prefill 只负责处理 Prompt 和生成初始 KV，完整响应还需要 Decode 继续生成；如果没有 Router，就必须由调用方自己完成 P/D 选择、请求拆分、KV/bootstrap 元数据传递、失败处理和流式响应协调，这实际上是在重新实现一个 P/D Router。Kubernetes Service 的四层负载均衡也不了解 Prefix Cache、实例排队长度、P/D 角色配比或一次请求的配对状态。

是否部署 SGLang Router 应按运行模式判断：

| SGLang 运行模式 | 是否需要 SGLang Router | 判断 |
| --- | --- | --- |
| P/D 分离，尚无其他 P/D 路由层 | 需要 | 使用 SGLang Model Gateway 选择并协调 Prefill/Decode |
| P/D 分离，已有兼容的 AIBrix、Dynamo 或自研 P/D Router | 不一定 | 只保留一个 P/D 路由权威；替代组件必须真正支持当前 SGLang P/D 协议和 KV 传输参数 |
| 聚合模式，只有一个 SGLang Engine | 不需要 | Higress 或普通 Service 可以直接转发到完整 Engine |
| 聚合模式，有多个同构 Engine | 可选但通常建议 | Kubernetes Service 能做基础分发；Router 才能提供 Cache/负载感知、实例摘除和更完整的推理指标 |
| 固定 1P1D 功能实验 | 可以临时省略 | 仅适合用脚本显式协调两端，不能据此推导生产入口不需要 Router |

#### Cache-aware 不等于跳过 Prefill

“请求已经有 95% KV Cache，可以直接跳到 Decode”描述的是一种有条件的优化方向，通常称为 **Conditional Disaggregation** 或 **Prefill Bypass**，但不能只根据命中比例决定。它实际省略的是**远端 Prefill 节点**，未命中的 Prompt Token 仍然需要由某个 Engine 计算 KV。

例如一个 100K Token 的 Prompt 在选中的 Decode Engine 上命中 95K，仍有 5K Token 未命中：

```text
普通 P/D：Prefill Engine 计算剩余 5K → 传输新增 KV → Decode
条件式 P/D：Decode Engine 本地计算剩余 5K → Decode
```

第二条路径只有在 Decode Engine 也具备本地执行少量 Prefill 的能力时才成立。即使命中率达到 95%，5K Token 的 Prefill 仍可能足以抵消一次远端调用和 KV 传输的开销；反过来，一个 1K Prompt 只剩 5 个 Token 未命中，则更可能适合留在 Decode 本地。因此生产决策应该比较**未命中 Token 的绝对数量与计算成本**和**远端 Prefill、KV 传输及协调开销**，而不是设置一个孤立的命中率阈值。

截至 2026-08-09 的 SGLang `main`，SGLang Model Gateway 的 `cache_aware` 策略属于**选节点策略**：它根据请求历史维护近似 Radix Tree，把请求送到更可能持有相同 Prefix 的 Prefill/Decode Worker，但没有据此省略 Prefill 阶段。当前 HTTP P/D 路径仍会选择一对 Prefill/Decode 并同时发送两个请求；Prefill 失败后，Router 会取消等待 KV 的 Decode 请求。因此，SGLang 的 Cache-aware Routing 不能等同于 Conditional Disaggregation。

新版 SGLang Runtime 提供 `--disaggregation-decode-enable-radix-cache`。启用后，Decode 可以复用自己已有的 Prefix KV，并通过 `decode_prefix_len` 告诉 Prefill 只传输未命中的后缀 KV；完整命中时甚至可以没有普通 KV Page 需要传输，但 Prefill 请求和必要的元数据/辅助状态协调仍然存在。这项能力优化的是**重复计算和 KV 传输量**，不是 Router 层直接跳过 Prefill。

llm-d Router 的 `prefix-based-pd-decider` 是 Conditional Disaggregation 的直接例子。它先选择 Decode，再根据该节点上的未命中后缀长度决定是否选择远端 Prefill：未命中 Token 达到 `nonCachedTokens` 阈值时走远端 P/D；低于阈值时不设置 Prefill Endpoint，由 Decode 节点本地完成剩余 Prefill 和 Decode。这里的核心参数是未命中 Token 的绝对数量，而不是“95%”这样的单一比例。

还要限定“SGLang Router 支持 vLLM”的范围。SGLang Model Gateway 可以为普通聚合式 vLLM 后端提供协议适配或路由，但这不等于支持 vLLM P/D 数据路径。上述版本的 gRPC Dual/PD 路径明确拒绝 vLLM Worker；HTTP P/D 路径使用的也是 SGLang Bootstrap 和请求字段。选型时必须分别验证“普通 OpenAI-Compatible/vLLM 路由”和“vLLM P/D 配对、KV Connector、Conditional Disaggregation”，不能从前者推导后者已经可用。

参考：[SGLang HTTP P/D Router](https://github.com/sgl-project/sglang/blob/449f0da78fda43b0e0d51254b8654671bd26e504/sgl-model-gateway/src/routers/http/pd_router.rs#L697-L732)、[SGLang Cache-aware Policy](https://github.com/sgl-project/sglang/blob/449f0da78fda43b0e0d51254b8654671bd26e504/sgl-model-gateway/src/policies/cache_aware.rs#L19-L30)、[SGLang Decode Radix Cache](https://github.com/sgl-project/sglang/blob/449f0da78fda43b0e0d51254b8654671bd26e504/docs/docs/advanced_features/server_arguments.mdx#L3009-L3012)、[SGLang vLLM P/D Check](https://github.com/sgl-project/sglang/blob/449f0da78fda43b0e0d51254b8654671bd26e504/sgl-model-gateway/src/routers/grpc/common/stages/client_acquisition.rs#L42-L52)、[llm-d Disaggregation and PD Decider](https://github.com/llm-d/llm-d-router/blob/main/docs/disaggregation.md#prefix-based-pd-decider)

因此，RBG 与 SGLang 的常见组合不是“RBG 直接对接 P 节点”，而是在同一个 `RoleBasedGroup` 中声明 `router`、`prefill`、`decode` 三个 Role，对外只暴露 Router Service，Prefill/Decode Service 保持集群内可见。RBG 官方的 SGLang P/D 示例也采用这一结构：Router Role 使用 `sglang_router.launch_router --pd-disaggregation`，并配置 Prefill 和 Decode Endpoint。

如果企业入口已经使用 Higress，可以保留 `Higress → SGLang Model Gateway → P/D` 两层结构：前者负责通用 API 治理，后者负责推理数据面。如果 AIBrix Gateway 或其他组件已经完成 SGLang P/D 配对，则不要再串联第二个 SGLang P/D Router，避免两层同时重试、重复选择 Endpoint 或对请求归属产生不同判断。

参考：[RBG SGLang P/D Example](https://github.com/sgl-project/rbg/blob/main/examples/inference/pd-disagg-standalone.yaml)、[SGLang P/D Disaggregation](https://docs.sglang.ai/backend/pd_disaggregation.html)、[SGLang Model Gateway](https://github.com/sgl-project/sglang/blob/main/docs/advanced_features/sgl_model_gateway.md)

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

## 12. sr1 控制面实验的边界

sr1 的 CPU Mock 只证明 RBG 的安装、角色依赖、服务发现、角色级伸缩和普通 Pod 自愈。它没有证明模型加载、GPU 通信、Ray Rank、P/D Router 或 KV Cache 传输。为了避免用 Mock 结果替真实推理背书，下一轮在生产 GPU 集群重新使用真实模型验收。

## 13. 生产 GPU 三种架构实测

生产验证遵守三个约束：只用标准推理节点池、不修改已有 AIBrix/Higress 服务、所有新模型使用独立名称。每个清单先以 `replicas: 0` 通过 API Server Dry Run 和控制器收敛检查，再逐个扩到 1；任何异常都可以按精确 RBG 名称缩回 0。

为了让 RBG 与 AIBrix 的差异可比较，Ray 和 P/D 两组实验没有重新制作镜像：它们直接复用现有 AIBrix 工作负载的同一运行时镜像、模型目录、精度和 vLLM 参数。变化的主要是 Kubernetes 编排对象，而不是 Runtime。

| 架构 | 模型与拓扑 | RBG 表达 | 实测结果 |
| --- | --- | --- | --- |
| 单卡聚合推理 | 7B 蒸馏模型，1 Pod × 1 GPU | `backend` Role + `standalonePattern` | Pod Ready，OpenAI-Compatible 请求成功 |
| Ray 多机模型并行 | 32B BF16，2 节点 × 1 GPU，PP=2 | `head`、`worker` 两个 Role，各一个 `standalonePattern` | Ray 聚合 2 GPU，17 个权重分片加载完成，请求返回 `RBG_RAY_OK` |
| NIXL P/D 分离 | 32B GPTQ Int4，Prefill 与 Decode 各 1 节点 × 1 GPU | `prefill`、`decode` 两个 Role，各一个 `standalonePattern` | 两侧 NIXL/UCX Ready，经 AIBrix Gateway 请求返回 `RBG_PD_OK` |

三组 Pod 均使用硬 Pod Anti-Affinity；Ray Head/Worker、Prefill/Decode 都实际落在不同宿主机，整个验证过程 Restart Count 保持为 0。这轮验证最高同时新增 5 张 GPU，没有容忍保留池或离线节点的污点。

### 13.1 单卡 `standalonePattern`

单卡场景先验证最短链路：RBG 创建 RoleInstanceSet、RoleInstance、Pod 和 Headless Service，vLLM 本身仍提供 OpenAI API。

```text
RoleBasedGroup
  └─ backend × 1
       └─ vLLM Pod × 1 GPU
```

这与 Deployment 的性能没有天然差异。RBG 的价值在于同一个 API 以后还能增加 Router、Worker、Prefill、Decode 或 Store Role；如果服务永远只有一个无状态 Pod，Deployment/KServe 通常更简单。

### 13.2 Ray 两节点 `head + worker`

生产集群没有为了本次实验额外安装 LeaderWorkerSet API，因此使用两个 RBG Role 表达 Ray Head 和 Worker：

```text
RoleBasedGroup
  ├─ head × 1：ray start --head，等待 Ray GPU=2，再启动 vLLM API
  └─ worker × 1：通过 RBG 稳定 DNS 加入 Head

vLLM：TP=1、PP=2、distributed-executor-backend=ray
```

RBG 自动生成的 Headless Service 即使没有 Service Port，也能提供 Pod 稳定 DNS；脚本仍需显式使用 Ray 端口。Head 日志先持续看到 `GPU=1`，Worker 镜像拉取并加入后变为：

```text
Active Ray nodes: 2
GPU: 2.0/2.0 reserved in placement groups
accelerator type: 2 × L20
```

随后 vLLM 的两个 `RayWorkerWrapper` 分别运行在两个节点，32B 模型完成 PP=2 初始化。真实请求返回：

```json
{"model":"rbg-qwen2-5-32b-ray-2n","content":"RBG_RAY_OK"}
```

本次从创建 Pod 到全部 Ready 约 8 分钟，其中 Worker 所在节点没有镜像缓存，拉取镜像占了约 4 分钟。它不是性能基准，却暴露了一个生产事实：多机服务的启动上限由最慢节点决定，Head 必须等待完整 GPU 数，Startup Probe、发布超时和扩容防抖都要覆盖镜像拉取与模型加载。

### 13.3 RBG 编排角色，AIBrix 完成 P/D 路由

P/D 两端完全复用既有 StormService 使用的 vLLM/NIXL 镜像和 GPTQ 模型，RBG 只接管 Pod 生命周期：

```text
AIBrix Gateway / P-D Router
  ├─ RBG prefill Role：vLLM + NixlConnector
  └─ RBG decode Role：vLLM + NixlConnector
```

为两个 Pod 增加 AIBrix 的模型名、端口、引擎和 `role-name` 标签，以及 `routingStrategy=pd` 注解后，现有 Gateway 能发现它们。两侧都加载约 18 GiB 权重，初始化 UCX Agent，并为 16K 上下文保留约 21 GiB KV Cache。

同一个 Request ID 的脱敏日志显示：

```text
Prefill: max_tokens=1, do_remote_decode=true
Decode:  do_remote_prefill=true,
         remote_engine_id=<PREFILL_ENGINE>,
         remote_block_ids=<BLOCKS>
```

最终经 Gateway 返回 `RBG_PD_OK`。这证明 RBG 管理的 Pod 可以接入当前 AIBrix P/D 数据路径，但不要把它描述为“RBG 自己实现了 P/D”：请求拆分、P/D 配对和 KV Transfer 参数仍由 AIBrix Gateway 产生，真正搬运 KV 的是 vLLM NIXL/UCX。

### 13.4 DeepSeek V4 Flash 的 SGLang 双机实测

在上述 vLLM 路径之外，仓库还准备了一组 DeepSeek V4 Flash 0731 的 SGLang P/D 清单，用一个 RBG 表达一个 Prefill Role 和一个 Decode Role，每个 Role 都是单机 8 卡 TP=8。常规部署通过反亲和把两个 Pod 分布到不同 H20 节点；RDMA 专项测试为了复用两台已经 cordon 的隔离节点，改用 `spec.nodeName` 分别直绑节点，全程没有执行 `uncordon`。SGLang 使用 NIXL 传输 KV，AIBrix Gateway 根据 `role-name`、`roleset-name` 和模型标签选择两端，并注入 SGLang 的 bootstrap 参数。

实际实验使用两台 8×H20 96 GB 节点。两个 Engine 都完成 DeepSeek V4 Flash 权重加载、Marlin 准备、NIXL 1.3.2 与 UCX 初始化，RBG 最终为 Ready；初始 TCP 基线通过反亲和分散 Pod，后续 RDMA 阶段改为分别直绑隔离节点。首次冷启动中，较慢节点拉取大镜像约 2 分钟，约 157 GiB 模型同步和单侧约 295 秒的 Marlin 权重准备/JIT 构成主要等待时间。

这次没有在 RBG 中再部署一个 SGLang Router Role，因为集群已有 AIBrix Gateway，并由它负责请求级 P/D 配对和 bootstrap 参数注入。RBG 只管理 Prefill/Decode 生命周期。若不使用 AIBrix，才应按 RBG 官方样例增加 `router` Role，对外只暴露 SGLang Router；不要把两个 Router 串联，否则会产生两层角色选择、超时和重试状态。

服务刚进入 Ready 后立即发出的第一条请求遇到 upstream timeout；待 SGLang 的 disaggregation warm-up 明确完成后，确定性请求在 0.25 秒内返回 `PD_OK`。稳态短测结果如下，全部请求成功：

| 场景 | 输出 tok/s | p95 TTFT | p95 TPOT | p95 ITL | p95 E2E |
| --- | ---: | ---: | ---: | ---: | ---: |
| 128/64，C=1 | 93.32 | 231.42 ms | 7.24 ms | 7.46 ms | 686.99 ms |
| 128/64，C=8 | 438.42 | 874.42 ms | 8.26 ms | 8.59 ms | 1400.97 ms |
| 4096/128，C=4 | 216.50 | 1431.91 ms | 7.94 ms | 8.44 ms | 2437.57 ms |

当前 Decode 的单 Token 间隔稳定，但 Prefill、KV 传输和请求协调成本偏高。4K 场景 p95 TTFT 与此前 vLLM Combined TP=8 的约 1.39 秒接近，输出吞吐低约 21.8%，而 P/D 使用了两倍 GPU。由于 Runtime 和优化参数仍不同，这只能用于确定下一步，不是严格框架排名。

资源最多容纳两台节点，因此严格 A/B 不再增加第三套服务，而采用串行切换：先保存 P/D 数据，停止双角色 RBG，再用其中一台部署同 SGLang 镜像、相同模型和参数的 Combined TP=8；客户端、Gateway、随机种子、请求集和 warm-up 均保持不变，并同时比较 tokens/s/GPU。RDMA 也必须作为单变量验证，不能只改一个 UCX 环境变量就宣称已经启用 RDMA。下一节记录了从设备注入到数据面计数器的完整证据链。

### 13.5 在 cordon 节点启用 RDMA：从“设备可见”到“真实流量”

这次测试节点已经被 cordon，目的是隔离实验流量。`nodeSelector`、亲和性和 toleration 仍然要经过调度器，不能让新 Pod 落到 cordon 节点；设置 `spec.nodeName` 后，Pod 不再经过调度器选址，因此可以在**不执行 `uncordon`** 的前提下由对应节点的 kubelet 接管。这个做法只适合已知节点的短期实验：它绕过调度器的 cordon、资源余量和拓扑检查，提交前必须先人工确认 GPU、RDMA、CPU 和内存都足够。

`nodeName` 也不等于可以删除 toleration。一次 HostPath 空间预检虽然成功直绑节点，却因没有容忍隔离节点的 `NoExecute` taint，被 Taint Manager 立即标记删除；补齐与正式 Engine 相同的 toleration 后才稳定执行。因此需要区分两个阶段：cordon/`NoSchedule` 主要阻止调度器选址，`NoExecute` 仍可在 Pod 已绑定后将其驱逐。

仅申请 RDMA Extended Resource 还不够。第一次 Preflight 能看到 `/dev/infiniband/uverbs*` 字符设备，却没有 RDMA 网络接口；而且脚本把设备名写死成 `uverbs0`，实际分配到了另一个 `uverbs`，造成了一次假失败。修正后的检查会枚举全部设备，并同时要求 Pod 具备：

```yaml
metadata:
  annotations:
    tke.cloud.tencent.com/networks: "tke-route-eni,tke-rdma-macvlan"
spec:
  nodeName: <CORDONED_RDMA_NODE>
  containers:
    - resources:
        requests:
          tke.cloud.tencent.com/tke-shared-rdma: "4"
        limits:
          tke.cloud.tencent.com/tke-shared-rdma: "4"
      securityContext:
        capabilities:
          add: ["IPC_LOCK"]
```

其中 CNI 注解负责创建 RDMA Macvlan 网络，Extended Resource 负责分配设备，`IPC_LOCK` 允许通信库锁定内存。正式 Pod 启动后，两侧各看到 4 个 RDMA 设备、4 个 RDMA 地址以及有效 GID；SGLang 日志显示 NIXL 1.3.2、UCX backend、P/D warm-up 全部完成。经 AIBrix Gateway 发起长 Prompt 请求得到预期响应，同时 Prefill 侧端口发送计数增加约 742 MiB，Decode 侧接收计数增加约 716 MiB，证明 KV 数据确实经过 RDMA，而不是仅仅“Pod 里有设备”。

为了把网络与 Runtime 分开，随后直接在两个 Engine Pod 之间运行 `ib_write_bw`：

```bash
# Decode 侧
ib_write_bw -d mlx5_bond_0 -x 3 -F --report_gbits -s 65536 -n 5000

# Prefill 侧，连接 Decode 的 RDMA 地址
ib_write_bw -d mlx5_bond_0 -x 3 -F --report_gbits -s 65536 -n 5000 <DECODE_RDMA_IP>
```

RoCE v2 GID index 3 的平均带宽为 **195.25 Gb/s**，峰值 **195.45 Gb/s**；所有端口的 `xmit_wait`、discard、receive error、remote physical error、symbol error 和 link recovery 都为 0。到这里可以排除 GPU 节点、RDMA 设备注入和底层 RoCE Fabric 带宽不足。

随后使用完全相同的设备和参数，只把 GID index 改为 2。连接虽然建立，但客户端在首批 128 个 Work Request 上立即出现 completion error（syndrome `0x81`），没有产生有效吞吐；服务端也因地址交换失败结束。这个单变量对比说明当前网络必须显式使用已经验证的 RoCE v2 GID index 3，不能依赖 UCX 自动选择，因此正式清单补充了：

```yaml
env:
  - name: UCX_IB_GID_INDEX
    value: "3"
```

但启用 RDMA 后的首轮应用压测反而严重退化：

| 场景 | 请求成功 | 输出 tok/s | p95 TTFT | p95 TPOT | p95 ITL |
| --- | ---: | ---: | ---: | ---: | ---: |
| 128/16，C=1，探索性小样本 | 2/2 | 1.31 | 4687.83 ms | 542.36 ms | 956.27 ms |
| 128/16，C=8，探索性小样本 | 8/8 | 1.78 | 61486 ms | 521.54 ms | 1042.65 ms |
| 128/16，C=1，固定 GID index 3 | 2/2 | 1.35 | 4540.22 ms | 541.88 ms | 971.10 ms |

这组小样本只用于定位异常，不能作为 RDMA 的最终性能结论。压测期间 GPU SM 多次空闲，Decode 日志在真正进入生成后仍能达到约 89 token/s，而长时间消耗在 `transfer-req` 对应的 KV 传输与协调阶段；并发请求还表现出明显串行等待。结合 195 Gb/s 的裸 RDMA 结果，问题范围已经从“硬件或网络是否正常”缩小到 **NIXL/UCX 的设备、GID、multi-rail 选择，内存注册和请求协调**。

固定 GID index 3 后，功能请求正常，但 C=1 的小样本性能与修改前几乎相同。index 2/3 的裸链路差异证明 GID 3 是当前 RoCE 网络的必要配置，却不是应用层慢的根因；不能把“纠正了一项错误配置”写成“性能问题已经修复”。

后续严格 A/B 按以下顺序进行，避免一次修改多个 Runtime 变量：

1. 保持 GID index 3，对比 `UCX_NET_DEVICES=all` 与显式单 rail，检查是否是 multi-rail 选择或注册成本；
2. 若单 rail 仍异常，再增加 NIXL/UCX 级 trace，拆分内存注册、元数据交换、KV Page 搬运与完成通知耗时；
3. 比较 RDMA P/D、TCP P/D 与同镜像 Combined TP=8，并同时记录每 GPU 吞吐和资源成本；
4. 如果 TCP P/D 仍慢，再把执行拓扑切换到社区已经验证的 TP=4、DP=4、DP Attention + DeepEP，避免把尚未验证的纯 TP=8 + Marlin FP4 组合误认为网络问题。

这个过程带来的关键经验是：**设备可见、NIXL 显示 UCX Ready、请求成功和 RDMA 高带宽，是四个不同层次的结论。** 只有应用请求期间的端口计数器能够证明数据路径，只有同请求集 A/B 才能证明性能收益。

#### 13.5.1 同镜像 Combined 对照将范围收敛到 P/D 路径

为了判断异常来自 DeepSeek V4 Runtime 本身，还是 P/D 特有的数据路径，随后停止双角色 RBG，在原 Decode 节点串行部署同一 SGLang 镜像、同一模型、同一 TP=8 和同一推理参数的 Combined Engine。Combined 不启用 `disaggregation-mode`，Prefill 和 Decode 都在同一个 8-GPU Pod 内完成；模型继续命中 HostPath，JIT Cache 则改为按 Runtime 版本隔离的 HostPath。

首次启动总计约 11 分钟：权重加载、FP8 转换和 MHC 预热约 278 秒，Decode CUDA Graph 捕获约 356 秒。进程树能看到 `cicc`、NVCC 和 Ninja 持续工作，因此这段无日志刷新不是 Pod hang。相同 Runtime 的后续重建可以复用最终 `.so`、CUBIN 和其他 JIT 产物，但仍要执行权重读入、显存分配和 CUDA Graph 捕获。

为避免外部数据集依赖，压测客户端使用本地 Tokenizer 生成固定长度 `random-ids`。首次遇到的新并发 shape 与长 Prompt shape 分别出现一次性停顿，相同参数立即复跑后恢复稳定，因此下表采用复跑数据：

| 场景 | 路径 | 成功 | 输出 tok/s | p95 TTFT | p95 TPOT | p95 ITL | p95 E2E |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 128/16，C=1 | RDMA P/D，固定 GID 3 | 2/2 | 1.35 | 4540.22 ms | 541.88 ms | 971.10 ms | - |
| 128/16，C=1 | TCP P/D | 2/2 | 1.66 | 1909.39 ms | 536.97 ms | 993.41 ms | 9803.95 ms |
| 128/16，C=1 | Combined TP=8 | 2/2 | 58.09 | 164.50 ms | 7.12 ms | 13.29 ms | 271.29 ms |
| 128/16，C=8 | RDMA P/D，multi-rail | 8/8 | 1.78 | 61486 ms | 521.54 ms | 1042.65 ms | - |
| 128/16，C=8 | TCP P/D | 8/8 | 3.44 | 29212.21 ms | 655.13 ms | 1114.56 ms | 37078.84 ms |
| 128/16，C=8 | Combined TP=8，复跑 | 8/8 | 283.04 | 323.50 ms | 8.49 ms | 16.60 ms | 441.44 ms |
| 4096/128，C=4 | Combined TP=8，复跑 | 4/4 | 329.36 | 555.85 ms | 7.85 ms | 15.76 ms | 1544.05 ms |

C=1 与 C=8 的 Combined 输出吞吐分别约为异常 RDMA P/D 的 43 倍和 159 倍，TPOT 则从约 0.52～0.54 秒恢复到 7～9 毫秒。由此可以排除同一镜像中的 DeepSeek V4 核心推理、模型权重、Marlin 和单机 TP=8 是主要根因；问题已经收敛到 P/D 特有的数据路径或 Decode mode。

TCP 对照保留相同的两个 Engine、模型、TP=8 和请求集，只把 `UCX_TLS` 从 `rc` 改为 `tcp,cuda_copy,cuda_ipc`。TCP 虽然缩短了一部分 TTFT，但 TPOT 仍为约 0.54～0.66 秒，和 RDMA P/D 处于同一异常数量级；Decode Engine 自身暴露的 ITL 指标也集中在 0.4～1 秒，说明慢速发生在 Engine 内部，而不是 Router 向客户端流式返回的过程。至此可以排除 RDMA/RoCE、multi-rail 和 GDR 是主要根因。

代码检查还排除了一个容易误判的参数：`disaggregation_decode_polling_interval=1` 表示 Scheduler Loop 间隔，不是每个 Token 等待 1 秒。Decode mode 在未启用 Radix Cache 时会强制使用 Chunk Cache，而 DeepSeek V4 的 Hybrid SWA 又不兼容 `disaggregation-decode-enable-radix-cache`，因此不能靠打开该开关规避。

当前最强的根因候选是 **DeepSeek V4 P/D 的执行拓扑与社区验证路径不一致**。本次组合是每侧纯 TP=8、Marlin FP4 Experts、未启用 DP Attention 和 DeepEP；SGLang 上游为 DeepSeek V4 增加的 P/D CI 则使用每侧 TP=4、DP=4、`--enable-dp-attention` 和 `--moe-a2a-backend deepep`。这还不能证明某一行 Kernel 存在缺陷，但已经把下一轮测试收敛为执行拓扑 A/B，而不是继续更换 RDMA 参数。参考：[SGLang DeepSeek V4 P/D CI PR #24973](https://github.com/sgl-project/sglang/pull/24973)、[SGLang P/D Disaggregation 文档](https://github.com/sgl-project/sglang/blob/main/docs/advanced_features/pd_disaggregation.md)。

随后对镜像做了源码级核验。镜像内 `sglang` 版本为 `0.0.0.dev1+g52afe87a0`，对应上游提交 `52afe87a08c6aa049c52f9507b4f0ca26cecb562`。SGLang 曾在 [PR #31901](https://github.com/sgl-project/sglang/pull/31901) 修复 DeepSeek V4 的 HiSparse P/D page-index 错配：旧路径把 Host KV Page ID 同时用于 Host 与 Device 目标，可能直接造成错误输出。当前镜像比该修复的合并提交多 271 个提交，因此不能再把本轮问题归因于“镜像缺少 #31901”。

但“包含已知修复”也不等于当前组合已经经过社区验证。0731 官方配方中，H200 的已验证低延迟路径使用 TP=4；没有 H20、每侧纯 TP=8、Marlin FP4 Experts 的 P/D 实测单元。上游仍有开放的 [issue #33397](https://github.com/sgl-project/sglang/issues/33397)，报告 0731 在 DSV4、FP8 KV 和批处理下出现随并发加重的输出损坏，复现拓扑还扩展到了非 P/D、无 DP Attention 等不同组合。这个 issue 与本轮“P/D Decode 每 Token 极慢”不是同一个已证明根因，却说明 0731 的 DSA/KV 路径仍在快速修复期。

因此当前结论是：**没有证据证明 SGLang 镜像版本过旧或权重损坏；有证据证明 H20 + 0731 FP4 + Marlin + 纯 TP=8 P/D 缺少上游验证，并存在相邻的准确率风险。** 下一步应优先复现社区的 TP=4/DP=4 + DP Attention + DeepEP 拓扑，或者先用官方已验证硬件/配方建立控制组；在此之前不把更换同系列镜像当成根因修复。

#### 13.5.2 8 GPU 为什么只有 4 个 RDMA NIC

实验节点的 Kubernetes RDMA Extended Resource 容量和可分配量都是 4，Pod 内能看到 `mlx5_bond_0` 到 `mlx5_bond_3` 四个设备，每个端口均报告 200 Gb/s。`nvidia-smi topo -m` 显示 NIC0/NIC1 位于 NUMA 0，覆盖前四张 GPU；NIC2/NIC3 位于 NUMA 1，覆盖后四张 GPU，其中各 NUMA 都有两张 GPU 到对应 NIC 为 `PIX`，其余同 NUMA GPU 为 `NODE`。8 张 GPU 之间则为 NVLink 互联。

因此 8 GPU Pod 申请 4 份 RDMA 资源符合机器的真实拓扑，并不要求 GPU 与 HCA 1:1。申请 8 反而会超过节点容量。单 rail 的链路理论值为 200 Gb/s，本次裸测约 195 Gb/s；四 rail 的理论链路聚合值约为 800 Gb/s，所以单口和四口的链路上限并不相同，但应用不会自动获得四倍速度。只有 UCX/NIXL 把足够大的并发数据正确条带化，并且 GPU Memory Registration、PCIe/NUMA 和完成同步都不成为瓶颈，才能接近聚合上限。小请求、单条串行传输或计算受限场景中，单口和四口的实测甚至可能接近。

后续 RDMA 测试应在 Pod 仍注入四个设备的条件下，先显式指定一个 `mlx5_bond_<N>:1` 测单 rail，再用 `UCX_NET_DEVICES=all` 测 multi-rail。这样才能区分“RDMA 相对 TCP 的收益”和“多 rail 相对单 rail 的收益”。

另外，之前 DeepSeek V4 的 vLLM P/D 基线并未使用 RDMA：两个 8-GPU Engine 都显式设置 `UCX_TLS=tcp,cuda_copy,cuda_ipc`，没有 RDMA CNI 注解，也没有申请 RDMA Extended Resource。每个 Engine 内部是单节点 TP=8，跨节点的只有 NIXL/UCX KV Transfer，因此准确表述应为 **NIXL over TCP**。后续 vLLM RDMA A/B 也必须保留这条 TCP 基线，不能把“使用 NIXL”直接等同于“使用 RDMA”。

### 13.6 用 HostPath 缓存大模型，避免每次重建都回源

RDMA 参数 A/B 需要多次重建 Engine。原清单把约 157 GiB 模型放在 `emptyDir`，Pod 删除后缓存也随之消失，每轮都要重新从对象存储同步两份模型，既慢又产生无意义的网络流量。两台隔离节点的本地 ext4 根盘各有约 935 GiB 可用空间，因此专项测试将模型卷改为节点级 HostPath：

```yaml
volumes:
  - name: model
    hostPath:
      path: /tmp/aik8s-model-cache/deepseek-v4-flash-0731
      type: DirectoryOrCreate
```

Init Container 不只判断目录是否存在，而是检查 `config.json`、权重索引、48 个 Safetensors 分片和完成标记。校验全部通过才直接退出；否则删除完成标记，继续增量同步，验证成功后再重新创建标记。这样下载中断不会把半成品误判成可用缓存，后续同节点重建又能在数秒内通过 Init。

切换卷模板时还遇到一个 RBG 生命周期细节：上层 `RoleInstanceSet` 已更新为 HostPath，但正在启动的旧 `RoleInstance` 仍保留 emptyDir 模板。此时只删除 Pod 会由旧 `RoleInstance` 按旧模板复建。实验中删除两个尚未 Ready 的 `RoleInstance`，由 `RoleInstanceSet` 按最新 revision 重新创建，才真正切换到 HostPath。

HostPath 在这里仅作为**可丢失的节点缓存**，不是持久化存储：Pod 必须回到同一节点才能命中，节点重装、磁盘故障或 `/tmp` 清理都会使缓存消失。生产环境应使用专用本地缓存盘和节点预热机制，并保留对象存储作为权威来源；如果模型需要跨节点共享或统一治理，仍应评估并行文件系统、镜像化分发或 P2P 模型分发。

### 13.7 冷启动期间究竟编译了什么

模型同步完成不等于 Engine 很快 Ready。本次 H20 启动日志在权重加载后显示 `DeepSeek V4 MHC prenorm prewarm: 16 n_splits buckets`，进程树中同时出现多组 `nvcc`。直接检查容器文件系统，可以把现场生成的产物分为三类：

| 产物 | 实测路径 | 内容 |
| --- | --- | --- |
| MHC/DeepGEMM Kernel | `/root/.cache/sglang/deep_gemm/cache/kernel.sm90_tf32_hc_prenorm_gemm.<hash>/kernel.cubin` | 针对 H20 `sm90` 和不同 `n_splits` bucket 生成的 CUDA Binary；本轮最终生成 16 个 CUBIN，目录约 688 KiB |
| SGL Kernel 通信扩展 | `/root/.cache/tvm-ffi/sgl_kernel_jit_communicator_<hash>__arch_9.0a__tvmffi_0.1.11/` | `main.cpp`、`cuda.cu` 经 Ninja/NVCC 编译出的 `sgl_kernel_jit_communicator_*.so` |
| CUDA IPC 与 Triton 辅助扩展 | `/root/.cache/tvm-ffi/sgl_kernel_jit_cuda_ipc_<hash>__arch_9.0a__tvmffi_0.1.11/*.so`、`/root/.cache/sglang/triton/<hash>/cuda_utils.cpython-312-x86_64-linux-gnu.so` | CUDA IPC、Triton Driver 等运行时扩展 |

FlashInfer 的缓存根目录在 `/root/.cache/sglang/.cache/flashinfer/<version>/<arch>/`。而 `/tmp/tmp*/tvm_kernels.cu`、`tmpxft_*`、LLVM bitcode 和预处理文件只是 NVCC 的中间产物，不应放入镜像。可以用下面的命令查看最终文件：

```bash
find /root/.cache/sglang /root/.cache/tvm-ffi \
  -type f \( -name '*.cubin' -o -name '*.so' -o -name 'build.ninja' \) \
  -ls
```

这些最终 `.cubin` 和 `.so` 很小，却可能花数分钟现场生成，因此预编译有价值。但它们不是通用二进制，至少绑定以下版本指纹：

本轮日志中 MHC prewarm 从 `19:36:47` 开始，16 个 CUBIN 生成完并进入 `Load weight end` 约为 `19:40:55`，这段约 **248 秒**；整个 `Load weight` 阶段约 **611 秒**。因此预编译预期能省掉其中约 4 分钟 JIT，而不能把 611 秒全部消除。

- GPU 架构，本次目录和文件名明确包含 `sm90`/`arch_9.0a`；
- SGLang、SGL Kernel、DeepGEMM 和具体 Kernel 源码；
- CUDA Toolkit/Driver、Torch、Triton、TVM-FFI 和 FlashInfer；
- Python ABI，本次辅助扩展为 CPython 3.12、x86_64。

推荐在同型号 H20 上用固定 Runtime 镜像和参数执行一次完整 warm-up，导出 `/root/.cache/sglang` 与 `/root/.cache/tvm-ffi`，再以完整版本指纹制作派生镜像。升级任一关键依赖后重新生成，不要跨 CUDA、Python 或 GPU 架构复用旧缓存。

还有一个容易忽略的挂载问题：本次 Pod 把 `/root/.cache` 挂成 `emptyDir`，如果直接把文件写入镜像的同一路径，运行时会被 Volume 完全遮住。可将预编译产物放在镜像的 `/opt/sglang-prebuilt-cache`，再由 Init Container 复制到可写的 `/root/.cache`；或者去掉该覆盖挂载。预编译只能省掉 JIT，权重读取与显存装载、部分 Marlin 权重重排、NIXL 初始化、warm-up 和 CUDA Graph capture 仍需在每个进程启动时执行。

参考：[腾讯云 TKE RDMA 网络使用说明](https://cloud.tencent.com/document/product/457/116720)、[OpenUCX 配置说明](https://openucx.readthedocs.io/en/master/faq.html)

公开清单仍使用不可访问的占位镜像和假 Secret，不包含内部 registry、对象存储、namespace、节点或凭据。

完整材料见：[DeepSeek V4 Flash：RBG + SGLang 双机 P/D 分离](https://github.com/runzhliu/aik8s/tree/main/examples/deepseek-v4-flash-sglang-rbg-pd)。

## 14. 同镜像、同模型下对比 RBG 与 AIBrix { #rbg-vs-aibrix-production }

这次最有价值的对比不是“谁的 YAML 更短”，而是谁拥有哪一层状态。Ray 与 P/D 都沿用相同 Runtime 后，得到下面的职责差异。

| 维度 | RBG 模式 | AIBrix 模式 | 实践判断 |
| --- | --- | --- | --- |
| 顶层对象 | `RoleBasedGroup` | Ray 用 `RayClusterFleet/RayCluster`；P/D 用 `StormService/RoleSet` | RBG 用一套通用 Role API；AIBrix 按场景提供专用对象 |
| Pod 所有权 | RBG → RoleInstanceSet → RoleInstance → Pod | Fleet → RayCluster → KubeRay Pod，或 StormService → RoleSet → Pod | 同一 Pod 只能选一个控制器拥有 |
| Ray Head/Worker | 本次需要自己写启动、等待 GPU 和 DNS 加入脚本 | KubeRay 原生表达 Head/Worker 和 Ray 状态 | 已经使用 KubeRay 时，AIBrix 路径更省胶水代码 |
| 多节点完整副本 | 可用 Role + Pattern 表达，扩容语义由清单设计 | RayClusterFleet 管理多份 RayCluster | 两者都能做；必须确认扩的是 Worker 还是完整 Engine |
| P/D Pod 编排 | Prefill/Decode 是普通 Role，可组合其他 Runtime | StormService/RoleSet 原生表达 Prefill/Decode | RBG 更中立，StormService 与 AIBrix 生态更紧密 |
| P/D 请求配对 | RBG 不处理请求，需要 AIBrix/SGLang/Dynamo Router | AIBrix Gateway 原生按 Role 选路并注入 KV 参数 | 只部署 RBG CRD 不会自动获得 P/D |
| 模型感知路由 | 无内置 Gateway；通过 Pod 标签接入外部路由 | Gateway、模型发现和路由策略属于同一平台 | 现有 AIBrix 用户继续走 AIBrix 最自然 |
| 服务发现 | 每 Role 一个稳定 Headless Service，并注入 RBG 拓扑变量 | KubeRay Head Service、Storm/RoleSet 标签和 Endpoint | RBG 对通用多角色 Peer 发现更统一 |
| 角色级伸缩 | ScalingAdapter 暴露 Scale 子资源，可接 HPA/KEDA | PodAutoscaler 可按 Role 与模型指标伸缩 | RBG 更通用；AIBrix 更懂推理指标和 P/D 语义 |
| 更新与恢复 | Role 级策略、依赖、稳定身份和协调策略 | Storm 顺序/原地更新，KubeRay/Fleet 各有恢复语义 | 需要做节点故障与请求排空实测，不能只看 CRD 字段 |
| Gateway 组合 | 天然可接 Higress；需要模型路由时再接 AIBrix 等 | 常见为 Higress → AIBrix Gateway → Runtime | 企业入口和模型路由仍应分层 |
| Runtime 倾向 | SGLang、Dynamo、Mooncake、vLLM 等多种 Runtime | 当前生产链路以 vLLM、AIBrix Gateway 为中心 | Runtime 中立是 RBG 的主要选型理由 |
| 成熟度风险 | 当前发布仍为 alpha，API 和运维经验较新 | 组件更多但已有完整路由、伸缩和实测链路 | 生产默认保留成熟路径，RBG 从旁路模型开始 |

### 14.1 对当前企业环境的建议

如果企业已经用 AIBrix `RayClusterFleet` 跑多机 vLLM，并用 `StormService` 跑 P/D，**不要只为统一 CRD 就迁移到 RBG**。现有路径已经把 KubeRay、P/D Router、模型发现和自动伸缩串起来，迁移会把一部分内置语义重新变成启动脚本和标签约定。

RBG 更适合从这些场景切入：

- 同一平台要同时承载 SGLang、Dynamo、Mooncake、vLLM 和自研 Runtime；
- 一个服务除 P/D 外还有 Router、KV Store、Metadata、Tokenizer 等多角色；
- 需要稳定身份、角色依赖、协调更新或完整副本级生命周期；
- 希望工作负载控制器与 AIBrix Gateway 解耦，允许将来替换路由层。

`AIBrix Gateway + RBG Pod` 已在本次功能实验中跑通，但它目前是一种**基于标签契约的组合**，不是 AIBrix 控制器原生管理 RBG。生产化还应补模型注册延迟、Pod 滚动期间 Endpoint 一致性、标签契约回归和双控制器升级矩阵。

### 14.2 不要混淆两种“多机多卡”

| 模式 | 两张 GPU 在做什么 | 扩容单位 |
| --- | --- | --- |
| Ray PP=2 | 两个 Rank 共同执行一个模型 Engine | 一整套 Head + Worker |
| P/D 分离 | 两个完整 Engine 分别处理 Prefill 和 Decode，再传 KV | Prefill Pool 与 Decode Pool 可分别扩 |

RBG 与 AIBrix 都只是把这些 Runtime 放到 Kubernetes。选择哪种 CRD 不会改变 PP 与 P/D 的计算本质，也不会自动让某种模式吞吐更高。

## 15. 生产实测暴露的缺口

- Ray Worker 节点首次拉取大镜像使整组 Ready 明显变慢，应建设镜像预热、P2P 分发或节点缓存；
- vLLM/c10d 对 Pod FQDN 做地址族探测时出现 IPv6 不可用告警，虽然本次回退 IPv4 成功，生产仍应固定 `GLOO_SOCKET_IFNAME`、`NCCL_SOCKET_IFNAME` 并验证多网卡；
- 当前 Ray 镜像缺少部分 `ray[default]` Dashboard 依赖，不影响推理，但会损失一部分 Ray 指标和页面能力；
- P/D 样例为了兼容 AIBrix 路由打开了 vLLM Development Endpoint，不能直接暴露到不可信网络；
- RBG Headless Service 本次主要用于 DNS，Gateway Endpoint 来自 Pod 标签；需要明确哪个系统负责端口发现和 Ready 过滤；
- 没有测试 Worker/Prefill/Decode 节点故障、网络分区、滚动升级、请求取消和流式响应中断；
- 没有进行同流量、同并发的 TTFT、TPOT、吞吐、Goodput 和成本对比，因此不能从“请求成功”推导性能优劣；
- 没有验证 `leaderWorkerPattern`、Gang Scheduling、ScalingAdapter 指标闭环和 Scale-to-Zero；
- 没有让 Higress 接管新样例入口，现有外部访问链路未修改。

## 16. 生产验收清单

- [x] RBG 版本固定，Chart、Controller 镜像和 Kubernetes 版本已记录；
- [x] Controller 使用两个副本并分散到不同节点；
- [x] Controller、CRD、Webhook 和证书注入正常；
- [x] 角色启动依赖、Headless Service、拓扑变量和 CPU Mock 已验证；
- [x] Decode Role 完成 2→3→2 独立扩缩，并验证字段所有权保护；
- [x] Prefill Pod 删除后恢复，RBG 回到 Ready；
- [x] 单卡真实模型和 OpenAI-Compatible API 已验证；
- [x] Ray 两节点、2 GPU、PP=2 与真实请求已验证；
- [x] Prefill/Decode 跨节点、NIXL KV Transfer 与 Gateway 请求已验证；
- [x] RBG 与 AIBrix 对照使用相同镜像、模型和关键 Runtime 参数；
- [ ] 多节点 Gang、GPU/NIC 拓扑和完整 Engine 故障恢复已验证；
- [ ] HPA/KEDA 指标、预热、排空和防抖已验证；
- [ ] 流式响应、取消、超时、节点故障和网络抖动已验证；
- [ ] 升级、回滚、CRD 转换、备份与灾难恢复已验证；
- [ ] Higress/AIBrix/RBG/Runtime 的路由、伸缩、重试和故障职责只有一个权威来源。

## 延伸阅读

- [RBG Installation](https://github.com/sgl-project/rbg/blob/v0.8.0-alpha.3/doc/install.md)
- [RBG Deploy Inference Service](https://github.com/sgl-project/rbg/blob/v0.8.0-alpha.3/doc/best-practice/zh/01-deploy-inference-service.md)
- [AIBrix 既有集群实战](aibrix-existing-cluster.md)
- [AIBrix 真实 GPU：两机、P/D 与八节点碎片卡](aibrix-gpu-multinode-pd-production.md)
- [Higress AI Gateway 实战](../inference/higress-ai-gateway.md)
- [多机与分离式 LLM 推理](../inference/distributed-serving.md)
