# Relay — shared graph memory for agent teams

> Working title. Built for **Graph Hacks: Context for AI Agents** (WeMakeDevs x FalkorDB), **Track 02: Agent Memory and Coordination**.

Relay gives a team of AI agents one place to remember, hand work to each other, and learn from failures. All of it lives in **FalkorDB**: memory, claims, handoffs and procedures are nodes and edges that every agent reads and writes on each step.

## The problem

Agents forget between sessions, step on each other when they share work, and can't say why they believe something. A flat vector store fixes the first problem at best.

## What Relay does

| Capability | How it works in the graph |
|---|---|
| Episodic memory | `Session -> Event -> Event` timelines, append-only |
| Semantic memory | `Entity -> Fact` with `valid_from` / `valid_to`, corrections create `SUPERSEDES` edges, so we can ask "what did we believe at time T?" |
| Procedural memory | `Procedure` nodes with versions, success/fail counts, preconditions, and a `violated_assumption` recorded after each failure |
| Shared state | `Incident -> Task / Hypothesis / Evidence` visible to every agent in the tenant |
| Safe coordination | Compare-and-set task claims with expiring leases, so two agents never own one task |
| Handoffs | Explicit `Handoff` nodes carrying context summary, open questions and evidence |
| Tenant isolation | One FalkorDB graph per tenant. The tenant comes from the API key, never from tool arguments |
| Consolidation | Background worker merges episodes into facts, supersedes stale ones, decays low-confidence memory |

## Demo scenario

A synthetic checkout-latency incident handled by four agents: **Triage -> Investigator -> Remediator -> Comms**. Two tenants run the same scenario to prove isolation. See [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

## Proofs the demo shows

1. **Persistence:** kill all agents, restart, the new session recalls the old one.
2. **Concurrency:** 20 agents race for 10 tasks, exactly 10 winners, 0 duplicates.
3. **Isolation:** tenant A's key cannot read tenant B's nodes.
4. **Learning:** a failed runbook gains a precondition, and the next incident chooses differently.
5. **Time travel:** a corrected fact can be queried as of an earlier time.

## Quickstart

```bash
# 1. FalkorDB
docker run -p 6379:6379 -p 3000:3000 -it --rm falkordb/falkordb:latest

# 2. Python env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Config
cp .env.example .env     # set ANTHROPIC_API_KEY, MODEL, ADMIN_TOKEN

# 4. Seed two tenants with synthetic data
python scripts/seed.py

# 5. Start the MCP memory server
uvicorn server.app.main:app --port 8080

# 6. Run the agent team for tenant A
python agents/runner.py --tenant acme

# 7. Dashboard
cd dashboard && npm install && npm run dev
```

Environment variables:

| Variable | Purpose |
|---|---|
| `FALKORDB_HOST` / `FALKORDB_PORT` | FalkorDB connection (default `localhost:6379`) |
| `ANTHROPIC_API_KEY` | Used by the agents and the consolidation worker |
| `MODEL` | Claude model id for agents |
| `ADMIN_TOKEN` | Protects tenant creation and the dashboard feed |

## Documentation

| File | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, request flow, tenancy, concurrency, memory lifecycle |
| [docs/GRAPH_DATA_MODEL.md](docs/GRAPH_DATA_MODEL.md) | Node labels, relationships, indexes, key Cypher |
| [docs/MCP_TOOLS.md](docs/MCP_TOOLS.md) | Every MCP tool: inputs, outputs, errors |
| [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md) | Time-boxed plan, roles, scope cuts |
| [docs/TEST_PLAN.md](docs/TEST_PLAN.md) | Concurrency, isolation and learning tests |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | 3-minute video script and seed data |
| [docs/AI_DISCLOSURE.md](docs/AI_DISCLOSURE.md) | AI assistant use, as the hackathon requires |
| [CLAUDE.md](CLAUDE.md) | Instructions for AI coding assistants working in this repo |

## Repository layout

```
relay/
  server/app/        MCP memory server (auth, tenancy, tools, consolidation)
  agents/            Triage, Investigator, Remediator, Comms, runner
  dashboard/         Live graph view, handoff feed, load and isolation panels
  scripts/           seed.py, load_test.py, isolation_test.py
  tests/             pytest suites
  docs/              Design and planning docs
```

## Hackathon compliance

- FalkorDB is the primary database and holds all memory and coordination state. Without it the product does not run.
- Data is fully synthetic. No private, personal or restricted data is loaded.
- Cypher queries and graph algorithms the product depends on are listed in [docs/GRAPH_DATA_MODEL.md](docs/GRAPH_DATA_MODEL.md) and implemented in `server/app/queries/`.
- AI coding assistant use is disclosed in [docs/AI_DISCLOSURE.md](docs/AI_DISCLOSURE.md).
- Track entered: **Track 02: Agent Memory and Coordination**.

## License

TBD (MIT recommended).
