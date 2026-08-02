# K3s 升级

这里收录 K3s 集群升级、兼容性检查以及升级后的验证记录。

## 升级报告

- [K3s 升级与 DRA 预检报告 — 192.168.1.200](k3s-upgrade-report-192.168.1.200.md)

报告现已转换为站点原生 Markdown，统一使用左侧导航、目录、搜索、代码复制和明暗主题。原始独立 HTML 保留在仓库的 `archive/` 目录，作为转换前归档。

报告包括：

- 从 `v1.32.5+k3s1` 到 `v1.36.2+k3s1` 的逐版本升级路线；
- SQLite、二进制、配置和运行状态的多阶段备份；
- cgroup v1 兼容、Flannel、Traefik 和 ServiceLB 问题处理；
- 核心组件、APIService 和工作负载基线验证；
- Kubernetes 1.36 DRA 与异构 GPU 管理预检。
