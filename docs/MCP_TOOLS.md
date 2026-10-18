# MCP Tool Specification

The memory server exposes a small set of typed tools. Agents never run raw Cypher.

Tools marked ★ are MVP. Everything else is a stretch goal.

## Conventions

- **Auth:** `Authorization: Bearer <api_key>`. The key resolves to `(tenant, agent_id, role)`. No tool takes `tenant_id` or `agent_id` as an argument; the server fills them in.
- **Idempotency:** every write takes an optional `idempotency_key` (string). A replay returns the original result.
- **Limits:** every recall tool takes `limit` (default 10, max 50). The server also caps total returned characters.
- **Timestamps:** epoch milliseconds.
- **Errors:** responses carry `error.code` and `error.message`.

| Code | Meaning |
|---|---|
| `FORBIDDEN` | Bad key, revoked key, or action not allowed for this role |
| `NOT_FOUND` | Node does not exist in this tenant's graph |
| `CONFLICT` | Compare-and-set lost (task already claimed, version mismatch) |
| `LEASE_EXPIRED` | Caller no longer owns the task |
| `INVALID` | Input failed validation |
| `UNAVAILABLE` | Database unavailable, retry with backoff |

---

## 1. Episodic memory

### ★ `start_session`
Starts a session and returns recent context for this agent.
- **In:** none
- **Out:** `session_id`, `last_session_summary`, `open_handoffs` (pending handoffs addressed to this agent), `open_tasks_claimed_by_me`

### ★ `log_event`
Appends an event to the current session timeline.
- **In:** `session_id`, `type` (`observation`, `action`, `decision`, `message`), `summary`, `payload?` (object), `entities?` (list of entity names), `idempotency_key?`
- **Out:** `event_id`, `seq`
- **Graph effect:** creates `Event`, `HAS_EVENT`, `NEXT`, and `MENTIONS` edges.

### ★ `recall_episodes`
Fetches past events.
- **In:** `query?` (keywords), `entity?`, `since?`, `until?`, `session_id?`, `limit?`
- **Out:** list of `{event_id, ts, type, summary, session_id, agent_id}`

### `end_session`
- **In:** `session_id`, `summary`
- **Out:** `ok`

---

## 2. Semantic memory

### ★ `upsert_fact`
Creates a fact, closing and superseding the current one for the same entity and predicate.
- **In:** `entity`, `predicate`, `value`, `confidence?` (0 to 1, default 0.8), `source_event_id?`, `visibility?` (`team` default, `private`), `idempotency_key?`
- **Out:** `fact_id`, `superseded_fact_id?`
- **Graph effect:** `Fact`, `HAS_FACT`, `SUPERSEDES`, `DERIVED_FROM`; creates the `Entity` if new.

### ★ `query_facts`
- **In:** `entity?`, `predicate?`, `as_of?` (timestamp, default now), `include_stale?`, `limit?`
- **Out:** list of `{fact_id, entity, predicate, value, confidence, valid_from, valid_to}`

### ★ `fact_history`
Shows every version of a fact.
- **In:** `entity`, `predicate`
- **Out:** ordered list of versions with `valid_from`, `valid_to`, `author_agent`, `source_event_id`

### `forget_fact`
- **In:** `fact_id`, `reason`
- **Out:** `ok`
- **Graph effect:** sets `valid_to` and `status = 'closed'`; the node stays for audit.

---

## 3. Procedural memory

### ★ `find_procedure`
Finds runbooks for a situation, ranked by smoothed success rate. Searches the tenant graph first, then `shared_runbooks`.
- **In:** `situation` (text), `limit?`
- **Out:** list of `{procedure_id, name, version, steps[], preconditions[], score, success_count, fail_count, source}`

### ★ `record_outcome`
Reports how a procedure went. On failure, forks a new version.
- **In:** `procedure_id`, `incident_id`, `success` (bool), `note?`, `failed_step?` (index), `violated_assumption?`, `new_precondition?`
- **Out:** `outcome_id`, `new_procedure_id?`
- **Graph effect:** `Outcome`, counters updated; on failure a new `Procedure` version with `PREVIOUS_VERSION`, the new precondition, and the old version retired.

### `get_procedure`
- **In:** `procedure_id`, `include_history?`
- **Out:** procedure with steps and version lineage

---

## 4. Coordination

### ★ `open_incident`
- **In:** `title`, `severity`
- **Out:** `incident_id`

### ★ `create_task`
- **In:** `incident_id`, `title`, `priority?`, `blocked_by?` (list of task ids)
- **Out:** `task_id`, `status` (`open`, or `blocked` if it has unfinished blockers)

### ★ `list_open_work`
- **In:** `incident_id?`, `limit?`
- **Out:** open tasks, tasks claimed by others (with owner and lease time), and pending handoffs for me

### ★ `claim_task`
Atomic compare-and-set claim with a lease.
- **In:** `task_id`, `lease_seconds?` (default 60)
- **Out:** `task_id`, `version`, `lease_expires_at`
- **Errors:** `CONFLICT` if another agent holds it

### ★ `renew_lease`
- **In:** `task_id`, `lease_seconds?`
- **Out:** `lease_expires_at`
- **Errors:** `LEASE_EXPIRED` if the caller no longer owns it

### `release_task`
- **In:** `task_id`, `note?`
- **Out:** `ok`

### ★ `complete_task`
Marks done and unblocks dependants whose blockers are all done.
- **In:** `task_id`, `result`
- **Out:** `unblocked_task_ids[]`

### ★ `add_hypothesis`
- **In:** `incident_id`, `text`, `confidence?`
- **Out:** `hypothesis_id`

### ★ `attach_evidence`
- **In:** `hypothesis_id`, `summary`, `ref?`, `supports` (bool; if false the hypothesis may move to `rejected`)
- **Out:** `evidence_id`, `hypothesis_status`

### ★ `create_handoff`
- **In:** `to_agent` (role or id), `context_summary`, `open_questions?` (list), `task_id?`, `hypothesis_ids?`, `evidence_ids?`
- **Out:** `handoff_id`

### ★ `accept_handoff`
- **In:** `handoff_id`
- **Out:** `context_summary`, `open_questions`, linked `hypotheses`, `evidence`, `task`

### `list_handoffs`
- **In:** `status?` (`pending` default), `direction?` (`to_me`, `from_me`)
- **Out:** list of handoff summaries

---

## 5. Insight tools (graph algorithms)

### `blast_radius`
- **In:** `service`, `depth?` (default 3, max 5)
- **Out:** impacted entities with distance

### `rank_critical_services`
- **In:** `limit?`
- **Out:** services ranked by PageRank over `DEPENDS_ON`

### `explain`
Shows why the system believes something.
- **In:** `node_id` (fact, hypothesis or task)
- **Out:** provenance chain (supersedes, derived-from events, evidence) as nodes and edges the dashboard can draw

### `request_approval`
Request human-in-the-loop admin approval before executing risky actions (`rollback_deploy`, `restart_service`, `scale_down`). Role rule: restricted to `remediator`.
- **In:** `task_id`, `action`, `justification`, `target?`
- **Out:** `{ok: true, approval_id, task_id, action, status: "pending", requested_at}`

### `check_approval`
Check decision status of an approval gate.
- **In:** `approval_id`
- **Out:** `{ok: true, approval: {approval_id, action, target, requested_by, status, reason, justification, requested_at, decided_at, decided_by}}`

---

## 6. Admin endpoints (not MCP tools, not visible to agents)

| Endpoint | Purpose |
|---|---|
| `POST /admin/tenants` | Create tenant graph and issue agent keys |
| `POST /admin/consolidate` | Run consolidation now (for deterministic demos) |
| `GET /admin/stream` | SSE feed of graph changes for the dashboard |
| `GET /admin/graph/{tenant}?as_of=<ms>` | Snapshot for dashboard, with optional historical point-in-time filtering |
| `GET /admin/timeline/{tenant}` | Min/max timestamps and key change markers for time travel |
| `GET /admin/explain/{tenant}/{node_id}` | Provenance chain nodes/edges and deterministic "because" rationale |
| `POST /admin/chaos/kill-agent` | Chaos button: abort agent mid-task without releasing claim for lease expiry demo |
| `POST /admin/chaos/reclaim-task` | Surviving agent recovery of re-opened expired tasks |
| `GET /admin/approvals?tenant=...` | List pending and decided approval requests |
| `POST /admin/approvals/{id}/decide` | Human-in-the-loop decision: approve or reject risky agent actions |
| `GET /admin/compare/latest` | Concurrency, Correction, and Isolation comparison vs flat memory baseline |

---

## 7. Role permissions (suggested)

| Role | Allowed |
|---|---|
| `triage` | all episodic and semantic tools, `open_incident`, `create_task`, `add_hypothesis`, `create_handoff` |
| `investigator` | read tools, `claim_task`, `attach_evidence`, `add_hypothesis`, `create_handoff`, `blast_radius` |
| `remediator` | read tools, `find_procedure`, `record_outcome`, `claim_task`, `complete_task`, `create_handoff`, `request_approval`, `check_approval` |
| `comms` | read tools, `log_event`, `upsert_fact`, `accept_handoff` |

Role checks are optional for the MVP but make a clean "read vs write separation" story.

---

## 8. Agent prompt hint: choosing the right tool

Put this in every agent's system prompt so tool selection is deliberate:

- Something that happened this session -> `log_event`
- Something that stays true until changed -> `upsert_fact`
- A way of doing something that worked or failed -> `record_outcome`
- Work to be done by someone -> `create_task` / `claim_task`
- Passing the baton to another agent -> `create_handoff` with open questions
- Before starting any incident -> `start_session`, `find_procedure`, `query_facts`
