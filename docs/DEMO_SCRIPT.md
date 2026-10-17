# Demo Script and Seed Data

Target: a **3-minute** video that shows five proofs with the graph visible the whole time. All data is synthetic.

## 1. Scenario

**Company:** Acme (tenant A). **Rival tenant:** Globex (tenant B), same service names, different facts.

**Incident:** `INC-1`, "Checkout latency spike", severity high.

### Seed entities (tenant Acme)
| Entity | Kind | Notes |
|---|---|---|
| `checkout-api` | service | depends on `payments-svc` and `redis-cache` |
| `payments-svc` | service | depends on `postgres-primary`; owner fact = `Team Core` |
| `redis-cache` | service | |
| `postgres-primary` | host | |
| `auth-svc` | service | red herring: noisy but healthy |

### Seed procedures
| Procedure | Trigger | Initial state |
|---|---|---|
| `restart-redis` v1 | "cache latency", "redis" | 2 successes, 0 failures. Looks like the best option |
| `rollback-deploy` v1 | "recent deploy", "latency after deploy" | 1 success, 1 failure |
| `scale-db-pool` v1 | "connection exhaustion" | 0 outcomes |

### Seed traps
1. **Stale ownership:** `payments-svc owner = Team Core` is outdated. A teammate corrects it to `Team Billing` mid-demo, and the old value stays queryable.
2. **Tempting but wrong runbook:** `restart-redis` ranks first, but a deploy 20 minutes ago caused the problem. It fails, and the system learns the precondition "check for a deploy in the last 30 minutes before restarting cache".
3. **Red herring:** `auth-svc` shows noisy logs. The Investigator rules it out and records the evidence.
4. **Cross-tenant bait:** Globex has `payments-svc` with `owner = Team Alpha`.

## 2. Storyboard (3:00)

| Time | On screen | Narration (short) | Proof |
|---|---|---|---|
| 0:00 to 0:15 | Title, one-line problem, dashboard with empty graph | "Agents forget and collide. Relay gives them a shared graph memory in FalkorDB." | Setup |
| 0:15 to 0:50 | Triage opens INC-1, creates hypothesis and tasks, hands off to Investigator. Handoff node appears with open questions | "Triage doesn't pass a chat log. It writes a handoff node with context and open questions." | Handoffs, shared state |
| 0:50 to 1:20 | Investigator accepts, claims a task, attaches evidence, rules out `auth-svc`, hands off to Remediator. Blast radius highlights affected services | "Every claim carries a lease, and every conclusion links to evidence." | Provenance, MCP tool selection |
| 1:20 to 1:55 | Remediator picks `restart-redis`, it fails, `violated_assumption` is recorded, new version with a precondition appears. Re-run chooses `rollback-deploy` and succeeds | "Failure doesn't vanish. The procedure forks with a new precondition." | Procedural learning |
| 1:55 to 2:15 | Correct `payments-svc` owner; run `query_facts(as_of=earlier)` and show both values with the `SUPERSEDES` edge | "We can ask what we believed at 2pm." | Time travel |
| 2:15 to 2:40 | Kill all agents, restart one. It calls `start_session` and recalls INC-1 | "New process, same memory." | Persistence |
| 2:40 to 2:55 | Load test: 20 agents, 10 tasks, counters show 10 winners, 0 duplicates. Then isolation test: Acme key asks for Globex node, blocked | "Concurrency is safe and tenants can't see each other." | Concurrency, isolation |
| 2:55 to 3:00 | Repo link, track name | "Relay. Track 02." | Close |

## 3. Pre-demo setup

1. `docker run` FalkorDB, run `scripts/seed.py` for both tenants.
2. Start the server and dashboard; confirm the graph shows seed entities.
3. Open three windows: dashboard graph, agent log stream, terminal for scripts.
4. Set agent temperature low and use the scripted scenario so the failure and learning moment is reliable.
5. Hide keys and tokens. Use a clean browser profile.

## 4. Dashboard must show

- Live graph with node colors by memory type (episodic, semantic, procedural, coordination)
- Handoff feed with from, to, status
- Task board with owner and lease countdown
- Fact timeline with the `SUPERSEDES` chain
- Load test counters (claims won, conflicts, duplicates = 0) and isolation test table

## 5. Backup plan

- If an LLM step misbehaves, replay a recorded run from `scripts/replay.py` that writes the same graph operations.
- If the dashboard breaks, fall back to FalkorDB Browser with saved queries (list them in this file once finalised).
- Record the video in segments so a bad take only costs one segment.

## 6. Saved FalkorDB Browser queries (fill in during build)

```cypher
// Whole incident view
MATCH (i:Incident {id: 'INC-1'})-[r*1..3]-(n) RETURN i, r, n

// Fact history for an entity
MATCH (e:Entity {name: 'payments-svc'})-[:HAS_FACT]->(f:Fact) RETURN e, f ORDER BY f.valid_from

// Handoff chain
MATCH (a:Agent)-[:CREATED]->(h:Handoff)-[:TO]->(b:Agent) RETURN a, h, b

// Procedure lineage
MATCH p = (v2:Procedure)-[:PREVIOUS_VERSION*1..3]->(v1:Procedure) RETURN p
```

## 7. Optional blog post outline (AirPods side prize)

1. Why chat history is not memory
2. Modeling episodic, semantic and procedural memory as a graph
3. Compare-and-set claims in one Cypher statement
4. One graph per tenant in FalkorDB
5. What the load and isolation tests showed
6. What we would build next
