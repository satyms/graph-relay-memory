# Hackathon Submission Dossier

**Hackathon**: Graph Hacks: Context for AI Agents (WeMakeDevs x FalkorDB)  
**Project Name**: Relay  
**Track Entered**: **Track 02 — Agent Coordination, Collaboration & Shared Graph Memory**  
**Repository**: [https://github.com/satyms/graph-relay-memory](https://github.com/satyms/graph-relay-memory)  
**Side Prize Entry**: Best Blog Post (AirPods 5) — [`BLOG_POST.md`](BLOG_POST.md)  

---

## 1. One-Line Pitch
**Relay gives autonomous AI agent fleets persistent episodic memory, race-free coordination, temporal fact supersession, and continuous procedural learning in FalkorDB.**

---

## 2. Short Description
Autonomous agent teams suffer from memory amnesia and collisions: flat vector stores discard causal relationships and temporal history, while concurrent agents clobber each other's work and repeat known failures. 

**Relay** solves this by modeling all memory and coordination subsystems as native nodes and relationships in **FalkorDB**:
- **Episodic Memory**: Append-only session timelines (`Session -> Event`) with causal session recovery.
- **Semantic Memory**: Temporal interval facts (`Entity -> Fact`) linked via `SUPERSEDES` relationships, allowing bi-temporal time-travel queries (*"What did we believe at 2:00 PM?"*).
- **Procedural Memory**: Laplace-smoothed runbook ranking with automated failure forking (`[:PREVIOUS_VERSION]`) that synthesizes preconditions when execution fails.
- **Atomic Coordination**: Single-statement Cypher Compare-and-Set (CAS) task claims with expiring leases that guarantee zero duplicate claims.
- **Cryptographic Tenancy**: Hard isolation using separate FalkorDB graphs per tenant (`tenant_<id>`) resolved strictly from SHA-256 bearer tokens.
- **Graph Topology & Insights**: Native FalkorDB `algo.pageRank` entity centrality and BFS blast radius calculation.
- **Local Acceleration**: Runs local inference via **Intel OpenVINO™ (Qwen2.5-7B INT4)** with automatic failover to **Google Gemini API**.

---

## 3. Verified Proof Metrics

| Proof | Target Metric | Measured Result |
|---|---|---|
| **Atomic CAS Concurrency** | 20 agents race for 10 tasks | **1,914 ops/sec**, p50: **5.26 ms**, **0 duplicate claims** |
| **Tenant Isolation** | 7 cross-tenant attack scenarios | **0 cross-tenant reads**, **7/7 ISO proofs passed** |
| **Procedural Learning** | Runbook failure recovery | `restart-redis v1` fails $\rightarrow$ forks `v2` with precondition $\rightarrow$ re-ranks to `rollback-deploy` (succeeds) |
| **Time-Travel Supersession** | Fact correction | `Team Core` superseded by `Team Billing`; historical queries accurately recall previous belief |
| **Test Coverage** | Full system test suite | **38/38 tests passing** in ~2.0s |

---

## 4. Key FalkorDB Cypher Queries

1. **Atomic CAS Task Claim**:
   ```cypher
   MATCH (t:Task {id: $task_id})
   WHERE t.status = 'open' AND t.claimed_by IS NULL
   SET t.status = 'in_progress', t.claimed_by = $agent_id, t.lease_expires_at = $expires
   RETURN t.id
   ```
2. **Bi-Temporal Fact Supersession**:
   ```cypher
   MATCH (e:Entity {name: $entity})-[:HAS_FACT]->(old:Fact {predicate: $predicate})
   WHERE old.valid_to IS NULL
   SET old.valid_to = $now, old.status = 'closed'
   RETURN old.id
   ```
3. **Native FalkorDB PageRank Entity Centrality**:
   ```cypher
   CALL algo.pageRank('Entity', 'DEPENDS_ON')
   YIELD node, score
   RETURN node.name AS service, round(score * 1000) / 1000 AS centrality
   ORDER BY score DESC
   ```

---

## 5. Submission Checklist & Rule Verification

- [x] **Primary Graph DB**: FalkorDB is the primary database powering all state and memory.
- [x] **Track Declared**: Track 02 — Agent Coordination, Collaboration & Shared Graph Memory.
- [x] **No Restricted / PII Data**: 100% synthetic incident response data.
- [x] **Graph Data Model Documented**: Documented in [`README.md`](README.md) and [`docs/GRAPH_DATA_MODEL.md`](docs/GRAPH_DATA_MODEL.md).
- [x] **AI Disclosure Included**: Documented in [`AI_DISCLOSURE.md`](AI_DISCLOSURE.md).
- [x] **Local Setup & Docker**: Detailed in [`README.md`](README.md) and [`docker-compose.yml`](docker-compose.yml).
- [x] **Demo Video Script Ready**: Documented in [`VIDEO_RECORDING_GUIDE.md`](VIDEO_RECORDING_GUIDE.md).
- [x] **Side Prize Blog Post Ready**: Documented in [`BLOG_POST.md`](BLOG_POST.md).
