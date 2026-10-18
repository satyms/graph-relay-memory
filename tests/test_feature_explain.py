"""
Feature 3 Tests: Click-to-Explain.
Tests:
- Explain a derived fact: provenance nodes include fact and source event, edge is DERIVED_FROM.
- Explain a superseded fact: provenance includes older fact, edge is SUPERSEDES.
- Explain a hypothesis: provenance includes supporting evidence events and SUPPORTED_BY edges.
- Error cases:
  * Node ID from another tenant returns NOT_FOUND (never crosses tenants).
  * Non-existent node ID returns NOT_FOUND.
  * Request without admin token returns FORBIDDEN.
- Deterministic plain-text 'because' summary is present and non-empty.
"""
import time
import pytest
from fastapi.testclient import TestClient

from server.app.main import app
from server.app.config import settings
from server.app.tenancy import provision_tenant, provision_agent_key
from server.app.queries.semantic import upsert_fact
from server.app.queries.episodic import start_session, log_event
from server.app.queries.coordination import add_hypothesis, attach_evidence, open_incident


@pytest.fixture(scope="module")
def explain_fixture():
    ts = int(time.time() * 1000)
    tenant_a = f"exp_a_{ts}"
    tenant_b = f"exp_b_{ts}"

    provision_tenant(tenant_a, "Explain Tenant A")
    provision_tenant(tenant_b, "Explain Tenant B")

    graph_a = f"tenant_{tenant_a}"
    graph_b = f"tenant_{tenant_b}"

    return {
        "tenant_a": tenant_a,
        "graph_a": graph_a,
        "tenant_b": tenant_b,
        "graph_b": graph_b,
    }


def test_explain_derived_fact(explain_fixture):
    client = TestClient(app)
    tenant_a = explain_fixture["tenant_a"]
    graph_a = explain_fixture["graph_a"]
    headers = {"Authorization": f"Bearer {settings.admin_token}"}

    # 1. Log an event
    sess = start_session(graph_a, "agent_triage", "triage")
    ev = log_event(
        graph_a,
        sess["session_id"],
        "observation",
        "Observed high memory pressure on redis-cache",
        idempotency_key="ev_mem_press"
    )
    event_id = ev["event_id"]

    # 2. Upsert fact derived from event
    fact = upsert_fact(
        graph_name=graph_a,
        entity_name="redis-cache",
        predicate="memory_status",
        value="critical_92pct",
        agent_id="agent_triage",
        source_event_id=event_id
    )
    fact_id = fact["fact_id"]

    # 3. Call GET /admin/explain/{tenant}/{node_id}
    res = client.get(f"/admin/explain/{tenant_a}/{fact_id}", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["node_id"] == fact_id
    assert "because" in data
    assert "redis-cache" in data["because"] or "memory_status" in data["because"]

    node_ids = [n["id"] for n in data["nodes"]]
    assert fact_id in node_ids
    assert event_id in node_ids

    edge_types = [e["type"] for e in data["edges"]]
    assert "DERIVED_FROM" in edge_types


def test_explain_superseded_fact(explain_fixture):
    client = TestClient(app)
    tenant_a = explain_fixture["tenant_a"]
    graph_a = explain_fixture["graph_a"]
    headers = {"Authorization": f"Bearer {settings.admin_token}"}

    # Fact v1
    f1 = upsert_fact(graph_a, "auth-svc", "status", "healthy", "agent_triage")
    f1_id = f1["fact_id"]

    # Fact v2 supersedes v1
    f2 = upsert_fact(graph_a, "auth-svc", "status", "degraded", "agent_investigator")
    f2_id = f2["fact_id"]

    res = client.get(f"/admin/explain/{tenant_a}/{f2_id}", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "superseded" in data["because"]

    node_ids = [n["id"] for n in data["nodes"]]
    assert f2_id in node_ids
    assert f1_id in node_ids

    edge_types = [e["type"] for e in data["edges"]]
    assert "SUPERSEDES" in edge_types


def test_explain_hypothesis_with_evidence(explain_fixture):
    client = TestClient(app)
    tenant_a = explain_fixture["tenant_a"]
    graph_a = explain_fixture["graph_a"]
    headers = {"Authorization": f"Bearer {settings.admin_token}"}

    inc = open_incident(graph_a, "INC-EXPLAIN", "sev1", "agent_triage")
    inc_id = inc["incident_id"]

    hyp = add_hypothesis(graph_a, inc_id, "Network drop caused timeouts", "agent_triage", confidence=0.88)
    hyp_id = hyp["hypothesis_id"]

    sess = start_session(graph_a, "agent_triage", "triage")
    ev = log_event(graph_a, sess["session_id"], "observation", "Packet drop at 45% on eth0", idempotency_key="ev_pkt_drop")
    event_id = ev["event_id"]

    attach_evidence(graph_a, hyp_id, event_id, agent_id="agent_triage", note="TCP retransmits spiked")

    res = client.get(f"/admin/explain/{tenant_a}/{hyp_id}", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "Packet drop" in data["because"] or "Network drop" in data["because"]

    node_ids = [n["id"] for n in data["nodes"]]
    assert hyp_id in node_ids
    assert event_id in node_ids

    edge_types = [e["type"] for e in data["edges"]]
    assert "SUPPORTED_BY" in edge_types


def test_explain_cross_tenant_isolation(explain_fixture):
    client = TestClient(app)
    tenant_a = explain_fixture["tenant_a"]
    tenant_b = explain_fixture["tenant_b"]
    graph_b = explain_fixture["graph_b"]
    headers = {"Authorization": f"Bearer {settings.admin_token}"}

    # Create private fact in tenant B
    f_b = upsert_fact(graph_b, "secret-db", "passphrase", "classified", "agent_b")
    fb_id = f_b["fact_id"]

    # Querying tenant A for tenant B's node ID must return 404 NOT_FOUND
    res = client.get(f"/admin/explain/{tenant_a}/{fb_id}", headers=headers)
    assert res.status_code == 404

    # Non-existent node ID returns 404
    res_fake = client.get(f"/admin/explain/{tenant_a}/fact_nonexistent_12345", headers=headers)
    assert res_fake.status_code == 404

    # Missing admin token returns 403 FORBIDDEN
    res_no_auth = client.get(f"/admin/explain/{tenant_a}/{fb_id}")
    assert res_no_auth.status_code == 403
