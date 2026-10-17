# Build Plan

**Deadline:** Oct 18, 11:59 PM IST (18:29 UTC). Plan assumes roughly 28 usable hours from now. Hours below are relative ("H+0" is when you start). Compress proportionally if you have less.

## 1. Roles (adapt to team size)

| Role | Owns | If solo |
|---|---|---|
| A: Graph and server | FalkorDB schema, queries, MCP server, auth, tenancy | Do first, keep it small |
| B: Agents | Four agent loops, prompts, scenario script, consolidation worker | Start with 2 agents, add the rest |
| C: Dashboard and demo | Live graph view, handoff feed, load and isolation panels, video | Use FalkorDB Browser as a fallback |
| D: Proof and docs | Tests, load test, README, blog post, submission | Do in the last 4 hours |

## 2. Scope by priority

### Must have (submission fails or looks weak without these)
- FalkorDB running, one graph per tenant, `control` graph for keys
- MCP server with auth and the ★ tools in [MCP_TOOLS.md](MCP_TOOLS.md)
- Atomic `claim_task` with lease and reaper
- Episodic + semantic (with supersede) + procedural (with failure fork)
- Two or more agents handing off through `Handoff` nodes
- Isolation test and concurrency test that actually run
- README with data model and Cypher, demo video, AI disclosure

### Should have
- All four agents (Triage, Investigator, Remediator, Comms)
- Live dashboard with graph and handoff feed
- Consolidation worker (events to facts)
- `as_of` time-travel query in the demo
- `explain` provenance tool

### Could have
- PageRank and blast radius tools
- Role-based permissions
- Visibility levels (`private`, `team`)
- Vector or full-text search
- Blog post (side prize)

### Won't do
- Real auth, real user data, raw-Cypher tool, multi-region anything

## 3. Timeline

| Hours | Goal | Done when |
|---|---|---|
| H+0 to H+1 | Repo, Docker FalkorDB, environment, agree on [GRAPH_DATA_MODEL.md](GRAPH_DATA_MODEL.md) | `docker run` works, Python can run `RETURN 1` |
| H+1 to H+4 | Server skeleton: key lookup, tenant graph selection, tenant creation, `start_session`, `log_event`, `recall_episodes` | Two tenants created, events land in the right graph |
| H+4 to H+8 | Semantic and procedural tools; coordination tools (`create_task`, `claim_task`, `renew_lease`, `complete_task`, handoffs) | Unit tests for each query pass |
| H+8 to H+10 | **Checkpoint 1:** run `scripts/isolation_test.py` and `scripts/load_test.py` (race test). Fix anything red | Exactly one winner per task, cross-tenant read blocked |
| H+6 to H+14 | Agents (in parallel with the above): runner, prompts, tool-use loop, scenario seed | Triage -> Investigator handoff works end to end |
| H+14 to H+18 | Remediator, Comms, procedure failure and fork, consolidation worker | Scripted incident shows the learning moment |
| H+10 to H+20 | Dashboard (in parallel): graph view, handoff feed, SSE | Live graph updates while agents run |
| H+20 to H+22 | **Checkpoint 2:** full dry run of the demo script, record rough take | Demo runs without manual fixes twice in a row |
| H+22 to H+25 | Polish: error handling, seed data traps, dashboard readability, time-travel query | Demo is stable |
| H+25 to H+27 | README, graph model write-up, queries listed, AI disclosure, final video | All checklist items in the rules file ticked |
| H+27 to H+28 | Buffer, deploy or finalize local instructions, submit | Submitted at least 1 hour before deadline |

## 4. Cut list (drop in this order if time runs short)

1. Blog post
2. PageRank and blast radius
3. Visibility levels and role permissions
4. Full-text and vector search
5. Dashboard polish (fall back to FalkorDB Browser plus a simple event log page)
6. Comms agent (three agents still show handoffs)
7. Consolidation worker (seed some facts directly and demo `upsert_fact` supersede)

**Never cut:** atomic claim, tenant isolation, procedure learning, the two proof scripts, the demo video, the README data model.

## 5. Daily standup questions

- Which proof (persistence, concurrency, isolation, learning, time travel) is still not demonstrable?
- What is blocking someone for more than 30 minutes?
- What can we cut right now to protect the demo?

## 6. Risks and mitigations

| Risk | Mitigation |
|---|---|
| FalkorDB syntax differs from examples | Test every query in FalkorDB Browser first; keep working versions in `server/app/queries/` |
| LLM agents behave unpredictably in the demo | Seed deterministic scenario, low temperature, scripted fallback path, record the best take |
| Concurrency test is flaky | Use a fixed task count, assert on totals not ordering, run it 5 times before recording |
| Running out of time on dashboard | Start with a plain event stream, add the graph view last |
| API rate limits during the demo | Cache or script some steps, use a smaller model for background work |
| Team unfamiliar with Cypher | Ask in the FalkorDB Discord; keep each query short and parameterised |

## 7. Definition of done

- [ ] `docker compose up` (or the README steps) brings the system up from scratch
- [ ] Both proof scripts pass and their output is shown in the video
- [ ] Demo video under the length you can comfortably keep tight (aim for 3 minutes)
- [ ] README has data model, setup, and the Cypher the product depends on
- [ ] AI disclosure filled in; every teammate can explain the code
- [ ] Repository is public and the track is named on the submission
