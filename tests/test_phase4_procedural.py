"""
Unit and integration tests for Phase 4: Procedural Memory and Learning.
PRO-1: find_procedure ranked by Laplace smoothed success rate
PRO-2: record_outcome failure forks new version with PREVIOUS_VERSION and added precondition
PRO-3: subsequent find_procedure returns new version and demotes or retires failed one
PRO-4: success increments counter and improves score
"""
import pytest
from server.app.auth import AuthContext
from server.app.tenancy import provision_tenant, provision_agent_key
from server.app.queries.procedural import seed_default_runbooks
from server.app.tools.coordination import open_incident_handler
from server.app.tools.procedural import (
    find_procedure_handler,
    record_outcome_handler,
    get_procedure_handler,
)


@pytest.fixture(scope="module")
def proc_fixture():
    import time
    suffix = f"p4_{int(time.time() * 1000)}"
    tenant_id = f"proc_acme_{suffix}"
    provision_tenant(tenant_id, "Acme Procedural Inc")
    
    key, key_hash = provision_agent_key(
        tenant_id=tenant_id,
        agent_id="remediator_1",
        role="remediator"
    )
    ctx = AuthContext(
        tenant_id=tenant_id,
        agent_id="remediator_1",
        role="remediator",
        graph_name=f"tenant_{tenant_id}",
        key_hash=key_hash
    )

    # Seed procedures in tenant graph
    seed_default_runbooks(ctx.graph_name)

    return {"ctx": ctx}


def test_find_procedure_laplace_ranking(proc_fixture):
    """PRO-1: find_procedure returns runbooks ranked by smoothed score."""
    ctx = proc_fixture["ctx"]
    res = find_procedure_handler(ctx, situation="cache latency on redis after spike")
    assert res["ok"] is True
    procs = res["procedures"]
    assert len(procs) > 0

    # restart-redis (2 success, 0 fail -> (2+1)/(2+0+2) = 0.75)
    # rollback-deploy (1 success, 1 fail -> (1+1)/(1+1+2) = 0.50)
    top = procs[0]
    assert "redis" in top["name"]
    assert top["score"] >= 0.75
    assert len(top["steps"]) == 3


def test_record_outcome_success(proc_fixture):
    """PRO-4: Success increments count and increases score."""
    ctx = proc_fixture["ctx"]
    # Open an incident
    inc = open_incident_handler(ctx, title="Minor scale issue", severity="sev3")
    inc_id = inc["incident_id"]

    # scale-db-pool starts at (0, 0) -> score (0+1)/(0+0+2) = 0.5
    pid = "proc_scale-db-pool_v1"
    res = record_outcome_handler(
        ctx,
        procedure_id=pid,
        incident_id=inc_id,
        success=True,
        note="Pool scaled cleanly without error"
    )
    assert res["ok"] is True
    assert res["new_procedure_id"] is None  # no fork on success

    updated = get_procedure_handler(ctx, pid)
    assert updated["ok"] is True
    assert updated["success_count"] == 1
    # score now (1+1)/(1+0+2) = 2/3 = 0.6667
    assert updated["score"] > 0.6


def test_failure_forks_new_version_with_precondition(proc_fixture):
    """PRO-2 & PRO-3: A failure creates v2 with new precondition and PREVIOUS_VERSION link."""
    ctx = proc_fixture["ctx"]
    inc = open_incident_handler(ctx, title="High latency incident", severity="sev1")
    inc_id = inc["incident_id"]

    pid_v1 = "proc_restart-redis_v1"

    # Simulate Remediator running restart-redis and failing because of recent deploy
    fail_res = record_outcome_handler(
        ctx,
        procedure_id=pid_v1,
        incident_id=inc_id,
        success=False,
        failed_step=3,
        note="Restart failed to resolve checkout latency; root cause was bad deploy",
        violated_assumption="assumed cache corruption, but code deployment was faulty",
        new_precondition="check for a deployment in the last 30 minutes before restarting cache"
    )
    assert fail_res["ok"] is True
    assert fail_res["new_procedure_id"] is not None
    pid_v2 = fail_res["new_procedure_id"]
    assert "v2" in pid_v2

    # Check v1 is retired
    v1_details = get_procedure_handler(ctx, pid_v1)
    assert v1_details["ok"] is True
    assert v1_details["status"] == "retired"
    assert v1_details["fail_count"] == 1

    # Check v2 is active and contains the new precondition
    v2_details = get_procedure_handler(ctx, pid_v2, include_history=True)
    assert v2_details["ok"] is True
    assert v2_details["version"] == 2
    assert v2_details["status"] == "active"
    assert "check for a deployment in the last 30 minutes before restarting cache" in v2_details["preconditions"]
    assert len(v2_details["history"]) == 1
    assert v2_details["history"][0]["procedure_id"] == pid_v1

    # Subsequent find_procedure returns v2, not v1
    find_res = find_procedure_handler(ctx, situation="redis cache latency")
    assert find_res["ok"] is True
    active_ids = [p["procedure_id"] for p in find_res["procedures"]]
    assert pid_v2 in active_ids
    assert pid_v1 not in active_ids  # retired version omitted from active search
