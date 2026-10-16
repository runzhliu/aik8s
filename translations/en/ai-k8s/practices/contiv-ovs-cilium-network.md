---
title: "Contiv, OVS, and Cilium in a Serial-Chained Network: Why kube-proxy May Not Receive Packets"
description: "Explains VLAN networking, Service translation, and kube-proxy's data path boundaries based on CNI configuration, OVS ports and flow tables, Cilium runtime status, and actual packet captures from an anonymized test cluster"
status: validated
last_reviewed: 2026-10-10
---

# Contiv, OVS, and Cilium in a Serial-Chained Network: Why kube-proxy May Not Receive Packets

When troubleshooting Kubernetes networking, it is easy to treat "Pods can reach each other," "Services can be reached," and "kube-proxy is healthy" as the same thing. In a test environment that retains Contiv and Open vSwitch, these are handled by different mechanisms: Contiv creates the Pod network, OVS connects Pods to the physical VLAN, and Cilium is chained onto the existing network to provide capabilities such as Service translation.

**This inspection confirmed: the cluster uses Cilium's kube-proxy replacement, there are currently no kube-proxy Pods, and the sampled nodes have no kube-proxy process; DNS, the API Service, and cross-node application Services are all reachable.** Therefore, the current state should be described as "Service proxying is handled by Cilium." As for why kube-proxy could not be used directly in the past, further investigation is needed into the host network path it depends on.

OVS Layer 2 switching may cause Pod packets to go directly through the switch toward the network gateway, bypassing the netfilter rules in the host IP stack. As a result, even if the kube-proxy process is healthy and iptables rules have been written, Pod access to Services may still fail. This article explains this path using actual configuration and packet captures; no historical kube-proxy failure logs were obtained this time, and Cilium was not disabled to reproduce the fault, so this cannot be used to determine the root cause of any past startup failure.

This article uses an anonymized cluster as a case study. Cluster name, node names, IPs, MACs, VLANs, private plugin names, and internal paths have all been replaced; addresses in the diagrams are example values. The inspection used only existing workloads and read-only commands; no components were restarted, no routes were changed, and no flow tables were modified.

## 1. First, Separate the Responsibilities of the Network Layers

Think of the cluster network as a campus. Contiv assigns addresses to each room and runs the cabling; OVS is the switch inside the building; VLANs are mutually isolated network partitions; the network gateway handles communication between different partitions. A Service is like a fixed switchboard number—calling the switchboard requires someone to forward the request to a specific room.

kube-proxy typically performs this translation in the node's host network path. Cilium can also select the room in advance when the application establishes a Socket connection, or perform the translation at the packet processing location on the NIC. If packets take a different path directly through the switch, the "forwarding rules" on the host never see them.

| Name | Full Name or Meaning | Responsibility in This Environment |
| --- | --- | --- |
| CNI | Container Network Interface, container network interface specification | Defines how the container runtime invokes network plugins to create and delete network attachments |
| Contiv Netplugin | Container network implementation | Creates veths, allocates Pod addresses, configures gateways and OVS ports |
| IPAM | IP Address Management | Manages allocation and reclamation of network addresses; in this case, Pod addresses are provided by the upstream network |
| veth | Virtual Ethernet, virtual Ethernet device pair | One end serves as the Pod's `eth0`, the other end connects to OVS on the node |
| OVS | Open vSwitch, open virtual switch | Performs switching based on ports, VLANs, and forwarding tables |
| VLAN | Virtual Local Area Network | Isolates different Pod networks; a single physical uplink carries multiple VLANs |
| Cilium | eBPF-based network implementation | Recognizes existing veths, registers endpoints, enforces policy, and provides Service proxying |
| eBPF | extended Berkeley Packet Filter | Runs verified programs at designated locations in the kernel |
| TC | Traffic Control, traffic control subsystem | The location where Cilium attaches packet processing programs on interfaces such as veth |
| kube-proxy | Kubernetes Service proxy component | Maintains forwarding rules based on Services and EndpointSlices; replaced by Cilium in this case |

CNI is an interface specification, not "a proxy server." Network plugins are primarily executed at network creation and deletion time; business packets do not invoke CNI on every packet. The chaining order of CNI plugins also cannot be directly treated as the forwarding order for every packet. [CNI specification](https://www.cni.dev/docs/spec/)

![Division of responsibilities between CNI invocation and data forwarding](../../assets/practices/contiv-ovs-cilium-network/responsibilities.png)

## 2. What the Actual Deployment Looks Like

This test environment has 12 nodes; at inspection time, 11 nodes were Ready, and the Cilium DaemonSet was also 11/12 Ready. Detailed data path sampling covered three online nodes, and Service access plus packet capture was performed on one existing regular Pod.

| Item | Inspection Result | Interpretation |
| --- | --- | --- |
| Kubernetes | 1.30.4 | This article analyzes based on this runtime environment and does not apply default values from newer proxy modes |
| Container runtime | containerd 1.7.14 | CNI configuration directory is `/etc/cni/net.d`, `max_conf_num=1` |
| Kernel | 5.10-series custom build | eBPF capabilities still require actual probing and program attachment verification; cannot be inferred from version number alone |
| OVS | 2.14.0 | Nodes run `ovsdb-server` and `ovs-vswitchd` |
| Contiv | Custom netplugin build on nodes | Not deployed as a Kubernetes DaemonSet; package directory names cannot be directly treated as community versions |
| OVS mode | `normal` | Flow tables on the primary sampled nodes are `actions=NORMAL` |
| Cilium | 1.16.1, custom image | Runtime status shows `CNI Chaining: generic-veth` |
| kube-proxy replacement | `True` | Service translation is handled by Cilium |
| Socket LB | `Enabled`, coverage `Full` | TCP requests can select a backend before packets are emitted |
| Host routing | `Legacy` | Preserves the original host network path; BPF Host Routing is not enabled |
| IPv4 Masquerade | Disabled | The inspected cross-node requests retain the source Pod IP on the physical uplink |

Among these, DaemonSet 11/12 Ready is node and component availability information; it cannot replace connectivity verification for all business networks. The Service smoke test results in this article also only cover the paths actually inspected.

### 2.1 Contiv Having No Pods Does Not Mean It Is Not Running

Running only `kubectl get pods -n kube-system` shows Cilium but not Contiv or OVS. After entering the authorized node inspection environment, the `netplugin`, `ovsdb-server`, and `ovs-vswitchd` processes on the host can be seen.

In this type of environment, network components may be managed through OS packages, host services, or platform scripts. Troubleshooting requires checking Kubernetes resources, host processes, and actual port status simultaneously; focusing only on DaemonSets will miss the components that actually build the underlying network.

Contiv's network state storage also needs to be distinguished from Cilium's state storage. This time, netplugin was observed pointing to the network system's own etcd endpoint, while Cilium reported `KVStore: Disabled`, using Kubernetes resources to manage related state. The latter does not mean the entire network system does not use etcd.

The community Contiv Netplugin inherently includes multi-host, tenant network, and physical network integration capabilities; the discussion here is about the OVS path and should not be conflated with Contiv-VPP, which uses the VPP data plane. [Contiv Netplugin](https://github.com/contiv/netplugin)

## 3. How CNI Chaining Works: Connect to the Network First, Then Attach Cilium

The node's actual configuration contains three plugins, invoked in the following order:

```text
containerd 创建 Pod 网络命名空间
  → Contiv CNI：创建网卡、地址、网关和 OVS 端口
  → Cilium CNI：发现已有 veth，向 agent 注册端点
  → 自定义后置插件：执行环境相关的网络扩展
```

Only the structure is shown below. `custom-gateway-plugin` is an anonymized placeholder name, and the protocol version uses an example value from the community documentation; this is not an installable configuration, nor is it a complete copy of the original file.

```json
{
  "name": "generic-veth",
  "cniVersion": "0.3.1",
  "plugins": [
    { "type": "contivk8s.bin" },
    { "type": "cilium-cni" },
    { "type": "custom-gateway-plugin", "advmss": 1420 }
  ]
}
```

Cilium's `generic-veth` mode attaches to the veth created by the preceding plugin. Checking the 1.16.1 source code shows that it parses the previous plugin's result, enters the Pod network namespace to find the veth, addresses, and peer index, and then determines the host-side interface. It does not require the underlying network to use a Pod network allocated by Cilium itself. [Cilium 1.16.1 generic-veth implementation](https://github.com/cilium/cilium/blob/v1.16.1/plugins/cilium-cni/chaining/generic-veth/generic-veth.go)

The runtime configuration for this case also includes:

```yaml
cni-chaining-mode: generic-veth
custom-cni-conf: "true"
read-cni-conf: /tmp/cni-configuration/cni-config
write-cni-conf-when-ready: /host/etc/cni/net.d/05-cilium.conflist
routing-mode: native
enable-host-legacy-routing: "true"
enable-local-node-route: "false"
auto-direct-node-routes: "false"
enable-ipv4-masquerade: "false"
kube-proxy-replacement: "true"
```

Together, these items express one direction: preserve the existing network and routes, then layer Cilium's capabilities on top. They are not a generic deployment template applicable to all CNIs.

### 3.1 Seeing Multiple Configuration Files Does Not Mean Each One Executes

At inspection time, the node retained both the chained `05-cilium.conflist` configuration and the older Contiv single-plugin configuration. containerd has `max_conf_num=1` set. Therefore, the network configuration actually selected by the runtime and the network creation results must be verified; not every file in the directory should be treated as the active default network.

This time, the following results further confirmed that regular Pods entered the chained path: the Pod address, host veth, OVS port, and Cilium Endpoint could be correlated, and the veth also had `cil_from_container` and `cil_to_container` programs attached.

### 3.2 The Address Pool in the Configuration Is Not Necessarily the Business Pod Address Pool

Cilium's state contains its own router address and address pool, while regular Pods use addresses allocated from the upstream network. When calculating address capacity or determining address conflicts, the actual Pod IPs, Contiv network configuration, and Cilium's internal address usage must be examined separately. Deriving the CIDR for all Pods solely from `cluster-pool-ipv4-cidr` will produce an incorrect network topology.

### 3.3 Custom Chained Plugins Require Separate Verification

There is also a custom plugin with `advmss=1420`; its related initialization logic involves the IP-in-IP kernel module. It is an environment extension; this inspection confirmed the configuration and deployment entry point but did not verify all branch implementations, so community Contiv or Cilium behavior descriptions cannot be directly applied to it.

MSS is Maximum Segment Size, the maximum segment size for TCP. The presence of an MSS parameter in the configuration does not mean it applies to all connections; the SYN captured from the application connection in this inspection still advertised MSS 1460. Nor can the existence of `tunl0` on the node be used to conclude that regular Pod traffic uses IP-in-IP tunneling. The requests inspected in this article were sent over the physical uplink with VLAN tagging, and no IP-in-IP encapsulation was observed for these requests.

## 4. How OVS Connects Pods to the Physical Network

The OVS structure on the sampled nodes can be summarized as:

```text
Bridge br-pod                 # 原桥名已替换
  Port veth-a, tag=200         # Pod A 的宿主机端
  Port veth-b, tag=200         # 同 VLAN 的另一个 Pod
  Port veth-c, tag=201         # 另一 Pod 网络
  Port bond-uplink            # 物理上联
  Port br-pod, type=internal   # OVS 本机端口

table=0, priority=0, actions=NORMAL
```

Here, the physical uplink first uses Linux bonding to aggregate two NICs into a bond interface, which is then added as an interface to OVS. This is not "a two-port bond created directly inside OVS"; when troubleshooting link aggregation, hashing, and member port errors, the Linux bond status must be checked.

`NORMAL` indicates the normal switching pipeline entering OVS, which determines the output port based on port configuration, VLANs, and MAC learning in the OVSDB. It does not mean "handed off to the Linux host's ordinary Layer 3 routing," nor does it automatically translate Kubernetes Services to backends. [OVS NORMAL Pipeline](https://docs.openvswitch.org/en/latest/ref/ovs-actions.7/#the-ovs-normal-pipeline)

### 4.1 Same Node, Same VLAN

The source Pod sends packets from `eth0`, through the veth to OVS. If the destination MAC has already been learned on a local port in the same VLAN, OVS can deliver directly to the destination Pod's port. How unknown unicast and broadcast are handled is affected by normal switching behavior and port configuration.

This path does not need to go through the node's host Layer 3 routing, nor does it need to leave the physical uplink.

### 4.2 Cross-Node, Same VLAN

OVS sends the source Pod's Ethernet frame to the physical uplink carrying that VLAN; the switching network delivers it to the destination node, which then delivers it from the corresponding Pod port into the Pod. When the Pod port is an access port, the Pod generally sees Ethernet frames without VLAN tags; the uplink carries the corresponding VLAN tag.

In this case, the backbone is VLAN access to the physical network, and no VXLAN port for regular Pod forwarding was observed on the sampled bridge. VXLAN is Virtual Extensible LAN, a common network overlay encapsulation; Contiv supports this path, but that does not mean it is enabled in the current environment.

### 4.3 Different VLAN or Different Subnet

Based on its own routing table, the Pod sends traffic destined for non-local subnets to its default gateway. Represented with anonymized examples:

```text
Pod A：10.244.8.23/22
默认网关：10.244.8.1
Pod B：10.244.20.31/22

Pod A → veth → OVS → VLAN 200 上联
      → 网络网关路由 → 目标 VLAN → 目标节点 OVS → Pod B
```

In the packet captures from this inspection, the destination MAC of the uplink packet corresponded to the source Pod's default gateway, and the destination IP was already the backend Pod in another subnet. This is consistent with the path of "select the backend first, then route through the existing network gateway." The packet capture only covered the node side; the physical switch was not logged into to verify every intermediate hop.

### 4.4 The Management Network and Pod Network Are Not the Same Entry Point

The node's own management IP is on a management VLAN subinterface of the bond, while Pods connect through multiple VLAN ports on OVS. Kubernetes API access, the node's default route, the Pod's default route, and the device detected by Cilium cannot be drawn as a single interface.

Similarly, `ip link` showing `ovs-system` or some OVS internal interface as DOWN is not sufficient evidence that the entire OVS data plane is down. `ovs-vswitchd`, actual ports, flow tables, counters, and connectivity must also be checked; switching and the local IP protocol stack are two different things.

## 5. Why kube-proxy May Be "Running but Not Forwarding"

kube-proxy's iptables mode watches Services and EndpointSlices and maintains rules in the host's netfilter to translate Service virtual addresses to real backends. DNAT is Destination Network Address Translation; for the rules to take effect, packets must first pass through the processing location where the rules reside. [Kubernetes Service proxying mechanism](https://kubernetes.io/docs/reference/networking/virtual-ips/#iptables-proxy-mode)

A typical Pod request needs to pass through the relevant entry point of the host IP stack to have a chance of hitting the Service rules in `PREROUTING`; requests initiated locally on the host usually enter through `OUTPUT`.

After OVS system ports receive packets, they can perform Layer 2 switching directly. The official OVS FAQ explicitly explains: packets on such ports are taken over by OVS before the normal host packet filtering hooks; OVS internal ports interact with the host IP stack differently. [Relationship between OVS and iptables](https://docs.openvswitch.org/en/latest/faq/issues/)

![Comparison of OVS Layer 2 switching and host netfilter paths](../../assets/practices/contiv-ovs-cilium-network/netfilter-paths.png)

For a VLAN network like this case, if no other mechanism translates the Service in advance, the request may take this path:

```text
Pod 访问 Service VIP
  → 按默认路由发给网络网关的 MAC
  → 宿主机 veth 被 OVS 接管
  → OVS NORMAL 将报文送到 VLAN 上联
  → 物理网络网关收到目的 IP 为 Service VIP 的报文
```

If the gateway has no Service routing or translation capability, the request fails. Even if kube-proxy in the node has already generated `KUBE-SERVICES` and backend DNAT rules, it has no opportunity to process this packet. This is a compatibility risk derived from the current port and routing structure, not a fault result reproduced in this session.

### 5.1 Three Different Problems Must Be Distinguished

| Symptom | What to Check | Observed This Time |
| --- | --- | --- |
| kube-proxy fails to start, exits, or CrashLoops | Logs, configuration, permissions, kernel modules, API access | No: the component is not currently deployed, and no historical failure logs were obtained |
| kube-proxy generates rules normally, but Pod Service is unreachable | Whether packets pass through the host IP stack, rule counters, OVS ports and flow tables, return path | This risk exists in the data path; the existing proxy was not disabled to reproduce the fault |
| No kube-proxy, but Service works normally | Whether the CNI's Service implementation has taken over | Confirmed: Cilium KubeProxyReplacement is True, and actual requests succeed |

Therefore, it cannot be written as "Contiv causes the kube-proxy process to fail to start," nor as "all OVS networks cannot use kube-proxy." OVS internal ports, routing access, OpenFlow forwarding, and different Service implementations can all form different paths.

### 5.2 Switching to IPVS Does Not Automatically Change the Path

IPVS is IP Virtual Server, a Layer 4 load balancing implementation in the Linux kernel. kube-proxy's IPVS mode still requires packets to enter the corresponding host protocol stack and netfilter processing path. It can change backend selection and table lookup methods, but it cannot automatically make a packet that leaves directly through OVS switching enter the host IP stack. [Kubernetes IPVS proxy mechanism](https://kubernetes.io/docs/reference/networking/virtual-ips/#ipvs-proxy-mode)

### 5.3 `br_netfilter` Is Not a Universal Patch for OVS

Linux Bridge and OVS are different implementations. Just because the Linux Bridge scenario requires `bridge-nf-call-iptables` does not mean that loading `br_netfilter` can fill in all OVS Service paths. The specific system/internal ports and packet direction should be checked here; a sysctl cannot replace path analysis.

### 5.4 Host Can Access but Pod Cannot Is Not a Contradiction

Requests initiated from the host can pass through `OUTPUT`, while Pod packets may leave directly through the OVS uplink. During troubleshooting, at least use the host, a regular Pod, and an `hostNetwork` Pod as sources separately; running `curl` only once on the node cannot validate the Service for regular Pods.

## 6. How Cilium Completes Service Translation in This Network

Cilium does not need to tear down Contiv and OVS first. `generic-veth` lets it recognize the created Pod network interfaces; Service state is synchronized into the eBPF load balancing map. On applicable Socket paths, the backend can be selected when the application calls `connect()`; on paths requiring packet-level translation, TC programs can also handle it. [Cilium Socket LB and TC fallback mechanism](https://docs.cilium.io/en/stable/network/kubernetes/kubeproxy-free/#socket-loadbalancer-bypass-in-pod-namespace)

The following programs exist on the host veth checked this time, with the original port names in the program names replaced:

```text
veth-a ingress：cil_from_container-veth-a  direct-action
veth-a egress ：cil_to_container-veth-a    direct-action
```

This proves that Cilium has attached to the data path of this endpoint. However, **the presence of a TC program does not mean every TCP Service translation happens at TC**. The evidence from this specific request points to the earlier Socket LB.

### 6.1 An Easily Misread Configuration: Written as false, but Actually Enabled

The original configuration contains `bpf-lb-sock: "false"`, but the runtime state shows:

```text
KubeProxyReplacement: True
Socket LB:           Enabled
Socket LB Coverage:  Full
EnableSocketLB:      true
BPFSocketLBHostnsOnly: false
```

Cross-checking the community Cilium 1.16.1 `initKubeProxyReplacementOptions`, when `kubeProxyReplacement=true`, it automatically enables Socket LB, NodePort, ExternalIPs, HostPort, and Session Affinity. Therefore, merely seeing the old value in the ConfigMap and inferring that Socket LB is disabled will draw the forwarding path incorrectly. The runtime result here is consistent with this community startup logic. [Cilium 1.16.1 kube-proxy replacement initialization](https://github.com/cilium/cilium/blob/v1.16.1/daemon/cmd/kube_proxy_replacement.go)

### 6.2 Why Packet Capture Cannot See the Service IP

Select an existing regular Pod and access the Service health endpoint of an application on another node. The desensitized address relationships are as follows:

| Object | Example Address |
| --- | --- |
| Source Pod | `10.244.8.23` |
| Application Service | `10.120.0.80:80` |
| Actual backend Pod | `10.244.20.31:3000` |
| Source network VLAN | `200` |

The request output shows it connects to the Service and ultimately returns HTTP 200:

```text
Connecting to 10.120.0.80 (10.120.0.80:80)
HTTP/1.1 200 OK
```

Meanwhile, the corresponding frontend and backend can be found in Cilium's BPF LB Map:

```text
Service frontend：10.120.0.80:80
Service backend ：10.244.20.31:3000
```

Capturing packets on the source Pod's `eth0`, the SYN seen is already:

```text
IP 10.244.8.23.<源端口> > 10.244.20.31.3000: Flags [S]
```

Capturing on the physical uplink, the destination IP is also the backend, the packet carries the source network VLAN, and the source Pod IP is preserved:

```text
ethertype 802.1Q, vlan 200,
10.244.8.23.<源端口> > 10.244.20.31.3000: Flags [S]
```

The above are excerpts of actual output, with addresses, MACs, VLANs, etc. replaced. When filtering Pod packet capture by the original Service IP only, no packets for this request were captured; after switching to filter by the backend, connection packets could be seen. Combined with the Socket LB runtime state, BPF Map, the absence of TC programs inside the Pod, and the check for no NAT translation rules, this is consistent with the behavior of a TCP connection selecting the backend at the Socket layer.

![Socket LB request and packet evidence explanation](../../assets/practices/contiv-ovs-cilium-network/socket-lb-evidence.png)

Therefore, when capturing packets, both the Service IP and the backend IP should be prepared. Especially when Socket LB is enabled, "no VIP packets inside the Pod" can be a normal phenomenon; directly concluding from this that the CNI is dropping packets will lead the troubleshooting in the wrong direction.

### 6.3 kube-proxy Replacement Does Not Mean Replacing All Underlying Networking

After Cilium completes Service translation here, subsequent packets still use the original Pod addresses, default gateway, OVS VLAN, and physical network. `routing-mode=native` and `Host Routing: Legacy` describe Cilium's own modes and cannot be used to infer that it has taken over all routing of the external switching network.

`enable-host-legacy-routing=true` was retained this time. The community has historically seen cases where `generic-veth` combined with BPF Host Routing bypassed the original routing, but that was a case from another version and another environment, and can only serve as a reference for validating routing compatibility before migration, not as evidence for this fault. [Cilium community issue #20135](https://github.com/cilium/cilium/issues/20135)

## 7. Actual Connectivity Check Results

To distinguish between "direct backend success" and "Service success," different sources and protocols were checked. No new stress test tasks were created, and no single success was used to declare the entire network healthy.

| Check | Source | Result | What It Demonstrates |
| --- | --- | --- | --- |
| DNS Service, UDP 53 | Existing tool Pod | `NOERROR`, correct record returned | UDP DNS Service requests succeed on this path |
| DNS Service, TCP 53 | Existing tool Pod | `NOERROR`, correct record returned | TCP DNS path is also usable |
| API Service `/version` | Existing tool Pod | HTTP 200 | TCP requests through the Service can reach the API |
| Direct access to API backend `/version` | Existing tool Pod | HTTP 200 | Backend direct access and Service path checked separately |
| API Service `/version` | Regular Pod with Cilium Endpoint | HTTP 200 | Regular Pods in the current chained network can access the API Service |
| Application Service `/api/health` | Same regular Pod, backend on another node | HTTP 200 | Cross-node application Service is accessible, corresponding to the BPF Map and packet capture |

API requests used health/version access without business credentials; the HTTPS smoke test disabled certificate verification and was used only to check network reachability, not as a TLS trust chain acceptance. HTTP 200 also does not mean business permissions or all APIs have been verified.

### 7.1 No `KUBE-SERVICES` Does Not Mean the Service Is Broken

The sampled node checked both the nft and legacy backends of iptables, and no kube-proxy `KUBE-SERVICES` translation chain was found, only some Cilium and kubelet-related rules. The Service still succeeded because it is implemented by eBPF.

`KUBE-KUBELET-CANARY` is a kubelet-related identifier and cannot be treated as evidence that kube-proxy Service rules already exist. Likewise, the command indicating "legacy table exists" only means the machine has two sets of interfaces to check, not that this Service failure was found.

### 7.2 A Historical OVS Rule Worth Noting

One sampled node additionally retained a high-priority rule similar to the following, with addresses desensitized:

```text
priority=1000,ip,nw_dst=10.120.0.0/24,actions=LOCAL
```

It attempts to send packets for a certain destination subnet to the OVS local port. However, this only covers one `/24` and cannot represent the entire Service address range; after being sent to `LOCAL`, whether the correct host IP stack, addresses, routing, translation, and return path exist still needs to be verified. During the check, this rule had no active hits for a long time and cannot explain the current success of all Services.

Such residual rules make behavior differ between nodes. During migration or troubleshooting, flow tables from each node should be saved and compared, and the owner, coverage, and exit conditions of each exception rule should be clarified.

### 7.3 Service Accessibility Does Not Mean Policy Coverage

Another finding: the historical tool Pod did not appear in the corresponding node's Cilium Endpoint list, and its host veth had no corresponding TC program, yet Service requests still succeeded. Node-level coverage of Socket LB can present different results from endpoint-level policy attachment.

Therefore, **Service reachability and NetworkPolicy coverage must be validated separately**. Adding a new CNI chaining configuration will not automatically re-run network creation for all existing Pods. For existing workloads, Endpoints, interface programs, and deny policies should be checked one by one, then handled according to the maintenance plan; a single `curl` cannot be relied upon.

## 8. Next Troubleshooting: Follow This Evidence Chain

First determine "who created the network" and "who proxies the Service," then trace the packets. The commands below are generic read-only examples; Pods, interfaces, and bridge names must be replaced with actual objects; host commands should be run in an authorized node diagnostic environment.

### Step 1: Check Kubernetes Resources and Actual Runtime State

```bash
kubectl -n kube-system get ds,pods -o wide
kubectl -n kube-system get cm cilium-config -o yaml
kubectl -n kube-system exec <cilium-pod> -c cilium-agent -- \
  cilium-dbg status --verbose
```

Also check the kube-proxy, netplugin, and OVS processes on the node. The absence of a DaemonSet cannot rule out host-level deployment; ConfigMap values cannot replace runtime state.

### Step 2: Correlate Pod, veth, OVS, and Cilium Endpoint

```bash
cat /etc/cni/net.d/05-cilium.conflist
ip -d link show
ovs-vsctl --timeout=5 show
ovs-vsctl --timeout=5 get Port <pod-veth> tag
ovs-ofctl dump-flows <pod-bridge>
tc filter show dev <pod-veth> ingress
tc filter show dev <pod-veth> egress
```

Confirm the Pod's address and default gateway, then correlate based on interface index, OVS port information, and Cilium Endpoint associated objects. At this point, it can be determined whether packets will go to the host protocol stack, another local port, or the VLAN uplink.

### Step 3: Check Both the Control Plane and Data Plane of the Service

```bash
kubectl -n <namespace> get svc <service> -o yaml
kubectl -n <namespace> get endpointslice \
  -l kubernetes.io/service-name=<service> -o wide
kubectl -n kube-system exec <cilium-pod> -c cilium-agent -- \
  cilium-dbg service list
kubectl -n kube-system exec <cilium-pod> -c cilium-agent -- \
  cilium-dbg bpf lb list
iptables-save -t nat
iptables-legacy-save -t nat
```

If the Service has no Ready backends, resolve the backend problem first. If the API object has been updated but the BPF Map has not, then check agent synchronization, capacity, or API watch. In environments using kube-proxy, also check the corresponding rule counters and synchronization logs.

### Step 4: Packet Capture Must Cover Before and After Translation

```bash
# 在源 Pod 的网络命名空间：同时考虑 Service 和后端地址
tcpdump -p -nn -i eth0 -s 96 -c 20 \
  'tcp and (host 10.120.0.80 or host 10.244.20.31)'

# 在宿主机物理上联：观察 VLAN、后端地址和源地址
tcpdump -p -nn -e -i <uplink> -s 96 -c 20 \
  'tcp and host 10.244.20.31'
```

Packet capture needs time limits and packet counts. The interface location affects the addresses seen: Socket, TC, host protocol stack, and OVS processing may occur before the capture point. The absence of packets at one location should be cross-judged against request logs, adjacent locations, and runtime state.

### Step 5: Combine Monitoring with Active Validation

| Dimension | Suggested Ongoing Focus | Problems It Can Locate |
| --- | --- | --- |
| Node networking | Traffic, errors, drops on physical ports, bond member ports, and Pod veths | Link anomalies, interface errors, local congestion |
| OVS | Port `ofport`, errors, drops, flow table counters, and uplink status | Port not created, exception flow tables, inconsistent forwarding |
| Cilium | Agent Ready, Endpoint status, drop reasons, Service/Backend map capacity | Missing endpoints, policy denials, state sync or capacity issues |
| Service discovery | Service, EndpointSlice, and Ready backend consistency | Selector errors, readiness changes, sync lag |
| Active probing | Pod → DNS, Pod → Service, Pod → backend, cross-node and cross-VLAN | User path fails while basic metrics are normal |

NIC bandwidth curves can prove traffic exists but cannot prove Service translation is correct; agent Ready also cannot prove that policies for existing Pods are attached. These metrics need to be placed on the same timeline as endpoints, rules, and real requests.

## 9. Deployment and Migration Recommendations

If VLAN and Contiv need to be retained, first turn the CNI call order, interface ownership, Service proxying, address pools, and default gateway into an explicit configuration checklist. Whether Cilium chaining meets business requirements must be validated against the actual version; parameters cannot be copied directly from a native Cilium deployment assuming all advanced capabilities apply. [Cilium generic-veth deployment and limitations](https://docs.cilium.io/en/stable/installation/cni-chaining-generic-veth/)

| Option | Applicability Considerations | Key Validation Points |
| --- | --- | --- |
| Retain Contiv/OVS, chain Cilium and let it proxy Services | Need to preserve existing Pod IPs, VLANs, and physical network access | Socket/TC paths, existing Endpoints, return path, policies, and custom plugins |
| Retain OVS, design a Service path that can enter the host IP stack | Must use kube-proxy and can maintain the supporting network integration | Internal ports, full Service range, routing, VLAN, translation, and reverse path |
| Adopt an OVS network solution with its own Service implementation | Want Service translation to stay in the switching data plane | The solution's specific controller, OpenFlow/conntrack implementation, and API semantics |
| Migrate to another unified managed CNI | Have a plan to replace the old network and bear the migration cost | Pod recreation, address changes, physical network connectivity, security policies, and rollback path |

This case is currently fully managed by Cilium for Service handling, so it is not suitable to directly start another default kube-proxy just to "see if it works." When the same Service is processed by multiple mechanisms simultaneously, it increases the complexity of address translation, connection tracking, and return-path analysis. Supported partial replacement or migration modes should follow the documentation for the specific version; "cannot be arbitrarily stacked" must not be expanded into "can never coexist."

The acceptance matrix should cover same-node, cross-node, same-VLAN, cross-VLAN, ClusterIP, NodePort, UDP, TCP, `hostNetwork`, and VM or sandbox runtimes. For scenarios involving Sidecar, Kata, KubeVirt, and similar, it is also necessary to confirm whether Socket LB applies and whether TC fallback is required; this article only checked the actual Service path for ordinary Pods and did not use it to replace acceptance for other runtimes.

Before the upgrade, preserve CNI files, runtime configuration, OVSDB port inventory, flow tables, routes, and agent running state, then compare item by item after the upgrade. For old configurations, existing Pods not yet migrated, and single-node exception rules, define a clear handling plan. Only this way can a mixed state of "new Pods work normally, old Pods still follow the old path" be avoided.

The most valuable diagnostic method in this investigation is to first confirm where the packet completes Service translation, and then confirm along which network path it is delivered to the backend. Component processes, configuration files, rule lists, and packet captures each only explain part of the picture; only by correlating them can you explain why, on the same OVS network, one request passes through kube-proxy while another request never reaches it at all.

## References

- [CNI Specification: Configuration, Calling Protocol, and Plugin Chaining](https://www.cni.dev/docs/spec/)
- [Contiv Netplugin Project](https://github.com/contiv/netplugin)
- [Open vSwitch: Common Configuration Issues and iptables Boundaries](https://docs.openvswitch.org/en/latest/faq/issues/)
- [Open vSwitch: NORMAL Pipeline](https://docs.openvswitch.org/en/latest/ref/ovs-actions.7/#the-ovs-normal-pipeline)
- [Kubernetes: Virtual IPs and Service Proxies](https://kubernetes.io/docs/reference/networking/virtual-ips/)
- [Cilium 1.16.1: generic-veth Implementation](https://github.com/cilium/cilium/blob/v1.16.1/plugins/cilium-cni/chaining/generic-veth/generic-veth.go)
- [Cilium 1.16.1: kube-proxy Replacement Initialization](https://github.com/cilium/cilium/blob/v1.16.1/daemon/cmd/kube_proxy_replacement.go)
- [Cilium: Socket LB and TC Fallback](https://docs.cilium.io/en/stable/network/kubernetes/kubeproxy-free/)
- [Cilium: generic-veth Deployment and Limitations](https://docs.cilium.io/en/stable/installation/cni-chaining-generic-veth/)
- [Cilium Community Issue #20135: generic-veth and BPF Host Routing](https://github.com/cilium/cilium/issues/20135)
