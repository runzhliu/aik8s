---
title: "Two Coding Agents, One Baseline: Which Patch Can You Merge?"
description: "Parallel changes, deletion, and conflicting policies, tested with CubeSandbox forks, a real model, and Git."
status: tested
last_reviewed: 2026-11-23
applicable_versions: "CubeSandbox v0.8.0"
tested_environment: "Kubernetes v1.37.2, x86_64 KVM, one Cube compute node"
---

# Two Coding Agents, One Baseline: Which Patch Can You Merge?

Before running two coding agents in parallel, decide who owns acceptance. We asked A to charge 5% and B to charge 8%. Both edited isolated copies of the same code and returned passing tests. The sandbox let them explore independently. Choosing what to ship required a pricing rule defined outside either candidate.

![Outputs from both agents and Git review](../../assets/rag-agent/cubesandbox-five-labs/edits-terminal.png)

*The terminal checks the archived patches and run results. Both alternatives used the same four integer-cent inputs.*

## Starting both workers from the same tree

The parent initialized a three-file Git repository, committed it, and removed write permissions from the baseline directory. One `fork(count=2)` produced two child sandboxes. Each used `git clone --no-hardlinks` to create a separate writable checkout. The external orchestrator called the model concurrently and retained its credentials. Public Internet access was disabled for both workspaces. The baseline fee function returned zero.

The model returned file contents and deletion intent. The driver allowed only the task paths, wrote each result in its own child, ran four assertions, and exported a patch with `git diff --cached`. The initial code template lacked Git. The measured run used a template with both Git and Python. Verify both binaries in the final template before starting.

## How two agents can edit one baseline independently

Two copy operations serve different purposes. On `fork`, CubeMaster snapshots the source once and derives multiple instances from that snapshot. In v0.8.0 a single request runs at most eight derivations concurrently. The SDK returns success or failure per child, and successful siblings survive a failure. A controller should record the successful IDs, keep those candidates, replace only the missing slot, and clean up each instance at the end. Pin the original baseline for retries. Deriving from a parent edited in the meantime would mix revisions in the comparison. Eight is an implementation limit, not a recommendation for team size. [CubeMaster derivation code](https://github.com/TencentCloud/CubeSandbox/blob/v0.8.0/CubeMaster/pkg/service/httpservice/cube/fork.go#L32-L110) · [Python SDK partial-success contract](https://github.com/TencentCloud/CubeSandbox/blob/v0.8.0/sdk/python/cubesandbox/sandbox.py#L1156-L1172)

Cloning the Git repository inside each guest kept a baseline available for verification and gave each worker a checkout from which to export its changes. A’s deletion entered A’s patch. B and the parent could still inspect the baseline. Mounting a common writable checkout in both guests would reintroduce shared writes. Independent Git worktrees can suffice for text-only edits that share dependencies. Separate guests become useful when candidates install different dependencies, build software, or execute code and therefore need independent processes and runtime environments.

## Reviewing the two patches

| Candidate | Output on 0, 99, 100, 12345 cents | Other changes |
| --- | --- | --- |
| A · 5% | 0, 4, 5, 617 | Updated policy and removed the legacy file |
| B · 8% | 0, 7, 8, 987 | Updated policy and retained the legacy file |

The reviewer opened a third checkout in the parent, checked A, applied it, and verified both the deletion and the 617-cent result. Running `git apply --check` on B now returned nonzero. The baseline worktrees in the parent and both children remained clean. Sandbox isolation contained writes, Git exposed the overlapping edits, and the review rule selected the 5% policy.

![Git output from both children and the reviewer](../../assets/rag-agent/cubesandbox-five-labs/edits-live.png)

*A repeat run supplied this transcript. A deleted the legacy file, B retained it, and the review checkout reported conflicts in both shared files.*

[Read the transcript excerpt](../../assets/data/cubesandbox-five-labs/edits-live.txt)

## Applying the pattern to a team

Give the reviewer the baseline commit, requirements, patches, test commands, and outcomes. Changes to disjoint files can still have incompatible behavior. Run integration tests after merging. The Kakurizai case also describes a shared baseline and change layers. This exercise used native forks and independent Git clones rather than deploying that application.

### Why passing tests still leaves a review decision

The original four assertions were generated using each candidate’s assigned rate, so A and B both scored 4/4. Now suppose the product owner has fixed the policy at 5% rounded down. Apply **one shared oracle** to the archived outputs. A still scores 4/4. B only passes the zero input and scores 1/4. A zero-amount smoke test would miss the wrong rate. The 99- and 100-cent inputs straddle the boundary where a 5% fee rises from four to five cents. These examples do not define refund or negative-amount behavior. Specify that policy before adding refund acceptance cases.

This suggests two ways to assign work. For **competing implementations**, give agents the same problem, freeze business examples in advance, and select a passing candidate. For **parallel contributions**, one agent might own pricing and another billing display. Agree on units, rounding, and the interface, then test a complete invoice after integration. Even if Git cleanly applies both patches, one module can emit cents while another treats the value as whole currency units. `git apply --check` answers whether a patch applies. The business oracle catches the units error. [Git patch checking](https://git-scm.com/docs/git-apply)

A and B intentionally received different requirements here. Selecting A cannot rank model ability. To evaluate the value of additional agents, give single-agent and multi-agent runs the same tasks and independent oracle. Count model calls, sandbox time, and human review minutes per accepted solution. The present experiment establishes the isolation and review behavior.

Download the [raw data](../../assets/data/cubesandbox-five-labs/edits.json) and [verification script](../../assets/data/cubesandbox-five-labs/verify.py) into one directory and run the command below.

```sh
python3 verify.py edits
```

[Download the lab scripts](../../assets/data/cubesandbox-five-labs/lab-sources.zip). After extracting them, configure the endpoint and templates as described in the README. Start with `edit.py`.

[Upstream Kakurizai case study](https://github.com/TencentCloud/CubeSandbox/blob/6843e3f97e67/docs/guide/usecases/kakurizai.md)
