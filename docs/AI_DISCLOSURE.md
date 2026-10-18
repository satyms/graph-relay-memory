# AI Use Disclosure

Graph Hacks requires that AI coding assistant use is disclosed, and that participants understand and can explain their submission. Fill this in before submitting and keep it accurate.

## 1. Tools used

| Tool | Version / model | Used for |
|---|---|---|
| Claude (chat) / Antigravity | Claude 3.7 / Antigravity Agent | Brainstorming architecture, drafting planning docs, demo features design |
| Antigravity AI Coding Assistant | Google DeepMind Agentic Assistant | Implementation of 5 demo features (Chaos button, Time-Travel, Click-to-Explain, Baseline comparison, Approval gate), Cypher queries, test suites, and dashboard UI wiring |

## 2. What AI assisted with

- [x] Brainstorming and architecture planning
- [x] Drafting documentation (`README.md`, `docs/*`)
- [x] Generating boilerplate (server skeleton, tests, dashboard scaffolding)
- [x] Writing or reviewing Cypher queries
- [x] Debugging and error recovery
- [x] Implementing demo features: Chaos Button, Time-Travel, Click-to-Explain, Baseline Memory Comparison, and Approval Gate

> [!NOTE]
> **AI Assistance Disclosure**: The five demo features (Feature 1: Chaos Button, Feature 2: Time-Travel Slider, Feature 3: Click-to-Explain, Feature 4: Baseline Comparison, and Feature 5: Approval Gate) were built with AI assistance using the Antigravity AI coding assistant.
>
> **Code Flagged for Team Review Before Final Release**:
> 1. `server/app/queries/approval.py` & `server/app/tools/coordination.py`: Human-in-the-loop approval state transitions and enforcement on risky operations (`rollback_deploy`, `restart_service`, `scale_down`).
> 2. `server/app/queries/insight.py`: Deterministic provenance traversal and plain-text "because" rationale synthesis without LLM calls.
> 3. `server/app/queries/timeline.py` & `server/app/queries/snapshot.py`: Historical snapshot filtering using `as_of` epochs on fact validity windows.
> 4. `server/app/main.py` (`POST /admin/chaos/kill-agent`): Asynchronous loop cancellation and background reaper lease expiry broadcasting.
> 5. `agents/baseline_memory.py` & `scripts/compare_baseline.py`: Fair baseline flat-memory store implementation ensuring comparisons are accurate and unbiased.

## 3. What was done by the team

Describe the contributions that were not generated, for example:

- Chose the problem, scope and demo scenario
- Designed the graph data model and made the tenancy and concurrency decisions
- Wrote, ran and verified every Cypher query against FalkorDB
- Wrote and ran the isolation and load tests and interpreted the results
- Reviewed all generated code before committing it

## 4. How we verified AI output

- Every Cypher query was run in FalkorDB Browser against seed data before use
- Generated code was read and understood by the teammate who owns that module
- Tests in `tests/` and the scripts in `scripts/` were run, and results are shown in the demo
- Anything unverified is marked **verify** in the docs and either tested or removed

## 5. Ownership of understanding

| Area | Teammate who can explain it |
|---|---|
| Graph data model and queries | _name_ |
| MCP server, auth and tenancy | _name_ |
| Agents and prompts | _name_ |
| Concurrency and tests | _name_ |
| Dashboard | _name_ |

## 6. Data

All data is synthetic and created for this project. No private, personal, login-protected or paywalled information is in the graph.

## 7. Third-party code and services

| Item | Purpose | License |
|---|---|---|
| FalkorDB | Primary graph database | _check_ |
| `falkordb` Python client | DB access | _check_ |
| MCP Python SDK | Tool server and client | _check_ |
| Anthropic SDK | Agent LLM calls | _check_ |
| _front-end libraries_ | Dashboard | _check_ |

Declared by: _names_ &nbsp;&nbsp; Date: _YYYY-MM-DD_
