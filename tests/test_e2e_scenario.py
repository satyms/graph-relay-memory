"""
Phase 7 End-to-End Scenario Verification Test.
Runs the complete incident scenario (TEST_PLAN Section 6 & 8) twice without manual intervention:
- All handoffs created and accepted
- Every task completed (done)
- Hypothesis supported with attached evidence
- Procedure failure fork produces v2 with PREVIOUS_VERSION edge and new precondition
- Fact supersession verified: time-travel query at t_between returns old owner ('Team Core'), while current query returns ('Team Billing')
- Explain tool traces complete provenance from conclusions back to root sources
"""
import pytest
from server.app.graph import execute_ro_query
from server.app.queries.semantic import query_facts
from server.app.queries.procedural import get_procedure
from server.app.tools.insight import explain_handler
from server.app.auth import AuthContext
from scripts.seed import seed_tenant, seed_default_runbooks
from agents.scenario import run_full_incident_scenario


@pytest.fixture(scope="module")
def seeded_e2e():
    tenant_id = "acme_e2e_test"
    # Seed shared runbooks and tenant
    seed_default_runbooks("shared_runbooks")
    seed_tenant(tenant_id, "Acme E2E Corp")
    return {"tenant_id": tenant_id, "graph_name": f"tenant_{tenant_id}"}


def test_e2e_scenario_run_one(seeded_e2e):
    """Run 1: Full incident scenario completes end-to-end and satisfies all proof gates."""
    tenant_id = seeded_e2e["tenant_id"]
    graph_name = seeded_e2e["graph_name"]

    res = run_full_incident_scenario(tenant_id=tenant_id)
    assert res["ok"] is True

    # 1. Verify every task is done
    task_res = execute_ro_query(graph_name, "MATCH (t:Task {id: $id}) RETURN t.status", {"id": res["task_id"]})
    assert task_res.result_set[0][0] == "done"

    # 2. Verify all handoffs accepted
    for ho_id in res["handoffs"]:
        ho_check = execute_ro_query(graph_name, "MATCH (h:Handoff {id: $id}) RETURN h.status", {"id": ho_id})
        assert ho_check.result_set[0][0] == "accepted"

    # 3. Verify hypothesis is linked to evidence
    hyp_check = execute_ro_query(
        graph_name,
        "MATCH (h:Hypothesis {id: $id})-[:SUPPORTED_BY]->(e:Event) RETURN count(e)",
        {"id": res["hypothesis_id"]}
    )
    assert hyp_check.result_set[0][0] >= 1

    # 4. Verify procedural learning: v1 is retired, v2 is active with PREVIOUS_VERSION link
    v1 = get_procedure(graph_name, res["v1_procedure_id"])
    assert v1["status"] == "retired"

    v2 = get_procedure(graph_name, res["v2_procedure_id"], include_history=True)
    assert v2["status"] == "active"
    assert v2["version"] == 2
    assert "check for a deployment in the last 30 minutes before restarting cache" in v2["preconditions"]
    assert len(v2["history"]) == 1
    assert v2["history"][0]["procedure_id"] == res["v1_procedure_id"]

    # 5. Time-Travel Query (MEM-2):
    # Current query returns new owner: 'Team Billing'
    curr_facts = query_facts(graph_name, entity="payments-svc", predicate="owner")
    assert len(curr_facts) == 1
    assert curr_facts[0]["value"] == "Team Billing"

    # As_of query at t_between returns old owner: 'Team Core'
    past_facts = query_facts(graph_name, entity="payments-svc", predicate="owner", as_of=res["t_between"])
    assert len(past_facts) == 1
    assert past_facts[0]["value"] == "Team Core"

    # 6. Provenance explain tool works
    ctx = AuthContext(tenant_id, "auditor", "admin", graph_name, "key")
    exp = explain_handler(ctx, node_id=res["new_fact_id"])
    assert exp["ok"] is True
    assert exp["provenance"]["value"] == "Team Billing"
    assert exp["provenance"]["previous_version"] is not None


def test_e2e_scenario_repeatable_run_two(seeded_e2e):
    """Run 2: Confirm scenario completes cleanly a second time in a fresh tenant (TEST_PLAN Section 8)."""
    tenant_id_2 = "acme_e2e_repeat"
    seed_tenant(tenant_id_2, "Acme Repeat Corp")
    graph_name = f"tenant_{tenant_id_2}"

    res = run_full_incident_scenario(tenant_id=tenant_id_2)
    assert res["ok"] is True

    # 1. Verify every task is done
    task_res = execute_ro_query(graph_name, "MATCH (t:Task {id: $id}) RETURN t.status", {"id": res["task_id"]})
    assert task_res.result_set[0][0] == "done"

    # 2. Verify all handoffs accepted
    for ho_id in res["handoffs"]:
        ho_check = execute_ro_query(graph_name, "MATCH (h:Handoff {id: $id}) RETURN h.status", {"id": ho_id})
        assert ho_check.result_set[0][0] == "accepted"

    # 3. Confirm procedural learning
    v1 = get_procedure(graph_name, res["v1_procedure_id"])
    assert v1["status"] == "retired"

    v2 = get_procedure(graph_name, res["v2_procedure_id"], include_history=True)
    assert v2["status"] == "active"
    assert v2["version"] == 2
    assert len(v2["history"]) == 1

    # 4. Confirm time-travel query
    curr_facts = query_facts(graph_name, entity="payments-svc", predicate="owner")
    assert curr_facts[0]["value"] == "Team Billing"

    past_facts = query_facts(graph_name, entity="payments-svc", predicate="owner", as_of=res["t_between"])
    assert past_facts[0]["value"] == "Team Core"
