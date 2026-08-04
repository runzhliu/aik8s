---
title: 离线环境部署 AI/LLM 平台
description: 在无公网环境同步镜像、Chart、模型、驱动、软件包和安全元数据
status: stable
last_reviewed: 2026-08-04
---

# 离线环境部署 AI/LLM 平台

离线部署不是把几个镜像复制进 Harbor。AI 平台还依赖 GPU 驱动、OS 软件包、Helm Chart、Operator Bundle、Python/Wheel、模型、Tokenizer、安全元数据和许可证。

## 1. 制品清单

| 类型 | 例子 | 目标存储 |
| --- | --- | --- |
| 容器镜像 | Kubernetes、Operator、训练/推理 Runtime | OCI Registry |
| Chart/YAML | CNI、CSI、GPU、Kueue、KServe | Git/OCI Registry |
| OS 软件 | RPM/DEB、内核、OFED、Firmware | 内部软件源 |
| Python/模型依赖 | Wheel、Conda、编译缓存 | PyPI/对象存储代理 |
| 模型 | 权重、Tokenizer、Config、License | 对象存储/OCI/模型仓库 |
| 供应链 | Digest、SBOM、签名、漏洞库 | Registry/安全平台 |

## 2. 推荐同步流程

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

## 3. 常见遗漏

- GPU Operator 运行时下载驱动或 Toolkit；
- Helm Chart 引用公网子 Chart；
- Python 启动时在线下载模型、Tokenizer 或 Wheel；
- Prometheus Dashboard、CRD 或 Webhook 镜像没有同步；
- 漏洞数据库和证书吊销信息长期不更新；
- 模型 License 不允许目标用途或再次分发。

## 4. DNS 与镜像重写

优先在制品清单和 GitOps Overlay 中显式改写 Registry，避免依赖所有节点的临时 `/etc/hosts`。保留上游来源、原始 Digest 和内部 Digest 的映射，支持审计和再次同步。

## 5. 验收

在完全断开公网的测试环境中，从空节点完成集群组件、GPU 节点、训练任务和推理服务安装；然后执行小版本升级和回滚。任何隐式联网请求都应失败并被记录。

延伸阅读：[模型制品](../data/model-artifacts.md)、[安全治理](../security-governance.md)、[平台运维](../platform-operations.md)

