"""
Feature 1 Tests: Chaos Button (kill agent mid-task, lease expiry, reaper recovery, and reclaim).
Tests:
- Kill an agent holding a claim.
- Advance time or wait out a short lease.
- Run the reaper: assert task status returns to open, version increments.
- Another surviving agent claims the task: assert version increments and no duplicate owners.
- Endpoint validation: POST /admin/chaos/kill-agent requires admin token and valid tenant.
"""
import time
import pytest
from fastapi.testclient import TestClient

from server.app.main import app
from server.app.auth import AuthContext
from server.app.config import settings
from server.app.tenancy import provision_tenant, provision_agent_key
from server.app.queries.coordination import (
    create_task,
    claim_task,
    reap_expired_leases_detailed,
    get_agent_tasks,
)
from server.app.graph import execute_ro_query


@pytest.fixture(scope="module")
def chaos_fixture():
    tenant_id = f"chaos_{int(time.time())}"
    provision_tenant(tenant_id, "Chaos Test Corp")
    graph_name = f"tenant_{tenant_id}"

    key_triage, hash_triage = provision_agent_key(tenant_id, "agent_triage", "triage")
    key_inv, hash_inv = provision_agent_key(tenant_id, "agent_investigator", "investigator")

    ctx_triage = AuthContext(
        tenant_id=tenant_id,
        agent_id="agent_triage",
        role="triage",
        graph_name=graph_name,
        key_hash=hash_triage,
    )
    ctx_inv = AuthContext(
        tenant_id=tenant_id,
        agent_id="agent_investigator",
        role="investigator",
        graph_name=graph_name,
        key_hash=hash_inv,
    )

    return {
        "tenant_id": tenant_id,
        "graph_name": graph_name,
        "ctx_triage": ctx_triage,
        "ctx_inv": ctx_inv,
    }


def test_kill_agent_and_reaper_recovery(chaos_fixture):
    """
    Test agent kill, short lease expiration, reaper reopening, and reclaim with version increment.
    """
    client = TestClient(app)
    tenant_id = chaos_fixture["tenant_id"]
    graph_name = chaos_fixture["graph_name"]

    # 1. Create a task with version initialized to 1
    task = create_task(graph_name, "Chaos Recovery Task", "agent_triage")
    task_id = task["task_id"]

    res_init = execute_ro_query(graph_name, "MATCH (t:Task {id: $id}) RETURN t.version, t.status", {"id": task_id})
    assert res_init.result_set[0][0] == 1
    assert res_init.result_set[0][1] == "open"

    # 2. Agent triage claims the task with a short 50ms lease
    claim_res = claim_task(graph_name, task_id, "agent_triage", ttl_ms=50)
    assert claim_res["ok"] is True
    assert claim_res["version"] == 2

    # 3. Call chaos endpoint: POST /admin/chaos/kill-agent
    # Verify FORBIDDEN without token
    bad_resp = client.post("/admin/chaos/kill-agent", json={"tenant": tenant_id, "agent_role": "triage"})
    assert bad_resp.status_code == 403

    # Call with admin token
    headers = {"Authorization": f"Bearer {settings.admin_token}"}
    resp = client.post(
        "/admin/chaos/kill-agent",
        json={"tenant": tenant_id, "agent_role": "triage"},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["killed_agent"] == "agent_triage"
    held_ids = [t["task_id"] for t in data["held_tasks"]]
    assert task_id in held_ids

    # 4. Wait out the 50ms lease
    time.sleep(0.08)

    # 5. Run reaper
    reaped = reap_expired_leases_detailed(graph_name)
    reaped_ids = [r["task_id"] for r in reaped]
    assert task_id in reaped_ids

    # Assert task is open, owner is cleared, version incremented to 3
    res_reaped = execute_ro_query(
        graph_name,
        "MATCH (t:Task {id: $id}) RETURN t.status, t.claimed_by, t.version",
        {"id": task_id},
    )
    assert res_reaped.result_set[0][0] == "open"
    assert res_reaped.result_set[0][1] is None
    assert res_reaped.result_set[0][2] == 3

    # 6. Surviving agent (investigator) reclaims task via endpoint
    reclaim_resp = client.post(
        "/admin/chaos/reclaim-task",
        json={"tenant": tenant_id, "agent_role": "investigator", "task_id": task_id},
        headers=headers,
    )
    assert reclaim_resp.status_code == 200
    rec_data = reclaim_resp.json()
    assert rec_data["ok"] is True
    assert rec_data["claimed_by"] == "agent_investigator"
    assert rec_data["version"] == 4

    # 7. Assert no duplicate owners: exactly one owner is in the graph
    res_final = execute_ro_query(
        graph_name,
        "MATCH (t:Task {id: $id}) RETURN t.status, t.claimed_by, t.version",
        {"id": task_id},
    )
    assert res_final.result_set[0][0] == "in_progress"
    assert res_final.result_set[0][1] == "agent_investigator"
    assert res_final.result_set[0][2] == 4
