---
title: "Karmada and Virtual Kubelet: Architecture, Scheduling, and Production Selection"
description: "Compare Karmada multi-cluster orchestration with Virtual Kubelet virtual nodes, starting from application object ownership; analyze replicas, capacity, networking, storage, failure recovery, and GPU scenarios, with configuration examples and observability methods"
status: evolving
last_reviewed: 2026-09-09
---

# Karmada and Virtual Kubelet: Architecture, Scheduling, and Production Selection

When building a multi-cluster platform, two common requirements are: publishing the same application to multiple regions, and letting existing clusters use external compute resources. Both involve cross-cluster or cross-cloud operations, but the controlled objects, scheduling processes, and failure boundaries differ.

**Karmada manages the placement and distribution of applications across multiple Kubernetes clusters; Virtual Kubelet (VK for short) provides a framework for building virtual node agents that connect external execution backends into Kubernetes' Node/Pod model.** The core decision for the former is "which clusters each run how many replicas"; the core adaptation for the latter is "how Pods scheduled to this virtual node are created, observed, and deleted externally." [Karmada Concepts](https://karmada.io/docs/core-concepts/concepts/), [Virtual Kubelet Architecture](https://virtual-kubelet.io/docs/architecture/)

When comparing, three levels should be distinguished: **the Karmada project, the VK core library, and specific Providers or complete products built on VK**. For example, Liqo also provides resource negotiation, networking, and storage mechanisms beyond virtual nodes; these capabilities cannot all be attributed to the VK core library. Nor can the limitations of one cloud Provider be generalized to all VK implementations.

This article is based on the Karmada **v1.18 official documentation**, VK project documentation, and named Provider documentation at the time of verification. The architecture diagrams and configurations are teaching examples; the production selection section is an engineering analysis based on these mechanisms and **does not include measured performance rankings of the two approaches**. Before installation, you still need to verify the actual version, feature flags, and the Provider's support matrix.

## 1. Placing Both in the Correct Management Layer

<picture>
  <source media="(max-width: 600px)" srcset="/assets/cluster/karmada-vs-virtual-kubelet/architecture-mobile.svg">
  <img src="/assets/cluster/karmada-vs-virtual-kubelet/architecture.svg" alt="Karmada's cluster-level orchestration and Virtual Kubelet's node-level adaptation">
</picture>

| Comparison Item | Karmada | Virtual Kubelet Core and Providers |
| --- | --- | --- |
| Primary abstraction | Member clusters, resource templates, propagation policies, resource bindings | Virtual Node, Pods assigned to that node, external execution instances |
| Typical input | Resources such as Deployments, plus PropagationPolicy, OverridePolicy | Pods produced by normal Kubernetes workloads, plus node selection and Provider configuration |
| Scheduling unit | Placement of resources and their replicas among member clusters | Upstream scheduler first binds Pods to the virtual node; the backend may perform another scheduling pass |
| Where the Deployment controller usually runs | Each member cluster reconciles the received Deployment independently | Upstream cluster reconciles the Deployment; the Provider usually handles the Pods it produces |
| Execution backend | Kubernetes member clusters | Container cloud APIs, remote Kubernetes, other supported execution systems |
| Whether member cluster governance boundaries are preserved | Explicitly preserved; member clusters continue to have their own control planes and schedulers | Depends on the backend; upstream sees nodes, the remote side may still be an independent cluster |
| How external resources are presented | Cluster and aggregated status; member nodes are not directly turned into a single set of Nodes | Nodes registered by the Provider, which can represent a group of external resources |
| Networking and storage | Must be combined with member cluster infrastructure and cross-cluster solutions | Must be implemented by the Provider/product with semantic mapping; support varies |
| Main integration work | Placement policies, dependencies, differential configuration, interpreters, health and status aggregation | Pod lifecycle, capacity, status, networking, volumes, identity, and debugging interface adaptation |
| Common operational costs | Federation control plane, member onboarding, distribution scale, policies, and multi-cluster failure management | Provider process, external APIs, dual-side object consistency, and feature compatibility |

This table reflects responsibility boundaries and does not imply that a VK-based solution is necessarily lightweight. A VK product that needs complete networking, storage, quota, and disaster recovery capabilities may be more complex than a Karmada deployment that only does resource distribution. For the main mechanisms, see [Karmada Components](https://karmada.io/docs/core-concepts/components/) and [VK project description](https://github.com/virtual-kubelet/virtual-kubelet).

### 1.1 Why VK Is Easier to Understand

If the requirement is "let an existing cluster borrow remote compute capacity," VK's entry point is indeed more intuitive: business continues to submit Deployments, the local cluster creates Pods, the scheduler places Pods on the virtual node, and the Provider handles remote execution. Business users can continue to use familiar Node, Pod, label, and taint concepts.

Karmada has more decisions to express: which clusters to publish to, how total replicas are allocated, what configuration different regions use, and whether to migrate on failure. It decomposes these decisions into separate objects, which increases learning and troubleshooting costs. The five types of objects below help understand the most common control chain; among them, **Cluster is an aggregated API resource, not a CRD**. [Karmada Components](https://karmada.io/docs/core-concepts/components/)

| Object | One-sentence understanding | Usually maintained by |
| --- | --- | --- |
| Cluster | Which member clusters are available for selection | Platform onboarding process and cluster management components |
| PropagationPolicy | Where this application goes and how many replicas each location gets | Platform templates or application delivery configuration |
| OverridePolicy | Which configurations need to differ after reaching different clusters | Platform or application team when differential requirements exist |
| ResourceBinding | Which clusters the scheduling result selected | Generated by controllers and updated by the scheduling chain; inspect during troubleshooting |
| Work | The resource content delivered to a specific member cluster | Generated by controllers; inspect distribution and feedback status during troubleshooting |

This does not require business users to hand-write five types of objects. The platform can generate policies through a publishing form and hide internal objects such as ResourceBinding and Work. But operations staff still need to trace failures along "template → policy → binding → distribution → member workload"; this complexity cannot be eliminated by UI encapsulation alone.

VK's clarity is mainly at the business entry point. Remote quota, resource fragmentation, networking, storage, identity, status synchronization, and deletion failures still need to be handled by the Provider or the complete product. The VK core reuses Node/Pod, but that does not mean all VK products avoid introducing CRDs; for example, Liqo's resource negotiation and offloading mechanisms include additional custom resources. [VK Architecture](https://virtual-kubelet.io/docs/architecture/), [Liqo Offloading](https://docs.liqo.io/en/latest/features/offloading.html)

Therefore, when selecting a solution, complexity should be evaluated separately as business learning cost, platform implementation cost, and failure handling cost. **When only remote execution is needed, prioritize evaluating VK Providers that meet compatibility requirements; when explicit management of multi-region placement, replicas, and differential policies is needed, then evaluate the benefits of Karmada.** This is an engineering recommendation based on responsibility boundaries; "managing hundreds of clusters" alone is not sufficient to decide which approach to adopt.

## 2. The Same Deployment Actually Goes Through Two Different Paths

### 2.1 Karmada: First Select Clusters, Then Member Clusters Create Pods

Using a Web service with a total of 6 replicas as an example, the typical flow is:

1. The user submits the Deployment resource template and propagation policy to the Karmada API Server.
2. Controllers establish a ResourceBinding for the matched resource; the scheduler selects member clusters based on the policy and assigns replica counts.
3. The distribution chain generates Work and writes the override-processed resources to the target member clusters.
4. The member cluster's Deployment/ReplicaSet controller creates Pods; the member cluster's scheduler then selects specific nodes.
5. Member status is reported back, and Karmada aggregates status based on resource type and interpreter rules.

In a typical configuration, the Deployment in the Karmada API is a resource template; the Deployment controller in the federation control plane does not directly create execution Pods. Actual execution happens in member clusters. [Karmada Architecture](https://karmada.io/docs/core-concepts/architecture/), [Karmada Components](https://karmada.io/docs/core-concepts/components/)

This also explains why "template submitted successfully," "resource distributed successfully," and "member Pod Ready" are three different states. The platform cannot treat the first two states as the application being available.

### 2.2 VK: First Produce Pods, Then Hand Execution to the Provider

The typical VK path is:

1. The user submits a Deployment to a normal Kubernetes API Server.
2. The local cluster's Deployment/ReplicaSet controller creates Pods.
3. kube-scheduler binds some Pods to the virtual node based on Node capacity, labels, taints, and other information.
4. VK/Provider handles the lifecycle of these Pods, creates corresponding instances on the external backend, and reports status back.
5. If the backend is also Kubernetes, the remote side usually needs to select physical nodes for the corresponding Pods; if it is a container cloud, instance creation is handled by the cloud service.

VK provides lifecycle and node agent related interfaces; how the specific backend implements logging, exec, metrics, configuration passing, and other capabilities needs to be checked against the Provider. You cannot infer from "kubectl can see the Pod" that all native kubelet behaviors are implemented. [VK Providers](https://virtual-kubelet.io/docs/providers/)

For example, Liqo uses a mapping between local Pods and remote objects, and supports remote reconciliation through mechanisms such as ShadowPod; this is Liqo's specific implementation, and other Providers do not necessarily replicate this design. [Liqo Offloading](https://docs.liqo.io/en/latest/features/offloading.html)

## 3. Replica Semantics: 6 Globally, or 6 Per Cluster

Karmada's `Duplicated` and `Divided` produce different resource bills:

| Template and Policy | Illustrative result when both clusters are selected | Semantics the platform needs to explain |
| --- | --- | --- |
| `replicas: 6` + `Duplicated` | A has 6, B has 6, total 12 | Each target cluster gets the full replica count |
| `replicas: 6` + `Divided` + weight 2:1 | A has 4, B has 2, total 6 | Total replicas are distributed among selected clusters |
| Normal Deployment of 6, some Pods scheduled to VK | Upstream expected total remains 6 | Pods are assigned to different nodes; the Deployment is not duplicated into two copies |

The first two rows assume clusters meet the selection conditions, scheduling and distribution complete, and no other controller changes the replica count. `clusterNames` defines candidate clusters; the actual number selected should also consider propagation policy constraints. Do not infer replica placement just because two names are listed. [Karmada Propagation Policy](https://karmada.io/docs/userguide/scheduling/propagation-policy/)

In the VK approach, the upstream Pod and the remote Pod may be two objects representing the same execution. When counting business instances and costs, their identities should be correlated to avoid double counting; similarly, duplicate backend instances that temporarily appear after retries cannot be masked by ordinary Ready counts.

## 4. Scheduling and Capacity: Total Capacity Is Sufficient, but an Individual Task May Still Not Fit

<picture>
  <source media="(max-width: 600px)" srcset="/assets/cluster/karmada-vs-virtual-kubelet/capacity-mobile.svg">
  <img src="/assets/cluster/karmada-vs-virtual-kubelet/capacity.svg" alt="Two-stage placement, resource fragmentation, and real executable capacity">
</picture>

### 4.1 Karmada's Two-Stage Scheduling

Karmada handles cluster-level placement; the member scheduler handles node-level placement. To avoid looking only at total cluster resources while ignoring node fragmentation, Karmada provides components such as scheduler-estimator to estimate how many replicas of a specific requirement can be scheduled in a member cluster. [Karmada Components](https://karmada.io/docs/core-concepts/components/)

But there is still a time gap between estimation and final binding. The platform must also consider the member cluster's local tasks, queue admission, image reachability, PVC topology, and scheduling plugin constraints. A successful cluster-level placement does not promise reserved GPUs, nor does it automatically replace Gang scheduling for training jobs.

### 4.2 VK's Capacity Is the View the Provider Commits to the Upstream

The `capacity` / `allocatable` of a VK node can represent external quotas or negotiated resource slices, not necessarily corresponding to a physical machine. Liqo, for example, maps negotiated resources to virtual nodes and manages resource usage in conjunction with remote quotas. [Liqo Resources Sharing and Reservation](https://docs.liqo.io/en/latest/usage/resource-reservation.html)

Therefore, four questions need to be answered: Is the capacity real-time available quantity or a quota ceiling? How often is it updated? How is backend rejection reported? Is there a reservation or admission mechanism between resource requests and backend creation? Without these constraints, only numbers in the API, "upstream scheduled but backend queued forever" can occur.

### 4.3 GPU Scenarios Especially Cannot Only Compare Card Counts

Suppose two external machines each have 4 GPUs remaining, and a Pod needs 8 GPUs on the same machine. Aggregating them as the virtual node's `8 GPU` may make the upstream think resources are sufficient, but no executable single-machine layout exists on the backend. This example illustrates the risk of abstraction losing topology; not all Providers report this way.

For AI platforms, capacity descriptions should at least include card type, GPU memory, available cards per machine, NUMA/PCIe/NVLink layout, RDMA domain, host memory, and local model cache. Physical topology and device allocation must be verified by the final execution layer; they cannot be solved by adding `nvidia.com/gpu` numbers to the virtual node. See [GPU Topology and Resource Fragmentation](../practices/gpu-topology-fragmentation-scheduling.md).

## 5. Configuration, CRDs, and Controller Ownership

### 5.1 Karmada Is Closer to "Distributing Application Objects"

Karmada can propagate Kubernetes resources and custom resources, but "can distribute CRs" and "understands CRs" are two different levels. For Ray, Flink, or training jobs, custom resource interpreters may be needed to explain how to extract replicas and resource requirements, aggregate status, determine health, preserve member fields, and resolve dependencies. The relevant CRDs and the Operators responsible for execution also need to be available in target clusters. [Customizing Resource Interpreter](https://karmada.io/docs/userguide/globalview/customizing-resource-interpreter/)

Differential configuration can be expressed through OverridePolicy, such as clusters using different image registry addresses or StorageClasses. Dependency propagation can be implemented through policies and interpreters; it does not automatically discover all objects in an application directory, and propagating PVC declarations does not mean the data in the volumes has been synchronized. [Override Policy](https://karmada.io/docs/userguide/scheduling/override-policy/), [Propagate Dependencies](https://karmada.io/docs/userguide/scheduling/propagate-dependencies/)

### 5.2 VK Is Closer to "Adapting Pod Execution"

The VK core does not automatically provide cross-cluster semantics for arbitrary Operators. For example, if an Operator is kept upstream while the Pods it produces are placed on a virtual node, you still need to confirm whether the Operator depends on local Nodes, PVCs, Pod IPs, exec, ServiceAccounts, or specific node agents.

Provider handling of auxiliary resources such as Secrets, ConfigMaps, and Services must also be checked item by item. Liqo's resource reflection provides synchronization capability for these resources, which is the part that a complete solution adds beyond Pod execution. [Liqo Offloading](https://docs.liqo.io/en/latest/features/offloading.html)

### 5.3 Each field must have exactly one clearly designated write owner

The following are production design recommendations, not product default configurations:

| Resource or field | Recommended designated owner | Conflicts to avoid |
| --- | --- | --- |
| Application image, configuration version | GitOps or release platform | Manual changes, GitOps, and propagation controllers overwriting each other in a loop |
| Cross-cluster placement and replica allocation | Karmada policies and the selected scaling system | Member HPA and federation controllers contending to write replicas |
| Upstream Deployment replicas | Upstream HPA or release platform | Provider creating a second, separate set of business replica controllers on its own |
| Remote execution instances | Selected Provider or member Operator | The same job being submitted twice, once via Karmada and once via VK |
| Data recovery location and primary write authority | Application recovery protocol and storage system | Both sides believing they are the primary instance |

Karmada provides mechanisms such as Retain for preserving specific member fields, but these still need to be configured according to the workload and scaling approach; it cannot be assumed that all replica controllers will negotiate automatically by default. [Resource Interpreter: Retain](https://karmada.io/docs/userguide/globalview/customizing-resource-interpreter/)

### 5.4 How many CRDs does Karmada actually have

This article performs a fixed check against the **Karmada v1.18.0** source manifest list, using the actual YAML's `kind: CustomResourceDefinition` with deduplication counting on `metadata.name`. The result is: **19 in the main installation manifest, plus 1 in the optional Operator; 20 definitions in total across both parts.** The 19 in the main manifest include **17 CRDs from Karmada API groups, plus 2 multi-cluster service standard CRDs from `multicluster.x-k8s.io`**. [Main installation manifest](https://github.com/karmada-io/karmada/blob/v1.18.0/charts/karmada/_crds/kustomization.yaml), [Operator CRD](https://github.com/karmada-io/karmada/blob/v1.18.0/operator/config/crds/operator.karmada.io_karmadas.yaml)

| Scope of count | Count | Meaning |
| --- | ---: | --- |
| `*.karmada.io` in the main manifest | 17 | Policies, bindings, propagation, interpreters, and extension features |
| `multicluster.x-k8s.io` in the main manifest | 2 | ServiceExport, ServiceImport |
| Main manifest total | **19** | Definitions in `charts/karmada/_crds/bases/` |
| Optional Operator | **1** | Karmada definition in `operator/config/crds/` |
| Union of definitions in both parts | **20** | Does not mean an API Server necessarily installs 20 |

Installation locations must also be distinguished: for example, Helm's host installation mode applies the main manifest to the **Karmada API Server** through an initialization Job; the Operator's CRDs are used on the host Kubernetes where the Operator is installed. Connecting to the host cluster and running `kubectl get crd` cannot be used to assert how many CRDs the federation control plane has. [Installation Job source](https://github.com/karmada-io/karmada/blob/v1.18.0/charts/karmada/templates/karmada-static-resource-job.yaml)

The following is the complete list of 19 items in the main manifest. In the scope column, "cluster-scoped" means the resource does not belong to a namespace within that API Server; it does not mean a new CRD is added for each member cluster joined. The purpose column is a functional summary; actual enablement also requires the corresponding controllers and configuration.

| # | Kind | API group | Scope | Purpose |
| --- | --- | --- | --- | --- |
| 1 | WorkloadRebalancer | apps.karmada.io | Cluster-scoped | Triggers rescheduling for selected workloads |
| 2 | CronFederatedHPA | autoscaling.karmada.io | Namespace-scoped | Adjusts federation scaling targets on a time schedule |
| 3 | FederatedHPA | autoscaling.karmada.io | Namespace-scoped | Performs federation-level horizontal scaling based on metrics |
| 4 | ResourceInterpreterCustomization | config.karmada.io | Cluster-scoped | Declares resource interpretation rules, such as replica extraction and status aggregation |
| 5 | ResourceInterpreterWebhookConfiguration | config.karmada.io | Cluster-scoped | Configures external resource interpreter webhooks |
| 6 | ServiceExport | multicluster.x-k8s.io | Namespace-scoped | Declares a service exported to the multi-cluster scope |
| 7 | ServiceImport | multicluster.x-k8s.io | Namespace-scoped | Represents imported multi-cluster service information |
| 8 | MultiClusterIngress | networking.karmada.io | Namespace-scoped | Describes ingress routing for multi-cluster services |
| 9 | MultiClusterService | networking.karmada.io | Namespace-scoped | Describes the service abstraction across member clusters |
| 10 | ClusterOverridePolicy | policy.karmada.io | Cluster-scoped | Configures cluster-level resource difference override policies |
| 11 | ClusterPropagationPolicy | policy.karmada.io | Cluster-scoped | Configures cluster-level resource propagation policies |
| 12 | ClusterTaintPolicy | policy.karmada.io | Cluster-scoped | Manages member cluster taints based on conditions |
| 13 | FederatedResourceQuota | policy.karmada.io | Namespace-scoped | Manages resource quotas for federated namespaces |
| 14 | OverridePolicy | policy.karmada.io | Namespace-scoped | Configures difference overrides for resources within a namespace |
| 15 | PropagationPolicy | policy.karmada.io | Namespace-scoped | Configures placement and propagation of resources within a namespace |
| 16 | Remedy | remedy.karmada.io | Cluster-scoped | Triggers management actions based on cluster conditions, such as TrafficControl |
| 17 | ClusterResourceBinding | work.karmada.io | Cluster-scoped | Stores target clusters and scheduling results for cluster-scoped resources |
| 18 | ResourceBinding | work.karmada.io | Namespace-scoped | Stores target clusters and scheduling results for namespace-scoped resources |
| 19 | Work | work.karmada.io | Namespace-scoped | Carries resources sent to member clusters and execution feedback |

Names, scopes, and API versions all come from the [CRD definitions directory](https://github.com/karmada-io/karmada/tree/v1.18.0/charts/karmada/_crds/bases) for this version. The conditions and actions of Remedy can be verified against the [API type definitions](https://github.com/karmada-io/karmada/blob/v1.18.0/pkg/apis/remedy/v1alpha1/remedy_types.go). The optional 20th item is **Karmada**, API group `operator.karmada.io`, namespace-scoped, used to declare Karmada control plane instances managed by the Operator.

There are four easily confused points when counting:

- **API resources are not the same as CRDs.** Cluster is provided by an aggregated API Server; Deployment, Pod, and Node are native resources and are not counted in the table above. The row count of `kubectl api-resources` cannot be used in place of the CRD count.
- **Multiple versions still count as one CRD.** In this version, both ResourceBinding and ClusterResourceBinding provide `v1alpha1` and `v1alpha2`, each counting as 1. The remaining manifest items provide `v1alpha1`.
- **Installed definitions do not equal enabled features.** The existence of the FederatedHPA or MultiClusterIngress CRD does not mean scaling and cross-cluster ingress have already been configured.
- **The number of definitions does not equal the number of objects or the amount of learning required.** One Work CRD can correspond to many Work instances; ordinary releases often only require touching workloads, propagation policies, and override policies as needed. Scaling, service governance, and interpreters can be introduced on demand.

The complete machine-readable list includes the resource name, version, and source link for each item, and can be downloaded as the [v1.18.0 CRD verification results](../../assets/cluster/karmada-vs-virtual-kubelet/crd-inventory-v1.18.0.json). The repository provides `scripts/inventory_karmada_crds.py`, which reads a specified version via the GitHub CLI and parses the YAML without accessing or modifying a Kubernetes cluster; it can be re-verified in an environment with `gh` and PyYAML installed:

```bash
python3 scripts/inventory_karmada_crds.py --ref v1.18.0 --output /tmp/karmada-crds.json
```

To verify an existing installation, first confirm that kubeconfig points to the Karmada API Server, then run the following read-only command; the example context name must be replaced with the actual name. The output includes other CRDs installed in that control plane and should be compared against the list above to identify missing or extra items, rather than assuming the result must be 19.

```bash
kubectl --context karmada-apiserver get crd \
  -o custom-columns='NAME:.metadata.name,KIND:.spec.names.kind,GROUP:.spec.group,SCOPE:.spec.scope'
```

**The CRD count can indicate the API surface that needs to be maintained, but it cannot by itself serve as a scoring criterion for technology selection.** A more valuable test is: whether the business must understand these objects, and whether, when "resources have been propagated but Pods are not ready," the platform can reduce the internal chain to a clear root cause. VK should also be verified as a complete Provider product for extension objects and operational costs; the interface count of the core library alone cannot be used for comparison.

## 6. Compatibility of networking, service discovery, and storage

| Capability | Karmada needs checking | VK approach needs checking |
| --- | --- | --- |
| Pod network | Internal network of each member cluster; cross-cluster links designed separately | Whether the backend IP is reachable, and whether a proxy or address mapping is needed |
| Service / DNS | Service propagation does not automatically generate a unified traffic entry point | How upstream Endpoints/EndpointSlice reflect external instances |
| Traffic switching | How global load balancing, DNS, or gateways perceive member health | Whether virtual Pod Ready matches the backend's actual ability to accept traffic |
| NetworkPolicy | Whether the target CNI supports it, and whether the rule scope is consistent | Whether the Provider can implement the corresponding isolation semantics |
| PVC / StorageClass | Storage type, topology, and data recovery in each cluster | Whether the volume type is supported, and how binding and mounting are mapped |
| hostPath / local NVMe | Data exists only on specific nodes; migration requires considering model and data re-preparation | A virtual node name does not mean an accessible host directory with the same name exists |
| exec / logs / metrics | Member access path, identity, and collection pipeline | The Provider's interface implementation, connection forwarding, and metrics coverage |

**Resource object replication and data replication should be designed separately.** Two clusters creating PVCs with the same name does not mean they read the same data; the upstream showing the same Pod IP also does not mean the network path and identity semantics are consistent. These are conditions that must be verified when reviewing an architecture.

Provider differences can be significant: Microsoft AKS virtual nodes documentation lists limitations on PVC/PV, DaemonSet, networking, and more; Liqo has a separate Network Fabric and Storage Fabric. The former's limitations cannot be used to prove that the VK framework generally does not support storage, and the latter's capabilities cannot be considered automatically available after installing the VK core library. [AKS Virtual Nodes](https://learn.microsoft.com/en-us/azure/aks/virtual-nodes), [Liqo Network Fabric](https://docs.liqo.io/en/latest/features/network-fabric.html), [Liqo Storage Fabric](https://docs.liqo.io/en/latest/features/storage-fabric.html)

## 7. Failure recovery: unreachability, process stoppage, and primary write authority are three separate things

### 7.1 Karmada's failure migration

Karmada provides cluster-level and application-level failure migration mechanisms, but the enablement conditions differ. At the time of verification, the v1.18 documentation still marks the cluster `Failover` feature as Beta and disabled by default; application-level migration also involves health interpretation, dependency propagation, and corresponding configuration. A technology selection evaluation should specify the concrete feature rather than broadly stating "automatic disaster recovery supported by default." [Cluster Failover](https://karmada.io/docs/userguide/failover/cluster-failover/), [Application-level Failover](https://karmada.io/docs/userguide/failover/application-failover/)

When the Karmada management control plane is briefly unavailable, applications already propagated to member clusters are usually still maintained by the member's local controllers; new cross-cluster scheduling, propagation, and status aggregation will be affected. Whether the application can continue to provide service also depends on whether it relies on centralized gateways, storage, or other shared components. This is a failure analysis derived from the layered control architecture; "local Pods are still alive" cannot be taken as a guarantee of full business continuity.

### 7.2 VK's failure recovery depends on the implementation

Provider process exit, external API unreachability, and actual backend compute failures should be tested separately. If the Provider process stops, the backend containers may still be running; upstream Node status changes and Pod eviction also do not prove that external instances have been deleted. Different implementations handle reconnection, recreation, and cleanup differently.

For example, Liqo documentation describes node health checks and the remote ShadowPod maintenance mechanism. Its recovery behavior is built on these components and cannot be summarized with the single phrase "VK simulates a kubelet." [Liqo Offloading](https://docs.liqo.io/en/latest/features/offloading.html)

### 7.3 Both approaches must verify duplicate execution under network partition

Imagine the management side cannot connect to cluster A, but A's business can still access the database. At this point, starting a replacement instance in B may cause the same task to execute twice or two primary instances to write simultaneously. There may also be a time gap between deletion requests, object disappearance, and actual process termination.

Therefore, stateful systems need their own leases, fencing (revoking the old instance's write eligibility), idempotency keys, checkpoints, and recovery procedures. PDB controls the budget for supported voluntary disruptions; it cannot serve as a cross-cluster primary write authority protocol, nor can it prevent all involuntary disruptions. [Kubernetes Disruptions](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/)

Karmada's state preservation mechanism can extract and pass through some recovery-related fields, but the `StatefulFailoverInjection` in the documentation is still Alpha and disabled by default. It does not transfer process memory, GPU HBM, or NCCL communication state. For training, the accurate statement is "recover from a checkpoint after the job is re-placed." [Karmada Cluster Failover: State Preservation](https://karmada.io/docs/userguide/failover/cluster-failover/)

## 8. How elasticity and performance should be compared

Karmada can adjust global replicas in combination with mechanisms such as FederatedHPA, then distribute them to member clusters through placement policies. In the VK approach, upstream controllers such as HPA typically generate more Pods, and the Provider then requests execution resources from the backend; whether CPU/memory metrics can participate in HPA depends on whether the metrics pipeline is complete. [Karmada FederatedHPA](https://karmada.io/docs/userguide/autoscaling/federatedhpa/), [VK Providers](https://virtual-kubelet.io/docs/providers/)

Neither approach can conclude "faster scaling" from an architecture diagram alone. It is recommended to uniformly measure the following timestamps:

```text
负载上升 → 产生扩容决策 → 目标集群/虚拟节点确定
        → 后端接受创建 → 资源获得准入 → 容器启动
        → 应用 Ready → 第一条真实请求成功
```

The startup latency used for comparison should cover the entire chain, with per-stage breakdowns retained. Even if the VK backend skips the step of creating a new VM, it may still be affected by quotas, image pulls, and model loading; Karmada choosing another existing cluster also does not mean that GPUs ready for immediate execution are reserved there.

A fair comparison should at least fix the same image, resources, storage, region, input load, and cache conditions, and separately report cold start, warm start, and no-available-capacity results. For inference, it should also report TTFT, TPOT, full-stream success rate, and achieved throughput; for training, it should report whole-job time-to-placement, effective training throughput, and checkpoint recovery time. This document does not give millisecond-level performance differences for solutions that have not been actually measured.

## 9. Security and Multi-Tenancy: How Many Boundaries Does One Authorization Cross

Karmada's Push mode has the control plane access members; Pull mode synchronizes desired state and status through a member-side agent. The direction in which the connection is initiated changes network and credential management, but it cannot replace identity authentication, RBAC, and auditing. [Karmada Components](https://karmada.io/docs/core-concepts/components/)

VK, on the other hand, requires checking the upstream node identity, the Provider's resource read permissions, and the backend cloud account or remote cluster identity. The VK documentation imposes constraints on data access through the Provider interface; this cannot be used to infer that the entire node agent process requires no Kubernetes API permissions at all. In actual deployment, authorization should be split by component and interface.

The following engineering constraints apply to both solutions:

- Clarify which tenant can send which data and Secrets to which backend, avoiding broad selectors or automatic reflection that expands the data scope.
- Correlate the upstream object UID, target cluster, backend instance ID, and operator to support cross-end auditing and deletion verification.
- Verify whether upstream admission policies remain effective on the remote side; a Namespace or ServiceAccount with the same name does not represent the same identity.
- Perform separate authorization and fault testing for logs, exec, and metrics forwarding, to avoid gaps where "the business API has permission isolation but the debugging interface does not."
- Make tenant quotas cover both upstream admission and actual backend resources; the capacity reported by virtual nodes must not be treated as a billing or isolation mechanism.

## 10. Two Configuration Examples: See Where the Policy Goes

The following only demonstrates resource semantics and was not executed in this document. `cluster-a`, `cluster-b`, image domains, and node labels are all example values. You must first complete Karmada member registration or the selected Provider's installation, network, and permission configuration, then replace these values. Commands explicitly specify the context to avoid writing federation templates into ordinary business clusters.

### 10.1 Karmada: 6 Replicas Distributed at 2:1

```yaml title="karmada-demo.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: demo-http
  namespace: platform-demo
spec:
  replicas: 6
  selector:
    matchLabels:
      app: demo-http
  template:
    metadata:
      labels:
        app: demo-http
    spec:
      containers:
        - name: http
          image: registry.example.com/platform/demo-http:1.0
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
            limits:
              cpu: "1"
              memory: 512Mi
          readinessProbe:
            httpGet:
              path: /ready
              port: 8080
---
apiVersion: policy.karmada.io/v1alpha1
kind: PropagationPolicy
metadata:
  name: demo-http-placement
  namespace: platform-demo
spec:
  resourceSelectors:
    - apiVersion: apps/v1
      kind: Deployment
      name: demo-http
  placement:
    clusterAffinity:
      clusterNames: [cluster-a, cluster-b]
    spreadConstraints:
      - spreadByField: cluster
        minGroups: 2
        maxGroups: 2
    replicaScheduling:
      replicaSchedulingType: Divided
      replicaDivisionPreference: Weighted
      weightPreference:
        staticWeightList:
          - targetCluster:
              clusterNames: [cluster-a]
            weight: 2
          - targetCluster:
              clusterNames: [cluster-b]
            weight: 1
```

```bash
# 先确认联邦及成员侧 Namespace 已按平台规则准备好。
kubectl --context karmada-apiserver apply -f karmada-demo.yaml
kubectl --context karmada-apiserver -n platform-demo get resourcebindings
kubectl --context cluster-a -n platform-demo get deployment,pods
kubectl --context cluster-b -n platform-demo get deployment,pods
```

When both candidate clusters satisfy the conditions and distribution completes, the expectation is to see 4 replicas in A and 2 replicas in B. You should also verify each member's Ready count; checking only the ResourceBinding is not sufficient. Static weights are used here to demonstrate replica distribution; this does not provide real-time capacity reservation, nor does it specify a complete policy for re-placement under failure conditions. Field references: [Propagation Policy](https://karmada.io/docs/userguide/scheduling/propagation-policy/).

### 10.2 VK: Accepting Pods from an Ordinary Deployment Through a Virtual Node

The labels and taints below are **platform-defined examples**, not installation conventions common to all VK Providers. Assume the virtual node managed by the Provider already carries the `platform.example.com/execution=external` label and the corresponding `NoSchedule` taint; these should be set according to the Provider's node configuration method, to avoid manually entered values being overwritten by automatic reconciliation.

```yaml title="vk-demo.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: external-http
  namespace: platform-demo
spec:
  replicas: 6
  selector:
    matchLabels:
      app: external-http
  template:
    metadata:
      labels:
        app: external-http
    spec:
      nodeSelector:
        platform.example.com/execution: external
      tolerations:
        - key: platform.example.com/execution
          operator: Equal
          value: external
          effect: NoSchedule
      containers:
        - name: http
          image: registry.example.com/platform/demo-http:1.0
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
            limits:
              cpu: "1"
              memory: 512Mi
          readinessProbe:
            httpGet:
              path: /ready
              port: 8080
```

```bash
kubectl --context workload-cluster apply -f vk-demo.yaml
kubectl --context workload-cluster get nodes \
  -l platform.example.com/execution=external
kubectl --context workload-cluster -n platform-demo get pods -o wide
```

You also need to confirm from the Provider or backend that 6 instances are actually created and reachable, and that the `/ready` probe semantics are supported. `tolerations` only allows a Pod to tolerate a taint; it does not guarantee the Pod will be scheduled to that node. The example also uses `nodeSelector` to restrict the target. Do not use `nodeName` to bypass normal scheduling and then treat the result as successful capacity scheduling. [Kubernetes Taints and Tolerations](https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/)

## 11. Prometheus / Grafana: How to See That the Difference Actually Takes Effect

Observability should be designed around two closed loops: **whether declarative objects have completed execution, and whether real requests benefit**. The following dashboard content is a recommendation, not an indication that every project ships metrics with the same names out of the box.

| Dashboard | Karmada Focus | VK / Provider Focus |
| --- | --- | --- |
| Global desired vs. actual | Template replicas, per-cluster distribution, member Ready, aggregated status update time | Upstream Pods, backend instances, status mapping update time, orphaned instances |
| Placement and admission | Scheduling wait, unplaceable reasons, distribution latency, member admission failures | Virtual Node allocatable, upstream bound but backend-not-admitted Pods |
| Control loop | Work queue, reconciliation errors, API rate limiting and retries | Provider call latency, backend 429/5xx, reconnects and retries |
| Capacity and cost | Cluster available resources, resource fragmentation, regional replicas and cost | Reported quota, backend actual available capacity, billed but upstream-invisible instances |
| Failure recovery | Anomaly detection, migration decisions, target Ready, traffic switchover | Node status, backend liveness, instance recreation, old instance cleanup |
| Application experience | End-to-end success rate and latency, split by member cluster | End-to-end success rate and latency, split by execution backend |

If every member has kube-state-metrics and attaches a unique `cluster` label at collection or remote-write time, you can start with the following query to observe member-side available replicas:

```promql
sum by (cluster) (
  kube_deployment_status_replicas_available{
    namespace="platform-demo", deployment="demo-http"
  }
)
```

This query assumes the data source contains only the member instances to be compared and that duplicate collection from Prometheus HA replicas has been handled. `cluster` is not a label present by default in all installations; without the label, mixed data cannot be treated as a cross-cluster comparison. For VK, kube-state-metrics usually only sees upstream declarations and reported status; you also need to integrate Provider or backend evidence.

It is recommended to record key timestamps by the same request ID or business execution ID. Aggregate charts show P50/P95/P99 and failure counts, while raw records retain the full trace. Object UIDs and backend instance IDs are better placed in logs or tracing than turned into long-term Prometheus labels.

## 12. Scenario Selection for GPU Platforms

The following recommendations are based on execution boundaries, not measured product rankings:

| Business Requirement | Priority Evaluation Direction | What to Verify Before Choosing |
| --- | --- | --- |
| Unified release and differentiated configuration for multi-region inference services | Karmada | Cluster capacity, model distribution, member Ready, cross-region traffic entry |
| Existing cluster temporarily borrowing external CPU container resources | VK Provider with the corresponding capability | Quota, network, image credentials, volumes, logging, and reclaim billing |
| Existing cluster transparently borrowing another Kubernetes resource set | Liqo and other full VK solutions | Resource negotiation, backend admission, network/storage, identity mapping |
| Training jobs selecting an entire group across multiple GPU clusters | Appropriate Karmada policy, or job-level multi-cluster scheduling solution | CRD interpretation, whole-Job admission, gang scheduling, data and checkpoints |
| One NCCL job stitching scattered GPUs across regions | Re-evaluate the execution domain first | Neither solution eliminates network latency, bandwidth, and topology constraints |
| Multi-tenant Notebooks and temporary development containers | Depends on "multi-region deployment" vs. "external execution" | Persistent directories, interactive connections, GPU devices, hibernation and recovery |
| Cluster installation, upgrades, and control plane repair | Dedicated cluster lifecycle tools | Neither Karmada nor VK has this as a core responsibility |

For tightly coupled training, the architecture that is easier to verify is usually "select the job placement across clusters, and complete whole-group GPU admission and communication within the cluster." For independent inference replicas, regional placement and request routing can be separated: Karmada decides which clusters the service appears in, the in-member inference platform decides local replicas and traffic; VK can provide an additional execution backend within verified members.

For broader multi-cluster training selection, see [Cross-Cluster and Large-Scale GPU](multi-cluster-ai.md); for node-level issues, see [GPU and Heterogeneous Resource Scheduling](../gpu-scheduling.md).

## 13. The Two Can Be Combined, but the Number of Control Loops Must Be Limited

One combination is: Karmada places a regional application into a member cluster, and that member then uses external resources through a VK Provider. In this case, there are three decisions that can affect the outcome: the federation selecting the member, the member selecting the virtual node, and the backend selecting the actual execution resource.

Before combining, clarify:

1. Whether the external capacity has already been counted by another member or the federation resource view, to avoid the same resource being promised twice.
2. Whether cluster failover migration and virtual node eviction could simultaneously create replacement instances for the same workload.
3. What object the global HPA, member HPA, and backend scaling each adjust, and who owns the final replica count.
4. Whether status latency will be amplified layer by layer; where queuing occurs, and who ends the timeout.
5. Whether the deletion chain for federation objects, member Pods, and backend instances can close, and whether duplicate creation occurs after recovery.

If the requirement is only unified release of manifests, first compare whether simple GitOps is sufficient; if the requirement is only stable local execution, an ordinary node pool should also be the baseline. Adding abstraction layers should have clear business benefit and verifiable boundaries.

## 14. How to Do Convincing Validation Before Go-Live

The following is a recommended acceptance scope, not tests executed in this document. Fault injection should be performed in an isolated environment, and retention policies for observability data and business data should be designed separately.

| Validation Item | Operation and Evidence | Pass Criteria Should Include |
| --- | --- | --- |
| Normal creation and scaling | Same image and replica count, correlating objects on each side | Backend instance count, Ready, real requests matching expectations |
| Insufficient capacity | Exceed backend quota or simulate node resource fragmentation | Cause is visible, no infinite retries, no hidden duplicate billing |
| Control path interruption | Block the management path, keep the business data path | Can distinguish unknown state from actual stoppage, avoid split-brain |
| Agent/controller restart | Restart the dedicated control component and recover | Correctly takes over existing instances, no duplicate creation or lost cleanup responsibility |
| Deletion and cancellation | Cancel queued, creating, and running items separately | Both upstream objects and backend execution terminate, cost stops growing |
| Storage and configuration updates | Update Secrets, write persistent data, migrate | Version consistency, permission boundaries, and data recovery are verifiable |
| Rolling release | Update while long connections and long-running tasks continue | Interruption rate, drain time, and rollback path meet business budgets |
| GPU jobs | Multi-card placement, device access, and communication verification | Whole group placed, topology matches expectations, throughput reaches baseline |
| Version upgrade | Specified version combination and Provider support matrix | Can roll back, existing objects and status mappings are not lost |

When managing hundreds of clusters, turn the above validations into a version admission and staged rollout process rather than a one-time demo. The platform needs to be able to explain "why there is an extra instance here, why there was no migration this time, why the node has quota but tasks are still queued," and provide evidence tracing from global objects to the real execution backend. Related experience can be found in [Stability Engineering for Hundreds of Kubernetes Clusters](../practices/kubernetes-fleet-reliability.md).
