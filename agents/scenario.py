"""
Scripted end-to-end incident execution engine for Acme scenario.
Can run in deterministic mode (for automated tests, CI, and rock-solid video demos)
or interactive mode via LLM tool-calling loop.
"""
import time
import logging
from typing import Any, Dict

from server.app.auth import AuthContext
from server.app.queries.semantic import upsert_fact, query_facts
from server.app.queries.procedural import find_procedure, record_outcome, get_procedure
from server.app.tools.coordination import (
    open_incident_handler,
    create_task_handler,
    claim_task_handler,
    release_task_handler,
    complete_task_handler,
    add_hypothesis_handler,
    attach_evidence_handler,
    create_handoff_handler,
    accept_handoff_handler,
)
from server.app.tools.episodic import start_session_handler, log_event_handler, end_session_handler
from server.app.tools.insight import blast_radius_handler, explain_handler
from server.app.consolidation import run_consolidation

log = logging.getLogger("scenario")


def run_full_incident_scenario(tenant_id: str = "acme") -> Dict[str, Any]:
    """
    Executes the complete demo script incident end-to-end:
    1. Seed trap: payments-svc owner = Team Core
    2. Triage: starts session, opens INC-1, creates hypothesis & task, hands off to Investigator
    3. Investigator: accepts handoff, claims task, analyzes blast radius, attaches evidence, rules out auth-svc, hands off to Remediator
    4. Remediator: accepts handoff, finds procedures (restart-redis ranks #1), executes restart-redis -> fails!
    5. Learning moment: records failure, forks restart-redis to v2 with new precondition, re-ranks and chooses rollback-deploy -> succeeds! Completes task.
    6. Ownership correction trap: corrects payments-svc owner to Team Billing (supersedes Team Core)
    7. Comms: generates final summary and consolidates knowledge graph
    """
    graph_name = f"tenant_{tenant_id}"
    log.info("Starting Full End-to-End Incident Scenario on %s", graph_name)

    # Contexts for each agent
    ctx_triage = AuthContext(tenant_id, "agent_triage", "triage", graph_name, "key_triage")
    ctx_inv = AuthContext(tenant_id, "agent_investigator", "investigator", graph_name, "key_inv")
    ctx_rem = AuthContext(tenant_id, "agent_remediator", "remediator", graph_name, "key_rem")
    ctx_comms = AuthContext(tenant_id, "agent_comms", "comms", graph_name, "key_comms")

    # Capture initial timestamp for time-travel query verification
    t_start = int(time.time() * 1000)

    # -------------------------------------------------------------
    # STEP 1: TRIAGE AGENT
    # -------------------------------------------------------------
    log.info("Step 1: Triage receives alert and opens incident...")
    s_tri = start_session_handler(ctx_triage)
    sess_tri_id = s_tri["session_id"]

    inc_res = open_incident_handler(ctx_triage, title="INC-1: Checkout latency spike", severity="sev1")
    inc_id = inc_res["incident_id"]

    log_event_handler(
        ctx_triage,
        session_id=sess_tri_id,
        event_type="observation",
        summary="checkout-api p99 latency spiked to 3200ms following high cache miss rate",
        entities=["checkout-api", "redis-cache"]
    )

    hyp_res = add_hypothesis_handler(
        ctx_triage,
        incident_id=inc_id,
        statement="Redis cache degradation or service outage is causing checkout timeouts",
        confidence=0.75
    )
    hyp_id = hyp_res["hypothesis_id"]

    task_res = create_task_handler(
        ctx_triage,
        title="Investigate cache health and eliminate upstream bottlenecks",
        incident_id=inc_id,
        priority=1
    )
    task_id = task_res["task_id"]

    ho_tri = create_handoff_handler(
        ctx_triage,
        to_agent="agent_investigator",
        context_summary="Alert received on checkout-api latency. Initial hypothesis is Redis cache stall.",
        task_id=task_id,
        incident_id=inc_id
    )
    ho_tri_id = ho_tri["handoff_id"]
    end_session_handler(ctx_triage, sess_tri_id, "Triage completed initial incident triage and dispatched to investigator")

    # -------------------------------------------------------------
    # STEP 2: INVESTIGATOR AGENT
    # -------------------------------------------------------------
    log.info("Step 2: Investigator accepts handoff and examines topology...")
    s_inv = start_session_handler(ctx_inv)
    sess_inv_id = s_inv["session_id"]

    # Accept handoff and claim work
    acc_res = accept_handoff_handler(ctx_inv, ho_tri_id)
    assert acc_res["ok"] is True

    claim_res = claim_task_handler(ctx_inv, task_id)
    assert claim_res["ok"] is True

    # Check blast radius for redis-cache
    blast = blast_radius_handler(ctx_inv, service="redis-cache", depth=3)
    impacted = [x["name"] for x in blast["impacted_services"]]
    assert "checkout-api" in impacted

    # Attach evidence and rule out red herring auth-svc
    ev_res = log_event_handler(
        ctx_inv,
        session_id=sess_inv_id,
        event_type="observation",
        summary="auth-svc is emitting noisy debug logs but has 0% error rate; ruled out",
        entities=["auth-svc"]
    )
    attach_evidence_handler(ctx_inv, hypothesis_id=hyp_id, event_id=ev_res["event_id"], note="Ruled out auth-svc; Redis is root anomaly")

    ho_inv = create_handoff_handler(
        ctx_inv,
        to_agent="agent_remediator",
        context_summary="Investigator verified Redis cache anomaly. Auth-svc ruled out as red herring.",
        task_id=task_id,
        incident_id=inc_id
    )
    ho_inv_id = ho_inv["handoff_id"]
    rel_inv = release_task_handler(ctx_inv, task_id)
    assert rel_inv["ok"] is True
    end_session_handler(ctx_inv, sess_inv_id, "Investigation complete; handed off to remediator")

    # -------------------------------------------------------------
    # STEP 3: REMEDIATOR AGENT (THE LEARNING MOMENT)
    # -------------------------------------------------------------
    log.info("Step 3: Remediator executes runbooks, encounters failure, and learns...")
    s_rem = start_session_handler(ctx_rem)
    sess_rem_id = s_rem["session_id"]

    acc_rem = accept_handoff_handler(ctx_rem, ho_inv_id)
    assert acc_rem["ok"] is True
    claim_rem = claim_task_handler(ctx_rem, task_id)
    assert claim_rem["ok"] is True

    # 1. Search runbooks for situation
    procs_before = find_procedure(graph_name, situation="redis cache latency")
    top_proc = procs_before[0]
    assert "redis" in top_proc["name"]  # restart-redis ranks #1 initially
    pid_v1 = top_proc["procedure_id"]

    # 2. Execute restart-redis -> FAILS because deploy 20 mins ago caused incompatible schema!
    log.info("Executing top-ranked runbook %s... Fails due to deploy trap!", pid_v1)
    fail_res = record_outcome(
        graph_name=graph_name,
        procedure_id=pid_v1,
        incident_id=inc_id,
        success=False,
        failed_step=3,
        note="Redis restart failed to restore checkout latency; deploy from 20m ago broke cache schema",
        violated_assumption="assumed cache was corrupted, but recent deploy caused incompatibility",
        new_precondition="check for a deployment in the last 30 minutes before restarting cache"
    )
    assert fail_res["new_procedure_id"] is not None
    pid_v2 = fail_res["new_procedure_id"]

    # 3. Procedural learning verification: query runbooks again!
    procs_after = find_procedure(graph_name, situation="recent deploy latency after deploy")
    next_proc = procs_after[0]
    assert "rollback-deploy" in next_proc["name"]

    # 4. Execute rollback-deploy -> SUCCEEDS!
    log.info("Executing alternative procedure rollback-deploy... Succeeded!")
    record_outcome(
        graph_name=graph_name,
        procedure_id=next_proc["procedure_id"],
        incident_id=inc_id,
        success=True,
        note="Deployment rolled back successfully; p99 latency returned to 45ms"
    )

    # Complete task with cascade unblock
    comp_res = complete_task_handler(ctx_rem, task_id=task_id, summary="Rolled back faulty deploy and stabilized Redis")
    assert comp_res["ok"] is True
    end_session_handler(ctx_rem, sess_rem_id, "Remediation complete with procedural v2 learned")

    # -------------------------------------------------------------
    # STEP 4: STALE OWNERSHIP CORRECTION (SUPERSEDES & TIME TRAVEL)
    # -------------------------------------------------------------
    log.info("Step 4: Correcting stale service ownership...")
    time.sleep(0.01)
    t_between = int(time.time() * 1000)
    time.sleep(0.01)

    # Correct ownership from 'Team Core' to 'Team Billing'
    upsert_res = upsert_fact(
        graph_name=graph_name,
        entity_name="payments-svc",
        predicate="owner",
        value="Team Billing",
        agent_id="agent_remediator",
        confidence=0.95
    )
    new_fact_id = upsert_res["fact_id"]

    # -------------------------------------------------------------
    # STEP 5: COMMS AGENT & KNOWLEDGE CONSOLIDATION
    # -------------------------------------------------------------
    log.info("Step 5: Comms summarizes incident and consolidates graph...")
    s_comms = start_session_handler(ctx_comms)
    sess_comms_id = s_comms["session_id"]

    log_event_handler(
        ctx_comms,
        session_id=sess_comms_id,
        event_type="decision",
        summary="INC-1 resolved: checkout-api healthy; procedure restart-redis updated to v2 with deploy check precondition",
        entities=["checkout-api", "payments-svc"]
    )
    end_session_handler(ctx_comms, sess_comms_id, "Executive summary posted to incident channel")

    # Run consolidation cycle
    cons_res = run_consolidation(graph_name)

    log.info("✓ Full Incident Scenario Finished Successfully on %s!", graph_name)

    return {
        "ok": True,
        "incident_id": inc_id,
        "task_id": task_id,
        "hypothesis_id": hyp_id,
        "handoffs": [ho_tri_id, ho_inv_id],
        "v1_procedure_id": pid_v1,
        "v2_procedure_id": pid_v2,
        "t_start": t_start,
        "t_between": t_between,
        "new_fact_id": new_fact_id,
        "consolidation": cons_res
    }
