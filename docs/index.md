# AI & K8s 知识库

这里用于整理 AI、Kubernetes、Linux 和基础设施相关的笔记与报告。

## 内容目录

- [AI on K8s](ai-k8s/index.md)：AI 工作负载在 Kubernetes 上十年的演进、核心技术栈与工具选型。
- [K3s 升级](k3s-upgrade/index.md)：K3s 升级过程、兼容性检查和验证报告。

## 如何添加内容

在 `docs/` 下创建不同的文件夹作为栏目，并在栏目内添加 Markdown 文件：

```text
docs/
├── index.md
├── k3s-upgrade/
│   ├── index.md
│   └── 升级记录.md
└── kubernetes/
    ├── index.md
    └── 调度.md
```

每个文件夹建议包含一个 `index.md`，作为该栏目的入口页。
