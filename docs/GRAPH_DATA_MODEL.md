# Graph Data Model

This document is the source for the README's required "graph data model" and "Cypher queries the product depends on" sections.

> Cypher below follows openCypher as supported by FalkorDB. Confirm syntax for `EXISTS`, `FOREACH`, index creation and algorithm procedure names against https://docs.falkordb.com before relying on them. Anything marked **verify** has not been run yet.

## 1. Graphs in the FalkorDB instance

| Graph | Contents | Access |
|---|---|---|
| `control` | `Tenant`, `ApiKey`, `AuditEntry` | Server only |
| `tenant_<id>` | All memory and coordination data for one tenant | Server, using that tenant's key only |
| `shared_runbooks` | Starter `Procedure` and `Step` nodes | Read-only via `find_procedure` |

All timestamps are integer epoch milliseconds (`ts`, `valid_from`, `lease_expires_at`) for simple comparison.

## 2. Control graph

| Label | Properties |
|---|---|
| `Tenant` | `id`, `name`, `created_at` |
| `ApiKey` | `key_hash`, `agent_id`, `role`, `created_at`, `revoked` |
| `AuditEntry` | `id`, `ts`, `agent_id`, `tool`, `ok`, `error_code` |

Relationships: `(ApiKey)-[:BELONGS_TO]->(Tenant)`, `(AuditEntry)-[:ABOUT]->(Tenant)`.

## 3. Tenant graph: nodes

### Actors and episodes
| Label | Key properties |
|---|---|
| `Agent` | `id`, `role`, `created_at` |
| `Session` | `id`, `agent_id`, `started_at`, `ended_at`, `summary` |
| `Event` | `id`, `seq`, `type`, `summary`, `payload` (JSON string), `ts`, `idem_key` |

### Semantic knowledge
| Label | Key properties |
|---|---|
| `Entity` | `id`, `name`, `kind` (service, host, team, person), `created_at` |
| `Fact` | `id`, `predicate`, `value`, `confidence`, `valid_from`, `valid_to` (null = current), `status` (`active`, `stale`, `closed`), `visibility`, `owner_agent` |

### Procedural knowledge
| Label | Key properties |
|---|---|
| `Procedure` | `id`, `name`, `trigger`, `version`, `status` (`active`, `retired`), `success_count`, `fail_count`, `preconditions` (JSON list), `violated_assumption` |
| `Step` | `id`, `idx`, `text` |
| `Outcome` | `id`, `ts`, `success`, `note`, `failed_step` |

### Coordination
| Label | Key properties |
|---|---|
| `Incident` | `id`, `title`, `severity`, `status`, `opened_at` |
| `Task` | `id`, `title`, `status` (`blocked`, `open`, `claimed`, `done`), `priority`, `version`, `owner`, `lease_expires_at`, `result` |
| `Hypothesis` | `id`, `text`, `confidence`, `status` (`proposed`, `supported`, `rejected`) |
| `Evidence` | `id`, `summary`, `ref`, `ts` |
| `Handoff` | `id`, `from_agent`, `to_agent`, `status` (`pending`, `accepted`, `declined`), `context_summary`, `open_questions`, `created_at`, `accepted_at` |
| `Approval` | `id`, `action`, `target`, `requested_by`, `status` (`pending`, `approved`, `rejected`), `reason`, `requested_at`, `decided_at`, `decided_by` |

## 4. Tenant graph: relationships

| Relationship | From -> To | Purpose |
|---|---|---|
| `RAN` | Agent -> Session | Who ran which session |
| `HAS_EVENT` | Session -> Event | Session timeline membership |
| `NEXT` | Event -> Event | Ordered timeline |
| `MENTIONS` | Event -> Entity | Links episodes to knowledge |
| `HAS_FACT` | Entity -> Fact | Current and historical facts |
| `SUPERSEDES` | Fact -> Fact | Correction chain (new -> old) |
| `DERIVED_FROM` | Fact -> Event | Provenance for explainability |
| `DEPENDS_ON` | Entity -> Entity | Service dependency map (algorithms) |
| `HAS_STEP` | Procedure -> Step | Ordered runbook steps |
| `PREVIOUS_VERSION` | Procedure -> Procedure | Version lineage |
| `RESULTED_IN` | Procedure -> Outcome | Learning signal |
| `USED_IN` | Outcome -> Incident | Which incident used it |
| `HAS_TASK` | Incident -> Task | Work breakdown |
| `BLOCKED_BY` | Task -> Task | Dependency, cascade unblock |
| `CLAIMED_BY` | Task -> Agent | Current owner, for visualisation |
| `HAS_HYPOTHESIS` | Incident -> Hypothesis | Working theories |
| `SUPPORTED_BY` | Hypothesis -> Evidence | Why we believe it |
| `CREATED` | Agent -> Handoff | Who handed off |
| `TO` | Handoff -> Agent | Who receives it |
| `CARRIES` | Handoff -> Hypothesis / Evidence / Task | What is being passed |
| `REQUIRES` | Task -> Approval | Human-in-the-loop safety gate for risky actions |

## 5. Indexes

```cypher
CREATE INDEX FOR (t:Task) ON (t.id)
CREATE INDEX FOR (t:Task) ON (t.status)
CREATE INDEX FOR (e:Entity) ON (e.id)
CREATE INDEX FOR (e:Entity) ON (e.name)
CREATE INDEX FOR (f:Fact) ON (f.id)
CREATE INDEX FOR (ev:Event) ON (ev.idem_key)
CREATE INDEX FOR (p:Procedure) ON (p.id)
CREATE INDEX FOR (h:Handoff) ON (h.id)
CREATE INDEX FOR (a:Approval) ON (a.id)
```

Full-text (verify procedure names): index `Event.summary`, `Fact.value`, `Procedure.trigger`.

## 6. Key Cypher queries

### 6.1 Claim a task (atomic compare-and-set)
Zero rows returned means the caller lost the race.

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

After a successful claim, refresh the visual edge (best effort; `owner` is the source of truth):

```cypher
MATCH (t:Task {id: $task_id})-[old:CLAIMED_BY]->()
DELETE old
```
```cypher
MATCH (t:Task {id: $task_id}), (a:Agent {id: $agent_id})
MERGE (t)-[:CLAIMED_BY]->(a)
```

### 6.2 Renew a lease (only the owner)
```cypher
MATCH (t:Task {id: $task_id, owner: $agent_id, status: 'claimed'})
SET t.lease_expires_at = $now + $lease_ms
RETURN t.id
```

### 6.3 Reap expired leases
```cypher
MATCH (t:Task {status: 'claimed'})
WHERE t.lease_expires_at < $now
SET t.status = 'open', t.owner = null, t.version = t.version + 1
RETURN t.id
```

### 6.4 Complete a task and cascade-unblock dependants (verify)
```cypher
MATCH (t:Task {id: $task_id, owner: $agent_id})
SET t.status = 'done', t.result = $result
RETURN t.id
```
```cypher
MATCH (d:Task {status: 'blocked'})-[:BLOCKED_BY]->(:Task {id: $task_id})
OPTIONAL MATCH (d)-[:BLOCKED_BY]->(o:Task)
WHERE o.status <> 'done'
WITH d, count(o) AS remaining
WHERE remaining = 0
SET d.status = 'open'
RETURN d.id
```

### 6.5 Idempotent event write
```cypher
MATCH (s:Session {id: $session_id})
MERGE (e:Event {idem_key: $idem_key})
ON CREATE SET e.id = $event_id, e.type = $type, e.summary = $summary,
              e.payload = $payload, e.ts = $now, e.seq = $seq
MERGE (s)-[:HAS_EVENT]->(e)
RETURN e.id AS id
```

### 6.6 Upsert a fact, superseding the current one (two steps; verify)
Step 1 closes the current fact (no-op if none) and creates the new one:

```cypher
MATCH (e:Entity {id: $entity_id})
OPTIONAL MATCH (e)-[:HAS_FACT]->(old:Fact {predicate: $predicate})
WHERE old.valid_to IS NULL
SET old.valid_to = $now, old.status = 'closed'
CREATE (e)-[:HAS_FACT]->(new:Fact {
  id: $fact_id, predicate: $predicate, value: $value,
  confidence: $confidence, valid_from: $now, valid_to: null,
  status: 'active', visibility: $visibility, owner_agent: $agent_id })
RETURN new.id AS id
```
Step 2 links the correction chain and provenance:

```cypher
MATCH (new:Fact {id: $fact_id}),
      (e:Entity {id: $entity_id})-[:HAS_FACT]->(old:Fact {predicate: $predicate, valid_to: $now})
WHERE old.id <> new.id
MERGE (new)-[:SUPERSEDES]->(old)
```
```cypher
MATCH (f:Fact {id: $fact_id}), (ev:Event {id: $source_event_id})
MERGE (f)-[:DERIVED_FROM]->(ev)
```

### 6.7 What did we believe at time T?
```cypher
MATCH (e:Entity {name: $name})-[:HAS_FACT]->(f:Fact)
WHERE f.valid_from <= $t AND (f.valid_to IS NULL OR f.valid_to > $t)
RETURN f.predicate AS predicate, f.value AS value, f.confidence AS confidence
```

### 6.8 Rank procedures for a situation
```cypher
MATCH (p:Procedure {status: 'active'})
WHERE toLower(p.trigger) CONTAINS toLower($keyword)
RETURN p.id AS id, p.name AS name, p.version AS version, p.preconditions AS preconditions,
       (toFloat(p.success_count) + 1.0) / (toFloat(p.success_count + p.fail_count) + 2.0) AS score
ORDER BY score DESC
LIMIT $limit
```

### 6.9 Record a failure and fork a new procedure version (application-orchestrated)
1. Create `Outcome` and link it:
```cypher
MATCH (p:Procedure {id: $procedure_id}), (i:Incident {id: $incident_id})
CREATE (p)-[:RESULTED_IN]->(o:Outcome {id: $outcome_id, ts: $now, success: $success,
                                        note: $note, failed_step: $failed_step})
CREATE (o)-[:USED_IN]->(i)
SET p.success_count = p.success_count + CASE WHEN $success THEN 1 ELSE 0 END,
    p.fail_count = p.fail_count + CASE WHEN $success THEN 0 ELSE 1 END
RETURN p.id
```
2. On failure, the server copies the procedure's steps into a new `Procedure` (`version + 1`), sets `preconditions` and `violated_assumption`, links `(new)-[:PREVIOUS_VERSION]->(old)`, and sets the old one to `retired`.

### 6.10 Handoff
```cypher
MATCH (a:Agent {id: $from_agent}), (b:Agent {id: $to_agent})
CREATE (h:Handoff {id: $handoff_id, from_agent: $from_agent, to_agent: $to_agent,
                   status: 'pending', context_summary: $summary,
                   open_questions: $questions, created_at: $now})
CREATE (a)-[:CREATED]->(h)
CREATE (h)-[:TO]->(b)
RETURN h.id
```
```cypher
MATCH (h:Handoff {id: $handoff_id, to_agent: $agent_id, status: 'pending'})
SET h.status = 'accepted', h.accepted_at = $now
RETURN h.id
```

### 6.11 Blast radius (reverse dependency traversal)
```cypher
MATCH (s:Entity {name: $service})<-[:DEPENDS_ON*1..$depth]-(dep:Entity)
RETURN DISTINCT dep.name AS impacted, dep.kind AS kind
```
(Variable-length bound parameters may need to be inlined as a validated integer. **verify**)

### 6.12 Critical services by PageRank (verify procedure name)
```cypher
CALL algo.pageRank('Entity', 'DEPENDS_ON') YIELD node, score
RETURN node.name AS service, score
ORDER BY score DESC
LIMIT 5
```

### 6.13 Provenance: why do we believe this fact?
```cypher
MATCH path = (f:Fact {id: $fact_id})-[:SUPERSEDES|DERIVED_FROM*1..4]->(src)
RETURN path
```

### 6.14 Approval gate for risky actions

Request approval linked to a task:
```cypher
MATCH (t:Task {id: $task_id})
CREATE (a:Approval {
    id: $approval_id,
    action: $action,
    target: $target,
    requested_by: $requested_by,
    justification: $justification,
    status: 'pending',
    reason: '',
    requested_at: $now,
    decided_at: null,
    decided_by: null
})
CREATE (t)-[:REQUIRES]->(a)
RETURN a.id AS id
```

Decide approval (admin):
```cypher
MATCH (a:Approval {id: $approval_id})
SET a.status = $decision,
    a.reason = $reason,
    a.decided_at = $now,
    a.decided_by = $decided_by
RETURN a.id AS id, a.status AS status
```

Check if task is approved for risky action before completion:
```cypher
MATCH (t:Task {id: $task_id})-[:REQUIRES]->(a:Approval)
WHERE a.action = $action AND a.status = 'approved'
RETURN count(a) > 0 AS approved
```

## 7. Example subgraph (demo)

```
(acme)-[Entity checkout-api]-DEPENDS_ON->(payments-svc)-DEPENDS_ON->(postgres-primary)
(payments-svc)-HAS_FACT->(Fact owner="Core")  <-SUPERSEDES-(Fact owner="Billing")
(Incident INC-1)-HAS_TASK->(Task t1)-BLOCKED_BY->(Task t0)
(Incident INC-1)-HAS_HYPOTHESIS->(H1)-SUPPORTED_BY->(Evidence e1)
(Agent triage)-CREATED->(Handoff)-TO->(Agent investigator)
(Procedure restart-redis v2)-PREVIOUS_VERSION->(Procedure restart-redis v1)
(Task rollback-t1)-REQUIRES->(Approval status="approved" action="rollback_deploy")
```

