---
title: "AgentTeams on Kubernetes: From a Chat Request to Worker Delivery"
description: "A test-cluster deployment of AgentTeams, documenting real Manager, Worker, Matrix, and shared-storage collaboration and its failure boundaries."
status: evolving
last_reviewed: 2026-11-10
---

# AgentTeams on Kubernetes: From a Chat Request to Worker Delivery

How do you know that a multi-agent demonstration actually performed work? A Manager saying “done” in chat is not enough: inspect the delegation, the Worker's output, and the file contents independently. This article deploys AgentTeams in a Kubernetes test cluster, follows a document-organizing task, and preserves screenshots from the real interface.

[AgentTeams](https://github.com/agentscope-ai/AgentTeams) is a multi-agent collaboration project from the AgentScope community: a Manager coordinates Workers, and people observe and participate in Matrix rooms. The project supplies a controller, model gateway, messaging, and shared storage; it is a collaboration platform rather than a model itself. Consult the [official Kubernetes guide](https://github.com/agentscope-ai/AgentTeams/blob/main/docs/usage/deployment/kubernetes.md) and the version being deployed for current details.

## Test environment and architecture

This test used AgentTeams **v1.2.6** in a dedicated test namespace. The controller, Manager, Worker, Element Web, Matrix service, Higress gateway, and MinIO object storage ran on Kubernetes. A local port-forward exposed the page to the workstation, which also supplied a model bridge. No production workloads were involved. Internal addresses are obscured in screenshots; the account and task are test data.

```mermaid
flowchart LR
  U[User / Element Web] --> M[Manager]
  M --> W[Document-organizing Worker]
  W --> S[MinIO shared files]
  W --> R[Matrix room report]
  R --> M
  M --> U
  M --> G[Higress model gateway]
  W --> G
  G --> B[Experimental model bridge]
```

This is a logical illustration of the test, not evidence of network isolation or high availability. Manager and Worker are separately running agents; Kubernetes hosts the workloads and control components, Matrix rooms carry collaboration, and MinIO stores task files.

## Deployment and checks

1. Install the target Helm Chart version in a test namespace with the controller, gateway, Matrix, MinIO, and frontend. Configure persistent volumes, reachable images, and a model service for the environment; keep credentials in restricted Secrets, not public values files.
2. Check that Pods and volumes are ready and that the Manager can reach the model gateway. This experiment used a separate workstation bridge to access the model: it was an environment-specific adaptation, not a universal official architecture.
3. Access Element through a local port-forward such as `kubectl -n <namespace> port-forward svc/higress-gateway 18088:80`. Sign in with a test account and open the Manager room.
4. Submit the task in the Manager room, then inspect the Worker room, runtime state, and task file. A Running Pod alone does not prove model calls or task delivery succeeded.

See the [official Kubernetes deployment guide](https://github.com/agentscope-ai/AgentTeams/blob/main/docs/usage/deployment/kubernetes.md) for installation options and compatibility. Storage, images, and model connectivity depend on the environment.

## Experiment: ask the Manager to create a document-organizing Worker

In Element, we asked the Manager to create `doc-organizer` and supplied three example notes: the model bridge works, the Matrix room is accessible, and the gateway plugin must be obtained from an image accessible inside the cluster. The Worker was asked to categorize the notes, preserve their original text, and report the result.

![Manager receiving a task and reporting the result](../../assets/practices/agentteams-sr1/manager.jpg)

*The real light-theme desktop view shows the Manager reporting Worker status, categorized summaries, and file delivery. Some internal identifiers and paths are obscured. The original Chinese screenshot is preserved.*

The Manager created an OpenClaw-based Worker and posted the assignment in its room. One detail matters: **the administrator sent an additional prompt in the Worker room**. The result demonstrates a human-assisted workflow; it does not establish that the first assignment completed without intervention.

![Worker room showing task execution and report](../../assets/practices/agentteams-sr1/worker.jpg)

*The Worker room shows the Manager's assignment, an additional administrator prompt, and the Worker's completion report. Internal addresses are obscured; the original Chinese screenshot is preserved.*

The Worker reported creating `result.md` with a categorized index, individual summaries, and an overall summary. We read the file in the Worker's task directory and confirmed all three original notes were retained. We then listed the object-storage files read-only and compared the object returned by `mc cat` byte for byte with the Worker's local file; they matched. This verifies that both copies were readable and identical in this test, not long-term storage reliability.

## Further experiments: task splitting, dispatch, and failure observation

We submitted another set of fictional tasks in the same test environment, asking the Manager to reuse the existing Worker, leave cluster configuration alone, and avoid deleting existing files:

| Experiment | Input and acceptance goal | Observed result |
| --- | --- | --- |
| A: metric analysis | 1,000 requests and 25 failures in five minutes; calculate the error rate and state what cannot be inferred | Manager also delegated this to the Worker, despite the request for independent Manager analysis. The expected arithmetic is 2.5%, not a measured Worker result |
| B: classify and deduplicate | Four records, including one duplicate; retain the originals, classify them, and identify the duplicate | The task specification was created and dispatched; no `result.md` was present when checked, so acceptance is incomplete |
| C: missing information | The same records lack timestamps; mark them unknown rather than inventing them | The task specification was created and dispatched; no `result.md` was present when checked, so acceptance is incomplete |

The Manager wrote separate specifications and sent the three tasks to the Worker, whose room displayed a failure to complete the request. The Manager then resent A on its own. At inspection, all three task directories in object storage contained `spec.md` and `meta.json` but no result file; the Worker Pod remained Running. **These were not three successful cases, and a Running Pod does not establish task success.**

![Worker reports failure after receiving additional tasks](../../assets/practices/agentteams-sr1/worker-failure.jpg)

*The real light-theme desktop screenshot shows the Manager's assignments and the Worker's failure message. Internal addresses are obscured; the original Chinese screenshot is preserved.*

At about the same time, Worker logs repeatedly showed `Shared-state read and cleanup failed` and `SQLite database file identity changed before existing-only open`. The errors coincided with the failure, but causation was not established. Preserve logs and investigate the SQLite database and WAL/SHM lifecycle, whether shared-directory synchronization replaces open files, and the runtime version and official known issues. Do not delete the database or blindly retry side-effecting tasks before understanding state-storage semantics. Reproduce in an isolated test environment and verify files and task results before and after any fix.

## Interruption and deployment constraints

The Worker room records that a gateway restart interrupted an earlier session; the Worker reported checking the directory, rebuilding the plan, and finishing. Eventual completion does not establish exact checkpoint resumption, automatic recovery of every side effect, or exactly-once execution.

The model service depended on a workstation bridge, so shutting down the workstation or interrupting the bridge affects inference; the page also depended on a local port-forward. Gateway plugins needed images reachable by the cluster. We also observed the controller resetting the gateway plugin failure policy. Its cause and target-version behavior require further investigation; do not treat the current configuration as a production security boundary.

A production evaluation should cover service identity, secret management, network controls, persistence and backup, Worker resource quotas, external ingress and HTTPS, gateway failure handling, and observability. End-to-end encryption was not enabled in this test room. That does not prove every transport hop lacked encryption, but sensitive data should not be put into this demonstration room. Enforce permissions in the runtime and policy layer rather than relying on prompts alone.

This test covered login, human task submission, Manager-created Worker, room assignment, a follow-up human prompt, file generation, and reporting. **It did not establish concurrency performance, cross-node recovery, production security readiness, or long-term object-storage reliability.** It is a functional exploration, not proof of production readiness.
