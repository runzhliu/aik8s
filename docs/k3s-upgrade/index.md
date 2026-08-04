---
title: K3s 集群跨版本升级
description: 从 K3s v1.32 逐小版本升级到 v1.36，并完成备份、兼容性处理、工作负载验证和 DRA 预检
status: stable
last_reviewed: 2026-08-04
---

# K3s 集群跨版本升级

本案例记录一台真实 K3s 单节点集群从 `v1.32.5+k3s1` 逐小版本升级到 `v1.36.2+k3s1` 的完整过程，包括升级规划、多阶段备份、兼容性问题处理、工作负载恢复和 Kubernetes DRA 预检。

[阅读完整升级报告](report.md){ .md-button .md-button--primary }
[浏览全部工程案例](../cases/index.md){ .md-button }

## 案例概览

| 项目 | 内容 |
| --- | --- |
| 环境 | Anolis OS 8.9、单节点 K3s、SQLite、cgroup v1 |
| 起始版本 | `v1.32.5+k3s1` |
| 目标版本 | `v1.36.2+k3s1` |
| 升级方式 | 按 Kubernetes 小版本顺序逐级升级 |
| 主要风险 | SQLite 一致性、cgroup v1、Flannel、Traefik、ServiceLB 和历史工作负载 |
| 最终结果 | Node Ready，核心 API、网络组件和升级前 Running 工作负载恢复 |
| 扩展验证 | Kubernetes 1.36 DRA API 与异构 GPU 管理预检 |

## 阅读路径

- 需要了解最终状态和关键结论：阅读报告的“最终结论”。
- 准备实施类似升级：重点查看“版本规划与准备”“备份记录”和“升级执行时间线”。
- 遇到 kubelet 无法启动：查看“cgroup v1 兼容处理”。
- 关注升级后的稳定性：查看组件、APIService、网络和工作负载验证。
- 评估新设备接口：查看 DRA 与异构 GPU 管理预检。

报告现已转换为站点原生 Markdown，统一使用左侧导航、目录、搜索、代码复制和明暗主题。原始独立 HTML 保留在仓库的 `archive/` 目录，作为转换前归档。

## 案例覆盖范围

- 从 `v1.32.5+k3s1` 到 `v1.36.2+k3s1` 的逐版本升级路线；
- SQLite、二进制、配置和运行状态的多阶段备份；
- cgroup v1 兼容、Flannel、Traefik 和 ServiceLB 问题处理；
- 核心组件、APIService 和工作负载基线验证；
- Kubernetes 1.36 DRA 与异构 GPU 管理预检。

## 复用边界

这是一次特定环境的工程记录，不是通用升级脚本。多 Server、嵌入式 etcd、外部数据库、不同 CNI、不同操作系统或生产高可用集群，需要重新设计备份、仲裁、升级顺序和回滚方案。执行前还应核对目标版本的 K3s 与 Kubernetes 官方升级说明。
