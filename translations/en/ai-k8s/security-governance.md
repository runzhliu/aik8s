---
title: "AI Platform Security and Governance"
description: "Identity, tenant isolation, Pod security, image and model supply chain, and compliance auditing"
status: stable
last_reviewed: 2026-08-02
---

# AI Platform Security and Governance

AI on Kubernetes inherits risks from container platforms, data platforms, and the model supply chain simultaneously. The GPU Operator requires elevated host privileges, Notebooks allow interactive code execution, model files may come from external communities, and Agents actively access networks and tools.

Security design must first draw clear trust boundaries, then select control measures.

## 1. Threat Surface Layering

| Layer | Primary Risks |
| --- | --- |
| Identity and API | Overly broad RBAC, shared ServiceAccounts, long-lived Tokens |
| Container and Node | Privileged containers, hostPath, driver and kernel attack surface |
| Image and Dependencies | Malicious images, dependency poisoning, unverified build provenance |
| Data and Model | Data leakage, model tampering, deserialization execution |
| Network and Tools | Arbitrary egress, lateral access, SSRF, tool abuse |
| Inference API | Privilege escalation, DoS, Prompt Injection, sensitive output |
| Operational Process | Secrets leaking into logs, missing audit, permanent exceptions |

Do not treat "inside the cluster" as a trusted network, and do not treat model weights as passive data files.

## 2. Identity Over Network Location

Recommendations:

- Personnel access via OIDC/SSO, no shared kubeconfig;
- Each controller and workload type uses a dedicated ServiceAccount;
- ServiceAccount Tokens are not auto-mounted by default;
- Short-lived credentials replace static cloud keys;
- Permission boundaries are separated for training, inference, pipelines, and Notebooks;
- Periodically analyze actual API calls and tighten RBAC;
- Tenants are prohibited from creating ClusterRoleBindings, Webhooks, and privileged RuntimeClasses.

Users who can execute code in a Notebook can typically read all credentials mounted to that Pod; they must be governed at equivalent permission levels.

## 3. How to Implement Pod Security Standards

Kubernetes defines three security levels, `privileged`, `baseline`, `restricted`, which can be enforced at the namespace level via Pod Security Admission in `enforce`, `audit`, `warn` modes. References: [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/), [Pod Security Admission](https://kubernetes.io/docs/concepts/security/pod-security-admission/)

Recommendations:

- Regular training, inference, and Notebook workloads target `restricted`;
- First use `warn`/`audit` to observe, then gradually move to `enforce`;
- GPU/Network/Storage Operators reside in dedicated system namespaces;
- Privileged exceptions are recorded by component, version, and responsible owner;
- Do not place all GPU workloads into a privileged namespace just because the GPU Operator requires privileges.

## 4. Special Risks of GPU Nodes

GPU nodes typically contain:

- Driver kernel modules;
- Device Plugin and container runtime hooks;
- `/dev/nvidia*` devices;
- DCGM, NVML, and PodResources Sockets;
- RDMA devices and Host Network;
- Possible MIG/MPS management components.

These components often require host privileges; image provenance should be restricted, versions pinned, upgrades performed independently, and all hostPath mounts monitored. Tenant containers must not directly access the Docker/containerd Socket or kubelet management interfaces.

## 5. Image Supply Chain

Minimum control chain:

```text
源码审查
  → 可复现 CI 构建
  → 漏洞和 Secret 扫描
  → 生成 SBOM/Provenance
  → 镜像按摘要签名
  → Admission 验证签名与来源
  → 运行时只拉取允许的摘要
```

Cosign can sign container images, and policy engines such as Kyverno can verify signatures and attestations at admission time. Reference: [Kyverno Sigstore Verification](https://kyverno.io/docs/policy-types/cluster-policy/verify-images/sigstore/)

Do not only scan image tags. Tags are mutable; deployments and audits should record the Digest.

## 6. Model Supply Chain

Model artifacts require controls similar to images:

- Pin repositories and immutable Revisions;
- Record SHA-256 or OCI Digest;
- Document training code, data, and base model provenance;
- Scan or convert external models in an isolated environment;
- Avoid loading formats or custom code that execute arbitrary Python;
- Evaluate licenses, usage restrictions, and data provenance;
- Run quality, security, and performance evaluations before release;
- Model registry retains approval and rollback state.

"From a well-known model community" does not mean it has passed enterprise trust review.

## 7. Secret Management

- Secrets do not enter Git, images, model packages, or Notebooks;
- Use an external Secret Manager/KMS and obtain credentials via short-lived identity;
- Enable encryption at rest for etcd and restrict backup access;
- Mount only the Secrets each service needs;
- Rotate periodically and verify applications can refresh without downtime;
- Redact headers, environment variables, and prompts in logs and traces;
- Avoid exposing Secrets as command-line arguments visible in process listings.

Kubernetes Secrets are just API objects and should not be treated as a complete enterprise key management system.

## 8. Network and Egress Access

Default-deny policies should cover at least:

- Lateral access between namespaces;
- Training/Notebook access to the Kubernetes API;
- Inference Pod access to metadata services;
- Arbitrary public egress from Agents or user code;
- Model downloads restricted to trusted Registries/object storage;
- DNS requests observable and anomalous domains restricted;
- Management plane, data plane, and RDMA networks separated.

Whether NetworkPolicy actually covers Host Network, RDMA VFs, and multi-NIC Pods depends on the CNI and deployment method; this must be verified by testing.

## 9. Inference API Governance

- Authentication and tenant isolation;
- Per-user/model request and Token quotas;
- Input size, context length, and concurrency limits;
- Timeouts, cancellation, and maximum output Tokens;
- Model allowlist and version routing;
- Minimal prompt/response logging by default;
- Content safety and output policies auditable;
- Prevent internal model endpoints from being accessed via the public internet, bypassing the gateway.

LLM cost-based DoS is often not high request volume, but a small number of requests with extremely long context and output.

## 10. Notebooks and Interactive Environments

Notebooks carry higher risk than ordinary stateless services because users can:

- Install and run arbitrary packages;
- Access mounted data and credentials;
- Establish reverse connections;
- Keep unpatched environments alive for long periods;
- Write sensitive output to persistent volumes.

Recommendations include short-lived lifecycles, dedicated ServiceAccounts, default-deny egress, resource limits, auto-sleep, and controlled base images. High-risk user code can use RuntimeClasses such as gVisor or Kata for stronger isolation, but this must still be combined with network and identity controls.

## 11. Policy Exception Governance

Every exception must include:

- The specific policy being bypassed;
- Technical justification and alternative measures;
- Applicable namespace, ServiceAccount, and image digest;
- Responsible owner;
- Expiration date;
- Review or removal conditions.

Exceptions without automatic expiration eventually become the default policy.

## 12. Audit Evidence

Should be able to answer:

- Who submitted, approved, and ran the job;
- Which image, model, and data version was used;
- Which Secrets and external services were accessed;
- Which policy allowed or denied the request;
- Which evaluations the model passed before release;
- Which administrator modified quotas, priorities, or privileged exceptions;
- Which logs and artifacts were retained when the incident occurred.

Audit logs themselves may contain sensitive information; access should be restricted and retention periods set.

## 13. Go-Live Checklist

- [ ] Personnel and workload identities separated, RBAC minimized;
- [ ] Regular workload namespaces enforce Baseline/Restricted policies;
- [ ] Privileged Operators in dedicated namespaces, with hostPath documented;
- [ ] Images deployed by Digest with signature/provenance verified;
- [ ] External models pinned to Revisions, digests verified, and scanned in isolation;
- [ ] Secrets do not enter Git, logs, Notebooks, or model packages;
- [ ] Default-deny network policies cover ingress and egress;
- [ ] Inference API has Token, context, and concurrency limits;
- [ ] Notebooks/Agents use dedicated identities and stronger isolation;
- [ ] Policy exceptions have owners and automatic expiration dates;
- [ ] Releases and high-privilege operations are auditable.

## Further Reading

- [Kubernetes Security](https://kubernetes.io/docs/concepts/security/)
- [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
- [Pod Security Admission](https://kubernetes.io/docs/concepts/security/pod-security-admission/)
- [Kyverno Pod Security](https://kyverno.io/docs/guides/pod-security/)
- [Kyverno Sigstore Verification](https://kyverno.io/docs/policy-types/cluster-policy/verify-images/sigstore/)
