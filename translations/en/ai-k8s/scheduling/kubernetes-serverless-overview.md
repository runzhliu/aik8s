---
title: "Kubernetes Serverless Overview: From Autoscaling to On-Demand Execution"
description: An overview of serverless services, events, functions, jobs, GPU inference and agent sandboxes on Kubernetes, including cold starts, reliability and adoption paths
status: evolving
last_reviewed: 2026-11-16
---

# Kubernetes Serverless Overview: From Autoscaling to On-Demand Execution

An internal API may be called only a few times per day, a data-cleaning task may receive a batch of messages every hour, and an agent may need a temporary environment for untrusted code. Their duration and resource requirements differ, but they share a goal: **start when needed, release resources after use, and avoid making users manage instances by hand.**

Serverless is a way to deliver applications and consume resources. Servers, Kubernetes nodes and storage still exist, but the platform offers a service, function or task interface and manages instance lifecycles, elasticity, routing and governance. This article maps the main Kubernetes implementation paths and establishes a framework for later hands-on comparisons; its architectures and examples are proposals, not claims of a completed deployment or test in a particular cluster.

## Conclusions at a glance

1. **Serverless is broader than functions or setting a Pod count to zero.** Request-driven container services, event-triggered jobs and function platforms can all be serverless; a complete platform also needs entry points, reliability, security, observability and resource governance.
2. **Knative Serving suits request-driven services.** It organizes services around HTTP requests, revisions and routing, with on-demand scaling; a zero-replica service needs an entry point to receive requests and trigger activation.
3. **KEDA connects existing workloads to event-driven autoscaling.** A `ScaledObject` scales supported workloads and a `ScaledJob` creates Jobs from event metrics; message and processing semantics remain the responsibility of the queue and application.
4. **Scale-to-zero has costs as well as benefits.** A first request waits for scheduling, image pulls and application initialization; warm capacity lowers latency while continuously using resources.
5. **Scaling Pods to zero does not automatically scale nodes or bills to zero.** Fixed physical clusters primarily gain capacity sharing; direct node-cost savings require infrastructure and billing that allow nodes to be reclaimed.
6. **Agent sandboxes and serverless systems have different responsibilities.** A sandbox provides an isolated execution environment; the platform handles requests, queues, identity, quotas and lifecycle. Together they can provide on-demand execution.
7. **GPU scale-to-zero depends on the workload.** Weight loading, GPU memory initialization and resource queues can be slow, so latency-sensitive or continuously busy services often need warm instances.

## 1. How serverless relates to Kubernetes

Kubernetes supplies primitives including Pods, Deployments, Jobs, Services, scheduling and HPA, but application teams often still manage images, instance configuration, endpoints and scaling policies. A serverless platform combines these primitives at a higher level: developers provide a function, image or job definition, and the platform creates and manages execution instances in response to requests, events or policies.

![Serverless platform responsibilities](../../assets/images/serverless-overview/platform.svg)

The control plane in the figure represents responsibilities a platform must compose; it does not claim that any single open-source project implements all of them. Identity, storage, capacity and failure handling still need design whether or not users see the underlying Pods.

### 1.1 CaaS, FaaS and serverless containers

| Form | What users provide | What the platform primarily manages | Examples |
| --- | --- | --- | --- |
| CaaS / ordinary container platform | Image and workload configuration | Container scheduling, networking and execution | Deployment, Job |
| Serverless containers | Container image that handles requests | Request entry, revisions, instances and scaling | Knative Serving |
| FaaS | Function code or package | Function runtime, triggers and execution environments | Fission, OpenFaaS |
| Event-driven jobs | Job image, event source and processing logic | Event-based scaling or job creation | KEDA, Kubernetes Job |

These categories overlap: a function may ultimately run in a container or Pod. Delivery and isolation boundaries depend on the implementation.

### 1.2 What scale-to-zero achieves

Stopping idle workload replicas releases schedulable resources such as CPU, memory and GPU capacity. Shared clusters can offer that capacity to other work; further infrastructure savings are possible only when the environment can also reclaim nodes and its billing charges for them.[Kubernetes node autoscaling](https://kubernetes.io/docs/concepts/cluster-administration/node-autoscaling/)

The control plane, message queues, storage, monitoring and warm instances often remain running. Include these recurring costs, request wait time and operations when evaluating benefits.

## 2. From zero to one: how a request wakes a service

A normal Service forwards requests to ready backends; with zero backends it does not itself reliably retain requests and create an instance. An HTTP-triggered system needs an available entry point to observe requests, trigger scaling and wait for a ready backend within bounded time and capacity.

![Waking an HTTP service from zero replicas](../../assets/images/serverless-overview/request-flow.svg)

Waiting is not unlimited: clients, ingress and platform entry points can all time out, and a burst can exceed buffering capacity. Knative's Activator receives and buffers requests at zero replicas and in some traffic scenarios; the actual path depends on configuration and load.[Knative request flow](https://knative.dev/v1.21-docs/serving/request-flow/)

At minimum, break **cold-start time** into activation and queueing, scheduling and resource wait, image pulls, container startup, application initialization, readiness checks, and weight loading where a model is involved. Comparisons should state whether images were cached, whether nodes already existed, concurrency and timing boundaries; numbers collected under different conditions are not directly comparable.

## 3. Main open-source options

| Option | Main capability | Good starting point | Additional considerations |
| --- | --- | --- | --- |
| Knative Serving | Request-driven container services, revisions, routing and scaling | Low-frequency HTTP APIs, webhooks, internal tools | Gateway and network choice, timeouts, cold starts |
| Knative Eventing | Event ingress, filtering and routing to subscribers | Event flows with multiple producers and consumers | Broker implementation, durability, retries and delivery semantics |
| KEDA | Scale workloads or create Jobs from external metrics | Queue consumers, batch processing, existing Deployments | Event-source reliability, processing logic and metric design |
| Fission | Function development, triggers and execution on Kubernetes | Delivering functions as the unit of deployment | Warm-pool resources, runtimes, isolation and maintenance |
| OpenFaaS | Function entry, packaging and execution platform | Adopting a function platform and its tools | Check licenses and features per edition, especially scale-to-zero |
| KServe | Model deployment and inference services | Model lifecycle and inference interfaces | Model cache, GPU cold starts and deployment mode |
| CubeSandbox with a control plane | Isolated execution environments and lifecycle | Agent code execution and controlled tests | Entry, queues, quotas and task reliability need additional design |

First decide whether the deliverable is an existing container service, a queue consumer, function code or an isolated execution task. These projects have different scopes and can also be combined.

### 3.1 Knative Serving and Eventing

Knative Serving combines revisions, routing and request-driven scaling for containerized services that need an endpoint and revision management.[Knative Serving](https://knative.dev/docs/serving/)

Knative Eventing organizes event ingestion and delivery using objects such as Brokers and Triggers. Consumers can be Knative services or other event receivers. Persistence and retries depend on the Broker implementation and configuration; Eventing alone does not guarantee that events cannot be lost. The project explicitly warns against using the default InMemoryChannel directly in production.[Knative Eventing](https://knative.dev/docs/eventing/); [Broker configuration](https://knative.dev/docs/eventing/brokers/create-broker/)

### 3.2 KEDA: event-driven autoscaling

KEDA reads metrics from queues, databases and other supported event sources. For a `ScaledObject`, KEDA handles transitions between zero and one and cooperates with HPA for higher replica counts; for a `ScaledJob`, it creates Kubernetes Jobs based on event metrics, suited to independent work that runs to completion.[KEDA architecture](https://keda.sh/docs/2.21/concepts/); [ScaledJob](https://keda.sh/docs/2.21/concepts/scaling-jobs/)

KEDA is not a message queue and does not automatically give an application exactly-once processing. Retries, message acknowledgments and failure destinations must be designed with the queue and consumer. For HTTP, evaluate the separate [KEDA HTTP Add-on](https://keda.sh/http-add-on/0.16/) and review the APIs and migration guidance for the chosen version.

### 3.3 Fission and OpenFaaS

Fission uses functions as deployment units and offers different execution strategies. PoolManager, for example, maintains generic warm Pods and specializes them for a function; dedicated Deployments and prebuilt containers are alternatives. Prewarming shortens part of the startup path, but reserved capacity is not free.[Fission executors](https://fission.io/docs/architecture/executor/)

OpenFaaS also focuses on functions and triggers, but features differ across distributions and licenses. Use the current official comparison to check Kubernetes deployment, commercial use, scale-to-zero, queues and support rather than assuming paid features are available in a community edition.[OpenFaaS edition comparison](https://docs.openfaas.com/openfaas-pro/comparison/)

### 3.4 Kubernetes native HPA

HPA adjusts replicas based on metrics. CPU and memory metrics come from running Pods, so they cannot by themselves determine when a zero-replica workload should wake up.

Kubernetes 1.37 made HPA scale-to-zero with Object or External metrics Beta and enabled it by default. It still requires a working external or object metric and compatible control-plane versions and configuration. HTTP request buffering also needs a separate entry layer. Older clusters differ in version and feature-gate behavior and must be checked before adoption.[Kubernetes 1.37 HPA scale-to-zero](https://kubernetes.io/blog/2026/09/02/kubernetes-v1-37-hpa-scale-to-zero-beta/)

## 4. Three representative workflows

### 4.1 Low-frequency HTTP service

Package an internal query API or webhook as a container and expose it through Knative. Try scaling to zero when idle, waking on the first request and scaling out as traffic grows. This suits services that are invoked infrequently and can tolerate the initial wait; latency-sensitive services can retain minimum replicas or warm capacity.

Acceptance checks should cover first-request success, cold and warm latency, scaling speed, timeouts and concurrency limits. Control-plane and entry-point failures should be tested separately.

### 4.2 Message-driven data cleaning

A producer puts a data location and task ID on a durable queue. KEDA scales Workers or creates Jobs based on queue metrics. A Worker reads the data, writes results to durable storage and acknowledges the message according to the business protocol.

Define idempotency keys for duplicate delivery, retry limits, dead letters, recovery after interruption, execution timeouts and result-commit order. An empty queue does not necessarily mean all running tasks have finished; scale-down rules must account for in-flight work.

### 4.3 On-demand sandbox execution for agents

DSH, OpenClaw and other agents can request a policy-constrained execution environment through an Adapter, run code, read results and release the sandbox. CubeSandbox supplies the sandbox environment, while the Adapter handles access concerns such as identity and policy; queues, resource quotas and product-level metering still need configuration or additional components.[CubeSandbox Agent Adapter practice](../rag-agent/cubesandbox-agent-adapter-v07.md)

A sandbox's lifecycle may differ from those of the agent session, job and durable result. Define timeouts, cancellation, lease renewal, abnormal cleanup and result storage separately; for long-running tasks, verify the runtime's actual recovery and snapshot capabilities before designing resumption.

## 5. Why GPU and model inference are harder

A GPU workload may wait for node capacity, drivers and devices, model weight downloads, loading into GPU memory and inference warmup in addition to Pod readiness. As models grow, cold starts and cache management can dominate the cost.

| Scenario | Priority | What to verify |
| --- | --- | --- |
| Non-real-time GPU batch work | Queues, quotas and release after completion | Queue wait, checkpoint recovery, duplicate execution |
| Low-frequency small-model inference | Scale-to-zero or a few warm instances | First-request latency, weight cache, capacity limits |
| High-frequency or low-latency large-model inference | Resident warm instances and load-based scaling | GPU memory, throughput, latency and scaling stability |

KServe can manage inference services with multiple deployment modes. Its documentation recommends Knative serverless mode primarily for predictive inference; generative inference needs a separate evaluation of standard Kubernetes deployment in light of GPUs, long requests and runtime behavior.[KServe serverless mode](https://kserve.github.io/website/docs/admin-guide/serverless)

## 6. What production adoption needs

- **Reliability**: define request timeouts, retries, idempotency, message durability, dead letters, cancellation and graceful shutdown; handle replica termination during execution.
- **Security**: integrate authentication and authorization, separate tenants, restrict service accounts, images, network egress and mounts, and choose an appropriate boundary for untrusted code.
- **Resource governance**: set per-tenant limits for concurrency, CPU, memory, GPUs, queue depth and execution time so bursts do not starve critical workloads.
- **Observability**: correlate request IDs, task IDs and execution instances; record queue wait, cold-start stages, execution duration, failures, consumption and cleanup status.
- **Data and cost**: persist state, results and audit records appropriately; include control-plane, warm capacity, queueing and fragmentation when comparing always-on and on-demand modes.

For private-network clusters, also check access to image registries, ingress, DNS, certificates, object storage and queues, and verify the chosen versions against the existing Kubernetes release.

## 7. Recommended hands-on path

1. **Knative HTTP service**: record wake-from-zero, idle scale-down, bursts and revision routing; distinguish cached and uncached images.
2. **KEDA queues and Jobs**: record backlog, scaling, completion and failure retries; test duplicate delivery and interrupted work.
3. **Adapter and CubeSandbox**: verify natural-language triggering, isolated execution, result return and lease cleanup, then test timeouts and failures.
4. **GPU jobs and inference**: where capacity permits, compare warm instances, scale-to-zero and prewarming; measure queueing, weight loading, first request and resource use.

For each run, record component versions, cluster capacity, image-cache state, concurrency, sample count, successes and failures, P50/P95/P99 latency and stage durations. Establish a baseline in a test cluster before drawing production conclusions.

## Further reading

- [AI workload autoscaling](autoscaling.md)
- [Agent sandbox selection and architecture](../rag-agent/agent-sandbox-selection.md)
- [CubeSandbox Agent Adapter v0.7 practice](../rag-agent/cubesandbox-agent-adapter-v07.md)
- [Model artifacts, distribution and caching](../data/model-artifacts.md)
