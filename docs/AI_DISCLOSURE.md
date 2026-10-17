# AI Use Disclosure

Graph Hacks requires that AI coding assistant use is disclosed, and that participants understand and can explain their submission. Fill this in before submitting and keep it accurate.

## 1. Tools used

| Tool | Version / model | Used for |
|---|---|---|
| _e.g. Claude (chat)_ | _model name_ | Brainstorming the architecture, drafting planning docs, reviewing queries |
| _e.g. Claude Code / Cursor / Copilot_ | _version_ | Code generation, refactoring, test scaffolding |
| _add rows_ | | |

## 2. What AI assisted with

Check what applies and add detail.

- [ ] Brainstorming and architecture planning
- [ ] Drafting documentation (`README.md`, `docs/*`)
- [ ] Generating boilerplate (server skeleton, tests, dashboard scaffolding)
- [ ] Writing or reviewing Cypher queries
- [ ] Debugging
- [ ] Other: ___________

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
