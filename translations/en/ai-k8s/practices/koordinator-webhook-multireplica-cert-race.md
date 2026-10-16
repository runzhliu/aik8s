---
title: "Koordinator Webhook Multi-Replica Certificate Race in Practice: From 60 HTTP 409 Responses per Second to Shared CA Convergence"
description: "A production cluster Koordinator Webhook certificate race — its diagnosis, fix, and verification, including sanitized real Grafana metrics, shared Secret configuration, certificate checks, and production acceptance methods"
status: stable
last_reviewed: 2026-09-20
---

# Koordinator Webhook Multi-Replica Certificate Race in Practice: From 60 HTTP 409 Responses per Second to Shared CA Convergence

A production cluster at the thousand-node scale, running tens of thousands of Pods, sustained roughly a thousand API Server requests per second over a long period. Business traffic showed no obvious growth, yet the control plane continuously exhibited two groups of anomalies:

- `MutatingWebhookConfiguration` and `ValidatingWebhookConfiguration` were being read and updated at high frequency;
- Update requests kept returning HTTP 409, while the five-member etcd concurrently showed elevated Backend Commit P99 and Slow Apply.

The root cause was ultimately traced to Koordinator Webhook certificate management: 8 `koord-manager` replicas each generated their own self-signed CA locally, while all of them modified the global WebhookConfiguration. Multiple replicas overwrote `caBundle` in turn, forming a loop of "configuration change → Informer event → re-sync → update again."

The fix did not replace Koordinator, nor did it scale out the API Server or etcd. We first pre-provisioned a shared certificate, explicitly switched the certificate Writer to Secret mode, then rolled out the 8 replicas. After the change, PUTs and 409s on the WebhookConfiguration both dropped to 0, eliminating the direct write amplification.

Here is an environmental background that defines the problem boundary: **this cluster does not provide a Kubernetes Service entry usable by the API Server for this Webhook call chain.** Standard Kubernetes deployments typically reference the Webhook Service in `clientConfig.service`, with in-cluster Service networking handling discovery and forwarding; this environment, constrained by legacy architecture and network path limitations, requires reaching the Webhook through an internal load balancer component, hence the `webhook_host` configuration. This is an environment adaptation, not a standard Kubernetes Webhook deployment pattern.

The problem therefore cannot be generalized as "Koordinator Webhook multi-replica deployments will always experience certificate races." A more accurate trigger condition is the combination of three factors: a non-standard external Host access path, this image's default choice of certificate Writer, and multiple replicas jointly maintaining the global `caBundle`. Other environments using the standard Service path, explicitly shared certificates, or a single controller maintaining the CA will not naturally reproduce this issue. The general value of this article lies in the diagnostic method: start from anomalous API requests to identify the written object, then cross-check multi-replica certificates, object versions, Leader boundaries, and global configuration ownership.

> This article comes from real production handling. Cluster names, domains, IPs, instance names, accounts, and internal system navigation have been removed or replaced; Grafana images retain the original curves, coordinates, and time relationships, with no data redrawn.

## 1. Start with the Most Distinctive Metric

Looking only at total API Server QPS, it is easy to attribute the problem to "large cluster scale." What is truly distinctive is breaking down requests by `resource + verb + code`.

Before the change, the two WebhookConfiguration types combined showed approximately:

| Request | 5-minute average | Expected shape under normal conditions |
| --- | ---: | --- |
| GET | 157.0 req/s | Should approach 0 once configuration is stable, retaining only low-frequency sync |
| PUT attempts | 82.4 req/s | Should only appear when certificates or rules actually change |
| PUT 409 | 60.1 req/s | Should be 0 |
| PUT 200 | 22.3 req/s | Should also approach 0 during steady state |

<img src="/assets/practices/koordinator-webhook-cert-race/grafana-webhook-conflicts-sanitized.png" alt="Real Grafana curves of WebhookConfiguration requests and API Server 409s before and after shared CA switchover, internal identifiers sanitized" width="1200">

60 HTTP 409 conflicts per second is not the occasional concurrent update of an ordinary business object; it is multiple controllers contending for the same set of cluster-level configuration objects. Adding more controller replicas only amplifies the conflict.

The right-side chart also answers a key question: whether these 409s are truly ordinary controller conflicts. Before the fix, Webhook configuration PUT 409s accounted for approximately 98.5% of all API Server 409s; after the fix, Webhook 409s dropped to zero, leaving only about 0.36/s of total 409s. The source of the anomalous conflicts and the object of the fix map directly to each other.

Below are the real Grafana curves within the change window. Total API Server QPS dropped from 1,071.1/s to 774.8/s, write requests from 501.0/s to 397.7/s, and read requests from 570.1/s to 377.1/s.

<img src="/assets/practices/koordinator-webhook-cert-race/grafana-apiserver-qps-sanitized.png" alt="Real Grafana curves of API Server read/write QPS before and after shared CA switchover, internal identifiers sanitized" width="1200">

The drop in total QPS can only serve as correlational evidence, since business traffic in the same time window may also have varied. Stronger causal evidence is: after the switchover, PUTs and 409s on both WebhookConfiguration types dropped to zero simultaneously, GETs fell to 0.28/s, and the configuration object's `generation` and `resourceVersion` subsequently remained stable.

## 2. Why 8 Replicas Produce 8 CAs

Koordinator's Webhook does more than serve the Admission HTTP endpoint; it must also prepare a server certificate and write the CA that issued that certificate into `MutatingWebhookConfiguration` and `ValidatingWebhookConfiguration`, in their `caBundle` fields.

The image in use at the time supported two certificate Writers:

| Writer | Certificate storage location | Multi-replica result |
| --- | --- | --- |
| `fs` | Each Pod's local filesystem | Each replica may obtain a different CA |
| `secret` | Kubernetes Secret | All replicas read the same CA and server certificate |

The external Webhook Host was configured because this environment cannot let the API Server reach the Webhook through the standard Kubernetes Service path; it can only rely on an internal load balancer entry for forwarding. `webhook_host` addresses reachability in this specific environment; it should not be treated as a general deployment template.

Under these conditions, when the deployment configured an external Webhook Host without explicitly specifying a Writer, the image in use selected the file Writer. The 8 Pods' temporary directories are isolated from one another, so each replica generated its own CA. Meanwhile, the certificate-to-WebhookConfiguration sync logic did not run only on the Leader; every replica attempted to write its own CA into the same global object.

```text
koord-manager-1 ── CA-1 ─┐
koord-manager-2 ── CA-2 ─┼──> 同一个 WebhookConfiguration.caBundle
koord-manager-3 ── CA-3 ─┤
...                       │
koord-manager-8 ── CA-8 ─┘
```

This simultaneously caused three problems:

1. **Write conflicts.** Multiple replicas updated the same object based on a stale `resourceVersion`, and the API Server returned 409.
2. **Trust root churn.** `caBundle` can ultimately hold only one valid trust root; each subsequent write overwrites the previous one.
3. **Unstable admission results.** When the API Server reaches a random backend through a VIP or load balancer, the current `caBundle` may not be able to verify that backend's certificate.

If the Webhook is configured with `failurePolicy: Ignore`, requests may continue on TLS errors or call failures. This reduces the risk of Webhook failures blocking business traffic, but it also means some objects may not have gone through the intended mutation or validation. The Kubernetes documentation defines `Ignore` as allowing requests on call errors and `Fail` as rejecting on call errors; both need to be designed with business semantics in mind, rather than simply choosing the option with "higher availability." [Dynamic Admission Control](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/) · [Admission Webhook Good Practices](https://kubernetes.io/docs/concepts/cluster-administration/admission-webhooks-good-practices/)

It should be emphasized that this conclusion applies to the image in use at the time, the non-standard access path, and the deployment parameters; it cannot be used to assert that all Koordinator versions exhibit the same problem. The current community code still shows the selection logic between the file Writer and the Secret Writer, with the Secret Writer storing certificates in a Kubernetes Secret; in actual handling, one should still verify the binary inside one's own image, Helm Values, and source version. [Koordinator Webhook Controller source](https://github.com/koordinator-sh/koordinator/blob/main/pkg/webhook/util/controller/webhook_controller.go) · [Koordinator writer package](https://pkg.go.dev/github.com/koordinator-sh/koordinator/pkg/webhook/util/writer)

## 3. Evidence Chain Established During Diagnosis

### 3.1 Break Down API Server Requests by Resource

First confirm which object the anomalous writes target, rather than looking only at total QPS:

```promql
sum by (resource, verb, code) (
  rate(apiserver_request_total{
    resource=~"mutatingwebhookconfigurations|validatingwebhookconfigurations"
  }[5m])
)
```

If `PUT 409` persists over time, then locate the writer by `client`, `userAgent`, or audit logs. Different Kubernetes versions and monitoring stacks may use different labels; inspect the raw time series first.

### 3.2 Continuously Observe generation and resourceVersion

```bash
kubectl get mutatingwebhookconfiguration <mutating-name> \
  -o jsonpath='{.metadata.generation}{" "}{.metadata.resourceVersion}{"\n"}'

kubectl get validatingwebhookconfiguration <validating-name> \
  -o jsonpath='{.metadata.generation}{" "}{.metadata.resourceVersion}{"\n"}'
```

Run multiple times at intervals of a few seconds. If rules, Selectors, and CA have no manual changes, yet `generation` or `resourceVersion` keep increasing, identify which controller is repeatedly writing.

### 3.3 Compute Hashes of the Configured CA and Each Pod's CA Separately

```bash
# 配置对象中的 caBundle，实际脚本应遍历全部 webhooks
kubectl get mutatingwebhookconfiguration <mutating-name> \
  -o jsonpath='{.webhooks[0].clientConfig.caBundle}' \
  | base64 -d | sha256sum

# 每个 Pod 内的证书目录以实际镜像为准
kubectl -n <namespace> exec <manager-pod> -- \
  sha256sum <cert-dir>/ca-cert.pem <cert-dir>/cert.pem
```

This inspection found that the 8 Pods' CA hashes all differed from one another, and the CA in the configuration object changed with whoever updated it. This evidence is more direct than "certificate errors in logs."

### 3.4 Check Whether Non-Leader Replicas Are Also Syncing Certificates

```bash
kubectl -n <namespace> logs <manager-pod> --since=10m \
  | grep -E 'sync webhook certs|object has been modified|ensure configuration'
```

If replicas not holding the Leader Lease continue to emit certificate and configuration sync logs, one cannot assume that Leader Election already protects this path.

### 3.5 Do Not Rely on a Single Pod Dry-Run

A successful `kubectl apply --dry-run=server` only proves that one request was not rejected. When using `failurePolicy: Ignore`, a request may succeed even if Webhook TLS validation fails. Acceptance must also combine:

- Admission Webhook call failure, Fail-open, or rejection metrics;
- TLS, x509, and timeout entries in API Server logs;
- Continuous access through the load balancer entry, covering all backends;
- Verification that business objects actually received the intended mutation or validation.

## 4. Fix: Make All Replicas Use the Same Secret

We first prepared a server certificate whose SAN, usage, and key matching had already been verified, then wrote it into a shared Secret. Next, we explicitly set the Writer type and Secret name:

```yaml
env:
  - name: WEBHOOK_CERT_WRITER
    value: secret
  - name: SECRET_NAME
    value: <webhook-tls-secret>
```

The `SecretCertWriter` in the image in use reads the Secret through the Kubernetes API and writes the certificate into the container's existing certificate directory, so no additional Secret Volume mount is required. This behavior is not a general Kubernetes convention; other versions or other Webhook implementations may require a read-only mount. Before rollout, the current image implementation must be inspected; do not infer behavior from variable names.

The shared certificate must at minimum satisfy the following checks:

```bash
# CA 能验证服务端证书
openssl verify -CAfile ca-cert.pem cert.pem

# 私钥和证书公钥一致
openssl x509 -in cert.pem -pubkey -noout | sha256sum
openssl pkey -in key.pem -pubout       | sha256sum

# 检查 SAN、用途、签发者和有效期
openssl x509 -in cert.pem -noout -text \
  | grep -A2 -E 'Subject Alternative Name|Extended Key Usage'
openssl x509 -in cert.pem -noout -subject -issuer -dates
```

If the WebhookConfiguration uses `clientConfig.service`, the SAN typically needs to cover the corresponding Service DNS; if it uses `clientConfig.url` pointing to an external VIP or domain, the certificate must cover the hostname or IP in that URL. The server certificate needs the Server Authentication usage, and `caBundle` must be able to verify the full certificate chain.

The rolling update used `maxUnavailable: 0`, with the following sequence:

1. Create and verify the shared Secret first;
2. Confirm the ServiceAccount has the minimal permission to read that Secret;
3. Update the two environment variables on the Deployment;
4. Replace Pods one at a time, waiting for each new replica to become Ready before continuing;
5. Verify the load balancer backends have removed the old Pods;
6. Complete certificate hash, configured CA, and TLS acceptance checks across all replicas.

## 5. Results After the Fix

Both before and after the change, 5-minute averages were taken. Metrics directly related to this fix and overall control plane metrics are listed separately:

| Metric | Before | After | Assessment |
| --- | ---: | ---: | --- |
| WebhookConfiguration GET | 157.0/s | 0.28/s | Down 99.8% |
| WebhookConfiguration PUT attempts | 82.4/s | 0 | Direct write amplification eliminated |
| WebhookConfiguration PUT 409 | 60.1/s | 0 | Multi-writer conflict eliminated |
| API Server total QPS | 1,071.1/s | 774.8/s | Down 27.7%, includes business fluctuation |
| API Server write QPS | 501.0/s | 397.7/s | Down 20.6%, includes business fluctuation |
| API Server CPU aggregate | 10.95 cores | 8.73 cores | Down 20.3%, includes business fluctuation |
| API core request P99 | 144.7 ms | 152.6 ms | No improvement |
| API 5xx / 429 | 0 / 0 | 0 / 0 | Service availability remained stable |

<img src="/assets/practices/koordinator-webhook-cert-race/grafana-apiserver-cpu-latency-sanitized.png" alt="Real Grafana curves of API Server CPU and core request P99 before and after shared CA switchover, internal identifiers sanitized" width="1200">

Placing CPU and P99 side by side avoids cherry-picking favorable metrics. API Server CPU aggregate dropped 20.3%, but core request P99 rose from 144.7 ms to 152.6 ms. Write amplification did disappear, yet other sources of control plane latency remain.

The acceptance results at the Pod and configuration level are:

- All 8/8 replicas are Ready, with 0 restarts;
- The CA and server certificate hashes of all Pods are identical;
- The `caBundle` of all 3 Mutating and 2 Validating Webhooks match the CA in the Secret;
- The `generation` and `resourceVersion` of both WebhookConfiguration objects remain stable across consecutive observation windows;
- Logs no longer show `object has been modified`, certificate sync failures, or conflict retries;
- 24 consecutive TLS requests were sent through the load balancer entry point, all returned HTTP 200, and client verification results were all 0.

## 6. etcd pressure dropped, but the problem cannot yet be declared resolved

After removing the write amplification, the aggregated Put and CPU of etcd members both dropped simultaneously:

<img src="/assets/practices/koordinator-webhook-cert-race/grafana-etcd-load-sanitized.png" alt="Real Grafana curves of aggregated etcd member Put and CPU before and after the shared CA switch, internal identifiers sanitized" width="1200">

Aggregated member Put dropped from 1,775.3/s to 1,543.3/s, and etcd CPU dropped from 4.38 cores to 3.55 cores. The two curves moved in the same direction, but the change did not form a vertical cliff at the switch point, so it can only be said that pressure receded after the change; the full reduction cannot be attributed to the certificate fix.

Slow Apply also dropped:

<img src="/assets/practices/koordinator-webhook-cert-race/grafana-etcd-slow-apply-sanitized.png" alt="Real Grafana curves of etcd Slow Apply before and after the shared CA switch, internal identifiers sanitized" width="1200">

| Metric | Before change | After change | Assessment |
| --- | ---: | ---: | --- |
| etcd Slow Apply | 1.39/s | 0.83/s | Down 40.4%, still not at zero |
| Failed Proposal | 0 | 0 | No consensus commit failures |
| Pending Proposal | 0.83 | 0.83 | Essentially unchanged |
| Aggregated etcd CPU | 4.38 cores | 3.55 cores | Down 18.9% |
| Slowest member Backend Commit P99 | 111.2 ms | 94.9 ms | Down 14.7%, still notably high |
| WAL Fsync P99 | ~0.99 ms | ~0.99 ms | Essentially unchanged |

<img src="/assets/practices/koordinator-webhook-cert-race/grafana-etcd-backend-sanitized.png" alt="Real Grafana curves of etcd Backend Commit P99 before and after the shared CA switch, internal identifiers sanitized" width="1200">

Backend Commit P99 dropped within a short window, but it remains far above the commonly used 25 ms observation line, and the curve still shows obvious spikes. WAL Fsync is close to 1 ms, which only indicates that the WAL path does not exhibit a comparable level of latency; it cannot rule out BoltDB data files, fragmentation, block device queues, CPU preemption, or host interference.

There is also a common measurement error: summing the `put_total` of 5 etcd members directly double-counts the same Raft work. The aggregated member value dropping from 1,775.3/s to 1,543.3/s is only suitable for comparing relative change under the same topology, and cannot be treated as independent business write volume.

Therefore, the accurate conclusion is: **the shared CA fix removed one confirmed source of control-plane write amplification; it did not cure etcd's tail latency.** Subsequent work still requires independent checks of database fragmentation, data disk `await` and queues, BoltDB commits, CPU steal, NUMA, and competition from processes on the same host.

## 7. If switching to cert-manager

A viable cert-manager structure is:

1. `Certificate` generates a shared TLS Secret;
2. All Webhook Pods use the same Secret;
3. cainjector injects the same CA into the `caBundle` of the Mutating/ValidatingWebhookConfiguration.

[cert-manager CA Injector](https://cert-manager.io/docs/concepts/ca-injector/) supports injecting CA into MutatingWebhookConfiguration, ValidatingWebhookConfiguration, CRD Conversion Webhook, and APIService.

The key point is not "whether cert-manager is installed," but that **certificates and `caBundle` can only have one clear Owner**. If cainjector and Koordinator's built-in controller both modify `caBundle`, you are simply turning the original 8 competitors into two categories of competitors. When adopting cert-manager, you need to disable the built-in CA write logic, or ensure it only reads the same certificate set and never overwrites cainjector's results.

## 8. Production configuration and alerting recommendations

### 8.1 Configuration principles

- Multi-replica Webhooks must share the same trust root and server certificate source;
- Certificate generation, Secret writes, and `caBundle` injection must each have a clearly designated single Owner;
- Prefer `clientConfig.service` so that Service DNS, Endpoints, and certificate lifecycle remain inside the cluster; if an external URL is truly required, include SAN, LB traffic draining, and probe protocol in the same change set;
- Long-validity certificates can reduce the frequency of emergency rotation, but cannot replace expiry alerts, automatic rotation, overlapping dual certificates, and rollback drills;
- Webhooks must not unconditionally respond to Update events for their own configuration objects; perform semantic comparison before updating, and only write when certificates or rules have actually changed;
- If the sync controller supports Leader Election, certificate and global configuration coordination should only be executed by the Leader; the Webhook HTTP Server itself can still serve from multiple replicas.

### 8.2 Recommended alerts

```promql
# 稳定运行期出现 WebhookConfiguration PUT
sum(rate(apiserver_request_total{
  resource=~"mutatingwebhookconfigurations|validatingwebhookconfigurations",
  verb="PUT"
}[5m])) > 0

# WebhookConfiguration 更新冲突
sum(rate(apiserver_request_total{
  resource=~"mutatingwebhookconfigurations|validatingwebhookconfigurations",
  verb="PUT",
  code="409"
}[5m])) > 0
```

The following synthetic checks should also be added:

- Periodically compute the CA and server certificate hash of each Pod, and alert immediately on any inconsistency;
- Compute the hash of the Secret CA against all `caBundle` entries, and block further rollout if any single one is inconsistent;
- Check remaining certificate validity, SAN, and EKU;
- Connect continuously through the Service or VIP to confirm all backends pass TLS verification;
- On Kubernetes versions that support the corresponding metrics, monitor Admission Webhook rejection, timeout, fail-open, and latency;
- Establish low-frequency sampling for `generation` or `resourceVersion` to detect sustained churn when there is no configuration change.

## 9. An actionable change acceptance checklist

| Check item | Pass condition | Action on failure |
| --- | --- | --- |
| Shared Secret | CA, certificate, and private key match; SAN/EKU correct | Do not update the Deployment |
| RBAC | ServiceAccount can read the target Secret, permissions not expanded | Fix to least privilege |
| Rolling update | All replicas Ready, 0 unexpected restarts | Pause rollout, retain the old ReplicaSet |
| Pod certificates | All CA/cert hashes identical | Find replicas still using the file Writer |
| Configuration CA | Each Webhook's `caBundle` matches the Secret CA | Stop traffic, restore the previous version |
| Configuration stability | `generation` and `resourceVersion` no longer change at high frequency | Check other writers and cainjector |
| Direct metrics | PUT and 409 close to 0 | Check Writer, event self-excitation, and conflict retries |
| TLS entry | Consecutive requests cover all backends, all verifications succeed | Check SAN, certificate chain, and draining of old backends |
| Admission semantics | Mutation/Validation actually takes effect | Do not treat HTTP 200 as success |
| Control plane | 5xx, 429, P99, etcd proposals do not worsen | Roll back and preserve evidence from the change window |

Incidents of this kind are most easily misdiagnosed as "poor etcd performance" or "cluster too large." The troubleshooting order should be reversed: first find who is generating duplicate writes, then assess whether etcd still has an independent problem. Otherwise, even scaling up the control plane will not change the logic of 8 replicas contending for the same `caBundle`.

## References

- [Koordinator project](https://github.com/koordinator-sh/koordinator)
- [Koordinator Webhook Controller source code](https://github.com/koordinator-sh/koordinator/blob/main/pkg/webhook/util/controller/webhook_controller.go)
- [Koordinator writer package](https://pkg.go.dev/github.com/koordinator-sh/koordinator/pkg/webhook/util/writer)
- [Kubernetes Dynamic Admission Control](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/)
- [Kubernetes Admission Webhook Good Practices](https://kubernetes.io/docs/concepts/cluster-administration/admission-webhooks-good-practices/)
- [cert-manager CA Injector](https://cert-manager.io/docs/concepts/ca-injector/)
