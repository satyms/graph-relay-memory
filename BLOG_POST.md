# Why Chat History is Not Memory: Building Shared Graph Memory for Agent Teams with FalkorDB

*Submitted for **Graph Hacks: Context for AI Agents** (WeMakeDevs x FalkorDB) — **Track 02: Agent Memory and Coordination***

---

When building multi-agent systems, the default approach to memory is deceptively simple: stuff recent messages into the context window, and when context runs out, chunk everything into an embedding vector store.

Within five minutes of running a multi-agent team in production, this breaks down.

Agents talk past each other. An investigator agent diagnoses an anomaly, but the remediator repeats the same diagnostic commands because chat summaries discard entity relationships. Worse, two agents attempt to remediate the same service simultaneously, clobbering each other. And when an agent executes a runbook that fails because of a recent deployment, that failure evaporates into conversational ether—dooming the next agent to repeat the exact same failure.

To solve this, we built **Relay**: a shared, multi-tenant memory and coordination engine for agent fleets powered entirely by **FalkorDB**.

---

## 1. Why Chat History is Not Memory

Human memory is not a text log. Cognitive science models memory across distinct subsystems:
- **Episodic memory**: Sequential experiences ordered in time ("What happened in session 12?").
- **Semantic memory**: Facts and relationships about the world ("Who owns payments-svc? What is its SLA?").
- **Procedural memory**: Knowledge of how to perform tasks, updated when actions fail or succeed ("How do we recover Redis latency?").

When you serialize all three into conversational text:
1. **Temporal causality is lost**: A vector similarity search on "payments service owner" returns two conflicting chunks from different days with no causal lineage.
2. **Race conditions are invisible**: Text cannot coordinate concurrent agents or provide atomic task leases.
3. **Failures do not create learning**: An agent cannot fork an existing procedure to append a newly learned precondition.

---

## 2. Modeling Memory as a Native Graph in FalkorDB

In Relay, all memory subsystems live inside **FalkorDB** as native nodes and relationships.

```
       (Session)-[:HAS_EVENT]->(Event)               [Episodic Memory]
                                  │
                                  ▼
(Entity)-[:HAS_FACT]->(Fact)-[:SUPERSEDES]->(Fact)   [Semantic Memory]
                                  │
                                  ▼
        (Incident)-[:USES_PROCEDURE]->(Procedure)   [Procedural Memory]
                                          │
                               [:PREVIOUS_VERSION]
                                          ▼
                                     (Procedure)
```

### Episodic Memory
Each agent turn logs structured `Event` nodes linked to a `Session` timeline. Events carry sequence numbers (`seq`), event types, affected entity references, and idempotency keys, providing a tamper-proof record of what each agent observed and decided.

### Semantic Memory & Bi-Temporal Time Travel
Facts are not static strings. Each `Fact` has `valid_from` and `valid_to` timestamps. When an agent discovers that service ownership changed from `Team Core` to `Team Billing`:
1. The active fact is closed (`valid_to = now`).
2. A new fact is created.
3. A `[:SUPERSEDES]` edge links the new fact to the old fact.

Because historical facts are never destroyed, agents can perform **bi-temporal time-travel queries**:
```cypher
MATCH (e:Entity {name: $entity})-[:HAS_FACT]->(f:Fact {predicate: $predicate})
WHERE f.valid_from <= $as_of AND (f.valid_to IS NULL OR f.valid_to > $as_of)
RETURN f.value
```
An agent can ask: *"What did the team believe at 2:00 PM before the incident escalated?"*

### Procedural Memory & Laplace Smoothing
Runbooks are modeled as `Procedure` nodes with ordered `Step` nodes. Each procedure maintains `success_count` and `fail_count`.
Rather than picking procedures by raw success rate, Relay ranks candidate runbooks using smoothed **Laplace probability**:
$$\text{Score} = \frac{\text{success\_count} + 1}{\text{success\_count} + \text{fail\_count} + 2}$$

When `restart-redis v1` fails because an unannounced deployment broke cache serialization, Relay records the `violated_assumption` and forks `restart-redis v2` with a `[:PREVIOUS_VERSION]` link, retiring `v1` and adding a new precondition: *"Check for a deployment in the last 30 minutes before restarting cache"*. On the next incident, the re-ranked query automatically picks `rollback-deploy` instead.

---

## 3. Compare-and-Set Task Claims in One Cypher Statement

In a multi-agent system, avoiding race conditions is critical. If Agent A and Agent B both detect an alert, they must not both claim the remediation task.

Relay achieves **atomic Compare-and-Set (CAS) claims** in a single FalkorDB write query:

```cypher
MATCH (t:Task {id: $task_id})
WHERE t.status = 'open' AND t.claimed_by IS NULL
SET t.status = 'in_progress',
    t.claimed_by = $agent_id,
    t.lease_expires_at = $expires
RETURN t.id
```

Because FalkorDB executes graph writes with serializable consistency, exactly one agent wins the claim. The other receives a `CONFLICT` status and claims the next open task. Every claim carries an expiring lease (`lease_expires_at`). If an agent crashes or stops renewing, a background reaper automatically transitions the task back to `open`, preventing deadlocks.

---

## 4. One Graph per Tenant: Cryptographic Isolation

Many multi-tenant architectures rely on adding `WHERE tenant_id = 'acme'` to every query. If an LLM crafts a prompt-injection payload or tool parameters are spoofed, data leaks across tenants.

Relay enforces hard isolation using FalkorDB's native multi-graph architecture:
1. Every tenant has its own isolated graph (e.g. `tenant_acme`, `tenant_globex`).
2. A separate `control` graph stores SHA-256 hashed bearer keys.
3. The server resolves the incoming bearer token strictly in the `control` graph to derive `(tenant_id, graph_name)`.
4. Tenant agents **never pass graph or tenant names in tool calls**—the graph context is derived server-side from cryptographic credentials.

---

## 5. What the Concurrency & Isolation Proofs Showed

To prove Relay's guarantees, we developed two automated proof suites:

### Concurrency Load Test (`scripts/load_test.py`)
- **Setup**: 20 concurrent agent threads racing to claim 10 open tasks simultaneously.
- **Results**:
  - **Total Operations**: 155 claim transactions
  - **Throughput**: **1,914 operations / second**
  - **p50 Latency**: **5.26 ms**
  - **p95 Latency**: **18.07 ms**
  - **Duplicate / Double Claims**: **0** (Exactly 10 winners, 10 conflicts handled)

### Cross-Tenant Isolation Test (`scripts/isolation_test.py`)
- **Suite**: 7 scenarios (ISO-1 to ISO-7) covering cross-tenant entity queries, task hijacking, graph-binding spoofing, key revocation audits, and shared catalog immutability.
- **Results**: **0 cross-tenant reads succeeded. 7/7 isolation proofs PASSED.**

---

## 6. What We Would Build Next

1. **Vector & Graph Hybrid Indexing**: Integrating FalkorDB's native vector indices directly on `Event` and `Fact` embeddings for semantic similarity alongside graph traversal.
2. **Dynamic Consensus Voting**: Allowing agent quorums to vote on procedure retirements when failure rates exceed thresholds across multiple tenants.
3. **Distributed Graph Federation**: Syncing shared runbooks across edge clusters while preserving tenant-local execution data.

---

## Try Relay

- **GitHub Repository**: [satyms/graph-relay-memory](https://github.com/satyms/graph-relay-memory) (Branch `nyx`)
- **Track**: Track 02 — Agent Coordination, Collaboration & Shared Graph Memory
- **Tech Stack**: FalkorDB, OpenVINO™ Toolkit (Qwen2.5-7B INT4), Google Gemini API, FastAPI, D3.js
