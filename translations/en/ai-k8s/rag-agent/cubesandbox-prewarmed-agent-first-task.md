---
title: "Prewarming a CubeSandbox Tool: Time to the First Valid Answer"
description: "Forty alternating runs separate create latency, tool readiness, and the first correct search result."
status: tested
last_reviewed: 2026-11-23
applicable_versions: "CubeSandbox v0.8.0"
tested_environment: "Kubernetes v1.37.2, x86_64 KVM, one Cube compute node"
---

# Prewarming a CubeSandbox Tool: Time to the First Valid Answer

When choosing a template for a search agent, start the clock where the user starts waiting. Stopping at the create response misses an index built on first use. In 20 paired trials on one KVM node, saving the ready index in a full snapshot brought median time to a correct result from 590 ms to 377 ms. That helps typical latency. A promise to finish every request within one second also has to account for the slowest restore.

![Three cumulative timings for lazy and warm initialization](../../assets/rag-agent/cubesandbox-five-labs/prewarm-latency.png)

*All three clocks start at the create request. Bars show medians over 20 observations per group in milliseconds.*

## Isolating the state of the index

Both snapshots had the same base image and running Python HTTP service. The first was captured before indexing. The second included an in-memory SQLite FTS5 index over the same 16,000 synthetic runbook entries. Both paths restore a snapshot. Cold refers specifically to index state. Each observation used a fresh writable instance that was released after the query.

The fixed query was `component7 AND symptom3`. A remote SDK driver called the HTTP service inside each guest, running `/alive`, `/prepare`, and `/query` in both groups. The first probe checked the initial state, the second ensured readiness idempotently, and the last had to return exactly 19 hits. Odd and even rounds ran the two variants in opposite order.

## What work does prewarming actually remove?

Imagine putting Python, SQLite, and all 16,000 source records in the image. The files are on disk at startup, but the service still has to open a database, tokenize the text, and build an inverted index. This database is named `:memory:`. The index lives in the service process that owns the connection. Restoring just the program and its dependencies from a filesystem snapshot would still incur the build. A full snapshot also saves guest memory, so the restored service can use its existing connection. If the application can open a prebuilt index file, benchmark that simpler alternative too. Its storage and startup costs will differ. [SQLite in-memory databases](https://www.sqlite.org/inmemorydb.html) · [v0.8.0 snapshot semantics](https://github.com/TencentCloud/CubeSandbox/blob/v0.8.0/sdk/python/cubesandbox/sandbox.py#L853-L877)

A template probe determines which moment is captured. As soon as the test server was listening, `/alive` returned HTTP 200 while its `ready` field was still false. Capturing solely on the status code would propagate an unbuilt index to every session. For a search service, have the readiness probe run a fixed lookup and check both the index version and the expected hit before reporting success. Repeat that lookup in a new instance of the finished template. The two checks catch an early capture and an unusable restore, respectively.

## Where the time went

| Cumulative time (ms) | Lazy P50 | Warm P50 | Lazy P95 | Warm P95 |
| --- | ---: | ---: | ---: | ---: |
| Create returned | 157 | 135 | 198 | 174 |
| Tool ready | 539 | 323 | 665 | 504 |
| First valid result | 590 | 377 | 759 | 590 |

Median create latency differed by about 22 ms. The gap opened when the lazy path had to build the index. All 40 queries passed. Outside the timing window, DeepSeek read one tool response from each mode and answered 19 both times. Measurements include SDK, forwarding, and command dispatch. The table excludes model generation. Each P95 is the 19th sorted observation.

![Terminal replay of the measured data](../../assets/rag-agent/cubesandbox-five-labs/prewarm-terminal.png)

*The checker validates the two model answers, all 40 hit counts, and both group sizes.*

## When prewarming is worth testing

For many sessions using one parser, toolchain, or index version, a template build can absorb repeated initialization work. With frequent index or model changes, budget for rebuilding and storing snapshots. Inject gateway credentials and user data after session creation. A short query on one shared node gives no estimate for cross-node restores of large snapshots or first-token latency.

### Apply your own first-request deadline

Subtract the timestamps **within each observation** before taking a median. Create-return to tool-ready was **373 ms** lazy and **181 ms** warm. Tool-ready to query result was **57 ms** and **55 ms**. The first interval includes both probes and command dispatch, so the roughly 192 ms gap cannot be assigned entirely to CPU time building the index. Within-pair savings to the first valid result had a median of **195 ms**. Subtracting the two group medians gives 213 ms, a different statistic.

Changing the service objective changes the decision. These deadlines are retrospective cuts through the same samples, rather than predeclared service commitments.

| Deadline from create to correct result | Lazy within deadline | Warm within deadline |
| --- | ---: | ---: |
| 500 ms | 0/20 | 17/20 |
| 600 ms | 11/20 | 19/20 |
| 1,000 ms | 20/20 | 19/20 |

The only pair that favored lazy initialization was the first: 926 ms lazy versus 2,131 ms warm. The warm create call alone took 1,705 ms. This locates the delay in creation. The records cannot separate caching, scheduling, and storage. For an interactive tool with a 600 ms target, the sample supports a limited warm rollout. For a hard one-second deadline, measure first pulls and repeat restores across nodes, retaining timeouts and snapshot sizes. To estimate the benefit over one template version, multiply its creation count by the **mean paired saving** (about 144 ms here). The result estimates accumulated waiting time saved. Account separately for build work, storage fees, and the cost of missed deadlines.

Download the [raw data](../../assets/data/cubesandbox-five-labs/prewarm.json) and [verification script](../../assets/data/cubesandbox-five-labs/verify.py) into one directory and run the command below.

```sh
python3 verify.py prewarm
```

[Download the lab scripts](../../assets/data/cubesandbox-five-labs/lab-sources.zip). After extracting them, configure the endpoint and templates as described in the README. Start with `prewarm.py`.

[Upstream service-prewarming tutorial](https://github.com/TencentCloud/CubeSandbox/blob/v0.8.0/docs/guide/tutorials/prewarm-template-service.md)
