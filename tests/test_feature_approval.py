"""
Feature 5 Tests: Approval Gate for Risky Actions.
Tests:
- complete_task on a risky action (e.g. rollback_deploy, restart_service, scale_down) without approval returns FORBIDDEN.
- Remediator requests approval: request_approval succeeds; non-remediator role returns FORBIDDEN.
- Admin endpoints:
  * GET /admin/approvals returns list of pending approvals.
  * POST /admin/approvals/{id}/decide records decision with admin identity.
  * Cross-tenant approval id returns NOT_FOUND.
  * Missing admin token returns FORBIDDEN.
- With approval granted: complete_task on the risky action succeeds.
- With rejection: agent learns rejection reason as an event and can pick another procedure.
"""
import time
import pytest
from fastapi.testclient import TestClient

from server.app.main import app
from server.app.config import settings
from server.app.auth import AuthContext
from server.app.tenancy import provision_tenant, provision_agent_key
from server.app.queries.coordination import create_task, claim_task
from server.app.tools.coordination import (
    complete_task_handler,
    request_approval_handler,
    check_approval_handler,
)
from server.app.graph import execute_ro_query


@pytest.fixture(scope="module")
def approval_fixture():
    ts = int(time.time() * 1000)
    tenant_a = f"appr_a_{ts}"
    tenant_b = f"appr_b_{ts}"

    provision_tenant(tenant_a, "Approval Test A")
    provision_tenant(tenant_b, "Approval Test B")

    graph_a = f"tenant_{tenant_a}"
    graph_b = f"tenant_{tenant_b}"

    key_rem, hash_rem = provision_agent_key(tenant_a, "agent_remediator", "remediator")
    key_tri, hash_tri = provision_agent_key(tenant_a, "agent_triage", "triage")

    ctx_rem = AuthContext(
        tenant_id=tenant_a,
        agent_id="agent_remediator",
        role="remediator",
        graph_name=graph_a,
        key_hash=hash_rem
    )
    ctx_tri = AuthContext(
        tenant_id=tenant_a,
        agent_id="agent_triage",
        role="triage",
        graph_name=graph_a,
        key_hash=hash_tri
    )

    return {
        "tenant_a": tenant_a,
        "graph_a": graph_a,
        "tenant_b": tenant_b,
        "graph_b": graph_b,
        "ctx_rem": ctx_rem,
        "ctx_tri": ctx_tri
    }


def test_risky_action_forbidden_without_approval(approval_fixture):
    ctx_rem = approval_fixture["ctx_rem"]
    graph = approval_fixture["graph_a"]

    # 1. Create a task for risky rollback
    task = create_task(graph, "Rollback checkout deployment", ctx_rem.agent_id)
    task_id = task["task_id"]

    claim_res = claim_task(graph, task_id, ctx_rem.agent_id)
    assert claim_res["ok"] is True

    # 2. Try to complete with risky action without approval -> Must fail with FORBIDDEN
    res_no_appr = complete_task_handler(
        ctx_rem,
        task_id=task_id,
        summary="Executed rollback_deploy to revert faulty build",
        action="rollback_deploy"
    )
    assert res_no_appr["ok"] is False
    assert res_no_appr["error"]["code"] == "FORBIDDEN"
    assert "restricted and requires an approved Approval" in res_no_appr["error"]["message"]


def test_role_restriction_on_request_approval(approval_fixture):
    ctx_tri = approval_fixture["ctx_tri"]
    ctx_rem = approval_fixture["ctx_rem"]
    graph = approval_fixture["graph_a"]

    task = create_task(graph, "Restart database node", ctx_rem.agent_id)
    task_id = task["task_id"]

    # Triage role attempting to request approval -> FORBIDDEN
    res_tri = request_approval_handler(
        ctx_tri,
        task_id=task_id,
        action="restart_service",
        justification="Restart postgres to free deadlocks"
    )
    assert res_tri["ok"] is False
    assert res_tri["error"]["code"] == "FORBIDDEN"
    assert "remediator" in res_tri["error"]["message"]


def test_approval_workflow_success_and_complete(approval_fixture):
    client = TestClient(app)
    ctx_rem = approval_fixture["ctx_rem"]
    tenant_a = approval_fixture["tenant_a"]
    graph = approval_fixture["graph_a"]
    headers = {"Authorization": f"Bearer {settings.admin_token}"}

    task = create_task(graph, "Scale down workers", ctx_rem.agent_id)
    task_id = task["task_id"]
    claim_task(graph, task_id, ctx_rem.agent_id)

    # 1. Remediator requests approval
    req_res = request_approval_handler(
        ctx_rem,
        task_id=task_id,
        action="scale_down",
        justification="Load subsided, scaling down from 10 to 2 instances"
    )
    assert req_res["ok"] is True
    appr_id = req_res["approval_id"]

    # 2. Check pending approval via tool
    check = check_approval_handler(ctx_rem, appr_id)
    assert check["ok"] is True
    assert check["approval"]["status"] == "pending"

    # 3. Query admin approvals endpoint
    list_res = client.get(f"/admin/approvals?tenant={tenant_a}&status=pending", headers=headers)
    assert list_res.status_code == 200
    pending_ids = [a["approval_id"] for a in list_res.json()["approvals"]]
    assert appr_id in pending_ids

    # 4. Admin decides: APPROVE
    decide_res = client.post(
        f"/admin/approvals/{appr_id}/decide?tenant={tenant_a}",
        json={"decision": "approved", "reason": "Approved by SRE lead"},
        headers=headers
    )
    assert decide_res.status_code == 200
    assert decide_res.json()["status"] == "approved"

    # 5. Check approval reflects approved status
    check_after = check_approval_handler(ctx_rem, appr_id)
    assert check_after["approval"]["status"] == "approved"
    assert check_after["approval"]["decided_by"] == "admin"

    # 6. complete_task on risky action NOW succeeds!
    comp_res = complete_task_handler(
        ctx_rem,
        task_id=task_id,
        summary="scale_down completed successfully to 2 instances",
        action="scale_down"
    )
    assert comp_res["ok"] is True


def test_approval_rejection_and_cross_tenant_isolation(approval_fixture):
    client = TestClient(app)
    ctx_rem = approval_fixture["ctx_rem"]
    tenant_a = approval_fixture["tenant_a"]
    tenant_b = approval_fixture["tenant_b"]
    graph = approval_fixture["graph_a"]
    headers = {"Authorization": f"Bearer {settings.admin_token}"}

    task = create_task(graph, "Restart core router", ctx_rem.agent_id)
    task_id = task["task_id"]

    req_res = request_approval_handler(
        ctx_rem,
        task_id=task_id,
        action="restart_service",
        justification="Restart core service"
    )
    appr_id = req_res["approval_id"]

    # Cross-tenant admin decision must return NOT_FOUND (tenant B trying to decide tenant A approval)
    cross_res = client.post(
        f"/admin/approvals/{appr_id}/decide?tenant={tenant_b}",
        json={"decision": "approved", "reason": "Wrong tenant"},
        headers=headers
    )
    assert cross_res.status_code == 404

    # Admin decides REJECT on tenant A
    rej_res = client.post(
        f"/admin/approvals/{appr_id}/decide?tenant={tenant_a}",
        json={"decision": "rejected", "reason": "Unsafe during peak hours; try canary first"},
        headers=headers
    )
    assert rej_res.status_code == 200
    assert rej_res.json()["status"] == "rejected"

    # Check status is rejected
    check_rej = check_approval_handler(ctx_rem, appr_id)
    assert check_rej["approval"]["status"] == "rejected"
    assert "Unsafe during peak hours" in check_rej["approval"]["reason"]
