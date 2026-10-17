# Relay: Build Phases

This file breaks the whole project into sequential phases. Each phase has a goal, the work to do, the files it touches, and an exit gate that must pass before moving on. The timings match [BUILD_PLAN.md](BUILD_PLAN.md), and the scope follows [MCP_TOOLS.md](MCP_TOOLS.md) and [GRAPH_DATA_MODEL.md](GRAPH_DATA_MODEL.md).

**Model provider:** the LLM is behind an adapter (`MODEL_PROVIDER=anthropic | openvino`), so every phase that calls a model works with either a cloud API or a local OpenVINO server.

---

## Phase 0: Foundations (H+0 to H+1)

**Goal:** a working environment and an agreed data model.

**Work**
- Create the repo `graph-relay-memory` with the layout from the README.
- Start FalkorDB in Docker and confirm a query runs.
- Create `requirements.txt`, `.env.example`, and a `.gitignore` that excludes `.env`.
- Review the graph model with the whole team and freeze the node and relationship names.

**Touches:** `README.md`, `CLAUDE.md`, `.env.example`, `requirements.txt`

**Exit gate**
- [ ] `docker run` FalkorDB works and `RETURN 1` succeeds from Python
- [ ] Every teammate can run the empty project
- [ ] Data model agreed and matches `GRAPH_DATA_MODEL.md`

---

## Phase 1: Graph core and tenancy (H+1 to H+4)

**Goal:** tenants are isolated at the database level, and writes go through one connection layer.

**Work**
- `graph.py`: FalkorDB connection pool, read-only and read-write helpers, parameterised queries only.
- `tenancy.py`: create tenant graphs, plus the `control` graph for tenants and hashed API keys.
- `auth.py`: map a bearer key to `(tenant, agent, role)`.
- Create the indexes from `GRAPH_DATA_MODEL.md`.
- Write the audit entry for every call.

**Touches:** `server/app/graph.py`, `tenancy.py`, `auth.py`, `queries/`

**Exit gate**
- [ ] Two tenants created, each with its own graph
- [ ] A key from tenant A resolves only to tenant A's graph
- [ ] Audit entries are written for successful and failed auth

---

## Phase 2: Memory tools (H+4 to H+8)

**Goal:** the episodic and semantic memory tools work, including supersession.

**Work**
- Episodic tools: `start_session`, `log_event` (idempotent), `recall_episodes`, `end_session`.
- Semantic tools: `upsert_fact` (close-and-supersede in two statements), `query_facts` with `as_of`, `fact_history`, `forget_fact`.
- Return the error codes from `MCP_TOOLS.md`.

**Touches:** `server/app/tools/episodic.py`, `semantic.py`, `queries/`

**Exit gate**
- [ ] Session 1 events are recalled in session 2 after a restart (MEM-1)
- [ ] `as_of` returns the old value and the current value returns the new one (MEM-2)
- [ ] Repeating a `log_event` with the same key creates one node (CON-2)

---

## Phase 3: Coordination (H+8 to H+10)

**Goal:** agents can safely claim work and hand it off.

**Work**
- Tools: `open_incident`, `create_task`, `list_open_work`, `claim_task`, `renew_lease`, `release_task`, `complete_task` (with cascade unblock).
- Tools: `add_hypothesis`, `attach_evidence`, `create_handoff`, `accept_handoff`.
- `reaper.py`: re-opens tasks whose lease has expired.

**Touches:** `server/app/tools/coordination.py`, `reaper.py`, `queries/`

**Exit gate (Checkpoint 1)**
- [ ] `load_test.py` with 20 agents and 10 tasks: exactly 10 winners, 0 duplicates (CON-1)
- [ ] Killed agent's task is reclaimed after lease expiry (CON-5)
- [ ] Completing a blocker unblocks its dependants (CON-6)
- [ ] `isolation_test.py` passes: no cross-tenant reads or writes (ISO-1 to ISO-7)

Do not start Phase 4 until this gate is green. Concurrency and isolation bugs are much harder to fix once agents are built on top.

---

## Phase 4: Procedural memory and learning (H+14 to H+18)

**Goal:** procedures rank by success, and a failure creates a new version with a precondition.

**Work**
- `find_procedure` (tenant graph first, then `shared_runbooks`), `record_outcome` with version fork on failure, `get_procedure`.
- Load the seed procedures and the shared runbook graph.
- Smoothed success-rate ranking.

**Touches:** `server/app/tools/procedural.py`, `queries/`, `scripts/seed.py`

**Exit gate**
- [ ] A failure creates `v2` with `PREVIOUS_VERSION` and the new precondition (PRO-2)
- [ ] The next `find_procedure` no longer returns the failed version first (PRO-3)

---

## Phase 5: Model adapter and agents (H+6 to H+14, in parallel with Phase 3)

**Goal:** four agents run a scripted incident through MCP tools.

**Work**
- `agents/base.py`: a tool-use loop over the MCP client, with the model behind an adapter (`anthropic` or `openvino`).
- Validate tool arguments on the server, since small local models produce malformed calls more often.
- Role prompts for Triage, Investigator, Remediator and Comms, each with the tool-selection hints from `MCP_TOOLS.md`.
- `runner.py` starts a team for one tenant and keeps the temperature low.
- `scripts/seed.py` loads the Acme and Globex scenario from `DEMO_SCRIPT.md`.

**Touches:** `agents/`, `scripts/seed.py`, `.env.example` (`MODEL_PROVIDER`, `MODEL`, `OPENVINO_BASE_URL`)

**Exit gate**
- [ ] Triage hands off to Investigator, which accepts it and shows up as a `Handoff` node (COO-1 to COO-3)
- [ ] The agent loop completes the scripted incident with the same model provider switched by env var

---

## Phase 6: Consolidation and insight (H+14 to H+18, parallel)

**Goal:** memory updates over time and the graph shows its algorithmic value.

**Work**
- `consolidation.py`: turn recent events into candidate facts with `DERIVED_FROM` links, decay stale facts, and expose `POST /admin/consolidate`.
- `explain` tool: provenance chain from a fact, hypothesis or task.
- Optional: `blast_radius` (BFS) and `rank_critical_services` (PageRank). Verify the procedure names first.

**Touches:** `server/app/consolidation.py`, `tools/insight.py`

**Exit gate**
- [ ] A 20-event session produces at least one derived fact with provenance (MEM-4)
- [ ] Low-confidence stale fact drops out of default results (MEM-5)
- [ ] `explain` returns a path from the conclusion to its source events

Skip the optional algorithms if behind schedule. Move them to the cut list.

---

## Phase 7: Failure and learning end to end (H+18 to H+20)

**Goal:** the full incident, with a visible failure, correction and learning moment.

**Work**
- Run the scripted incident: restart-redis fails, the procedure forks, the next run chooses rollback-deploy and succeeds.
- Owner correction (`Team Core` to `Team Billing`) to demonstrate supersede.
- Run the end-to-end test (`tests/test_e2e_scenario.py`).

**Touches:** `tests/test_e2e_scenario.py`, `agents/` tuning

**Exit gate**
- [ ] Scenario completes twice in a row without manual intervention (TEST_PLAN section 8)
- [ ] Every handoff accepted, every task done, a supported hypothesis with evidence

---

## Phase 8: Dashboard (H+10 to H+20, parallel)

**Goal:** judges can see the graph, handoffs and proofs live.

**Work**
- `GET /admin/stream` SSE feed and `GET /admin/graph/{tenant}` snapshot in the server.
- React app with a force-directed graph (colors by memory type), a handoff feed, a task board with lease countdown, a fact timeline with the supersede chain, and proof panels for load and isolation results.
- Fallback: FalkorDB Browser with saved queries from `DEMO_SCRIPT.md`.

**Touches:** `dashboard/`, `server/app/main.py`

**Exit gate**
- [ ] The graph updates live while agents run
- [ ] Load and isolation results display without manual steps

---

## Phase 9: Hardening and deployment (H+22 to H+25)

**Goal:** the project runs from a clean machine, and the demo is stable.

**Work**
- Error handling: `UNAVAILABLE` retry with backoff, clear messages for `FORBIDDEN` and `CONFLICT`.
- Remove hard-coded values; everything configurable in `.env`.
- Run `isolation_test.py` three times and `load_test.py` five times.
- Deploy: either a public URL (VM or container host with FalkorDB) or full local setup steps in the README. Prepare a `docker-compose.yml` if time allows.
- If using OpenVINO, benchmark latency and pick the model size that keeps each agent turn acceptable.

**Touches:** `docker-compose.yml`, `README.md`, `.env.example`

**Exit gate**
- [ ] Fresh clone runs following the README alone
- [ ] Both proof scripts pass repeatedly

---

## Phase 10: Demo, documentation and submission (H+25 to H+28)

**Goal:** a complete, honest submission before the deadline.

**Work**
- Record the 3-minute video following `DEMO_SCRIPT.md`, in segments.
- Finalise `README.md`: setup, graph data model, Cypher queries the product depends on, track name.
- Fill in `AI_DISCLOSURE.md` truthfully, and confirm each teammate can explain their module.
- Check every item in the rules checklist (`rule_&_regulation.md`).
- Optional: blog post for the side prize.
- Make the repository public and submit on the form, naming Track 02, at least an hour before the deadline (Oct 18, 18:29 UTC).

**Exit gate**
- [ ] All checklist items ticked
- [ ] Submission confirmed before the cut-off

---

## Cut order if time runs short

1. Blog post
2. Optional algorithms (`blast_radius`, `rank_critical_services`)
3. Visibility levels and role permissions
4. Full-text and vector search
5. Dashboard polish (fall back to FalkorDB Browser)
6. Comms agent
7. Consolidation worker (seed facts directly)

**Never cut:** atomic claim, tenant isolation, procedural learning, the two proof scripts, the demo video, the README data model and queries.
