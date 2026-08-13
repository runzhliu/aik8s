# DeepSeek Harness 刚开源，我先把 Docker、Compose 和 Helm 补齐了

DeepSeek 最近开源了一个新项目：**DeepSeek Harness**。

看到名字，很多人的第一反应可能是：DeepSeek 又开源了一个推理框架？

并不是。

DeepSeek Harness 不是模型权重，也不是 vLLM、SGLang 这一类推理引擎。它更接近一套完整的 **AI Agent Runtime**：模型适配、会话、工具、权限、工作区、子 Agent、Web UI 和 Headless 入口，都在同一个运行时里完成组装。

官方给出的启动方式很简单：

```bash
npx @deepseek-ai/dsh web
```

但我真正想做的，不是把这条命令再抄一遍。

我想回答的是另一个问题：

> 如果要把 DeepSeek Harness 当成一个可以复现、分发和部署的开源项目，它的 Dockerfile、Docker Compose、Kubernetes YAML 和 Helm Chart 应该怎么做？

于是，我们把它做成了一个独立的社区项目：`deepseek-harness-docker`。

现在它已经包含：

- 多阶段、非 Root 的 Dockerfile；
- 默认只监听宿主回环地址的 Docker Compose；
- 单副本 StatefulSet、PVC、Service 和 NetworkPolicy；
- 可直接安装的 Helm Chart；
- `linux/amd64` 与 `linux/arm64` 双架构镜像；
- 中英文 README、CI、Smoke Test、Security Policy 和真实运行截图；
- 已发布到 Docker Hub 的社区镜像。

这篇文章既讲 DeepSeek Harness 到底是什么，也完整复盘我们把它容器化时遇到的几个关键问题。

## DeepSeek Harness 到底是什么

DeepSeek 官方把它称为 Agent Harness。

它的底层由 Cordis 驱动，核心设计可以概括成一句话：**一切皆插件。**

模型适配器是插件，工具注册表是插件，会话日志是插件，Agent Loop 是插件，Web Server 也是插件。运行中的 `dsh`，本质上是一棵在启动时被组装出来的插件树。

```text
dsh CLI
  │
  ▼
Profile
  │
  ├─ Base Bundle
  ├─ Web / Headless Bundle
  ├─ 用户 cordis.patch.yml
  └─ 命令行 --patch
  │
  ▼
Cordis Plugin Tree
  │
  ├─ Agent / Session / LLM
  ├─ Tools / Filesystem / Shell / PTY
  ├─ Permission / Sandbox / Approval
  ├─ Web Surface
  └─ Headless Surface
```

这里有两个重要概念。

第一个是 **Profile**。

官方发行物内置了 `web` 和 `headless` 两类 Profile。`web` 启动浏览器交互界面，`headless` 面向 CLI、CI 或一次性任务。它们共享同一套 Agent 核心和状态模型，不是两套互不相干的实现。

第二个是 **Bundle 与 patch**。

Profile 不是一份不能修改的最终配置。Bundle、用户 patch 和命令行 `--patch` 会按顺序叠加，后面的配置可以通过稳定 ID 覆盖前面的插件条目。

这条机制后来成为容器化的关键：我们不需要 fork DeepSeek Harness 源码，就可以用一份容器专用 Cordis overlay 修改 Web Server 的监听地址。

## 它的 Agent 是怎样运行的

DeepSeek Harness 区分 Turn 和 Step。

一个 Step 是一次模型请求，以及随后发生的工具调用；一个 Turn 可以包含多个 Step，直到工具不再要求继续请求，也没有新的用户输入需要处理。

```text
用户输入
  │
  ▼
turn/start
  │
  ├─ step/start
  ├─ 组合 System Prompt 与 Tool Schema
  ├─ 请求 LLM
  ├─ assistant/chunk*
  ├─ assistant/message
  ├─ tool/call → execute → tool/result
  └─ step/end
  │
  ▼
turn/end
```

它还有一个很重要的原则：**模型可见即已记录。**

模型真正看到的上下文，必须能够从 Session 事件日志重建。会话恢复、Fork、Transcript、上下文压缩和 UI 回放，都是从这条事件流派生出来的。

这意味着，容器中的会话目录不是普通缓存。

如果 Pod 重建时把这些数据丢了，损失的不只是聊天记录，还会改变 Agent 的恢复语义。

也正因为如此，DeepSeek Harness 更适合放在“AI Agent Runtime 云原生化”专题，而不是“LLM 推理部署”专题。

## 为什么不能只写一行 npx

一个最简单的镜像看起来可能是这样：

```dockerfile
FROM node
RUN npm install -g @deepseek-ai/dsh
CMD ["dsh", "web"]
```

它很可能能构建，甚至能启动。

但从“进程启动”到“一个可交付的容器项目”，中间至少还隔着六个关键问题。

## 第一个问题：到底应该打什么版本 Tag

我们最终发布的镜像是：

```text
runzhliu/deepseek-harness:0.1.0-rc.6
```

这个版本不是社区项目自己定义的。

它与官方 npm 发行物严格对应：

```text
@deepseek-ai/dsh@0.1.0-rc.6
                 │
                 ▼
runzhliu/deepseek-harness:0.1.0-rc.6
```

有意思的是，在我们完成构建时，npm Registry 的最新可安装版本已经是 `rc.6`，但 GitHub 公开 `master` 中的 CLI `package.json` 仍标记为 `rc.5`。

我们封装的是官方 npm 成品，而不是从 GitHub 源码重新编译，所以选择以可安装发行物为准。

同时，我们没有发布 Docker `latest`。

DeepSeek Harness 仍处于 Developer Preview 和 RC 阶段。固定完整版本，才能让一次构建、一个问题和一组测试结果准确对应。等 `rc.7` 出现后，应该走一次显式升级和回归，而不是让已有部署悄悄漂移。

## 第二个问题：原生 Node 模块和双架构

上游要求 Node.js `^22.19.0 || >=24.0.0`，我们把 Node 24 作为镜像基线。

但真正容易踩坑的是 `node-pty`。

Harness 的 Shell 和终端能力依赖原生模块。某些 CPU 架构没有直接可用的预编译产物，npm 会回退到 `node-gyp` 本地编译。第一版 arm64 构建就因为缺少 make 和编译工具链而失败。

最终 Dockerfile 使用多阶段构建：

```text
Builder
  ├─ Python
  ├─ build-essential
  ├─ node-gyp
  └─ npm install @deepseek-ai/dsh@固定版本

Runtime
  ├─ Node.js 24 slim
  ├─ Git / SSH / Python / ripgrep / tini
  ├─ 已编译的 DSH 与原生模块
  └─ 不包含 gcc / make
```

最后的验证也不是只执行一次 `require('node-pty')`。

我们在 `linux/amd64` 和 `linux/arm64` 上都实际创建 PTY、启动 `/bin/sh`，并确认返回 `PTY_OK`。模块能加载，不代表原生 helper 一定能真正创建进程；这两个测试不是一回事。

## 第三个问题：容器需要 0.0.0.0，但官方为什么阻止它

Docker bridge 的端口转发要求容器内进程监听非 Loopback 地址。

如果 DSH 只监听容器内的 `127.0.0.1`，宿主的 `-p 3080:3080` 无法正常访问它。

最自然的想法是：

```bash
dsh web --host 0.0.0.0
```

但官方 CLI 会主动阻止这种直接改法。

原因不是“容器支持没做好”，而是一个明确的安全决策：当前 Web Server 没有 TLS、身份认证和 Origin Policy，背后的 Agent 工具还可以读写文件、启动 Shell 和执行代码。

把它直接监听到局域网或公网，相当于暴露一个无认证的代码执行入口。

我们的处理方式是分成两层：

```text
浏览器
  │ http://127.0.0.1:3080
  ▼
宿主回环端口
  │ Docker Port Forward
  ▼
容器内 0.0.0.0:3080
  │
  ▼
DeepSeek Harness Web
```

容器内部通过官方 Cordis patch 机制，把 `webserver` 插件改为监听 `0.0.0.0`：

```yaml
- id: webserver
  name: '@deepseek-ai/dsh-host-webserver'
  config:
    host: '0.0.0.0'
    port: !!js ctx.webStartup.port ?? 3080
```

Docker Compose 则只允许宿主回环访问：

```yaml
ports:
  - "127.0.0.1:3080:3080"
```

内部监听和外部暴露是两个不同的安全边界。

把端口简化为 `-p 3080:3080`，或者把它改成 Kubernetes NodePort、LoadBalancer 和公开 Ingress，都会破坏这个模型。

## 第四个问题：页面启动后为什么又崩了

第一版容器成功返回页面后，很快又出现了另一个错误：

```text
--expose-internals is required for HMR service
```

Web Profile 在启动后会挂载配置 watcher，当前 HMR 服务需要访问 Node Internals。

最简单的处理是设置：

```text
NODE_OPTIONS=--expose-internals
```

但这会被 Agent 创建的所有 Node 子进程继承，扩大一个本来只属于 DSH Host 的运行参数。

我们最终把它只放在容器入口里：

```dockerfile
ENTRYPOINT [
  "/usr/bin/tini", "--",
  "node", "--expose-internals",
  "/usr/local/lib/node_modules/@deepseek-ai/dsh/lib/bin.js"
]
```

只给主进程需要的权限，不把它传播给 Agent 启动的工具进程。

## 第五个问题：那个 EROFS 到底是怎么来的

容器运行起来后，我们在 Web 里新建文件夹，遇到了这条错误：

```text
EROFS: read-only file system, mkdir '/home/node/test'
```

![只读根文件系统下 Web 目录选择器创建文件夹失败](assets/deepseek-harness-eroFS.png)

这个问题很有代表性。

为了收紧容器权限，我们启用了只读根文件系统。`/home/node` 属于镜像层，不能写；但 Web 目录选择器使用 Node.js 的 `os.homedir()` 作为浏览首页，而它当时返回的正是 `/home/node`。

错误的修法有两个：

- 关闭只读根文件系统；
- 直接改成 Root 用户运行。

这两种方式都只是把路径错误藏起来。

真正应该做的是，把交互主目录指向已经明确挂载为可写的工作区：

```dockerfile
ENV HOME=/workspace
```

同时保持 Harness 自己的状态目录独立：

```text
HOME=/workspace
DSH_HOME=/home/node/.dsh
```

两条路径各自承担不同职责：

```text
/workspace
  └─ 用户代码和 Agent 实际操作的文件

/home/node/.dsh
  ├─ profiles
  ├─ settings.yaml
  ├─ credentials
  ├─ sessions
  └─ storages
```

修复以后，Web 目录选择器的首页是 `/workspace`，新建目录落在可写挂载中，而容器根文件系统仍然保持只读。

## 第六个问题：PID 1 和 Agent 子进程

普通 Web 服务可能只需要一个长期 Node 进程，但 Agent Runtime 会创建 Shell、PTY、语言服务和其他子进程。

如果直接让 Node 充当容器 PID 1，信号转发和孤儿进程回收可能出现不一致。

镜像加入 `tini`，让它负责：

- 向 DSH 转发 Docker/Kubernetes 终止信号；
- 回收已经退出的孤儿进程；
- 让 `docker stop` 和 Pod 终止宽限期更可控。

它不是一个华丽功能，但属于 Agent 容器能否稳定停止的基础工程。

## Docker Compose 最终表达了什么

最后的 Compose 文件不只是“少打一串 docker run 参数”，它把支持边界写进了配置：

- 镜像固定为 `runzhliu/deepseek-harness:0.1.0-rc.6`；
- 宿主只发布 `127.0.0.1:3080`；
- `dsh-home` 命名卷持久化 Profile、设置和会话；
- 用户指定的代码目录挂载到 `/workspace`；
- Root Filesystem 只读；
- `/tmp` 使用独立 tmpfs；
- Drop 全部 Linux Capabilities；
- 启用 `no-new-privileges`；
- 限制最大进程数；
- 通过容器内部 HTTP 请求执行 Health Check。

现在启动只需要：

```bash
git clone https://github.com/runzhliu/deepseek-harness-docker.git
cd deepseek-harness-docker

docker compose pull
DSH_WORKSPACE=/absolute/path/to/project \
  docker compose up -d --no-build
```

然后打开：

```text
http://127.0.0.1:3080
```

这是最终从 Docker Hub 新拉取镜像、使用全新状态卷启动后的真实页面：

![DeepSeek Harness Docker 干净实例的真实运行页面](assets/deepseek-harness-docker-web.png)

截图里没有 API Key、会话内容、宿主路径或私有工作区名称。

## Kubernetes 为什么选择 StatefulSet

项目同时提供了 Helm Chart。

这里我们没有使用多副本 Deployment，而是固定为单副本 StatefulSet。

原因很简单：当前 Harness 是有状态、单用户的 Agent Runtime。

Profile、模型设置、凭据、Session Event Log 和 Workspace 索引都具有状态；目前也没有证据表明多个副本可以安全并发写同一套本地数据。

如果只是把 `replicas` 改成 3，并不会自动获得高可用，反而可能制造状态竞争。

Chart 的结构是：

```text
可信运维人员
  │ kubectl port-forward
  ▼
Headless Service
  │
  ▼
StatefulSet（replicas=1）
  ├─ /home/node/.dsh → PVC
  ├─ /workspace      → existing PVC / emptyDir
  └─ /tmp            → Memory emptyDir
```

同时加入了这些默认值：

- PVC Retention Policy 为 Retain；
- `automountServiceAccountToken: false`；
- UID/GID 1000；
- `RuntimeDefault` Seccomp；
- 只读 Root Filesystem；
- Drop ALL Capabilities；
- 禁止 Privilege Escalation；
- 默认拒绝 Pod 入站流量的 NetworkPolicy；
- 不创建 Ingress 或 LoadBalancer；
- Provider 凭据通过已有 Secret 注入。

安装方式：

```bash
helm upgrade --install deepseek-harness \
  charts/deepseek-harness \
  --namespace deepseek-harness \
  --create-namespace
```

访问仍然通过 API Server 转发：

```bash
kubectl -n deepseek-harness \
  port-forward service/deepseek-harness 3080:3080
```

当前版本明确不把 Kubernetes 部署包装成公共 SaaS 服务。

未来只有在上游具备身份认证、租户隔离、并发安全的共享状态后端和明确的横向扩展契约后，才适合讨论多副本 Deployment 或公开入口。

## 容器不是 Agent Sandbox

这是整个方案里最容易被误解的一点。

容器限制的是 DSH 进程能够看到哪些宿主文件、Capabilities、资源和网络；Harness 自己的审批与 Sandbox，则限制 Agent 工具在这个容器内部可以做什么。

```text
Docker / Kubernetes
  └─ 保护宿主机和挂载边界

Harness Permission / Sandbox
  └─ 约束 Agent 工具行为

gVisor / Kata / VM
  └─ 为不可信代码提供更强隔离

Tool Gateway
  └─ 管理外部 API 的身份、权限和审计
```

这几层不能互相替代。

我们不会为了让某次 Shell 调用成功，就给容器加 `--privileged`、挂载 Docker Socket 或授予宽泛 Capabilities。对于公网用户提交的代码或强对抗多租户场景，普通容器也不是充分安全边界，应继续使用 gVisor、Kata 或独立 VM，并默认限制出站网络。

## 最后到底验证了什么

“页面能打开”只是整个验证矩阵里的一个格子。

最终我们完成了这些检查：

1. `linux/amd64` 与 `linux/arm64` 均可构建；
2. 两个架构都实际创建原生 PTY，并得到 `PTY_OK`；
3. `dsh --version` 与固定构建版本一致；
4. Cordis 最终配置中的容器监听地址是 `0.0.0.0`；
5. Compose 首页返回 HTTP 200，容器进入 Healthy；
6. 强制重建后，`DSH_HOME` 状态仍然保留；
7. Web 目录首页变为 `/workspace`，不再出现 `/home/node` EROFS；
8. Root Filesystem、UID、Capabilities 和宿主回环绑定符合预期；
9. `helm lint --strict` 以及持久化、临时存储两组模板渲染通过；
10. 从 Docker Hub 分别拉取两个平台镜像后，再次完成 CLI、配置、PTY 和 Web Smoke Test。

最终发布的 OCI Index 是：

```text
docker.io/runzhliu/deepseek-harness:0.1.0-rc.6

sha256:1027950ebf5374e9b75961ad6009c912
       da85f56562e160dc191046151ea09f9f
```

镜像同时带有两个平台各自的 SBOM 和 Build Provenance Attestation。

## 这是不是官方镜像

不是。

这是一个独立的社区容器项目，不代表 DeepSeek 官方发布。

截至项目完成时，上游仓库没有 Dockerfile、Compose 或 Kubernetes 清单；上游贡献指南也说明当前暂不接受外部 Pull Request，并鼓励社区创建生态项目和教程。

因此，我们没有把它包装成“官方镜像”，而是完整保留了来源、版本和支持边界：

- DSH 来自官方 MIT 许可的 npm 发行物；
- Dockerfile、Compose、Helm 和文档由社区项目维护；
- 镜像 OCI Metadata 指向独立项目；
- README 明确声明无认证 Web UI 的部署限制；
- 每次上游版本升级都必须重新执行双架构与运行时验证。

## 写在最后

这次工作一开始看起来只是“给新项目写一个 Dockerfile”。

真正做下去以后，我们处理的是一整组运行时契约：原生模块、配置叠加、Web 暴露、HMR、主目录、状态持久化、PID 1、Pod Security、NetworkPolicy 和双架构供应链。

最值得保留的也不是某一条 Docker 命令，而是三个边界：

1. 容器内部监听 `0.0.0.0`，不等于允许宿主对外暴露；
2. `/workspace` 是用户工作区，`$DSH_HOME` 是 Harness 的持久状态；
3. 容器安全基线，不等于不可信 Agent 代码已经获得强隔离。

如果你只想快速体验 DeepSeek Harness，官方的 `npx` 已经足够。

如果你希望把它作为一个可复现、可审查、可持续升级的 Agent Runtime 部署，那么 Dockerfile 只是起点，Compose、StatefulSet、PVC、Secret、网络边界和验证证据必须一起出现。

项目地址：

```text
https://github.com/runzhliu/deepseek-harness-docker
```

Docker Hub：

```text
https://hub.docker.com/r/runzhliu/deepseek-harness
```

完整的 DeepSeek Harness 架构、运行机制和容器化分析，将放在“阅读原文”的 aik8s.run 专题文章中。
