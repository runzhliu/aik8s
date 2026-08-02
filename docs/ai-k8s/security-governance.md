# AI 平台安全与治理

AI on Kubernetes 同时继承了容器平台、数据平台和模型供应链的风险。GPU Operator 需要较高主机权限，Notebook 允许交互执行代码，模型文件可能来自外部社区，而 Agent 还会主动访问网络和工具。

安全设计必须先画清信任边界，再选择控制措施。

## 一、威胁面分层

| 层级 | 主要风险 |
| --- | --- |
| 身份与 API | 过宽 RBAC、共享 ServiceAccount、长期 Token |
| 容器与节点 | 特权容器、hostPath、驱动和内核攻击面 |
| 镜像与依赖 | 恶意镜像、依赖投毒、未验证构建来源 |
| 数据与模型 | 数据泄漏、模型篡改、反序列化执行 |
| 网络与工具 | 任意出网、横向访问、SSRF、工具滥用 |
| 推理接口 | 越权、DoS、Prompt Injection、敏感输出 |
| 运营流程 | 密钥进入日志、缺少审计、例外永久化 |

不要把“集群内”当作可信网络，也不要把模型权重当成被动数据文件。

## 二、身份优先于网络位置

推荐：

- 人员通过 OIDC/SSO 访问，不共享 kubeconfig；
- 每类控制器和工作负载使用独立 ServiceAccount；
- 默认不自动挂载 ServiceAccount Token；
- 短期凭证替代静态云密钥；
- 训练、推理、流水线和 Notebook 的权限边界分开；
- 定期分析实际 API 调用并收缩 RBAC；
- 禁止租户创建 ClusterRoleBinding、Webhook 和特权 RuntimeClass。

能在 Notebook 中执行代码的用户，通常可以读取该 Pod 挂载的所有凭证，必须按等价权限治理。

## 三、Pod Security Standards 怎么落地

Kubernetes 定义 `privileged`、`baseline`、`restricted` 三个安全级别，并可通过 Pod Security Admission 在 namespace 级以 `enforce`、`audit`、`warn` 模式执行。参考：[Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)、[Pod Security Admission](https://kubernetes.io/docs/concepts/security/pod-security-admission/)

建议：

- 普通训练、推理和 Notebook 目标是 `restricted`；
- 先用 `warn`/`audit` 观察，再逐步 `enforce`；
- GPU/Network/Storage Operator 放在独立系统 namespace；
- 特权例外按组件、版本和责任人记录；
- 不因为 GPU Operator 需要特权，就让所有 GPU 工作负载进入特权 namespace。

## 四、GPU 节点的特殊风险

GPU 节点上通常存在：

- 驱动内核模块；
- Device Plugin 和容器运行时 Hook；
- `/dev/nvidia*` 设备；
- DCGM、NVML 和 PodResources Socket；
- RDMA 设备与 Host Network；
- 可能的 MIG/MPS 管理组件。

这些组件往往需要主机权限，应该限制镜像来源、固定版本、独立升级并监控所有 hostPath。租户容器不应直接访问 Docker/containerd Socket 或 kubelet 管理接口。

## 五、镜像供应链

最低控制链：

```text
源码审查
  → 可复现 CI 构建
  → 漏洞和 Secret 扫描
  → 生成 SBOM/Provenance
  → 镜像按摘要签名
  → Admission 验证签名与来源
  → 运行时只拉取允许的摘要
```

Cosign 可以签名容器镜像，Kyverno 等策略引擎能在准入阶段验证签名和 Attestation。参考：[Kyverno Sigstore Verification](https://kyverno.io/docs/policy-types/cluster-policy/verify-images/sigstore/)

不要只扫描镜像标签。标签可变，部署和审计应记录 Digest。

## 六、模型供应链

模型制品需要类似镜像的控制：

- 固定仓库和不可变 Revision；
- 保存 SHA-256 或 OCI Digest；
- 记录训练代码、数据和基础模型来源；
- 在隔离环境扫描或转换外部模型；
- 避免加载会执行任意 Python 的格式或自定义代码；
- 评估许可证、使用限制与数据来源；
- 发布前执行质量、安全和性能评估；
- 模型注册表保存审批与回滚状态。

“来自知名模型社区”不等于已经通过企业信任审查。

## 七、Secret 管理

- Secret 不进入 Git、镜像、模型包或 Notebook；
- 使用外部 Secret Manager/KMS，并通过短期身份获取；
- etcd 开启静态加密并限制备份访问；
- 每个服务只挂载需要的 Secret；
- 定期轮换并验证应用能无停机刷新；
- 日志和 Trace 对 Header、环境变量、Prompt 做脱敏；
- 避免把 Secret 作为命令行参数暴露到进程列表。

Kubernetes Secret 只是 API 对象，不应被当成完整的企业密钥管理系统。

## 八、网络与出站访问

默认拒绝策略至少覆盖：

- namespace 间横向访问；
- 训练/Notebook 到 Kubernetes API；
- 推理 Pod 到元数据服务；
- Agent 或用户代码的任意公网出站；
- 模型下载只允许受信 Registry/对象存储；
- DNS 请求可观测并限制异常域名；
- 管理面、数据面和 RDMA 网络分开。

NetworkPolicy 是否真正覆盖 Host Network、RDMA VF 和多网卡 Pod，取决于 CNI 与部署方式，必须实测。

## 九、推理 API 的治理

- 身份验证和租户隔离；
- 每用户/模型的请求与 Token 限额；
- 输入大小、上下文长度和并发上限；
- 超时、取消和最大输出 Token；
- 模型白名单和版本路由；
- Prompt/响应日志默认最小化；
- 内容安全和输出策略可审计；
- 防止内部模型端点被公网绕过网关访问。

LLM 的成本型 DoS 往往不是高请求数，而是少量超长上下文和输出请求。

## 十、Notebook 与交互环境

Notebook 风险高于普通无状态服务，因为用户可以：

- 安装并运行任意包；
- 访问挂载数据和凭证；
- 建立反向连接；
- 长时间保留未打补丁环境；
- 把敏感输出写入持久卷。

建议使用短生命周期、独立 ServiceAccount、默认拒绝出网、资源上限、自动休眠和受控基础镜像。高风险用户代码可以使用 gVisor、Kata 等 RuntimeClass 增强隔离，但仍需结合网络与身份控制。

## 十一、策略例外治理

每个例外必须包含：

- 需要绕过的具体策略；
- 技术原因和替代措施；
- 适用 namespace、ServiceAccount 和镜像摘要；
- 负责人；
- 到期时间；
- 复查或移除条件。

没有自动到期的例外，最终会变成默认策略。

## 十二、审计证据

应能回答：

- 谁提交、批准和运行了任务；
- 使用了哪个镜像、模型和数据版本；
- 读取了哪些 Secret 和外部服务；
- 哪个策略允许或拒绝了请求；
- 模型发布前通过了哪些评估；
- 哪个管理员修改了配额、优先级或特权例外；
- 事件发生时哪些日志和制品被保留。

审计日志本身也可能包含敏感信息，应限制访问并设置保留周期。

## 十三、上线清单

- [ ] 人员和工作负载身份分开，RBAC 最小化；
- [ ] 普通 workload namespace 执行 Baseline/Restricted 策略；
- [ ] 特权 Operator 独立 namespace，并记录 hostPath；
- [ ] 镜像按 Digest 部署且验证签名/来源；
- [ ] 外部模型固定 Revision、校验摘要并隔离扫描；
- [ ] Secret 不进入 Git、日志、Notebook 和模型包；
- [ ] 默认拒绝网络策略覆盖入站和出站；
- [ ] 推理 API 有 Token、上下文和并发限制；
- [ ] Notebook/Agent 使用独立身份和更强隔离；
- [ ] 策略例外有负责人和自动到期时间；
- [ ] 发布和高权限操作可审计。

## 延伸阅读

- [Kubernetes Security](https://kubernetes.io/docs/concepts/security/)
- [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
- [Pod Security Admission](https://kubernetes.io/docs/concepts/security/pod-security-admission/)
- [Kyverno Pod Security](https://kyverno.io/docs/guides/pod-security/)
- [Kyverno Sigstore Verification](https://kyverno.io/docs/policy-types/cluster-policy/verify-images/sigstore/)
