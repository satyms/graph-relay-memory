# Relay — Shared Graph Memory for Agent Teams

> Built for **Graph Hacks: Context for AI Agents** (WeMakeDevs x FalkorDB), **Track 02: Agent Memory and Coordination**.

Relay gives an autonomous team of AI agents a unified, multi-tenant memory and coordination engine powered entirely by **FalkorDB**. Memory, task claims, agent handoffs, semantic facts, and procedural runbooks are modeled as native graph nodes and edges that agents inspect and update at every turn.

---

## The Problem

Standard AI agent teams suffer from three fundamental limitations:
1. **Memory Amnesia**: Flat vector stores discard temporal sequence, entity relationships, and causal history.
2. **Coordination Collisions**: Agents step on each other's work or duplicate tasks due to race conditions.
3. **Procedural Stagnation**: When an agent fails executing a runbook, that failure is lost in a chat log; the next agent repeats the exact same mistake.

---

## What Relay Does

| Capability | Graph Data Model | Key Feature |
|---|---|---|
| **Episodic Memory** | `Session -> Event -> Event` | Idempotent append-only timeline, causal session reconstruction |
| **Semantic Memory** | `Entity -> Fact` with `valid_from` / `valid_to` | Temporal intervals with `SUPERSEDES` edge; enables bi-temporal time-travel queries ("What did we believe at 2:00 PM?") |
| **Procedural Memory** | `Procedure -> Step` | Laplace-smoothed ranking ($s = \frac{k+1}{n+2}$), failure forking with `PREVIOUS_VERSION` edge and automatic precondition synthesis |
| **Shared State & Claims** | `Incident -> Task / Hypothesis / Evidence` | Atomic single-query Compare-and-Set (CAS) task claims with expiring leases and automatic cascade unblocking |
| **Approval Safety Gate** | `(Task)-[:REQUIRES]->(Approval)` | Human-in-the-loop signoff gate for high-risk actions (`rollback_deploy`, `restart_service`, `scale_down`) |
| **Agent Handoffs** | `Handoff {from, to, status, context}` | Explicit, structured handoffs carrying context, tasks, and open questions |
| **Click-to-Explain** | Path traversal over `SUPERSEDES`, `DERIVED_FROM`, `SUPPORTED_BY` | One-click deterministic graph provenance and natural-language "because" rationale without LLM hallucination |
| **Graph Topology & Insights** | `Entity -[:DEPENDS_ON]-> Entity` | Native FalkorDB `algo.pageRank` entity centrality and BFS blast-radius calculation |
| **Tenant Isolation** | One FalkorDB graph per tenant (`tenant_<id>`) | Cryptographically enforced via SHA-256 bearer tokens in the `control` graph; immune to prompt-injection tenant spoofing |
| **Consolidation Worker** | Background worker | Synthesizes episodic events into high-confidence facts with `DERIVED_FROM` provenance and decays stale knowledge |

---

## Interactive Demo Features

1. **Chaos Button (Agent Failure & Auto-Recovery)**: Abort an agent mid-task with `POST /admin/chaos/kill-agent`. The task lease naturally expires (`CHAOS_LEASE_SECONDS = 10`), the background reaper unblocks the task, and surviving teammates automatically reclaim it without duplicate ownership.
2. **Time-Travel Slider**: Bi-temporal reconstruction via `GET /admin/graph/{tenant}?as_of=<epoch_ms>` and `GET /admin/timeline/{tenant}`. Drag the UI slider to inspect historical beliefs, dim superseded facts, and jump back to live SSE.
3. **Click-to-Explain**: Inspect any fact, hypothesis, or task via `GET /admin/explain/{tenant}/{node_id}` to illuminate its full provenance chain in the graph and read a data-driven justification.
4. **Relay vs Flat Memory Baseline**: Run `scripts/compare_baseline.py` to benchmark Relay against a fair flat memory baseline across Concurrency (20 workers racing 10 tasks), Correction (past vs present knowledge), and Multi-Tenant Isolation. View results live in the dashboard.
5. **Approval Gate for Risky Actions**: Gated completion on high-impact procedures. Remediators request approval, pending badges alert administrators, and admin approval enables execution via `POST /admin/approvals/{id}/decide`.

---

## Proofs Demonstrated in the Demo

1. **Atomic CAS Concurrency**: 20 agents race for 10 tasks; exactly 10 winners, 0 double-claims, ~1,900 ops/sec throughput.
2. **Cryptographic Tenant Isolation**: Tenant A's key cannot read, claim, or reference Tenant B's data (0 cross-tenant reads across 7 ISO test suites).
3. **Procedural Learning**: `restart-redis v1` fails on deploy trap $\rightarrow$ automatically retires and forks `v2` with new precondition $\rightarrow$ subsequent query selects `rollback-deploy v1` and succeeds.
4. **Bi-Temporal Time Travel**: Correcting `payments-svc` ownership from `Team Core` to `Team Billing` supersedes the fact while allowing queries `as_of` earlier timestamps to return the historical truth.
5. **Persistence & Chaos Recovery**: Killing agents mid-task leaves leases to cleanly expire and recover. Restarting agent processes restores complete situational awareness from FalkorDB.
6. **Human-in-the-Loop Safety**: Remediator cannot execute destructive actions without explicit, cryptographically authenticated admin approval.

---

## Quickstart

### 1. Prerequisites & FalkorDB
Ensure Docker or local FalkorDB is running:
```bash
docker run -p 6379:6379 -p 3000:3000 -d --name falkordb-relay falkordb/falkordb:latest
```
*(Or use `docker-compose up -d`)*

### 2. Environment Setup
```bash
# Clone and enter repo
git clone https://github.com/satyms/graph-relay-memory.git
cd graph-relay-memory

# Setup virtual environment
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
cp .env.example .env
```

### 3. Seed Synthetic Tenants & Runbooks
```bash
python scripts/seed.py
```

### 4. Start the Memory Server & Dashboard
```bash
uvicorn server.app.main:app --port 8080 --reload
```
Open **`http://localhost:8080/dashboard/`** in your browser to inspect the interactive force-directed graph, live SSE stream, task board, and proof panels.

### 5. Local LLM Acceleration (Optional / Recommended)
To run local inference via OpenVINO™ (Qwen2.5-7B-Instruct INT4):
```bash
python server_openvino.py --port 8000
```
*(If no local GPU/CPU model is loaded, Relay automatically falls back to Gemini API via `.env`)*

---

## Runtime Architecture

```
                                 ┌───────────────────────────────────┐
                                 │       Relay Web Dashboard         │
                                 │   (D3.js Force Graph & Proofs)    │
                                 └─────────────────▲─────────────────┘
                                                   │ SSE & REST
┌───────────────────────┐        ┌─────────────────┴─────────────────┐
│     Agent Fleet       │        │        FastAPI Memory Engine      │
│ ┌───────────────────┐ │  Tool  │ ┌───────────────────────────────┐ │
│ │ Triage Agent      │ │ Calls  │ │ Auth & Tenant Graph Resolver  │ │
│ ├───────────────────┤ │───────>│ ├───────────────────────────────┤ │
│ │ Investigator      │ │        │ │ Episodic / Semantic / Proced. │ │
│ ├───────────────────┤ │        │ ├───────────────────────────────┤ │
│ │ Remediator        │ │        │ │ Coordination & Leases         │ │
│ ├───────────────────┤ │        │ ├───────────────────────────────┤ │
│ │ Comms Agent       │ │        │ │ Approvals & Provenance Chain  │ │
│ └───────────────────┘ │        │ └───────────────┬───────────────┘ │
│                       │        └─────────────────┼─────────────────┘
└───────────▲───────────┘                          │ openCypher
            │                    ┌─────────────────▼─────────────────┐
     Inference API               │             FalkorDB              │
            │                    │ ┌───────────────┬───────────────┐ │
┌───────────┴───────────┐        │ │ control graph │ shared_runbks │ │
│   LLM Inference Layer │        │ ├───────────────┼───────────────┤ │
│ • OpenVINO™ Toolkit   │        │ │ tenant_acme   │ tenant_globex │ │
│   (Qwen2.5-7B INT4)   │        │ └───────────────┴───────────────┘ │
│ • Google Gemini Cloud │        └───────────────────────────────────┘
│   Fallback            │
└───────────────────────┘
```

---

## Verification & Test Suite

Run the full automated test suite (52 tests covering tenancy, memory, coordination, procedural learning, graph insight, dashboard endpoints, chaos button, time-travel, explainability, baseline comparison, and approval gates):
```bash
pytest -v
```

Run the standalone proof scripts:
```bash
# Concurrency & CAS Load Test (20 agents, 10 tasks)
python scripts/load_test.py --agents 20 --tasks 10

# Cross-Tenant Cryptographic Isolation Test (ISO-1 to ISO-7)
python scripts/isolation_test.py

# Relay vs Flat Memory Benchmark Comparison
python scripts/compare_baseline.py

# Complete End-to-End Incident Scenario & Learning Verification
pytest -v tests/test_e2e_scenario.py
```

---

## Key Cypher Queries the Product Depends On

### Atomic CAS Task Claim (with Version and Lease Expiry)
```cypher
MATCH (t:Task {id: $task_id})
WHERE t.status = 'open'
   OR (t.status = 'claimed' AND t.lease_expires_at < $now)
SET t.status = 'claimed',
    t.owner = $agent_id,
    t.version = t.version + 1,
    t.lease_expires_at = $now + $lease_ms
RETURN t.id AS id, t.version AS version
```

### Bi-Temporal Fact Supersession
```cypher
// 1. Close current active fact
MATCH (e:Entity {id: $entity_id})
OPTIONAL MATCH (e)-[:HAS_FACT]->(old:Fact {predicate: $predicate})
WHERE old.valid_to IS NULL
SET old.valid_to = $now, old.status = 'closed'
CREATE (e)-[:HAS_FACT]->(new:Fact {
  id: $fact_id, predicate: $predicate, value: $value,
  confidence: $confidence, valid_from: $now, valid_to: null,
  status: 'active', visibility: $visibility, owner_agent: $agent_id })
RETURN new.id AS id

// 2. Link SUPERSEDES correction lineage
MATCH (new:Fact {id: $fact_id}),
      (e:Entity {id: $entity_id})-[:HAS_FACT]->(old:Fact {predicate: $predicate, valid_to: $now})
WHERE old.id <> new.id
MERGE (new)-[:SUPERSEDES]->(old)
```

### Time-Travel Point-in-Time Snapshot Filtering
```cypher
MATCH (e:Entity)-[:HAS_FACT]->(f:Fact)
WHERE f.valid_from <= $as_of AND (f.valid_to IS NULL OR f.valid_to > $as_of)
RETURN e, f
```

### Click-to-Explain Provenance Traversal
```cypher
MATCH path = (f:Fact {id: $fact_id})-[:SUPERSEDES|DERIVED_FROM*1..4]->(src)
RETURN path
```

### Approval Gate Creation & Verification
```cypher
// Request approval attached to a task
MATCH (t:Task {id: $task_id})
CREATE (a:Approval {
    id: $approval_id, action: $action, target: $target,
    requested_by: $requested_by, justification: $justification,
    status: 'pending', reason: '', requested_at: $now,
    decided_at: null, decided_by: null
})
CREATE (t)-[:REQUIRES]->(a)
RETURN a.id AS id

// Check if task has approval for risky action before complete_task
MATCH (t:Task {id: $task_id})-[:REQUIRES]->(a:Approval)
WHERE a.action = $action AND a.status = 'approved'
RETURN count(a) > 0 AS approved
```

### Procedural Laplace-Smoothed Ranking
$$Score = \frac{success\_count + 1}{success\_count + fail\_count + 2}$$

```cypher
MATCH (p:Procedure {status: 'active'})
OPTIONAL MATCH (p)-[:HAS_STEP]->(s:Step)
RETURN p.id, p.name, p.trigger, p.version, p.success_count, p.fail_count, s.idx, s.text
ORDER BY p.id, s.idx ASC
```

### Native FalkorDB PageRank Entity Centrality
```cypher
CALL algo.pageRank('Entity', 'DEPENDS_ON')
YIELD node, score
RETURN node.name AS service, round(score * 1000) / 1000 AS centrality
ORDER BY score DESC
```

---

## Admin Endpoints Summary

| Endpoint | Method | Description |
|---|---|---|
| `/admin/tenants` | POST | Provision tenant graph and issue agent keys |
| `/admin/stream` | GET | Real-time SSE event bus |
| `/admin/graph/{tenant}?as_of=<ms>` | GET | Graph snapshot with temporal filtering |
| `/admin/timeline/{tenant}` | GET | Timeline bounds and milestone markers |
| `/admin/explain/{tenant}/{node_id}` | GET | Graph provenance chain & "because" rationale |
| `/admin/chaos/kill-agent` | POST | Abort agent mid-claim to demonstrate lease expiry |
| `/admin/chaos/reclaim-task` | POST | Surviving agent auto-reclaim of expired tasks |
| `/admin/approvals?tenant=...` | GET | List pending/decided approval requests |
| `/admin/approvals/{id}/decide` | POST | Human-in-the-loop decision (approve/reject) |
| `/admin/compare/latest` | GET | Latest Relay vs Flat Memory benchmark report |
| `/admin/consolidate` | POST | Trigger background memory consolidation |


---

## Hackathon Compliance

- **Primary Database**: FalkorDB is the core state store and primary graph database. All memory types and multi-agent coordination rely on it.
- **Track**: **Track 02 — Agent Coordination, Collaboration & Shared Graph Memory**.
- **Data**: 100% synthetic incident response data. No restricted, private, or PII data.
- **AI Disclosure**: Documented in [`AI_DISCLOSURE.md`](AI_DISCLOSURE.md).
- **License**: MIT License ([`LICENSE`](LICENSE)).
