---
title: DeepSeek Harness Docker、Compose 与 Helm 部署实战
description: 为 DeepSeek Harness 构建多架构 Docker 镜像，并用 Docker Compose 与 Kubernetes StatefulSet 安全部署，解决 EROFS、持久化、原生模块和 Web 暴露问题
status: evolving
last_reviewed: 2026-08-14
---

# DeepSeek Harness Docker、Compose 与 Helm 部署实战

本文聚焦一个明确目标：把仍处于开发者预览阶段的 DeepSeek Harness，整理成可构建、可复现、可持久化并具备安全基线的容器项目。

如果想先理解它为什么使用 Cordis、Agent turn/step 如何运行、会话为何采用事件溯源，以及 Filesystem、Shell、Sandbox 等能力如何被替换，请先阅读独立的源码分析：[DeepSeek Harness GitHub 仓库深度解析](deepseek-harness-repository-analysis.md)。如果更关心 all-in-one Chromium、DSH Browser Plugin、Tailscale 入口，以及真实测试集群中的 StatefulSet、PVC、NetworkPolicy 和 Cilium 探针冲突，请继续阅读 [从 Docker 到 Kubernetes：DeepSeek Harness、内置 Chromium 与 DSH Plugin 实战](../practices/deepseek-harness-kubernetes.md)。

如果目标是保留 DSH Runtime，把 Shell、文件与 PTY 下沉到独立 MicroVM，并实测网络、暂停恢复、回滚和多方案并行 Clone，参见[用 CubeSandbox 增强 OpenClaw 与 DSH：企业安全执行面实战](cubesandbox-openclaw-dsh-enterprise-practice.md)。

配套实现已经整理在独立开源项目 [runzhliu/deepseek-harness-docker](https://github.com/runzhliu/deepseek-harness-docker)，镜像发布在 [Docker Hub：runzhliu/deepseek-harness](https://hub.docker.com/r/runzhliu/deepseek-harness)。项目包含：

- 多阶段、非 root 的 Dockerfile；
- 本机安全默认值的 `compose.yaml`；
- 基于 StatefulSet 的 Helm Chart；
- Kubernetes 原生 YAML 渲染能力；
- 中英文 README、运行截图和验证脚本。

本文基于 2026-08-13 复核的 `@deepseek-ai/dsh@0.1.0-rc.6`。上游仍可能发生破坏性变更，生产采用前应重新验证版本、配置和安全假设。

## 1. 先给部署结论

- 镜像标签应跟随上游 DSH 运行时版本，因此使用 `runzhliu/deepseek-harness:0.1.0-rc.6`；
- 容器内 Web Server 必须监听 `0.0.0.0`，但宿主端口只能发布到 `127.0.0.1`；
- `$DSH_HOME` 和 `/workspace` 是两个不同生命周期的数据边界，应该分别挂载；
- `HOME=/workspace` 是修复 Web 目录选择器在只读根文件系统下创建 `/home/node/test` 报 EROFS 的关键；
- `node-pty` 等原生依赖要求多阶段构建同时验证 `linux/amd64` 与 `linux/arm64`；
- Kubernetes 默认使用单副本 StatefulSet，不应在缺乏共享状态与并发契约时假装可以水平扩展；
- 当前 Web Surface 没有 TLS、认证和 Origin 策略，默认访问方式应是宿主回环或 `kubectl port-forward`；
- Docker/Pod 安全上下文不能替代 Harness 的工具审批和 Agent Sandbox，两层必须同时存在。

## 2. 为什么镜像标签是 `0.1.0-rc.6`

`0.1.0-rc.6` 不是给 `deepseek-harness-docker` 随意定义的社区版本，而是构建时锁定的官方 npm 运行时版本：

```text
Docker image tag                         npm package
runzhliu/deepseek-harness:0.1.0-rc.6  →  @deepseek-ai/dsh@0.1.0-rc.6
```

这样做有三个好处：

1. 看到镜像标签就知道里面运行的是哪个 DSH；
2. 上游升级时可以并存多个镜像，回滚不依赖漂移的 `latest`；
3. 问题报告、SBOM 和构建日志可以落到同一个运行时版本。

当时上游 GitHub `master` 中的源码包版本与 npm 最新发行节奏并不完全同步，因此源码分析要记录 commit，容器镜像要记录实际安装的 npm 版本。两者不是冲突，而是不同制品的可追溯标识。

`latest` 可以作为方便用户试用的浮动别名，但文档、Compose 和 Helm 的默认值应尽量固定到 `0.1.0-rc.6`。未来升级到 rc.7 或稳定版时，应重新构建、完成验证矩阵，再发布对应的新标签。

## 3. 容器化真正需要解决的边界

直接执行以下命令只能证明 npm 包在当前宿主上能启动：

```bash
npx @deepseek-ai/dsh@0.1.0-rc.6 web
```

一个可发布的容器方案还必须明确：

| 问题 | 容器项目的答案 |
| --- | --- |
| Node 版本 | 固定 Node.js 24 基线 |
| npm 包版本 | 构建参数固定为 `0.1.0-rc.6` |
| 原生模块 | Builder 编译，Runtime 只保留运行产物 |
| 进程管理 | `tini` 作为 PID 1 |
| 运行身份 | UID/GID 1000，非 root |
| Harness 状态 | `/home/node/.dsh` 独立持久化 |
| 用户工作区 | `/workspace` 单独挂载 |
| 临时文件 | `/tmp` 使用 tmpfs 或临时卷 |
| 根文件系统 | 默认只读 |
| Web 暴露 | 容器内非 loopback，外部只允许可信入口 |
| Kubernetes 控制器 | 单副本 StatefulSet |
| 凭据 | 运行时 Secret 注入，不写入镜像和 values |

## 4. 状态模型：`DSH_HOME` 与 `/workspace` 必须分开

Harness home 的解析顺序是 `$DSH_HOME`，其次为 `~/.dsh`。容器中应显式设置：

```text
DSH_HOME=/home/node/.dsh
HOME=/workspace
```

推荐的数据布局是：

```text
/home/node/.dsh/
├── profiles/       # Profile、Bundle 元数据和用户 patch
├── settings.yaml   # 模型与运行设置
├── credentials*    # 凭据或其引用
├── sessions/       # 会话事件日志
└── storages/       # Workspace 等领域状态

/workspace/         # 用户代码和 Agent 实际操作目录
```

`/home/node/.dsh` 不是普通 cache。会话日志是模型上下文和恢复语义的事实源，Profile 与设置也决定 Runtime 如何组装。因此它应该使用命名卷或 PVC。

`/workspace` 则属于用户数据：本机可以使用 bind mount，Kubernetes 可以使用独立 PVC，也可以在确实允许任务结束即删除时使用 `emptyDir`。不要把两者合并到一个匿名卷，否则难以备份、迁移和设置最小权限。

## 5. EROFS 报错的根因与正确修复

用户在 Web 目录选择器中创建 `test` 文件夹时出现：

```text
cannot create /home/node/test:
EROFS: read-only file system, mkdir '/home/node/test'
```

根因不是 Docker 卷失效，而是两个配置组合后的路径错误：

1. 为了安全，容器根文件系统设置为只读；
2. Web 目录选择器以 Node.js `os.homedir()` 返回的 `/home/node` 作为首页；
3. 真正可写的用户工作区却挂载在 `/workspace`。

正确修复是把进程的 home 指到已挂载的工作区：

```dockerfile
ENV HOME=/workspace \
    DSH_HOME=/home/node/.dsh
```

修复后的写入边界是：

```text
Web directory picker home
          │ os.homedir()
          ▼
      /workspace  ── writable mount

Harness internal state
          ▼
  /home/node/.dsh ── persistent volume
```

不要用以下方式掩盖问题：

- 关闭只读根文件系统；
- 改成 root 用户；
- 让整个 `/home/node` 变成宽权限可写目录；
- 给容器增加 `--privileged`。

验证修复不能只看容器状态为 healthy，必须进入 Web 目录选择器实际创建一个文件夹，并检查它落在挂载的 `/workspace` 中。

## 6. Dockerfile 的八个关键设计

### 6.1 固定 DSH 发行版本

通过 `ARG DSH_VERSION=0.1.0-rc.6` 安装明确版本，并在构建阶段执行 `dsh --version`。不要让构建隐式追随 npm `latest`。

### 6.2 使用 Node.js 24

上游 `engines` 要求 Node.js `^22.19.0 || >=24.0.0`。Node.js 24 是清晰且容易维护的镜像基线，避免依赖宿主 Node 版本。

### 6.3 多阶段构建原生模块

Agent 的 Shell 和终端能力依赖 `node-pty` 等原生模块。某些 CPU 架构没有匹配的预编译产物，npm 会回退到 `node-gyp`。

Builder 阶段应包含 Python、编译器和 make；Runtime 阶段只复制最终 npm 安装结果及必要动态库。这样同时满足：

- `linux/amd64` 和 `linux/arm64` 构建；
- 运行镜像不长期保留完整编译工具链；
- PTY 不是“包安装成功但运行时 spawn 失败”。

### 6.4 为 DSH 主进程保留必要 Node 参数

Web Profile 会挂载配置 watcher，当前版本 HMR 服务需要 Node 的 `--expose-internals`。参数只应传给 DSH 主进程，不应写入可能被 Bash、LSP 或其他工具子进程继承的全局 `NODE_OPTIONS`。

### 6.5 用 `tini` 管理 PID 1

Agent 会创建 Shell、PTY、语言服务和其他子进程。`tini` 负责转发终止信号和回收孤儿进程，使 `docker stop` 与 Kubernetes 终止流程具有一致语义。

### 6.6 非 root 与只读根文件系统

运行时使用 UID/GID 1000，只允许 `/workspace`、`$DSH_HOME` 与 `/tmp` 写入；同时 drop 全部 Linux capabilities、启用 `no-new-privileges` 和默认 seccomp。

### 6.7 保留 Agent 确实需要的基础工具

精简镜像不能等同于删除 Agent 的工作能力。Git、OpenSSH Client、Python、ripgrep 和 `procps` 是合理基线；Java、Go、Rust 或项目专用依赖应通过派生镜像增加。

### 6.8 默认关闭遥测

社区镜像设置 `DSH_TELEMETRY_DISABLED=1`，让使用者在理解数据边界后显式选择是否开启。

## 7. Web 监听：容器内 `0.0.0.0` 不等于公网暴露

上游 `web` Profile 默认监听 `127.0.0.1:3080`。这对宿主直接运行是安全默认值，但 Docker bridge 无法把宿主端口转发到容器内部的 loopback listener。

容器通过 Cordis patch 把 Web Server 改为：

```yaml
- id: webserver
  name: '@deepseek-ai/dsh-host-webserver'
  config:
    host: '0.0.0.0'
    port: !!js ctx.webStartup.port ?? 3080
```

这只解决容器网络可达性。上游 Web Server 当前没有 TLS、认证和 Origin 策略，而背后的 Agent 能访问文件、启动 Shell 和执行代码，因此入口仍必须限制为：

```text
Browser
  │ http://127.0.0.1:3080
  ▼
Host loopback publication
  │ Docker port forwarding
  ▼
Container 0.0.0.0:3080
  ▼
DeepSeek Harness + code-execution tools
```

Docker 命令应明确写出宿主地址：

```bash
docker run --rm \
  --name deepseek-harness \
  -p 127.0.0.1:3080:3080 \
  -v deepseek-harness-home:/home/node/.dsh \
  -v "$PWD:/workspace" \
  runzhliu/deepseek-harness:0.1.0-rc.6
```

`-p 3080:3080` 往往会监听所有宿主接口，不应作为本文的默认示例。

## 8. Docker Compose：把安全默认值写进配置

Compose 的价值不是缩短一条 `docker run` 命令，而是把运行契约固化下来：

- `127.0.0.1:3080:3080`，避免意外暴露局域网；
- `dsh-home` 命名卷持久化 Harness 状态；
- 用户选择的目录 bind 到 `/workspace`；
- `read_only: true`，`/tmp` 使用 tmpfs；
- `cap_drop: [ALL]` 与 `no-new-privileges:true`；
- 限制进程数量，降低 fork bomb 风险；
- 容器内部 HTTP 健康检查；
- 明确重启策略。

典型使用方式是：

```bash
git clone https://github.com/runzhliu/deepseek-harness-docker.git
cd deepseek-harness-docker
docker compose up -d
docker compose ps
docker compose logs -f
```

然后访问 `http://127.0.0.1:3080`。首次配置模型凭据后，还应完成真实模型请求、文件读写和 PTY 命令，而不是把 HTTP 200 当成全部验收。

持久化测试至少包括：

1. 创建 Profile 或会话；
2. 在 `/workspace` 中创建文件夹和文件；
3. 强制重建容器；
4. 确认 Harness 状态仍在；
5. 确认工作区内容来自预期 bind mount。

## 9. Kubernetes：为何选择 StatefulSet，而不是 Deployment

当前 Web Surface 是有状态、单用户的 Runtime。Profile、凭据、会话和 Workspace 状态都会写入本地数据目录，上游没有给出多个副本并发读写同一状态的契约。

因此默认控制器选择单副本 StatefulSet：

```mermaid
flowchart LR
  USER["Trusted operator"] -->|kubectl port-forward| SVC["ClusterIP Service"]
  SVC --> POD["StatefulSet Pod"]
  POD --> DSH["/home/node/.dsh"]
  POD --> WS["/workspace"]
  DSH --> PVC1["State PVC"]
  WS --> PVC2["Optional workspace PVC / emptyDir"]
  NP["NetworkPolicy: deny ingress"] -. protects .-> POD
```

StatefulSet 在这里的意义不是为了扩容，而是：

- 提供稳定 Pod 身份；
- 用 `volumeClaimTemplates` 管理 Harness state PVC；
- 明确 PVC retention 行为；
- 让滚动升级和故障重建仍挂载同一份状态。

Deployment 只有在使用外部共享会话后端、明确支持并发、并把工作区迁移到可协调的远端执行环境后，才可能成为合理选择。把 `replicas` 从 1 改到 3 不会自动得到高可用，只会让三个 Runtime 对状态和任务归属产生竞争。

## 10. Helm Chart 的安全与状态基线

Chart 默认应包含：

- `replicas: 1`；
- StatefulSet 与 `/home/node/.dsh` PVC；
- 可选的 `workspace.existingClaim`；
- PVC retention policy 为 `Retain`；
- `automountServiceAccountToken: false`；
- UID/GID 1000、`RuntimeDefault` seccomp、只读根文件系统和 drop ALL；
- `/tmp` 的 `emptyDir`；
- 默认拒绝 Pod 入站的 NetworkPolicy；
- 不创建 Ingress、NodePort 或 LoadBalancer；
- 使用 `existingSecret` 注入模型提供方凭据。

安装示例：

```bash
helm upgrade --install deepseek-harness \
  ./charts/deepseek-harness \
  --namespace deepseek-harness \
  --create-namespace
```

默认访问方式：

```bash
kubectl -n deepseek-harness \
  port-forward service/deepseek-harness 3080:3080
```

然后仍然只通过 `http://127.0.0.1:3080` 访问。

如果企业确实需要共享入口，应先增加经过验证的 OAuth2/OIDC 认证代理、TLS、细粒度授权、审计、出站网络控制和独立 Sandbox，再评估 Ingress；不能只在前面加一个域名和证书。

## 11. Secret、网络与工作区权限

模型 API Key 不应出现在以下位置：

- Dockerfile 的 `ARG` 或 `ENV`；
- Compose 文件的明文默认值；
- Helm `values.yaml`；
- Git 仓库；
- 构建日志和镜像层。

本机可使用 `.env` 或 Docker Secret，但必须避免提交；Kubernetes 使用用户预先创建的 `existingSecret`。如果平台已有 External Secrets、Vault 或云厂商 Secret Manager，应让控制器把凭据投影到 Pod，而不是复制进 Chart。

NetworkPolicy 默认拒绝入站只是第一步。Agent 可能通过模型请求、Git、curl、包管理器或工具把工作区数据发送到外部。处理不可信仓库时还应考虑默认拒绝出站，仅允许模型 Gateway、代码源和必要软件仓库。

工作区也应坚持最小挂载：不要把宿主 home、SSH 目录、云凭据目录或 Docker Socket整体挂进 Agent 容器。特别是 `/var/run/docker.sock`，它通常等价于把宿主控制权交给容器。

## 12. 容器隔离不等于 Agent Sandbox

| 层 | 主要保护对象 | 不能单独解决的问题 |
| --- | --- | --- |
| Docker/Kubernetes | 宿主目录、capabilities、资源和 Pod 网络 | Agent 在已挂载工作区内的误操作 |
| Harness 审批与 Sandbox seam | 工具调用、文件策略和进程启动 | 容器逃逸、内核漏洞和租户强隔离 |
| gVisor/Kata/VM | 更强内核或虚机边界 | 凭据滥用、业务越权和数据外传 |
| Tool Gateway | 外部 API 身份、授权和审计 | 本地代码执行与宿主隔离 |

Landlock、用户命名空间和原生 helper 能否工作，取决于目标 Linux 内核和容器运行时。不要为了让一次命令成功就增加 `--privileged`、挂载 Docker Socket 或授予宽泛 capabilities。

不可信代码、多用户或联网自动执行场景，应把 Harness 放进独立的 Agent Sandbox、gVisor、Kata 或 VM 边界，配合一次性工作区和默认拒绝出站网络。

## 13. 发布前验证矩阵

| 验证项 | 最低通过条件 |
| --- | --- |
| 版本 | `dsh --version` 等于镜像标签对应的固定版本 |
| 架构 | `linux/amd64` 与 `linux/arm64` 均能构建 |
| 原生模块 | PTY 能实际 spawn，而不只是 npm 安装成功 |
| 用户 | 主进程非 root，工作区文件 UID/GID 符合预期 |
| Web | 健康检查为 200，宿主只监听 `127.0.0.1` |
| EROFS | Web 目录选择器能在 `/workspace` 创建文件夹 |
| 状态 | 强制重建容器或 Pod 后 Profile 与会话仍存在 |
| 信号 | `docker stop` 与 Pod 终止能在宽限期内退出 |
| 权限 | 根文件系统只读、drop ALL、无提权、无 SA Token |
| Compose | 配置渲染、健康检查、重建与卷恢复通过 |
| Helm | `helm lint --strict` 和多组 `helm template` values 通过 |
| 工具 | 真实文件、Shell、PTY 与模型请求成功 |
| 安全 | 无默认公网入口，Secret 不进入 Git 或镜像层 |

HTTP 200 只证明 Web Server 启动；它不能证明凭据正确、PTY 可用、会话可恢复或 Sandbox 生效。镜像发布证据必须覆盖这些互相独立的边界。

## 14. 从本机试用到生产评估

推荐按以下阶段推进：

1. **本机 Compose**：宿主回环端口、可信代码、单用户；
2. **Kubernetes 单副本**：StatefulSet、PVC、Secret、NetworkPolicy 和 port-forward；
3. **隔离执行**：远端 Sandbox 或 gVisor/Kata/VM，收紧出站网络；
4. **企业入口**：OIDC、TLS、授权、审计与 Tool Gateway；
5. **高可用评估**：等待或实现共享状态、任务归属和并发一致性，再考虑多副本。

配套项目把前两个阶段做成可审查的开源基线，而不是宣称当前预览版已经天然适合公网、多租户和水平扩展。

## 15. 项目与后续方向

- GitHub：[runzhliu/deepseek-harness-docker](https://github.com/runzhliu/deepseek-harness-docker)
- Docker Hub：[runzhliu/deepseek-harness](https://hub.docker.com/r/runzhliu/deepseek-harness)
- 源码分析：[DeepSeek Harness GitHub 仓库深度解析](deepseek-harness-repository-analysis.md)

后续可以继续增加：

1. 多架构 OCI 镜像的 SBOM、签名和 provenance；
2. 自动检测上游版本，由 Pull Request 固定并执行升级验证；
3. gVisor/Kata RuntimeClass 示例；
4. OAuth2/OIDC 代理与 Tool Gateway 的受控共享部署；
5. 上游状态后端成熟后的备份、灾备和多副本实验。

## 参考资料

- [DeepSeek Harness 官方仓库](https://github.com/deepseek-ai/deepseek-harness)
- [DeepSeek Harness 架构文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.zh.md)
- [Web Server 子系统](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/web-server.md)
- [持久化目录](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/persistence-catalog.zh.md)
- [上游贡献指南](https://github.com/deepseek-ai/deepseek-harness/blob/master/CONTRIBUTING.zh.md)
- [`@deepseek-ai/dsh` npm 发行物](https://www.npmjs.com/package/@deepseek-ai/dsh)
- [deepseek-harness-docker 配套项目](https://github.com/runzhliu/deepseek-harness-docker)
- [DeepSeek Harness GitHub 仓库深度解析](deepseek-harness-repository-analysis.md)
