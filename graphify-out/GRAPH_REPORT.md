# Graph Report - graph-relay-memory  (2026-10-18)

## Corpus Check
- Corpus is ~35,171 words - fits in a single context window. You may not need a graph.

## Summary
- 425 nodes · 1334 edges · 16 communities (13 shown, 3 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 46 edges (avg confidence: 0.92)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Incident Scenario & Tool Dispatch
- CAS Concurrency & Query Execution
- Relay Agent Fleet & Execution Loop
- Procedural Memory & Laplace Ranking
- FastAPI Engine & SSE Real-time Server
- Consolidation Worker & Fact Derivation
- Semantic Memory & Supersession History
- OpenVINO Model Server & LLM Adapter
- Tenancy Lifecycle & Key Provisioning
- Authentication & Cryptographic Tokens
- Auth Context & Tenant Binding
- Concurrency Benchmark & Seed Scripts
- Cross-Tenant Isolation & Seeding
- PageRank Centrality & Blast Radius
- Control Graph Schema & Key Lookup

## God Nodes (most connected - your core abstractions)
1. `AuthContext` - 60 edges
2. `execute_query()` - 51 edges
3. `execute_ro_query()` - 47 edges
4. `log_audit()` - 43 edges
5. `provision_tenant()` - 28 edges
6. `run_full_incident_scenario()` - 27 edges
7. `dispatch_tool_call()` - 27 edges
8. `provision_agent_key()` - 25 edges
9. `upsert_fact()` - 21 edges
10. `run_load_test()` - 19 edges

## Surprising Connections (you probably didn't know these)
- `RelayAgent` --uses--> `AuthContext`  [INFERRED]
  agents/base.py → server/app/auth.py
- `_get_ctx()` --calls--> `AuthContext`  [EXTRACTED]
  agents/runner.py → server/app/auth.py
- `trigger_isolation_test()` --indirect_call--> `run_isolation_tests()`  [INFERRED]
  server/app/main.py → scripts/isolation_test.py
- `trigger_load_test()` --indirect_call--> `run_load_test()`  [INFERRED]
  server/app/main.py → scripts/load_test.py
- `proc_fixture()` --uses--> `AuthContext`  [INFERRED]
  tests/test_phase4_procedural.py → server/app/auth.py

## Import Cycles
- None detected.

## Communities (16 total, 3 thin omitted)

### Community 0 - "Incident Scenario & Tool Dispatch"
Cohesion: 0.09
Nodes (36): run_full_incident_scenario(), dispatch_tool_call(), AuthContext, log_audit(), accept_handoff_handler(), add_hypothesis_handler(), attach_evidence_handler(), claim_task_handler() (+28 more)

### Community 1 - "CAS Concurrency & Query Execution"
Cohesion: 0.07
Nodes (30): run_load_test(), worker_claim(), worker_log(), execute_query(), execute_ro_query(), accept_handoff(), add_hypothesis(), attach_evidence() (+22 more)

### Community 2 - "Relay Agent Fleet & Execution Loop"
Cohesion: 0.06
Nodes (10): RelayAgent, call_gemini(), call_openvino(), generate(), run_incident_team(), _get_ctx(), Settings, test_agent_tool_loop_with_mocked_llm() (+2 more)

### Community 3 - "Procedural Memory & Laplace Ranking"
Cohesion: 0.10
Nodes (13): find_procedure(), _query_graph(), get_procedure(), init_procedure_schema(), seed_procedure(), _err(), find_procedure_handler(), get_procedure_handler() (+5 more)

### Community 4 - "FastAPI Engine & SSE Real-time Server"
Cohesion: 0.10
Nodes (11): broadcast_event(), _determine_memory_type(), get_graph_snapshot(), health(), lifespan(), _reaper_background_loop(), root(), stream_events() (+3 more)

### Community 5 - "Consolidation Worker & Fact Derivation"
Cohesion: 0.12
Nodes (8): consolidate_session_events(), decay_stale_facts(), run_consolidation(), get_client(), get_graph(), test_blast_radius_bfs(), test_consolidation_and_derived_from(), test_pagerank_centrality()

### Community 6 - "Semantic Memory & Supersession History"
Cohesion: 0.15
Nodes (9): fact_history(), fact_history_handler(), forget_fact_handler(), query_facts_handler(), upsert_fact_handler(), test_cross_tenant_memory_isolation(), test_forget_fact(), test_idempotent_event_writes() (+1 more)

### Community 7 - "OpenVINO Model Server & LLM Adapter"
Cohesion: 0.14
Nodes (7): build_qwen_chat_prompt(), chat_completions(), ChatCompletionRequest, health(), list_models(), Message, parse_tool_calls()

### Community 8 - "Tenancy Lifecycle & Key Provisioning"
Cohesion: 0.13
Nodes (9): create_api_key(), init_control_schema(), provision_agent_key(), provision_tenant(), setup_tenants(), memory_fixture(), proc_fixture(), agent_fixture() (+1 more)

### Community 9 - "Authentication & Cryptographic Tokens"
Cohesion: 0.18
Nodes (10): authenticate_bearer(), authenticate_key(), verify_admin_token(), get_tenant_graph_name(), test_admin_token_verification(), test_audit_logging(), test_bearer_header_parsing(), test_key_authentication_and_tenant_resolution() (+2 more)

### Community 12 - "Cross-Tenant Isolation & Seeding"
Cohesion: 0.23
Nodes (7): run_isolation_tests(), seed_all(), seed_tenant(), revoke_api_key(), seed_default_runbooks(), seeded_e2e(), client()

### Community 13 - "PageRank Centrality & Blast Radius"
Cohesion: 0.28
Nodes (3): blast_radius(), explain(), rank_critical_services()

### Community 14 - "Control Graph Schema & Key Lookup"
Cohesion: 0.25
Nodes (4): create_tenant(), get_tenant(), lookup_api_key(), test_tenant_creation_and_isolation()

## Knowledge Gaps
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `execute_ro_query()` connect `CAS Concurrency & Query Execution` to `Incident Scenario & Tool Dispatch`, `Relay Agent Fleet & Execution Loop`, `Procedural Memory & Laplace Ranking`, `FastAPI Engine & SSE Real-time Server`, `Consolidation Worker & Fact Derivation`, `Semantic Memory & Supersession History`, `Authentication & Cryptographic Tokens`, `Auth Context & Tenant Binding`, `Concurrency Benchmark & Seed Scripts`, `Cross-Tenant Isolation & Seeding`, `PageRank Centrality & Blast Radius`, `Control Graph Schema & Key Lookup`?**
  _High betweenness centrality (0.114) - this node is a cross-community bridge._
- **Are the 34 inferred relationships involving `AuthContext` (e.g. with `RelayAgent` and `dispatch_tool_call()`) actually correct?**
  _`AuthContext` has 34 INFERRED edges - model-reasoned connections that need verification._
- **Should `Incident Scenario & Tool Dispatch` be split into smaller, more focused modules?**
  _Cohesion score 0.09192982456140351 - nodes in this community are weakly interconnected._
- **Why does `execute_query()` connect `CAS Concurrency & Query Execution` to `Incident Scenario & Tool Dispatch`, `Procedural Memory & Laplace Ranking`, `FastAPI Engine & SSE Real-time Server`, `Consolidation Worker & Fact Derivation`, `Tenancy Lifecycle & Key Provisioning`, `Authentication & Cryptographic Tokens`, `Auth Context & Tenant Binding`, `Concurrency Benchmark & Seed Scripts`, `Cross-Tenant Isolation & Seeding`, `PageRank Centrality & Blast Radius`, `Control Graph Schema & Key Lookup`?**
  _High betweenness centrality (0.095) - this node is a cross-community bridge._
- **Should `CAS Concurrency & Query Execution` be split into smaller, more focused modules?**
  _Cohesion score 0.06768388106416276 - nodes in this community are weakly interconnected._
- **Why does `AuthContext` connect `Incident Scenario & Tool Dispatch` to `CAS Concurrency & Query Execution`, `Relay Agent Fleet & Execution Loop`, `Procedural Memory & Laplace Ranking`, `Consolidation Worker & Fact Derivation`, `Semantic Memory & Supersession History`, `Tenancy Lifecycle & Key Provisioning`, `Authentication & Cryptographic Tokens`, `Auth Context & Tenant Binding`?**
  _High betweenness centrality (0.090) - this node is a cross-community bridge._
- **Should `Relay Agent Fleet & Execution Loop` be split into smaller, more focused modules?**
  _Cohesion score 0.058823529411764705 - nodes in this community are weakly interconnected._