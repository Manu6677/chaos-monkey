# Chaos Monkey --- Kubernetes Resilience Experiment

A hands-on Kubernetes resilience project built from scratch with
**FastAPI, Docker, Kubernetes, Kind, Python Kubernetes Client, RBAC,
Services, Readiness Probes, and an HTTP availability watcher**.

The goal is not simply to delete Pods.

The goal is to answer a more interesting engineering question:

> **Can we deliberately kill a running application instance and still
> keep the application available to clients?**

------------------------------------------------------------------------

## 1. What This Project Demonstrates

This project recreates the core Chaos Monkey experiment:

-   Run a FastAPI application with multiple replicas.
-   Expose the application through a Kubernetes Service.
-   Use Kubernetes readiness probes so only healthy Pods receive
    traffic.
-   Give a Chaos Monkey workload a dedicated ServiceAccount.
-   Grant it only the RBAC permissions it needs.
-   Periodically select and delete a Ready FastAPI Pod.
-   Let Kubernetes automatically recreate the deleted Pod.
-   Continuously send HTTP requests through the Service.
-   Measure request success/failure while failures are being injected.

The important separation is:

``` text
Chaos Monkey = creates the failure
Kubernetes   = recovers from the failure
Watcher      = measures the impact
```

------------------------------------------------------------------------

# 2. High-Level Architecture

``` mermaid
flowchart TB

    U[Developer / Client]

    W[HTTP Availability Watcher<br/>Python requests]

    PF[kubectl port-forward<br/>localhost:8000 -> Service:80]

    S[Kubernetes Service<br/>chaos-monkey-fastapi:80]

    ES[EndpointSlice<br/>Ready Pod endpoints]

    P1[FastAPI Pod A<br/>:8000]
    P2[FastAPI Pod B<br/>:8000]
    P3[FastAPI Pod C<br/>:8000]

    CM[Chaos Monkey Pod<br/>Python]

    SA[ServiceAccount<br/>chaosmonkey]

    RBAC[Role + RoleBinding<br/>list/delete Pods]

    D[Deployment]
    RS[ReplicaSet]

    U --> W
    W --> PF
    PF --> S
    S --> ES
    ES --> P1
    ES --> P2
    ES --> P3

    CM --> SA
    SA --> RBAC
    CM -->|List Ready Pods| KAPI[Kubernetes API Server]
    CM -->|Delete selected Pod| KAPI

    D --> RS
    RS -->|maintains desired replicas| P1
    RS -->|maintains desired replicas| P2
    RS -->|maintains desired replicas| P3

    KAPI --> RS
```

------------------------------------------------------------------------

# 3. The Core Experiment

The system has three independent responsibilities.

``` mermaid
flowchart LR

    CM[Chaos Monkey<br/>Failure Injection]

    K[Kubernetes<br/>Reconciliation + Recovery]

    W[Watcher<br/>Traffic Measurement]

    CM -->|Delete Pod| K
    K -->|Create replacement| K
    W -->|HTTP requests| K

    CM -. "What happens if<br/>an instance dies?" .-> K
    W -. "Did users notice?" .-> K
```

Think of the experiment as:

``` text
        FAILURE
           │
           ▼
    Chaos Monkey
           │
           │ deletes
           ▼
       FastAPI Pod
           │
           │ disappears
           ▼
   Kubernetes detects
   desired != actual
           │
           ▼
   ReplicaSet creates
   replacement Pod
           │
           ▼
       Pod becomes
          Ready
           │
           ▼
      Service routes
       traffic again

Meanwhile:

Watcher
   │
   ├── request
   ├── request
   ├── request
   ├── request
   └── measure success/failure
```

------------------------------------------------------------------------

# 4. Kubernetes Architecture

``` mermaid
flowchart TB

    subgraph ControlPlane["Kubernetes Control Plane"]
        API[kube-apiserver]
        ETCD[etcd]
        SCH[kube-scheduler]
        CTRL[kube-controller-manager]
    end

    subgraph Node["Kind Control Plane Node"]
        KL[kubelet]
        CP[containerd]
        PODS[Application Pods]
    end

    API --> ETCD
    API --> SCH
    API --> CTRL
    API --> KL

    SCH -->|assign Pod to node| API
    CTRL -->|reconcile desired state| API

    KL -->|create/start containers| CP
    CP --> PODS
```

The API Server is the central communication point.

For a Pod deletion:

``` text
Chaos Monkey
      |
      | DELETE /api/v1/namespaces/default/pods/<pod>
      ▼
kube-apiserver
      |
      ▼
Pod object is marked for deletion
      |
      ▼
ReplicaSet observes fewer Pods
      |
      ▼
ReplicaSet creates replacement Pod
      |
      ▼
Scheduler assigns node
      |
      ▼
kubelet notices assigned Pod
      |
      ▼
containerd starts container
      |
      ▼
readiness probe succeeds
      |
      ▼
Pod becomes Ready
```

------------------------------------------------------------------------

# 5. Deployment → ReplicaSet → Pod

The application is not managed directly by the Service.

The Service only provides stable networking.

The Deployment/ReplicaSet is responsible for maintaining the desired
number of Pods.

``` mermaid
flowchart TB

    DEP[Deployment<br/>chaos-monkey-fastapi<br/>replicas: 3]

    RS[ReplicaSet]

    P1[FastAPI Pod]
    P2[FastAPI Pod]
    P3[FastAPI Pod]

    DEP --> RS

    RS --> P1
    RS --> P2
    RS --> P3
```

If one Pod is deleted:

``` text
Desired = 3
Current = 2

                    ReplicaSet
                        │
                        │ reconcile
                        ▼
                  create Pod #4
                        │
                        ▼
                    Pending
                        │
                        ▼
               ContainerCreating
                        │
                        ▼
                    Running
                        │
                        ▼
                     Ready

Final:

Desired = 3
Current = 3
```

------------------------------------------------------------------------

# 6. Service Architecture

Clients should not depend on individual Pod IPs.

Pod IPs are disposable.

The Service provides a stable endpoint.

``` mermaid
flowchart LR

    C[Client]

    S[Service<br/>chaos-monkey-fastapi<br/>ClusterIP :80]

    ES[EndpointSlice]

    A[Pod A<br/>10.244.x.x:8000]
    B[Pod B<br/>10.244.x.x:8000]
    C2[Pod C<br/>10.244.x.x:8000]

    C --> S
    S --> ES

    ES --> A
    ES --> B
    ES --> C2
```

The client uses:

``` text
http://chaos-monkey-fastapi/
```

rather than:

``` text
http://10.244.0.40:8000/
```

because the Pod IP can change whenever the Pod is recreated.

------------------------------------------------------------------------

# 7. Readiness Probe

The FastAPI application exposes:

``` text
GET /healthz
```

The Deployment configures Kubernetes to check it.

``` yaml
readinessProbe:
  httpGet:
    path: /healthz
    port: 8000
  initialDelaySeconds: 2
  periodSeconds: 5
```

The important distinction is:

``` text
Running != Ready
```

A Pod can be:

``` text
Running
0/1
```

while Kubernetes is still waiting for its readiness probe to succeed.

Once:

``` text
GET /healthz -> HTTP 200
```

the Pod becomes:

``` text
1/1 Ready
```

and becomes eligible for Service traffic.

------------------------------------------------------------------------

# 8. Traffic Flow During Normal Operation

``` mermaid
sequenceDiagram

    participant W as Watcher
    participant PF as Port Forward
    participant S as Service
    participant ES as EndpointSlice
    participant P as FastAPI Pod

    loop Every request
        W->>PF: GET localhost:8000/
        PF->>S: GET Service:80
        S->>ES: Select Ready endpoint
        ES->>P: Forward request
        P-->>ES: HTTP 200
        ES-->>S: Response
        S-->>PF: Response
        PF-->>W: HTTP 200
    end
```

The Watcher does not need to know which Pod handled the request.

------------------------------------------------------------------------

# 9. Chaos Monkey Flow

The Chaos Monkey runs as a Kubernetes Deployment.

It receives its Kubernetes identity through:

``` yaml
serviceAccountName: chaosmonkey
```

Its permissions are intentionally limited.

``` mermaid
flowchart TB

    CM[Chaos Monkey Container]

    SA[ServiceAccount<br/>chaosmonkey]

    RB[RoleBinding]

    R[Role<br/>pods: list, delete]

    API[Kubernetes API Server]

    CM --> SA
    SA --> RB
    RB --> R

    CM -->|authenticated API calls| API
    R -. allows .-> API
```

The intended permissions are:

``` text
pods:
  list
  delete
```

Not:

``` text
create deployments
update nodes
delete namespaces
```

This follows the least-privilege principle.

------------------------------------------------------------------------

# 10. Chaos Monkey Decision Flow

``` mermaid
flowchart TD

    START[Chaos Monkey starts]

    LOAD[Load in-cluster Kubernetes config]

    LIST[List Pods in namespace]

    FILTER[Filter target FastAPI Pods]

    READY[Keep only Ready Pods]

    CHECK{Ready Pods > minimum alive?}

    SKIP[Skip deletion<br/>Sleep]

    SELECT[Select target Pod]

    DELETE[Delete selected Pod]

    SLEEP[Sleep for configured interval]

    START --> LOAD
    LOAD --> LIST
    LIST --> FILTER
    FILTER --> READY
    READY --> CHECK

    CHECK -->|No| SKIP
    CHECK -->|Yes| SELECT

    SELECT --> DELETE
    DELETE --> SLEEP
    SKIP --> SLEEP

    SLEEP --> LIST
```

The minimum-alive rule prevents the experiment from intentionally
removing the last available application instance.

For example:

``` text
Ready Pods = 3
Minimum alive = 1

Delete one:

3 -> 2

Safe.
```

But:

``` text
Ready Pods = 1
Minimum alive = 1

Do not delete.
```

------------------------------------------------------------------------

# 11. Full Failure Injection Sequence

This is the most important diagram in the project.

``` mermaid
sequenceDiagram

    participant CM as Chaos Monkey
    participant API as API Server
    participant RS as ReplicaSet
    participant P1 as FastAPI Pod A
    participant P2 as FastAPI Pod B
    participant P3 as FastAPI Pod C
    participant W as Watcher
    participant S as Service

    Note over P1,P3: 3 Ready FastAPI Pods

    CM->>API: List Ready Pods
    API-->>CM: A, B, C

    CM->>API: Delete Pod B

    API-->>P2: Termination requested

    RS->>API: Observe current replicas < desired
    RS->>API: Create replacement Pod D

    Note over P2: Terminating

    Note over P1,P3: A and C remain Ready

    loop HTTP traffic
        W->>S: GET /
        S->>P1: Route to Ready endpoint
        P1-->>W: 200 OK
    end

    Note over P2: Pod B terminates

    API-->>RS: Replacement Pod D exists

    RS->>API: Pod D scheduled

    Note over P1,P3: Existing Pods continue serving

    API-->>P3: Readiness remains healthy
    API-->>P1: Readiness remains healthy

    Note over P2: B gone
    Note over P1,P3: Service still has healthy endpoints

    API-->>P1: Pod D starts
    API-->>P1: Readiness probe eventually succeeds

    Note over P1,P3: New Pod becomes Ready
```

------------------------------------------------------------------------

# 12. Why the Application Can Survive Pod Deletion

Suppose:

``` text
3 replicas
```

and Chaos Monkey deletes one:

``` text
Before:

Service
  │
  ├── Pod A ✓
  ├── Pod B ✓
  └── Pod C ✓
```

After deleting Pod B:

``` text
Service
  │
  ├── Pod A ✓
  ├── Pod B ✗ Terminating
  └── Pod C ✓
```

The Service still has healthy endpoints.

Then Kubernetes creates Pod D:

``` text
Service
  │
  ├── Pod A ✓
  ├── Pod C ✓
  └── Pod D → starting
```

Eventually:

``` text
Service
  │
  ├── Pod A ✓
  ├── Pod C ✓
  └── Pod D ✓
```

The key concept:

> **Kubernetes does not keep the same Pod alive. It keeps the desired
> state alive.**

------------------------------------------------------------------------

# 13. Availability Watcher

The Watcher runs outside Kubernetes for the current experiment.

It continuously sends requests to:

``` text
http://localhost:8000/
```

which is connected to the Kubernetes Service through:

``` bash
kubectl port-forward service/chaos-monkey-fastapi 8000:80
```

Conceptually:

``` mermaid
flowchart LR

    W[Watcher]

    L[localhost:8000]

    PF[kubectl port-forward]

    S[Service :80]

    P1[Ready Pod]
    P2[Ready Pod]
    P3[Ready Pod]

    W --> L
    L --> PF
    PF --> S

    S --> P1
    S --> P2
    S --> P3
```

------------------------------------------------------------------------

# 14. Request Success Rate

The basic metric is:

``` text
Success Rate =
successful requests / total requests × 100
```

Example:

``` text
Total requests      = 1000
Successful requests = 998
Failed requests     = 2

Success Rate = 99.8%
```

This is an experiment metric.

It answers:

> "How much did the injected failure affect client-visible traffic?"

It is not the same thing as Pod health.

------------------------------------------------------------------------

# 15. Pod Recovery vs Application Availability

These are two different measurements.

### Pod recovery

``` text
Pod deleted
    ↓
replacement created
    ↓
Running
    ↓
Readiness succeeds
    ↓
Ready
```

Measure:

``` text
Recovery Time =
replacement Pod Ready time
-
deletion time
```

### Application availability

``` text
HTTP requests
     ↓
success / failure
     ↓
success rate
```

Measure:

``` text
Availability =
successful requests / total requests
```

A system can have:

``` text
Pod recovery = 4 seconds
Application success rate = 99.9%
```

because the other replicas continued serving traffic while the
replacement was starting.

------------------------------------------------------------------------

# 16. The Complete System

``` mermaid
flowchart TB

    subgraph ClientSide["Client / Observation"]
        WATCH[Availability Watcher]
        METRICS[Success Count<br/>Failure Count<br/>Success Rate]
    end

    subgraph Kubernetes["Kind Kubernetes Cluster"]

        subgraph Traffic["Traffic Layer"]
            SERVICE[Service]
            ENDPOINTS[EndpointSlice]
        end

        subgraph App["Application"]
            DEPLOY[Deployment<br/>replicas: 3]
            RS[ReplicaSet]
            A[FastAPI Pod]
            B[FastAPI Pod]
            C[FastAPI Pod]
        end

        subgraph Chaos["Failure Injection"]
            CMD[Chaos Monkey Deployment]
            CMP[Chaos Monkey Pod]
            SA[ServiceAccount]
            ROLE[Role]
            BIND[RoleBinding]
        end

        API[Kubernetes API Server]
        KUBELET[kubelet]
        RUNTIME[containerd]
    end

    WATCH --> METRICS
    WATCH --> SERVICE

    SERVICE --> ENDPOINTS
    ENDPOINTS --> A
    ENDPOINTS --> B
    ENDPOINTS --> C

    DEPLOY --> RS
    RS --> A
    RS --> B
    RS --> C

    CMD --> CMP
    CMP --> SA
    SA --> BIND
    BIND --> ROLE

    CMP -->|list/delete Pods| API

    API --> RS
    API --> KUBELET
    KUBELET --> RUNTIME
```

------------------------------------------------------------------------

# 17. Local Environment

The project uses Kind for a local Kubernetes cluster.

``` text
Mac
 │
 ├── Docker Desktop
 │
 └── Kind
      │
      └── chaos-eng-control-plane
           │
           ├── kube-apiserver
           ├── etcd
           ├── kube-scheduler
           ├── kube-controller-manager
           ├── kubelet
           ├── kube-proxy
           └── containerd
```

Kind means:

> **Kubernetes IN Docker**

The Kubernetes node itself runs as a Docker container.

------------------------------------------------------------------------

# 18. Container Image Flow

The local FastAPI image is built with Docker.

``` text
docker build
     │
     ▼
Docker Desktop image store
     │
     │ kind load docker-image
     ▼
Kind node containerd
     │
     ▼
Kubernetes Pod
     │
     ▼
FastAPI container
```

For this local project:

``` bash
docker build -t chaos-monkey-fastapi:latest .
kind load docker-image chaos-monkey-fastapi:latest --name chaos-eng
```

The same approach is used for the Chaos Monkey image.

------------------------------------------------------------------------

# 19. Project Structure

A representative structure is:

``` text
chaos-monkey-fastAPI/
│
├── app/
│   └── main.py
│
├── chaos/
│   └── main.py
│
├── scripts/
│   └── watcher.py
│
├── k8/
│   ├── deployment.yml
│   ├── service.yml
│   ├── rbac.yml
│   └── chaos-deployment.yml
│
├── Dockerfile
├── Dockerfile.chaos
├── requirements.txt
└── README.md
```

Responsibilities:

``` text
app/
    FastAPI application

chaos/
    Kubernetes failure injector

scripts/
    Client-side traffic/availability measurement

k8/
    Kubernetes manifests

Dockerfile
    FastAPI container

Dockerfile.chaos
    Chaos Monkey container
```

------------------------------------------------------------------------

# 20. FastAPI Application

The application exposes:

``` text
GET /
GET /healthz
```

The root endpoint returns the hostname so that Pod replacement is
visible.

Example:

``` json
{
  "message": "Hello from FastAPI",
  "hostname": "chaos-monkey-fastapi-xxxxx"
}
```

This is useful during the experiment because a changed hostname
demonstrates that the request reached a different Pod.

------------------------------------------------------------------------

# 21. Readiness and Service Relationship

``` mermaid
flowchart TD

    P[FastAPI Pod starts]

    R[Readiness Probe]

    H[GET /healthz]

    RESULT{HTTP 200?}

    READY[Pod Ready = true]

    NOTREADY[Pod Ready = false]

    EP[EndpointSlice includes Pod]

    TRAFFIC[Service can route traffic]

    P --> R
    R --> H
    H --> RESULT

    RESULT -->|Yes| READY
    RESULT -->|No| NOTREADY

    READY --> EP
    EP --> TRAFFIC
```

This is why readiness is important for the experiment.

A newly created Pod should not immediately receive traffic before the
application is ready.

------------------------------------------------------------------------

# 22. What Happens When a Pod Is Deleted?

``` mermaid
sequenceDiagram

    participant CM as Chaos Monkey
    participant API as API Server
    participant RS as ReplicaSet
    participant S as Service
    participant OLD as Old Pod
    participant NEW as Replacement Pod

    CM->>API: DELETE old Pod
    API-->>OLD: Termination begins

    API-->>S: Endpoint membership changes

    RS->>API: Observe fewer replicas
    RS->>API: Create replacement Pod

    NEW->>API: Pod scheduled
    NEW->>API: Container starts

    loop Readiness checks
        API->>NEW: GET /healthz
        NEW-->>API: 200 OK
    end

    API-->>S: Replacement becomes eligible endpoint

    Note over S,NEW: Service now routes to replacement
```

------------------------------------------------------------------------

# 23. What the Watcher Tells Us

Without the watcher:

``` text
"Chaos Monkey deleted a Pod."
```

With the watcher:

``` text
"Chaos Monkey deleted a Pod,
but client traffic remained successful."
```

That is a much stronger resilience test.

Example:

``` text
Before chaos:

100 requests
100 successful
100.00%

During Pod deletion:

1000 requests
998 successful
2 failed
99.80%

After recovery:

1000 requests
1000 successful
100.00%
```

------------------------------------------------------------------------

# 24. Important Mental Models

### Pod

A Pod is disposable.

``` text
Pod IP + Pod identity
        ↓
       can change
```

### Deployment

Maintains the desired number of replicas.

``` text
desired = 3
```

### ReplicaSet

Keeps actual replicas aligned with desired replicas.

### Service

Provides stable networking to a changing set of Pods.

### Readiness Probe

Determines whether a Pod is ready to receive Service traffic.

### ServiceAccount

Provides workload identity.

### Role

Defines permissions.

### RoleBinding

Connects identity to permissions.

### Chaos Monkey

Intentionally introduces failure.

### Watcher

Measures client-visible impact.

------------------------------------------------------------------------

# 25. Why the Experiment Is Interesting

A simple failure test asks:

> "Can Kubernetes restart my container?"

This project asks a better question:

> "Can Kubernetes maintain application availability while individual
> application instances are continuously destroyed?"

That difference matters.

A Pod being recreated successfully does not automatically mean users
experienced zero impact.

That's why we need both:

``` text
Infrastructure signal
    ↓
Pod deleted
Pod recreated
Pod Ready

AND

Application signal
    ↓
HTTP success
HTTP failure
Success rate
```

------------------------------------------------------------------------

# 26. Current Experiment Loop

``` mermaid
flowchart LR

    A[3 Ready Pods]

    B[Chaos Monkey selects one]

    C[Pod deleted]

    D[2 healthy Pods remain]

    E[ReplicaSet creates replacement]

    F[Replacement becomes Ready]

    G[3 Ready Pods again]

    H[Watcher measures HTTP traffic]

    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> B

    H -. observes .-> A
    H -. observes .-> C
    H -. observes .-> G
```

------------------------------------------------------------------------

# 27. Configuration

Chaos Monkey runtime behavior is configured through environment
variables rather than hardcoded values.

Example:

``` yaml
env:
  - name: CHAOS_INTERVAL
    value: "60"

  - name: CHAOS_MIN_ALIVE
    value: "1"

  - name: CHAOS_NAMESPACE
    value: "default"
```

This gives the image a separation between:

``` text
Image
  = application code

Environment
  = runtime configuration
```

So changing the interval does not require rebuilding the image.

------------------------------------------------------------------------

# 28. Safety Rule

The most important safety check is:

``` text
if ready_pods <= minimum_alive:
    do not delete
```

Example:

``` text
Ready = 3
Min alive = 1
       ↓
Delete one
       ↓
2 remain
```

But:

``` text
Ready = 1
Min alive = 1
       ↓
Do NOT delete
```

This prevents the Chaos Monkey from intentionally taking the entire
application offline.

------------------------------------------------------------------------

# 29. Useful Commands

### Cluster

``` bash
kind get clusters
kubectl cluster-info
kubectl get nodes
```

### Application

``` bash
kubectl get deployment
kubectl get rs
kubectl get pods -o wide
```

### Service

``` bash
kubectl get svc
kubectl get endpointslices
```

### Watch Pod lifecycle

``` bash
kubectl get pods -w
```

### Watch Chaos Monkey

``` bash
kubectl logs -f deployment/chaos-monkey
```

### Verify RBAC

``` bash
kubectl auth can-i list pods \
  --as=system:serviceaccount:default:chaosmonkey

kubectl auth can-i delete pods \
  --as=system:serviceaccount:default:chaosmonkey
```

### Expose Service locally

``` bash
kubectl port-forward service/chaos-monkey-fastapi 8000:80
```

### Test application

``` bash
curl http://localhost:8000/
```

------------------------------------------------------------------------

# 30. Running the Experiment

### 1. Start the Service tunnel

``` bash
kubectl port-forward service/chaos-monkey-fastapi 8000:80
```

### 2. Start the watcher

``` bash
python scripts/watcher.py
```

### 3. Observe Kubernetes

``` bash
kubectl get pods -w
```

### 4. Observe Chaos Monkey

``` bash
kubectl logs -f deployment/chaos-monkey
```

You should be able to correlate:

``` text
Chaos Monkey:
    Deleted Pod A
         ↓
Kubernetes:
    Pod A Terminating
    Replacement Pod D created
    Pod D Running
    Pod D Ready
         ↓
Watcher:
    HTTP requests continue
    Success rate changes or remains stable
```

------------------------------------------------------------------------

# 31. What Success Looks Like

A successful experiment is not:

``` text
Pod deleted ✓
```

It is:

``` text
Pod deleted
      ↓
Application continues serving traffic
      ↓
Replacement Pod created
      ↓
Replacement becomes Ready
      ↓
Service endpoint set recovers
      ↓
HTTP success rate remains high
```

The stronger the client-visible availability during failure injection,
the stronger the resilience demonstrated by the system.

------------------------------------------------------------------------

# 32. What This Project Taught Me

The biggest lesson was that Kubernetes resilience is not about keeping a
specific container alive.

It is about maintaining **desired application state** while individual
instances are disposable.

The mental model became:

``` text
Don't protect this Pod.

Protect the desired state.

Don't connect to this Pod IP.

Connect to the Service.

Don't ask whether the container exists.

Ask whether the application is Ready.

Don't only check whether Kubernetes recreated the Pod.

Check whether users could still make successful requests.
```

------------------------------------------------------------------------

# 33. Future Improvements

The current project intentionally keeps the experiment small.

Possible next steps:

-   Use labels instead of Pod-name prefixes to identify chaos targets.
-   Add an explicit opt-in label for Pods that may be terminated.
-   Add dry-run mode.
-   Add structured logging.
-   Record deletion timestamp and replacement-ready timestamp.
-   Measure Pod recovery time automatically.
-   Track rolling availability over time.
-   Export Prometheus metrics.
-   Add Grafana dashboards.
-   Run the watcher inside Kubernetes.
-   Add request latency measurements.
-   Add controlled failure scenarios beyond Pod deletion.
-   Add multiple application replicas and compare resilience.
-   Introduce multiple failure-injection policies.

------------------------------------------------------------------------

# 34. Final Architecture Summary

``` text
                         ┌────────────────────────┐
                         │       HTTP Watcher      │
                         │                        │
                         │ success / failure      │
                         │ success rate           │
                         └───────────┬────────────┘
                                     │
                              localhost:8000
                                     │
                              port-forward
                                     │
                                     ▼
                         ┌────────────────────────┐
                         │       Service          │
                         │  stable application    │
                         │       endpoint         │
                         └───────────┬────────────┘
                                     │
                              EndpointSlice
                                     │
                   ┌─────────────────┼─────────────────┐
                   ▼                 ▼                 ▼
             ┌──────────┐      ┌──────────┐      ┌──────────┐
             │ FastAPI  │      │ FastAPI  │      │ FastAPI  │
             │  Pod A   │      │  Pod B   │      │  Pod C   │
             │  Ready   │      │  Ready   │      │  Ready   │
             └──────────┘      └──────────┘      └──────────┘
                   ▲                 ▲                 ▲
                   │                 │                 │
                   └─────────────────┼─────────────────┘
                                     │
                               ReplicaSet
                                     ▲
                                     │
                                Deployment

                     ┌────────────────────────┐
                     │     Chaos Monkey        │
                     │                        │
                     │ list Ready Pods        │
                     │ choose target          │
                     │ delete target          │
                     │ wait                   │
                     │ repeat                 │
                     └───────────┬────────────┘
                                 │
                              RBAC
                                 │
                         Kubernetes API
```

------------------------------------------------------------------------

## Project Principle

> **Inject failure deliberately. Let Kubernetes recover. Measure what
> the client experienced.**

That is the essence of this project.
