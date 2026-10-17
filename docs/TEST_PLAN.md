# Test Plan

These tests double as the **proofs** shown in the demo. Each one has a script or pytest module and a clear pass condition.

## How to run

```bash
pytest tests/ -q                       # unit and integration
python scripts/isolation_test.py       # cross-tenant proof
python scripts/load_test.py --agents 20 --tasks 10   # concurrency proof
```

Run against a fresh FalkorDB with `scripts/seed.py` applied.

## 1. Tenant isolation (`tests/test_isolation.py`, `scripts/isolation_test.py`)

| ID | Scenario | Pass condition |
|---|---|---|
| ISO-1 | Tenant A key calls `query_facts` for an entity that exists only in tenant B | Returns empty or `NOT_FOUND`, never B's data |
| ISO-2 | Tenant A key calls `accept_handoff` / `claim_task` with a node id from tenant B | `NOT_FOUND`, B's node unchanged |
| ISO-3 | Tool call includes a `tenant_id` or `graph` argument | Ignored or rejected with `INVALID`; data still comes from the key's tenant |
| ISO-4 | Revoked or unknown key | `FORBIDDEN`, audit entry written |
| ISO-5 | Same entity name (`payments-svc`) exists in both tenants with different facts | Each tenant sees only its own facts |
| ISO-6 | After the run, count nodes in each tenant graph | No node in A references a node id from B |
| ISO-7 | Attempt to write to `shared_runbooks` through any tool | Rejected; shared graph is unchanged |

Demo output: a table of attempts and results, ending with "0 cross-tenant reads succeeded".

## 2. Concurrency (`tests/test_concurrency.py`, `scripts/load_test.py`)

| ID | Scenario | Pass condition |
|---|---|---|
| CON-1 | 20 agents race to claim 10 open tasks | Exactly 10 successful claims, 0 tasks with two owners, 10 agents receive `CONFLICT` or move on to another task |
| CON-2 | Same agent retries `log_event` 5 times with one `idempotency_key` | Exactly 1 `Event` node |
| CON-3 | 10 agents upsert the same entity/predicate at once | Exactly 1 fact with `valid_to = null` afterwards; the rest closed, forming a `SUPERSEDES` chain |
| CON-4 | Mixed load: 50 concurrent reads and writes across 2 tenants for 30 seconds | No errors other than expected `CONFLICT`; no cross-tenant leakage; report p50 and p95 latency |
| CON-5 | Agent claims a task then stops renewing | After lease expiry the reaper re-opens it and another agent claims it |
| CON-6 | Completing a blocker task | Dependants with all blockers done become `open`; others stay `blocked` |

Report in the demo: operations per second, p50/p95 latency, duplicate claims = 0.

> If CON-3 shows more than one current fact, make the supersede path a single atomic statement or serialize per entity with a version property on `Entity`.

## 3. Memory behaviour

| ID | Scenario | Pass condition |
|---|---|---|
| MEM-1 | Log events in session 1, kill the process, start session 2 | `start_session` returns session 1's summary; `recall_episodes` finds its events |
| MEM-2 | `upsert_fact(payments-svc, owner, Core)` then later `upsert_fact(..., Billing)` | `query_facts` returns Billing; `query_facts(as_of=<between>)` returns Core; `SUPERSEDES` edge exists |
| MEM-3 | `forget_fact` | Fact no longer in default results; still returned by `fact_history` |
| MEM-4 | Consolidation run over a session of 20 events | At least one new fact created with `DERIVED_FROM` links to its source events |
| MEM-5 | Low-confidence fact untouched past the decay window | Marked `stale`, excluded unless `include_stale=true` |
| MEM-6 | Recall with a large result set | Output respects `limit` and the character cap |

## 4. Procedural learning

| ID | Scenario | Pass condition |
|---|---|---|
| PRO-1 | `find_procedure("redis latency")` before any outcomes | Returns seeded procedures ranked by smoothed score |
| PRO-2 | `record_outcome(success=false, violated_assumption=..., new_precondition=...)` | New version created with `PREVIOUS_VERSION`, old retired, precondition present |
| PRO-3 | Next incident calls `find_procedure` | Returns the new version with its precondition; failed version no longer ranks first |
| PRO-4 | Two successes on a procedure | `success_count` increments and score rises |

## 5. Coordination and handoffs

| ID | Scenario | Pass condition |
|---|---|---|
| COO-1 | Triage creates a handoff to Investigator | `Handoff` node with `status = 'pending'`, `CREATED` and `TO` edges |
| COO-2 | Investigator calls `start_session` | `open_handoffs` includes it |
| COO-3 | `accept_handoff` | Status `accepted`, returns context, open questions, linked hypotheses and evidence |
| COO-4 | Handoff to an agent that does not exist | `NOT_FOUND` |
| COO-5 | Agent with the wrong role calls a restricted tool | `FORBIDDEN` (if roles enabled) |

## 6. Agent end-to-end (`tests/test_e2e_scenario.py`)

Runs the scripted incident with the real agent loop and checks the final graph:

- At least 3 handoffs exist and all were accepted
- Every task is `done`
- At least one hypothesis is `supported` with evidence
- The chosen procedure's outcome is recorded
- `explain` on the final conclusion returns a path to source events

## 7. Query validation

Before wiring a query into a tool, run it in FalkorDB Browser against seed data and save the working text in `server/app/queries/`. Every query in [GRAPH_DATA_MODEL.md](GRAPH_DATA_MODEL.md) marked **verify** needs a passing test before release.

## 8. Pre-recording checklist

- [ ] Fresh FalkorDB, seed applied
- [ ] `isolation_test.py` passes 3 times in a row
- [ ] `load_test.py` passes 5 times in a row with the demo parameters
- [ ] Scripted incident completes twice without manual intervention
- [ ] Dashboard shows handoffs, claims and the supersede chain clearly
- [ ] Keys and tokens are not visible on screen
