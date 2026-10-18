"""
Phase 3 unit tests: Coordination tools.
"""
import time
import pytest

from server.app.auth import AuthContext
from server.app.tenancy import provision_tenant, provision_agent_key
from server.app.tools.coordination import (
    open_incident_handler,
    create_task_handler,
    list_open_work_handler,
    claim_task_handler,
    renew_lease_handler,
    release_task_handler,
    complete_task_handler,
    add_hypothesis_handler,
    attach_evidence_handler,
    create_handoff_handler,
    accept_handoff_handler,
)
from server.app.queries.coordination import reap_expired_leases
from server.app.queries.episodic import start_session, log_event


# ───────────────── fixtures ─────────────────

@pytest.fixture(scope="module")
def coord_fixture():
    suffix = f"cd_{int(time.time() * 1000)}"
    provision_tenant(f"coord_acme_{suffix}", "Acme Corp")
    provision_tenant(f"coord_globex_{suffix}", "Globex Corp")

    acme_key, acme_hash = provision_agent_key(
        tenant_id=f"coord_acme_{suffix}", agent_id="agent_triage", role="triage"
    )
    acme_ctx = AuthContext(
        tenant_id=f"coord_acme_{suffix}",
        agent_id="agent_triage",
        role="triage",
        graph_name=f"tenant_coord_acme_{suffix}",
        key_hash=acme_hash,
    )

    inv_key, inv_hash = provision_agent_key(
        tenant_id=f"coord_acme_{suffix}", agent_id="agent_inv", role="investigator"
    )
    inv_ctx = AuthContext(
        tenant_id=f"coord_acme_{suffix}",
        agent_id="agent_inv",
        role="investigator",
        graph_name=f"tenant_coord_acme_{suffix}",
        key_hash=inv_hash,
    )

    globex_key, globex_hash = provision_agent_key(
        tenant_id=f"coord_globex_{suffix}", agent_id="agent_g", role="triage"
    )
    globex_ctx = AuthContext(
        tenant_id=f"coord_globex_{suffix}",
        agent_id="agent_g",
        role="triage",
        graph_name=f"tenant_coord_globex_{suffix}",
        key_hash=globex_hash,
    )

    return {"acme": acme_ctx, "inv": inv_ctx, "globex": globex_ctx}



# ───────────────── tests ─────────────────

def test_open_incident_and_create_task(coord_fixture):
    """CON-basic: incident creation, task linkage, list_open_work."""
    ctx = coord_fixture["acme"]

    inc = open_incident_handler(ctx, title="DB latency spike", severity="sev2")
    assert inc["ok"] is True
    inc_id = inc["incident_id"]

    task = create_task_handler(ctx, title="Investigate slow queries", incident_id=inc_id, priority=1)
    assert task["ok"] is True
    task_id = task["task_id"]

    work = list_open_work_handler(ctx)
    assert work["ok"] is True
    assert any(t["task_id"] == task_id for t in work["tasks"])


def test_claim_task_atomic(coord_fixture):
    """CON-1: exactly one claimant wins when two agents race."""
    ctx_a = coord_fixture["acme"]
    ctx_b = coord_fixture["inv"]

    task = create_task_handler(ctx_a, title="Atomic claim test")
    task_id = task["task_id"]

    # simulate race: both try to claim
    res_a = claim_task_handler(ctx_a, task_id)
    res_b = claim_task_handler(ctx_b, task_id)

    winners = [r for r in (res_a, res_b) if r["ok"]]
    losers  = [r for r in (res_a, res_b) if not r["ok"]]

    assert len(winners) == 1, "Exactly one agent should win the claim"
    assert len(losers) == 1
    assert losers[0]["error"]["code"] == "CONFLICT"


def test_renew_and_release(coord_fixture):
    """Leaseholder can renew; releasing returns task to open."""
    ctx = coord_fixture["acme"]

    task = create_task_handler(ctx, title="Lease lifecycle test")
    task_id = task["task_id"]

    claim_task_handler(ctx, task_id)

    renew = renew_lease_handler(ctx, task_id)
    assert renew["ok"] is True
    assert renew["lease_expires_at"] > int(time.time() * 1000)

    release = release_task_handler(ctx, task_id)
    assert release["ok"] is True

    # Can be claimed again after release
    reclaim = claim_task_handler(ctx, task_id)
    assert reclaim["ok"] is True


def test_complete_task_cascade_unblock(coord_fixture):
    """CON-6: completing a blocker opens the blocked task."""
    ctx = coord_fixture["acme"]

    blocker = create_task_handler(ctx, title="Blocker task")
    blocker_id = blocker["task_id"]

    blocked = create_task_handler(ctx, title="Blocked task", blocks=[])
    blocked_id = blocked["task_id"]

    # Wire BLOCKS edge
    from server.app.queries.coordination import create_task as q_create
    # shortcut: set status to blocked manually via direct query, then complete blocker
    from server.app.graph import execute_query
    execute_query(ctx.graph_name, "MATCH (t:Task {id: $id}) SET t.status = 'blocked'", {"id": blocked_id})
    execute_query(ctx.graph_name,
        "MATCH (a:Task {id: $aid}), (b:Task {id: $bid}) MERGE (a)-[:BLOCKS]->(b)",
        {"aid": blocker_id, "bid": blocked_id})

    # Claim then complete blocker
    claim_task_handler(ctx, blocker_id)
    done = complete_task_handler(ctx, blocker_id, summary="Fixed the root cause")
    assert done["ok"] is True

    # Verify blocked is now open
    from server.app.graph import execute_ro_query
    res = execute_ro_query(ctx.graph_name, "MATCH (t:Task {id: $id}) RETURN t.status", {"id": blocked_id})
    assert res.result_set[0][0] == "open"


def test_lease_reaper(coord_fixture):
    """CON-5: killed agent's task is reclaimed after lease expiry."""
    ctx = coord_fixture["acme"]

    task = create_task_handler(ctx, title="Reaper test task")
    task_id = task["task_id"]

    # Claim with a 1ms TTL so it expires immediately
    claim_task_handler(ctx, task_id, ttl_ms=1)
    time.sleep(0.01)  # let lease expire

    reaped = reap_expired_leases(ctx.graph_name)
    assert reaped >= 1

    # Now another agent can claim it
    ctx_b = coord_fixture["inv"]
    reclaim = claim_task_handler(ctx_b, task_id)
    assert reclaim["ok"] is True


def test_handoff_workflow(coord_fixture):
    """COO-1 to COO-3: create handoff, only recipient can accept."""
    ctx_a = coord_fixture["acme"]
    ctx_b = coord_fixture["inv"]

    task = create_task_handler(ctx_a, title="Handoff task")
    task_id = task["task_id"]

    ho = create_handoff_handler(ctx_a, to_agent=ctx_b.agent_id,
                                context_summary="DB investigation handed off",
                                task_id=task_id)
    assert ho["ok"] is True
    ho_id = ho["handoff_id"]

    # Non-recipient cannot accept
    wrong_ctx = coord_fixture["globex"]
    bad = accept_handoff_handler(wrong_ctx, ho_id)
    assert bad["ok"] is False
    assert bad["error"]["code"] == "FORBIDDEN"

    # Correct recipient accepts
    accepted = accept_handoff_handler(ctx_b, ho_id)
    assert accepted["ok"] is True
    assert accepted["context_summary"] == "DB investigation handed off"


def test_hypothesis_and_evidence(coord_fixture):
    """Hypothesis creation and evidence attachment."""
    ctx = coord_fixture["acme"]

    inc = open_incident_handler(ctx, title="Memory leak", severity="sev3")
    inc_id = inc["incident_id"]

    hyp = add_hypothesis_handler(ctx, incident_id=inc_id,
                                 statement="Connection pool exhausted", confidence=0.7)
    assert hyp["ok"] is True
    hyp_id = hyp["hypothesis_id"]

    # Create a real event to attach
    sess = start_session(ctx.graph_name, ctx.agent_id, ctx.role)
    ev = log_event(ctx.graph_name, sess["session_id"], "observation",
                   "Saw 5000 open connections", idempotency_key="ev_hyp_test_1")
    ev_id = ev["event_id"]

    evidence = attach_evidence_handler(ctx, hypothesis_id=hyp_id, event_id=ev_id, note="smoking gun")
    assert evidence["ok"] is True


def test_incident_idempotency(coord_fixture):
    """Same idempotency key returns the same incident."""
    ctx = coord_fixture["acme"]

    r1 = open_incident_handler(ctx, title="Dup incident", severity="sev4", idempotency_key="idem_inc_01")
    r2 = open_incident_handler(ctx, title="Dup incident", severity="sev4", idempotency_key="idem_inc_01")
    assert r1["incident_id"] == r2["incident_id"]
    assert r2["created"] is False
