---
title: "KServe on Kubernetes: Deploy a Model and Call Its Inference API"
description: Deploy an Iris classifier with KServe on Kubernetes, exercise V1 and V2 inference and replica changes, and explain the relationship with Knative and inference engines
status: evolving
last_reviewed: 2026-11-16
---

# KServe on Kubernetes: Deploy a Model and Call Its Inference API

Packaging a model in a container and creating a Deployment can provide an inference API. What does KServe add? In a Kubernetes test cluster we deployed KServe and a real scikit-learn Iris classifier, exercising model artifacts, `InferenceService`, runtime selection, inference calls, and replica changes.

**KServe's central value is declaring model deployment as Kubernetes resources and having a controller coordinate runtimes, model storage, and service lifecycles.** It does not replace inference engines such as vLLM; it can manage model services that use them. This is a CPU classifier functional test, not a test of LLMs, GPU performance, or production high availability.

## Results and scope

| Item | Result |
| --- | --- |
| Kubernetes / KServe | v1.30.4 / v0.15.0 |
| Deployment mode | RawDeployment, without Knative |
| Model | SVC trained on Iris, scikit-learn 1.5.1, 150 training examples |
| Storage | 1 GiB local PVC, `ReadWriteOnce` |
| Inference | Both V1 and V2 HTTP succeeded; three inputs returned classes `[0, 1, 2]` |
| Replicas | Raising the minimum from 1 to 2 produced 2/2 ready; restoring 1 returned to 1/1 |
| Access | ClusterIP and local port forwarding; no external Ingress created |

Three inputs are functional examples, not independent test-set accuracy or a throughput or latency benchmark. Changing the minimum verifies control-plane and HPA convergence to configuration; **it is not load-driven autoscaling**.

![The KServe ModelServer Swagger API page](../../assets/images/kserve-kubernetes-practice/swagger-overview.png)

*Actual Swagger page for the KServe ModelServer used in this experiment, showing V1 and V2 APIs. This is runtime API documentation, not a complete KServe management console.*

## 1. Why this version and mode

The KServe v0.15 documentation requires Kubernetes 1.30 or later, matching our existing 1.30.4 test cluster. This release is old: the experiment does not establish the behavior of newer releases or production security. Current installation documentation requires Kubernetes 1.32 or later. For production, select a supported version using the current support policy and security advisories, upgrading Kubernetes first if necessary. [v0.15 installation](https://kserve.github.io/archive/0.15/admin/kubernetes_deployment/) · [Current installation requirements](https://kserve.github.io/website/docs/admin-guide/kubernetes-deployment/) · [Release support policy](https://github.com/kserve/kserve/blob/master/RELEASES.md)

| Mode | How it works | Scaling characteristics |
| --- | --- | --- |
| RawDeployment (v0.15) | Controller creates Deployment, Service and HPA; Ingress is configurable | Kubernetes HPA; HTTP activation from zero is not supported in this mode |
| Serverless (v0.15) | Uses Knative Serving and a networking layer | Can use request-driven scaling, scale-to-zero and Revisions; requires more components |

Later releases call RawDeployment Standard; use the terminology and configuration for the selected release. We verified only the first row, not Knative, scale-to-zero, canary rollout, or request-driven scaling. [v0.15 Serverless installation](https://kserve.github.io/archive/0.15/admin/serverless/serverless/)

## 2. Where KServe fits

```text
InferenceService → KServe controller → Deployment + Service + HPA
                       ↓                        ↓
                ServingRuntime            ModelServer + PVC
                                                  ↓
                                           HTTP V1 / V2
```

`InferenceService` declares model format, runtime, storage, replicas, and other properties. `ClusterServingRuntime` supplies the model-server container and arguments. The controller reconciles the declaration into Kubernetes resources, while the runtime performs inference. Here the KServe SKLearn Server loads `model.joblib` from a PVC; the controller does not classify the inputs itself.

This PVC is a single-node local disk using RWO. It constrains Pod placement and sharing and does not demonstrate multi-node availability, shared storage, or high availability. Production also needs artifact versioning, permissions, caching, and recovery.

## 3. Installation and environment

We mirrored the controller, proxy and SKLearn Server images, used a dedicated test namespace, disabled Ingress creation, and supplied an experimental self-signed webhook certificate. To avoid installing a shared cert-manager just for this lab, we injected a CA into rendered manifests and restricted namespaced admission rules to the lab namespace. The certificate is experimental and has no automatic rotation. Controller RBAC, CRDs and some webhooks remain cluster-scoped; a namespace is not complete isolation.

The more conventional upstream Helm procedure below **requires cert-manager to be installed and healthy**; it is not an exact reproduction of our self-signed certificate handling. First inspect existing CRDs, webhooks and releases to avoid overwriting a deployment. Helm, kubectl, metrics-server, reachable images, and cluster-admin privileges are required. Do not run this blindly on a shared production cluster. [Installation prerequisites](https://kserve.github.io/archive/0.15/admin/kubernetes_deployment/)

```bash
kubectl create namespace kserve-lab
helm install kserve-crd oci://ghcr.io/kserve/charts/kserve-crd \
  --version v0.15.0 -n kserve-lab
helm install kserve oci://ghcr.io/kserve/charts/kserve \
  --version v0.15.0 -n kserve-lab \
  --set kserve.controller.deploymentMode=RawDeployment \
  --set kserve.controller.gateway.disableIngressCreation=true \
  --wait --timeout 10m
kubectl -n kserve-lab get pods
```

When using an internal registry, configure the controller, proxy, storage initializer and model runtime images individually and keep their versions compatible. Do not publish internal registry addresses or credentials. The example model is a trusted local artifact: `joblib` uses pickle, so **do not load model files from untrusted sources**.

## 4. Prepare the model and PVC

The following trains the example directly in the KServe SKLearn Server image and writes it to a PVC. It matches our final training approach, omitting the initial import of an older upstream sample. The Job runs as root to write the test volume; production should avoid unnecessary root through appropriate UID, fsGroup and storage permission design. Adapt the StorageClass and capacity to your environment.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: iris-model-pvc
  namespace: kserve-lab
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
---
apiVersion: batch/v1
kind: Job
metadata:
  name: iris-model-train
  namespace: kserve-lab
spec:
  backoffLimit: 1
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: train
          image: kserve/sklearnserver:v0.15.0
          securityContext: {runAsUser: 0}
          command: ['/prod_venv/bin/python', '-c']
          args:
            - |
              import os, sklearn
              from joblib import dump
              from sklearn import datasets, svm
              data = datasets.load_iris()
              model = svm.SVC(gamma='scale').fit(data.data, data.target)
              dump(model, '/output/model.tmp')
              os.replace('/output/model.tmp', '/output/model.joblib')
              print('scikit-learn:', sklearn.__version__, 'training examples:', len(data.target))
          resources:
            requests: {cpu: 100m, memory: 256Mi}
            limits: {cpu: '1', memory: 1Gi}
          volumeMounts:
            - {name: output, mountPath: /output}
      volumes:
        - name: output
          persistentVolumeClaim: {claimName: iris-model-pvc}
```

Save as `iris-storage.yaml` and run:

```bash
kubectl apply -f iris-storage.yaml
kubectl -n kserve-lab wait --for=condition=complete job/iris-model-train --timeout=120s
kubectl -n kserve-lab logs job/iris-model-train
```

Our log reported `scikit-learn: 1.5.1 training examples: 150`. Initially, an upstream sample serialized with scikit-learn 1.0.1 produced a version mismatch warning in runtime 1.5.1. We retrained and serialized with the same runtime and reloaded it; the warning disappeared. The first write also encountered insufficient PVC directory permissions; changing the test Job's runtime identity allowed it to complete.

## 5. Create an InferenceService

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: sklearn-iris
  namespace: kserve-lab
  annotations:
    serving.kserve.io/deploymentMode: RawDeployment
spec:
  predictor:
    minReplicas: 1
    maxReplicas: 2
    model:
      modelFormat:
        name: sklearn
      runtime: kserve-sklearnserver
      storageUri: pvc://iris-model-pvc/
      args:
        - --enable_docs_url=True
      resources:
        requests:
          cpu: 100m
          memory: 512Mi
        limits:
          cpu: '1'
          memory: 1Gi
```

Save as `iris-isvc.yaml`:

```bash
kubectl apply -f iris-isvc.yaml
kubectl -n kserve-lab get inferenceservice,deploy,svc,hpa,pvc
kubectl -n kserve-lab port-forward svc/sklearn-iris-predictor 19896:80
```

The `InferenceService` status may show an example domain, but Ingress creation is disabled in this lab; that domain does not mean it is externally reachable. Port forwarding above listens locally only. Stop it with Ctrl-C when finished.

## 6. Call V1 and V2

Run the V1 request in another terminal:

```bash
curl -sS -H 'Content-Type: application/json' \
  -d '{"instances":[[5.1,3.5,1.4,0.2],[6.2,2.9,4.3,1.3],[6.5,3.0,5.5,1.8]]}' \
  http://127.0.0.1:19896/v1/models/sklearn-iris:predict
```

It returns `{"predictions":[0,1,2]}`. Then use V2:

```bash
curl -sS -H 'Content-Type: application/json' \
  -d '{"inputs":[{"name":"predict","shape":[3,4],"datatype":"FP32","data":[[5.1,3.5,1.4,0.2],[6.2,2.9,4.3,1.3],[6.5,3.0,5.5,1.8]]}]}' \
  http://127.0.0.1:19896/v2/models/sklearn-iris/infer
```

The V2 response also has `[0, 1, 2]` in `outputs[0].data`. The screenshot below shows the result after actually submitting the V2 request in the runtime's Swagger page.

![Actual V2 inference request and HTTP 200 response in Swagger](../../assets/images/kserve-kubernetes-practice/swagger-v2-result.png)

*Actual desktop-browser V2 request, HTTP 200, and three predicted classes. The address is a local port forward, not an externally exposed service.*

## 7. Change replicas and observe resources

```bash
kubectl -n kserve-lab patch inferenceservice sklearn-iris --type=merge \
  -p '{"spec":{"predictor":{"minReplicas":2}}}'
kubectl -n kserve-lab wait --for=jsonpath='{.status.readyReplicas}'=2 \
  deployment/sklearn-iris-predictor --timeout=90s
kubectl -n kserve-lab get inferenceservice,deploy,hpa
kubectl -n kserve-lab patch inferenceservice sklearn-iris --type=merge \
  -p '{"spec":{"predictor":{"minReplicas":1}}}'
```

We observed 2/2 ready, then 1/1 after restoring configuration. HPA metrics and control loops have their own sampling intervals, so displayed state can temporarily lag the Deployment. Because this example uses a local RWO PVC, both replicas ran on the node allowed to access that volume; this **does not establish multi-node fault tolerance**.

## 8. Relationship with Knative and vLLM

| Project | Main responsibility | Relationship in this experiment |
| --- | --- | --- |
| KServe | Model-service declarations, runtime selection, storage integration and resource reconciliation | Actually deployed and tested here |
| Knative Serving | Request-driven container elasticity, Revisions and traffic management | Can underpin KServe Serverless mode; not installed here |
| vLLM / SGLang | LLM inference engines responsible for loading models and generation | Can be packaged or managed by a platform; not deployed here and no GPU test was run |
| Ordinary Deployment | Runs containers and manages replicas | KServe RawDeployment creates and reconciles one underneath |

Start with model type, storage, and performance targets, then decide whether unified model APIs, artifact management, and multiple runtimes are needed. A direct Deployment has fewer dependencies. KServe provides a uniform abstraction but requires maintenance of its controller, CRDs, webhooks, certificates, and upgrade compatibility. [KServe project](https://github.com/kserve/kserve) · [Knative Serving](https://knative.dev/docs/serving/)

## 9. Boundaries and cleanup

This test did not cover load-driven HPA, Knative scale-to-zero, GPU, LLM streaming, authentication, multi-tenant isolation, or multi-node recovery. Before production, validate artifact trust, quotas, identity and network policies, persistence, monitoring, alerts, and rolling upgrades.

We resolved a model volume mount-path conflict by using a direct `pvc://` mount and recreating the lab predictor Deployment. An image-mirroring network interruption completed after retry. Cluster-wide webhooks and CRDs require careful impact assessment; an expired certificate affects the corresponding admission path.

For cleanup, first remove the experiment's `InferenceService`, test Jobs and PVC, then remove the controller using the actual installation method. Deleting the PVC may delete model data. Cluster-wide CRDs and RBAC may be shared by other installations: confirm there are no dependencies before removal, and do not clean shared resources blindly.
