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
| **Agent Handoffs** | `Handoff {from, to, status, context}` | Explicit, structured handoffs carrying context, tasks, and open questions |
| **Graph Topology & Insights** | `Entity -[:DEPENDS_ON]-> Entity` | Native FalkorDB `algo.pageRank` entity centrality and BFS blast-radius calculation |
| **Tenant Isolation** | One FalkorDB graph per tenant (`tenant_<id>`) | Cryptographically enforced via SHA-256 bearer tokens in the `control` graph; immune to prompt-injection tenant spoofing |
| **Consolidation Worker** | Background worker | Synthesizes episodic events into high-confidence facts with `DERIVED_FROM` provenance and decays stale knowledge |

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
│ ├───────────────────┤ │        │ └───────────────┬───────────────┘ │
│ │ Comms Agent       │ │        └─────────────────┼─────────────────┘
│ └───────────────────┘ │                          │ openCypher
└───────────▲───────────┘        ┌─────────────────▼─────────────────┐
            │                    │             FalkorDB              │
     Inference API               │ ┌───────────────┬───────────────┐ │
            │                    │ │ control graph │ shared_runbks │ │
┌───────────┴───────────┐        │ ├───────────────┼───────────────┤ │
│   LLM Inference Layer │        │ │ tenant_acme   │ tenant_globex │ │
│ • OpenVINO™ Toolkit   │        │ └───────────────┴───────────────┘ │
│   (Qwen2.5-7B INT4)   │        └───────────────────────────────────┘
│ • Google Gemini Cloud │
│   Fallback            │
└───────────────────────┘
```

---

## Proofs Demonstrated in the Demo

1. **Atomic CAS Concurrency**: 20 agents race for 10 tasks; exactly 10 winners, 0 double-claims, ~1,900 ops/sec throughput.
2. **Cryptographic Tenant Isolation**: Tenant A's key cannot read, claim, or reference Tenant B's data (0 cross-tenant reads across 7 ISO test suites).
3. **Procedural Learning**: `restart-redis v1` fails on deploy trap $\rightarrow$ automatically retires and forks `v2` with new precondition $\rightarrow$ subsequent query selects `rollback-deploy v1` and succeeds.
4. **Bi-Temporal Time Travel**: Correcting `payments-svc` ownership from `Team Core` to `Team Billing` supersedes the fact while allowing queries `as_of` earlier timestamps to return the historical truth.
5. **Persistence**: Restarting agent processes restores complete situational awareness from FalkorDB graph memory.

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

## Verification & Test Suite

Run the full automated test suite (38 tests covering tenancy, memory, coordination, procedural learning, graph insight, and dashboard endpoints):
```bash
pytest -v
```

Run the standalone proof scripts:
```bash
# Concurrency & CAS Load Test (20 agents, 10 tasks)
python scripts/load_test.py --agents 20 --tasks 10

# Cross-Tenant Cryptographic Isolation Test (ISO-1 to ISO-7)
python scripts/isolation_test.py

# Complete End-to-End Incident Scenario & Learning Verification
pytest -v tests/test_e2e_scenario.py
```

---

## Key Cypher Queries

### Atomic CAS Task Claim
```cypher
MATCH (t:Task {id: $task_id})
WHERE t.status = 'open' AND t.claimed_by IS NULL
SET t.status = 'in_progress', t.claimed_by = $agent_id, t.lease_expires_at = $expires
RETURN t.id
```

### Temporal Fact Supersession
```cypher
// Close active fact
MATCH (e:Entity {name: $entity})-[:HAS_FACT]->(old:Fact {predicate: $predicate})
WHERE old.valid_to IS NULL
SET old.valid_to = $now, old.status = 'closed'
RETURN old.id

// Link new fact with lineage
MATCH (e:Entity {name: $entity}), (old:Fact {id: $old_id})
CREATE (e)-[:HAS_FACT]->(new:Fact {predicate: $predicate, value: $value, valid_from: $now, valid_to: null, status: 'active'})
CREATE (new)-[:SUPERSEDES]->(old)
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

## Hackathon Compliance

- **Primary Database**: FalkorDB is the core state store and primary graph database. All memory types and multi-agent coordination rely on it.
- **Track**: **Track 02 — Agent Coordination, Collaboration & Shared Graph Memory**.
- **Data**: 100% synthetic incident response data. No restricted, private, or PII data.
- **AI Disclosure**: Documented in [`AI_DISCLOSURE.md`](AI_DISCLOSURE.md).
- **License**: MIT License ([`LICENSE`](LICENSE)).
