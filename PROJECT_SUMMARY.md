# Relay — Project Architecture & Graph Summary

> Generated via **Graphify** knowledge graph extraction (425 nodes, 1,334 edges, 16 functional communities).  
> Built for **Graph Hacks: Context for AI Agents** (WeMakeDevs x FalkorDB) — **Track 02: Agent Memory and Coordination**.

---

## 1. Executive Summary

**Relay** is an open-source, multi-tenant memory and coordination engine for autonomous AI agent fleets, powered natively by **FalkorDB**. It eliminates the three classic failure modes of multi-agent architectures:
1. **Memory Amnesia**: Flat vector stores discard temporal sequence, entity relationships, and causal history. Relay introduces native **Episodic**, **Semantic**, and **Procedural** graph memory.
2. **Coordination Collisions**: Concurrent agents race and clobber shared tasks. Relay provides single-statement **Atomic Compare-and-Set (CAS)** claims with expiring leases.
3. **Procedural Stagnation**: When runbooks fail, agents repeat mistakes. Relay models procedures as versioned graph entities with **Laplace-smoothed ranking** and automatic **Failure Forking**.

---

## 2. Graphify Knowledge Graph Map

```
                                  ┌───────────────────────────┐
                                  │      Client Surface       │
                                  │ • Web Dashboard (D3.js)   │
                                  │ • Server-Sent Events (SSE)│
                                  └─────────────┬─────────────┘
                                                │ REST / SSE
                                  ┌─────────────▼─────────────┐
                                  │       FastAPI Core        │
                                  │ (Community 4: main.py)    │
                                  └──────┬─────────────┬──────┘
                                         │             │
                    ┌────────────────────┴───┐     ┌───┴────────────────────┐
                    │    Security & Auth     │     │      Agent Fleet       │
                    │ (Community 9/10/14)    │     │ (Community 0/2/7)      │
                    │ • AuthContext          │     │ • Triage Agent         │
                    │ • SHA-256 Tokens       │     │ • Investigator Agent   │
                    │ • Control Graph Schema │     │ • Remediator Agent     │
                    └───────────┬────────────┘     │ • Comms Agent          │
                                │                  │ • OpenVINO LLM Adapter │
                                │                  └───────────┬────────────┘
                                │                              │
                                └──────────────┬───────────────┘
                                               │ Tool Calls
                                ┌──────────────▼──────────────┐
                                │      FalkorDB Storage       │
                                │   (Community 1/3/5/6/13)    │
                                │ • Episodic Timelines        │
                                │ • Semantic Supersession     │
                                │ • Procedural Laplace Graphs │
                                │ • CAS Task Claims & Leases  │
                                │ • Native PageRank & BFS     │
                                └─────────────────────────────┘
```

---

## 3. Top Core Abstractions ("God Nodes")

Graphify centrality analysis identified the top 10 structural hubs holding the codebase together:

| Rank | Symbol | Location | Degree (Connections) | Architectural Role |
|:---:|---|---|:---:|---|
| **1** | `AuthContext` | `server/app/auth.py` | **60** | Immutable security context mapping bearer tokens to tenant graph names. Prevents tenant identity spoofing. |
| **2** | `execute_query()` | `server/app/graph.py` | **51** | Primary write query router executing serializable openCypher mutations against FalkorDB. |
| **3** | `execute_ro_query()` | `server/app/graph.py` | **47** | Read-only query router for high-throughput memory queries and topological traversal. |
| **4** | `log_audit()` | `server/app/auth.py` | **43** | Write-ahead audit logging into the `control` graph for forensic traceability of all agent tool invocations. |
| **5** | `provision_tenant()` | `server/app/tenancy.py` | **28** | Multi-tenant lifecycle engine that provisions isolated graphs and indexes in FalkorDB. |
| **6** | `run_full_incident_scenario()` | `agents/scenario.py` | **27** | End-to-end multi-agent incident orchestration engine (Triage $\rightarrow$ Investigator $\rightarrow$ Remediator $\rightarrow$ Comms). |
| **7** | `dispatch_tool_call()` | `agents/tools_registry.py` | **27** | Central dispatcher mapping LLM tool-call names to authenticated graph handlers. |
| **8** | `provision_agent_key()` | `server/app/tenancy.py` | **25** | Generates and hashes agent bearer keys with role-based access control. |
| **9** | `upsert_fact()` | `server/app/queries/semantic.py` | **21** | Bi-temporal semantic fact updater establishing `[:SUPERSEDES]` lineage edges. |
| **10** | `run_load_test()` | `scripts/load_test.py` | **19** | High-concurrency CAS claim verification engine. |

---

## 4. Key Functional Communities

Graphify clustered the 425 nodes across 16 cohesive communities:

### Community 0: Incident Scenario & Tool Dispatch
- **Key Modules**: `agents/scenario.py`, `agents/tools_registry.py`, `server/app/tools/coordination.py`
- **Role**: Dispatches tool calls, coordinates handoffs between agents, and runs the incident response loop.

### Community 1: CAS Concurrency & Coordination Queries
- **Key Modules**: `server/app/queries/coordination.py`, `scripts/load_test.py`
- **Role**: Manages atomic task claims, lease renewals, reaper sweeps, and cascade unblocking.

### Community 2: Agent Fleet & Execution Engine
- **Key Modules**: `agents/base.py`, `agents/runner.py`, `agents/llm_adapter.py`
- **Role**: Implements the base `RelayAgent` turn loop, prompt templating, and model tool invocation.

### Community 3: Procedural Memory & Laplace Ranking
- **Key Modules**: `server/app/queries/procedural.py`, `server/app/tools/procedural.py`
- **Role**: Implements smoothed Laplace scoring ($s = \frac{k+1}{n+2}$), procedure search, and failure forking with preconditions.

### Community 4: FastAPI Server & Real-Time SSE Engine
- **Key Modules**: `server/app/main.py`
- **Role**: Serves the REST API, graph snapshot endpoints, live Server-Sent Events (SSE) feed, and web dashboard.

### Community 5: Consolidation Worker & Derived Facts
- **Key Modules**: `server/app/consolidation.py`
- **Role**: Background worker that derives semantic facts from episodic sessions with `[:DERIVED_FROM]` provenance edges.

### Community 6: Semantic Memory & Supersession History
- **Key Modules**: `server/app/queries/semantic.py`, `server/app/tools/semantic.py`
- **Role**: Maintains bi-temporal interval facts (`valid_from`, `valid_to`) and supports time-travel queries.

### Community 7: OpenVINO Model Server & Local Inference
- **Key Modules**: `server_openvino.py`
- **Role**: Hosts local Intel OpenVINO™ Qwen2.5-7B INT4 inference with OpenAI-compatible tool calling.

### Community 8 & 9: Tenancy Lifecycle, Auth & Control Graph
- **Key Modules**: `server/app/tenancy.py`, `server/app/auth.py`, `server/app/queries/control.py`
- **Role**: Cryptographic bearer token hashing, tenant graph provisioning, and audit recording.

### Community 12 & 13: Isolation Proofs & Graph Topology Insights
- **Key Modules**: `scripts/isolation_test.py`, `server/app/queries/insight.py`
- **Role**: Native FalkorDB PageRank entity centrality, BFS blast radius calculation, and cross-tenant attack verification.

---

## 5. Empirical Proofs & Performance

| Benchmark | Test Target | Result | Status |
|---|---|---|:---:|
| **Concurrency CAS Claims** | 20 agents racing for 10 tasks | **1,914 ops/sec** throughput, p50: **5.26 ms**, **0 duplicate claims** | **PASS** |
| **Tenant Isolation** | 7 ISO attack scenarios | **0 cross-tenant reads**, tenant A cannot reach tenant B | **PASS** |
| **Procedural Learning** | Runbook failure trap | `restart-redis v1` fails $\rightarrow$ forks `v2` with precondition $\rightarrow$ re-ranks to `rollback-deploy` (succeeds) | **PASS** |
| **Bi-Temporal Time Travel** | Fact supersession | `payments-svc` ownership superseded; queries `as_of` earlier time return historical truth | **PASS** |
| **System Test Suite** | Full test suite | **38/38 tests passing** (100% green in ~2s) | **PASS** |

---

## 6. Graph Artifacts Generated

- Interactive Graph Visualization: [`graphify-out/graph.html`](graphify-out/graph.html)
- Community Labels: [`graphify-out/community_labels.json`](graphify-out/community_labels.json)
- Graph Data Export: [`graphify-out/graph.json`](graphify-out/graph.json)
- Technical Blog Post: [`BLOG_POST.md`](BLOG_POST.md)
- Submission Dossier: [`SUBMISSION_DOSSIER.md`](SUBMISSION_DOSSIER.md)
