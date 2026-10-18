"""
Tests for Phase 6: Consolidation Worker & Graph Insight Tools.
Verifies:
- MEM-4: Consolidation produces derived facts with DERIVED_FROM edges from session events
- MEM-5: Stale, low-confidence facts decay out of active queries
- INS-1: BFS blast_radius calculates impacted upstream dependants
- INS-2: FalkorDB algo.pageRank centrality ordering
- INS-3: explain returns provenance trace for facts, hypotheses, and tasks
"""
import time
import pytest

from server.app.auth import AuthContext
from server.app.tenancy import provision_tenant, provision_agent_key
from server.app.graph import execute_query
from server.app.queries.episodic import start_session, log_event
from server.app.queries.semantic import upsert_fact, query_facts
from server.app.consolidation import consolidate_session_events, decay_stale_facts, run_consolidation
from server.app.tools.insight import (
    blast_radius_handler,
    rank_critical_services_handler,
    explain_handler
)
from server.app.tools.coordination import add_hypothesis_handler, attach_evidence_handler, open_incident_handler


@pytest.fixture(scope="module")
def p6_fixture():
    ts = int(time.time() * 1000)
    tenant_id = f"p6_tenant_{ts}"
    provision_tenant(tenant_id, "Phase 6 Corp")
    
    key, key_hash = provision_agent_key(tenant_id, "investigator_p6", "investigator")
    ctx = AuthContext(
        tenant_id=tenant_id,
        agent_id="investigator_p6",
        role="investigator",
        graph_name=f"tenant_{tenant_id}",
        key_hash=key_hash
    )

    # Seed dependencies for blast radius and PageRank
    dep_cypher = """
    MERGE (c:Entity {name: 'checkout-api'}) ON CREATE SET c.id = 'c1', c.kind = 'service'
    MERGE (p:Entity {name: 'payments-svc'}) ON CREATE SET p.id = 'p1', p.kind = 'service'
    MERGE (r:Entity {name: 'redis-cache'}) ON CREATE SET r.id = 'r1', r.kind = 'service'
    MERGE (db:Entity {name: 'postgres-primary'}) ON CREATE SET db.id = 'db1', db.kind = 'host'
    
    MERGE (c)-[:DEPENDS_ON]->(p)
    MERGE (c)-[:DEPENDS_ON]->(r)
    MERGE (p)-[:DEPENDS_ON]->(db)
    """
    execute_query(ctx.graph_name, dep_cypher)

    return {"ctx": ctx}


def test_blast_radius_bfs(p6_fixture):
    """INS-1: blast_radius reverse-traverses DEPENDS_ON to find impacted dependants."""
    ctx = p6_fixture["ctx"]
    # If redis-cache fails, checkout-api depends on it
    res = blast_radius_handler(ctx, service="redis-cache", depth=3)
    assert res["ok"] is True
    impacted = [s["name"] for s in res["impacted_services"]]
    assert "checkout-api" in impacted

    # If postgres-primary fails, both payments-svc (direct) and checkout-api (transitive) are impacted
    res_db = blast_radius_handler(ctx, service="postgres-primary", depth=3)
    assert res_db["ok"] is True
    impacted_db = [s["name"] for s in res_db["impacted_services"]]
    assert "payments-svc" in impacted_db
    assert "checkout-api" in impacted_db


def test_pagerank_centrality(p6_fixture):
    """INS-2: rank_critical_services returns PageRank centrality ranking."""
    ctx = p6_fixture["ctx"]
    res = rank_critical_services_handler(ctx, limit=5)
    assert res["ok"] is True
    critical = res["critical_services"]
    assert len(critical) > 0
    # postgres-primary has the highest in-degree / dependency centrality
    names = [c["service"] for c in critical]
    assert "postgres-primary" in names
    assert all("score" in c for c in critical)


def test_consolidation_and_derived_from(p6_fixture):
    """MEM-4: Events are synthesized into facts with DERIVED_FROM edges."""
    ctx = p6_fixture["ctx"]
    sess = start_session(ctx.graph_name, ctx.agent_id, ctx.role)
    sess_id = sess["session_id"]

    # Log 3 observation events
    e1 = log_event(ctx.graph_name, sess_id, "observation", "redis-cache memory exceeded 90% quota", idempotency_key="e1_p6")
    e2 = log_event(ctx.graph_name, sess_id, "observation", "payments-svc request latency climbed to 450ms", idempotency_key="e2_p6")

    # Run consolidation
    res = run_consolidation(ctx.graph_name, session_id=sess_id)
    assert res["ok"] is True
    assert res["derived_facts_count"] >= 2

    # Check DERIVED_FROM edge in graph
    first_fact_id = res["derived_facts"][0]["fact_id"]
    explain_res = explain_handler(ctx, node_id=first_fact_id)
    assert explain_res["ok"] is True
    assert explain_res["provenance"]["node_type"] == "Fact"
    assert explain_res["provenance"]["source_event"] is not None


def test_decay_stale_facts(p6_fixture):
    """MEM-5: Low-confidence facts past decay window become stale and drop from active query."""
    ctx = p6_fixture["ctx"]

    # Insert fact with low confidence and manually adjust valid_from to the past
    fact = upsert_fact(ctx.graph_name, "test-svc", "temp_metric", "42", ctx.agent_id, confidence=0.3)
    f_id = fact["fact_id"]

    # Set valid_from to 10 days ago (past 7-day default decay window)
    ten_days_ago = int((time.time() - 10 * 86400) * 1000)
    execute_query(ctx.graph_name, "MATCH (f:Fact {id: $id}) SET f.valid_from = $ts", {"id": f_id, "ts": ten_days_ago})

    # Initially returned in query_facts
    active_before = query_facts(ctx.graph_name, entity="test-svc", predicate="temp_metric")
    assert len(active_before) == 1

    # Run decay worker
    decayed_count = decay_stale_facts(ctx.graph_name, max_age_ms=7 * 86400 * 1000, confidence_threshold=0.5)
    assert decayed_count >= 1

    # Default query_facts excludes stale
    active_after = query_facts(ctx.graph_name, entity="test-svc", predicate="temp_metric")
    assert len(active_after) == 0

    # Including stale still returns it
    all_facts = query_facts(ctx.graph_name, entity="test-svc", predicate="temp_metric", include_stale=True)
    assert len(all_facts) == 1
    assert all_facts[0]["status"] == "stale"


def test_explain_hypothesis_and_task(p6_fixture):
    """INS-3: explain traces hypothesis evidence and task blockage."""
    ctx = p6_fixture["ctx"]
    inc = open_incident_handler(ctx, title="P6 Incident", severity="sev2")
    inc_id = inc["incident_id"]

    hyp = add_hypothesis_handler(ctx, incident_id=inc_id, statement="Cache bottleneck", confidence=0.85)
    hyp_id = hyp["hypothesis_id"]

    sess = start_session(ctx.graph_name, ctx.agent_id, ctx.role)
    ev = log_event(ctx.graph_name, sess["session_id"], "observation", "Cache hit ratio dropped to 12%", idempotency_key="ev_p6_hyp")
    attach_evidence_handler(ctx, hypothesis_id=hyp_id, event_id=ev["event_id"], note="Direct evidence")

    # Explain hypothesis
    exp_hyp = explain_handler(ctx, node_id=hyp_id)
    assert exp_hyp["ok"] is True
    prov = exp_hyp["provenance"]
    assert prov["node_type"] == "Hypothesis"
    assert len(prov["supporting_evidence"]) >= 1
    assert prov["supporting_evidence"][0]["event_id"] == ev["event_id"]
