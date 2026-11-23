---
title: "Why Can a Webhook Fail After a Sandbox Is Created? CubeSandbox Logs, Delivery, and Tracing"
description: "A real allocation, an HTTP 503 retry, stable event identity, and OpenTelemetry stage checks."
status: tested
last_reviewed: 2026-11-23
applicable_versions: "CubeSandbox v0.8.0 + isolated CubeMaster source 6843e3f97e67"
tested_environment: "Kubernetes v1.37.2, x86_64 KVM, one Cube compute node"
---

# Why Can a Webhook Fail After a Sandbox Is Created? CubeSandbox Logs, Delivery, and Tracing

If creation succeeds but an inventory has no entry, submitting another create can allocate a second sandbox. We made the receiver return HTTP 503 and then 204 and queried the logs by the same sandbox ID. The result was one instance, one event, and two HTTP deliveries. An integration needs a way to recognize duplicates and to discover allocations that never made it into its inventory.

![Verified log count, webhook retries, and OTel stage outcomes](../../assets/rag-agent/cubesandbox-five-labs/observability-terminal.png)

*Logs and notifications in the upper half refer to the same real instance. The lower half shows separately executed CubeMaster worker tests.*

## How the two versions participated

The installed release was v0.8.0 with an existing adapter for console event reads. A separate Kubernetes namespace ran Linux test binaries built from upstream commit `6843e3f97e67`, which includes later webhook and OpenTelemetry work. Its test pod had no mounted service-account token. It called the existing CubeAPI to create a short-lived base sandbox, and the namespace was removed after the experiment.

The fixture reused the upstream CubeMaster create handler and asynchronous publisher. Its allocation function delegated to the cluster API and returned the actual ID to the handler. A real HTTP server inside the test pod received deliveries. This ties the notification to a real instance while keeping the serving control plane on its release. The five components were not replaced with development builds, and a five-service end-to-end trace was not captured.

## Who is still working after creation succeeds?

At the pinned upstream revision, the create handler obtains its business result and submits a lifecycle event to a publisher. Background work matches subscriptions and attempts HTTP delivery to each destination. The business API and the receiver’s durable write have separate completion conditions. A caller may already have a usable sandbox while the receiver is down. Issuing another create solely because a notification is missing can turn an integration failure into duplicate allocation. Query the known sandbox ID first, then investigate delivery separately. [Upstream event boundaries and delivery semantics](https://github.com/TencentCloud/CubeSandbox/blob/6843e3f97e67/docs/guide/webhooks.md)

A particularly difficult retry occurs when the receiver commits its transaction but the success response is lost. The sender sees a timeout and submits the same event again. Deduplicating by `e2b-delivery-id` would accept both attempts as new work. Deduplicating by sandbox ID could suppress a genuinely new pause or resume for the same sandbox. The payload `id` identifies one event and makes a suitable consumer-side key. If multiple independent consumers must each do the work once, include the consumer identity in the uniqueness scope.

## Three types of evidence from the lab

| Signal | Observation | Question answered |
| --- | --- | --- |
| Logs | 27 records for the same instance, with timestamp, level, and message | What records exist for this instance? |
| Webhook | One event got HTTP 503 then 204. The event ID matched and delivery IDs differed | Did the integration receive it, and does it need deduplication? |
| OTel | Separate resume-success and pause-failure worker tests placed the failure in pause.runtime | Which lifecycle stage reported an error? |

A receiver can deduplicate on event ID and log each attempt by delivery ID. Persist the business update and deduplication result before acknowledging it. A separate test held the receiver open with a 300 ms request timeout and a three-attempt limit. All three attempts timed out before terminal failure. Long receiver outages also call for reconciliation against the actual business state.

![HTTP deliveries and spans logged by the isolated test pod](../../assets/rag-agent/cubesandbox-five-labs/observability-live.png)

*Selected output from the actual test processes. Deliveries at the top refer to one real allocation. The spans below come from two separate worker tests.*

[Read the transcript excerpt](../../assets/data/cubesandbox-five-labs/observability-live.txt)

## Reading the recorded stages

A successful resume worker produced sibling `prepare`, `runtime`, and `finalize` spans with status `Unset`. A separately injected pause failure marked `cubemaster.sandbox.pause.runtime` as `Error`. The real SDK recorded spans while the Cubelet RPC and selected dependencies were replaced for the worker test. These observations validate instrumentation and attribution. They cannot establish production P95 or a full Jaeger trace for the allocation.

### When should the receiver return 2xx?

Consider a receiver that registers a pending task after sandbox creation. One table can act as both the receipt and a durable work queue. Use consumer plus event ID as the unique key, insert a pending task in a transaction, and acknowledge after commit. A duplicate that finds the same row can also be acknowledged. The minimal SQLite schema and insert below bind consumer and payload event ID to the two placeholders. The accompanying checker replays a synthetic ID twice and finds one pending task.

```sql
CREATE TABLE work_inbox (
    consumer TEXT NOT NULL,
    event_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    PRIMARY KEY (consumer, event_id)
);

INSERT INTO work_inbox (consumer, event_id) VALUES (?, ?)
ON CONFLICT (consumer, event_id) DO NOTHING;
```

A real task also needs enough payload to do the work. If its receipt transaction fails, let the sender retry. If the transaction commits and the worker restarts, the task is still in the queue. When work calls another service, propagate a stable business idempotency key. A crash between external success and marking the task complete can otherwise repeat the effect. This handles duplicates. Even when all events arrive, a kill notification can reach the receiver before an earlier create notification. An inventory consumer can use a notification to refresh the sandbox’s current state by ID. That prevents a late create from resurrecting a terminated instance in the inventory.

This revision keeps queue and delivery state in each Master process. Restart, saturation, or retry exhaustion can lose work. Periodic comparison with platform state can repair an inventory, but it cannot reconstruct every intermediate transition. A complete audit history needs a durable event source. [Upstream capacity, loss, and replay semantics](https://github.com/TencentCloud/CubeSandbox/blob/6843e3f97e67/docs/guide/webhooks.md#capacity-loss-and-shutdown)

### Which signal should an operator inspect first?

If the caller has an ID but the business integration has no record, inspect the increase in `cubemaster_webhook_operations_total` across all Masters during the incident. Rising `ingress/full` or `put/capacity` counts indicate possible loss before any HTTP request. The receiver’s access log would have nothing to show. Rising `send/timeout` or `terminal/failed` counts point toward receiver latency, responses, and the retry budget. Once the receiver has the event ID, check whether its work item committed and a worker consumed it. If the user is instead blocked on the resume request itself, follow its request context into the resume spans and inspect logs for the failing stage. This ordering keeps a notification incident from triggering unnecessary restarts of working sandboxes. [Upstream metric definitions](https://github.com/TencentCloud/CubeSandbox/blob/6843e3f97e67/docs/guide/webhooks.md#diagnose-and-verify)

Download the [raw data](../../assets/data/cubesandbox-five-labs/observability.json) and [verification script](../../assets/data/cubesandbox-five-labs/verify.py) into one directory and run the command below.

```sh
python3 verify.py observability
```

[Download the lab scripts](../../assets/data/cubesandbox-five-labs/lab-sources.zip). After extracting them, configure the endpoint and templates as described in the README. Start with `lab_observation_test.go`.

[Upstream webhook configuration and delivery semantics](https://github.com/TencentCloud/CubeSandbox/blob/6843e3f97e67/docs/guide/webhooks.md)

[Upstream lifecycle tracing and exporter configuration](https://github.com/TencentCloud/CubeSandbox/blob/6843e3f97e67/docs/guide/tracing.md)
