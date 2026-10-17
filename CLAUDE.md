# CLAUDE.md — instructions for AI coding assistants

This file tells coding assistants (Claude Code, Cursor, Copilot, etc.) how to work in this repo. Read it first, then the docs it links.

## Project in one paragraph

Relay is a shared graph memory and coordination layer for teams of AI agents, built for the Graph Hacks hackathon (Track 02). **FalkorDB is the primary and required database.** Agents talk to an MCP memory server, which runs parameterised Cypher against one FalkorDB graph per tenant. Read these before coding:

- `docs/ARCHITECTURE.md`
- `docs/GRAPH_DATA_MODEL.md`
- `docs/MCP_TOOLS.md`
- `docs/TEST_PLAN.md`

## Hard rules (do not break these)

1. **No tenant input from callers.** Tools never accept `tenant_id`, `agent_id`, or a graph name as arguments. They come from the API key lookup in `server/app/auth.py`.
2. **No raw Cypher exposed.** Do not add a tool that runs caller-supplied Cypher.
3. **Parameterised queries only.** Never build Cypher with f-strings or concatenation from user input. If a value cannot be a parameter (for example a variable-length bound), validate it as an integer in range and inline it.
4. **Queries live in `server/app/queries/`.** One named function per query, each with a docstring and a test.
5. **Races are atomic.** Claims, lease renewals and fact supersession must be a single Cypher statement or have a test that proves they are safe under concurrency.
6. **Writes are idempotent.** Every write tool accepts `idempotency_key` and uses `MERGE` on it.
7. **Read tools use read-only queries** (`ro_query` in the FalkorDB client).
8. **Never destroy history.** Corrections close `valid_to` and add `SUPERSEDES`. Do not overwrite facts.
9. **Synthetic data only.** Never add real names, emails, tokens or private documents to seeds or tests.
10. **Do not remove FalkorDB or replace it with another store.** The graph must remain load-bearing.

## Repo layout

```
server/app/
  main.py            FastAPI + MCP mount, SSE feed
  auth.py            key lookup -> (tenant, agent, role)
  tenancy.py         graph selection, tenant creation
  graph.py           FalkorDB connection pool and helpers
  queries/           named Cypher query functions
  tools/             episodic.py semantic.py procedural.py coordination.py insight.py
  consolidation.py   events -> facts, decay
  reaper.py          re-open expired task leases
agents/
  runner.py          start an agent team for a tenant
  base.py            LLM tool-use loop with MCP client
  triage.py investigator.py remediator.py comms.py
dashboard/           React app (graph view, handoffs, load and isolation panels)
scripts/             seed.py load_test.py isolation_test.py replay.py
tests/               pytest suites (see docs/TEST_PLAN.md)
docs/                design docs
```

## Stack and commands

- Python 3.11+, FastAPI, official `falkordb` Python client, MCP Python SDK, Anthropic SDK
- Dashboard: React + Vite + a force-graph library

```bash
docker run -p 6379:6379 -p 3000:3000 -it --rm falkordb/falkordb:latest
pip install -r requirements.txt
uvicorn server.app.main:app --reload --port 8080
pytest tests/ -q
python scripts/seed.py
python scripts/isolation_test.py
python scripts/load_test.py --agents 20 --tasks 10
```

## Conventions

- Timestamps are integer epoch milliseconds.
- IDs are prefixed strings (`task_`, `fact_`, `evt_`, `hnd_`, `proc_`) generated with UUIDs.
- Tool handlers return `{ok: true, ...}` or `{ok: false, error: {code, message}}` with codes from `docs/MCP_TOOLS.md`.
- Keep functions small and typed. Add a test with every new query.
- Model id comes from the `MODEL` environment variable. Do not hard-code it.
- Log tool name, tenant, agent, and outcome; never log API keys.

## How to add a new tool

1. Add or update the spec in `docs/MCP_TOOLS.md`.
2. Add the Cypher to `server/app/queries/` and any new labels or relationships to `docs/GRAPH_DATA_MODEL.md`.
3. Implement the handler in `server/app/tools/` using only the tenant graph from the auth context.
4. Add tests (happy path, `NOT_FOUND`, `FORBIDDEN`, and a concurrency case if it writes).
5. Update the agent prompt hints if the new tool changes which tool an agent should choose.

## Things to verify in FalkorDB docs before using

`EXISTS` subqueries, `FOREACH`, variable-length bounds as parameters, full-text index procedures, vector index syntax, and exact algorithm procedure names (`algo.pageRank`, BFS, shortest path). Test in FalkorDB Browser first and note the working form in the query file.

## Hackathon requirements to keep in mind

- Public repo, README with setup and the graph data model, the Cypher the product depends on, demo video, and live deployment or full local instructions.
- AI assistant use must be disclosed in `docs/AI_DISCLOSURE.md`. When you generate substantial code, tell the user so it can be recorded.
- Teammates must be able to explain what was built. Prefer simple, readable code with short comments on the graph reasoning over clever abstractions.

## Do not

- Do not add dependencies without need; the build window is short.
- Do not write large generated files that nobody has read.
- Do not weaken a test to make it pass. If a proof fails (duplicate claim, cross-tenant read), fix the design.
