---
title: "Offline Deployment of AI/LLM Platforms"
description: "Synchronize images, charts, models, drivers, packages, and security metadata in environments without public network access"
status: stable
last_reviewed: 2026-08-04
---

# Offline Deployment of AI/LLM Platforms

Offline deployment is not just copying a few images into Harbor. AI platforms also depend on GPU drivers, OS packages, Helm Charts, Operator Bundles, Python/Wheels, models, tokenizers, security metadata, and licenses.

## 1. Artifact List

| Type | Examples | Target Storage |
| --- | --- | --- |
| Container images | Kubernetes, Operator, training/inference runtimes | OCI Registry |
| Charts/YAML | CNI, CSI, GPU, Kueue, KServe | Git/OCI Registry |
| OS packages | RPM/DEB, kernel, OFED, firmware | Internal software repository |
| Python/model dependencies | Wheels, Conda, build caches | PyPI/object storage proxy |
| Models | Weights, tokenizer, config, license | Object storage/OCI/model registry |
| Supply chain | Digest, SBOM, signatures, vulnerability database | Registry/security platform |

## 2. Recommended Synchronization Workflow

```text
联网构建区
  → 解析完整依赖和许可证
  → 锁定版本、Digest、SBOM 与签名
  → 恶意代码和漏洞扫描
  → 审批与离线介质/跨域传输
  → 离线 Registry、对象存储和软件源
  → 校验后发布到测试集群
  → 基准、升级和回滚演练
```

## 3. Common Oversights

- GPU Operator downloads drivers or the Toolkit at runtime;
- Helm Charts reference public sub-charts;
- Python downloads models, tokenizers, or Wheels online at startup;
- Prometheus dashboards, CRDs, or Webhook images are not synchronized;
- Vulnerability databases and certificate revocation information are not updated for long periods;
- Model licenses do not permit the intended use or redistribution.

## 4. DNS and Image Rewriting

Prefer explicitly rewriting the registry in the artifact manifest and GitOps overlays, avoiding reliance on temporary `/etc/hosts` on all nodes. Keep the mapping of upstream source, original digest, and internal digest to support auditing and re-synchronization.

## 5. Acceptance

In a test environment fully disconnected from the public network, complete installation of cluster components, GPU nodes, training jobs, and inference services from empty nodes; then perform a minor version upgrade and rollback. Any implicit network requests should fail and be recorded.

Further reading: [Model artifacts](../data/model-artifacts.md), [Security governance](../security-governance.md), [Platform operations](../platform-operations.md)
