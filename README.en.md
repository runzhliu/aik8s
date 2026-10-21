# AI/LLM on Kubernetes Infrastructure Knowledge Base

[简体中文](README.md) | [English](README.en.md)

Hi, I'm runzhliu 👋. I'm an engineer with ten years of experience in AI/LLM, big data, and Kubernetes, and I enjoy keeping detailed notes. This site brings together notes from my work on AI/LLM infrastructure over the past few years, with some language-model-assisted editing. I hope it provides a place to exchange ideas and learn together. Whether you want to discuss an article or the work behind it, feel free to reach out at runzhliu@163.com.

Engineering documentation for platform engineers, SREs, training teams, model serving teams, and agent platform teams.

The documentation covers Kubernetes, GPU/LLM infrastructure, and agent engineering through architecture and source analysis, deployments, performance tests, troubleshooting, and migrations. Model experiments aim to retain versions, hardware, request conditions, raw results, and monitoring screenshots. Community designs, production metric observations, and local experiments each explain their evidence and scope.

Website: [English](https://aik8s.run/en/) · [简体中文](https://aik8s.run/)

## Where to Start

| Your area of interest | Topics and reading paths |
| --- | --- |
| Kubernetes reliability and scale | [Fleet reliability](translations/en/ai-k8s/practices/kubernetes-fleet-reliability.md), [large-cluster optimization](translations/en/ai-k8s/practices/large-scale-kubernetes-optimization.md), [scheduler optimization](translations/en/ai-k8s/practices/large-scale-kubernetes-scheduler-optimization.md), [API Server load balancing](translations/en/ai-k8s/practices/kube-apiserver-load-balancing.md) |
| GPU platforms and resource scheduling | [GPU node stack](translations/en/ai-k8s/cluster/gpu-node-stack.md), [device management and DRA](translations/en/ai-k8s/accelerators/device-management.md), [queues and multitenancy](translations/en/ai-k8s/queue-multitenancy.md), [Koordinator colocation](translations/en/ai-k8s/scheduling/koordinator-colocation.md) |
| LLM inference and model testing | [Inference platform overview](translations/en/ai-k8s/llm-inference.md), [engine selection](translations/en/ai-k8s/inference/engines.md), [KV cache](translations/en/ai-k8s/inference/kv-cache-overview.md), [practice and troubleshooting index](translations/en/ai-k8s/practices/index.md) |
| Training, storage, and recovery | [Distributed training and checkpoint recovery](translations/en/ai-k8s/training/distributed-training-frameworks-recovery.md), [SFT fundamentals](translations/en/ai-k8s/training/sft-concepts.md), [model artifacts and distribution](translations/en/ai-k8s/data/model-artifacts.md) |
| Agent execution, memory, and evaluation | [Harnesses](translations/en/ai-k8s/rag-agent/agent-harness-technology-overview.md), [memory](translations/en/ai-k8s/rag-agent/agent-memory-technology-overview.md), [evaluation methods](translations/en/ai-k8s/rag-agent/agent-evaluation-overview.md), [resuming long-running tasks](translations/en/ai-k8s/rag-agent/agent-long-running-durable-execution.md) |
| Sandboxes and enterprise agent platforms | [Sandbox selection](translations/en/ai-k8s/rag-agent/agent-sandbox-selection.md), [Firecracker and CubeSandbox](translations/en/ai-k8s/rag-agent/firecracker-cubesandbox-enterprise-selection.md), [OpenSandbox practice](translations/en/ai-k8s/rag-agent/opensandbox-kubernetes-practice.md), [OpenClaw Enterprise practice](translations/en/ai-k8s/rag-agent/openclaw-enterprise-kubernetes-practice.md) |
| Networking and observability | [Contiv to Kube-OVN migration](translations/en/ai-k8s/practices/contiv-to-kubeovn-underlay.md), [OpenTelemetry fundamentals](translations/en/ai-k8s/opentelemetry-kubernetes-fundamentals.md), [Kubernetes components and Grafana practice](translations/en/ai-k8s/practices/opentelemetry-kubernetes-components-grafana.md), [large-scale monitoring and time-series databases](translations/en/ai-k8s/practices/large-scale-kubernetes-monitoring-tsdb.md) |

See the [technology map](translations/en/ai-k8s/index.md) for the complete index. For platform planning, start with the [production reference architectures](translations/en/ai-k8s/guides/reference-architectures.md) and [cluster component checklist](translations/en/cases/ai-cluster-component-checklist.md).

## Practice and Technical Analysis

| Article | Main topics |
| --- | --- |
| [DeepInfer deep dive](translations/en/ai-k8s/inference/deepinfer-architecture-analysis.md) | Source architecture, performance definitions, hardware restrictions, and production integration boundaries |
| [Agent RL: veRL and Miles](translations/en/ai-k8s/rag-agent/agent-rl-verl-miles-overview.md) | Tool calls, interaction trajectories, reward design, and training frameworks |
| [OpenSandbox on Kubernetes](translations/en/ai-k8s/rag-agent/opensandbox-kubernetes-practice.md) | Official Console, task execution, automatic cleanup, and a CubeSandbox comparison |
| [Single-node Contiv to Kube-OVN migration](translations/en/ai-k8s/practices/contiv-to-kubeovn-underlay.md) | Preserving physical VLANs while validating IPAM, bidirectional connectivity, and monitoring |
| [DeepSeek 1017 Day0](translations/en/ai-k8s/practices/deepseek-v41-flash-1017-day0.md) | vLLM deployment, performance tests, and a million-token experiment on eight H20 GPUs |
| [DeepSeek: PRO 5000 and H20 production observations](translations/en/ai-k8s/practices/deepseek-v41-pro5000-h20-observation.md) | Hardware differences and daily performance from production metrics, without additional load testing on production services |
| [Qwen-Image-2.1 on one L20 with two engines](translations/en/ai-k8s/practices/qwen-image21-l20-benchmark.md) | Image generation, editing, native resolutions, and memory limits |
| [Koordinator Webhook certificate-race investigation](translations/en/ai-k8s/practices/koordinator-webhook-multireplica-cert-race.md) | A multi-replica certificate problem in a custom access environment, its fix, and before/after metrics |

## WeChat Official Account

Hands-on AI/LLM on Kubernetes articles, deployment notes, and performance analyses are also shared through the WeChat official account **AI-K8S技术工程**. Scan the QR code with WeChat or search for `AI-K8S技术工程` in WeChat Search:

<p align="center">
  <img src="docs/assets/wechat-official-account-promo.png" alt="Scan the QR code or search WeChat for the AI-K8S技术工程 official account" width="900">
</p>

## Reading, Feeds, and Feedback

- Chinese and English articles are paired and can be switched through the site's language menu. Articles display publication and update dates.
- The site provides search, an article timeline, and topic filters. Article images and Mermaid diagrams can be enlarged by clicking them.
- RSS: [Chinese](https://aik8s.run/rss.xml) · [English](https://aik8s.run/en/rss.xml); Atom: [Chinese](https://aik8s.run/atom.xml) · [English](https://aik8s.run/en/atom.xml). `/feed.xml` and `/en/feed.xml` are feed aliases.
- Feeds contain articles only; asset directories, supporting README files, and section landing pages are excluded.
- Articles support link copying and sharing. Comments use [Giscus](https://github.com/giscus/giscus) with this repository's GitHub Discussions. Issues and pull requests are welcome for corrections.

## Local Preview

The site uses Markdown and Zensical, with navigation and theme settings in `zensical.toml`. `make dev` runs a pinned Zensical image through Docker. A complete bilingual build also requires Python 3.11 or later on the host:

```bash
make dev
```

Open <http://localhost:8000>. This development command previews the Chinese source with automatic reload. For a complete bilingual preview, run `make build`, then `python3 -m http.server 8000 --directory site`. The English version is available at <http://localhost:8000/en/>.

You can also use a Python virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/zensical serve
```

Both `serve` workflows above preview Chinese only. To build the bilingual site without Docker, activate the virtual environment containing the installed dependencies and run:

```bash
source .venv/bin/activate
python scripts/build_bilingual.py
python -m http.server 8000 --directory site
```

## Bilingual Build and Publication

```bash
make build
```

This command checks bilingual coverage and synchronization, then builds Chinese and English in strict mode. Output is written to `site/` and `site/en/`; generated files are excluded from Git. English has its own navigation, search, feeds, and page language metadata. The language menu switches to the corresponding article.

The ordinary bilingual build already generates article dates, RSS/Atom feeds, the article timeline, a sitemap with modification dates, sharing controls, social metadata, and TechArticle/BreadcrumbList structured data. The following command additionally injects production advertising and analytics scripts:

```bash
make build-production
```

Publication and update dates appear below article titles in Beijing time. The publication date comes from the file's first appearance in Git history, following renames. The update date is the later of its most recent commit and `last_reviewed` metadata. Dates are generated by `build_distribution.py` during the bilingual build and do not change simply because the site is rebuilt. Run `make build` to preview them locally.

After a push to `main`, GitHub Actions checks bilingual integrity, internal links, images, browser interactions, and asset sizes, then publishes the artifact to the `site-production` GitHub Release. The server pulls and verifies artifacts over HTTPS, installs them into a new release directory, and atomically switches `/srv/aik8s/current`. A failed post-activation health check triggers rollback.

See [Server-pull deployment](ops/aik8s-pull-deploy/README.md) for the current deployment procedure and [.github/workflows/deploy.yml](.github/workflows/deploy.yml) for the workflow.

## Adding Content

Public documentation includes complete Chinese and English versions by default. Chinese sources live in `docs/`; English sources live in `translations/en/` at identical relative paths. When adding, updating, or moving a Chinese page, update its English counterpart, `translations/navigation.en.json`, and `translations/manifest.json` as well. An English summary or a Chinese fallback page does not replace a full translation. See the [bilingual publishing guide](translations/README.md).

Directory and file names form public URLs. Use lowercase English letters, digits, and hyphens; put Chinese display names in the main heading or the `nav` configuration in `zensical.toml`. Existing Chinese URLs remain unchanged. English URLs add the `/en/` prefix.

Test and benchmark plans stay in the local `.local/test-plans/` directory and are excluded from GitHub and the site source tree. Public documentation contains completed measurements, verified fixes, and reproducible materials. Any pending plans embedded in an existing report should first be moved to local storage. Some historical result reports retain URLs containing `plan` to preserve existing links.

Each section should have an `index.md`, for example:

```text
docs/
└── kubernetes/
    ├── index.md
    ├── basic-concepts.md
    └── cluster-deployment.md
```

After adding or moving pages, update navigation in `zensical.toml`. Before committing, run:

```bash
python3 scripts/bilingual.py
make build
git diff --check
```

Keep this README and its [Chinese counterpart](README.md) synchronized too. After reviewing both, run `python3 scripts/record_translation.py --readme` to update their synchronization record.

## Project Structure

```text
.
├── docs/                  # Markdown documentation and static assets
│   ├── ai-k8s/            # Core AI/LLM on Kubernetes topics
│   ├── cases/             # Engineering checklists and case index
│   ├── k3s-upgrade/       # Cluster upgrade case study
│   └── assets/            # Article images, charts, and experiment screenshots
├── examples/              # Public examples, scripts, and experimental results
├── articles/wechat/       # WeChat manuscripts and illustrations
├── overrides/             # Site templates
├── ops/aik8s-pull-deploy/  # Current server-pull deployment procedure
├── deploy/                # Deployment examples and historical instructions
├── scripts/               # Bilingual build, content checks, and publishing tools
├── translations/          # English documentation, navigation, and synchronization records
├── zensical.toml          # Site navigation and theme configuration
├── requirements.txt       # Local Python build dependencies
└── Makefile               # Local preview and build entry points
```
