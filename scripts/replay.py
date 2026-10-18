"""
Deterministic Scenario Replay Engine for Relay (Acme INC-1).
Provides:
- Recorded, rock-solid scenario execution steps that can be displayed offline or on stage without model drift.
- Function get_replay_steps() returning structured steps for showcase demo flow.
- CLI runner: python scripts/replay.py [--live]
"""
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def get_replay_steps() -> List[Dict[str, Any]]:
    """
    Returns 8 deterministic replay steps for the Acme incident walkthrough.
    Each step specifies the agent, role, tool call, outcome, graph delta, and visualization highlights.
    """
    return [
        {
            "step": 1,
            "agent": "agent_triage",
            "role": "triage",
            "title": "Alert Received & Incident Opened",
            "summary": "Triage agent receives alert: checkout-api latency spiked to 3200ms. Opens INC-1, logs episodic observation, formulates initial hypothesis.",
            "tool_call": {
                "tool": "open_incident",
                "parameters": {
                    "title": "INC-1: Checkout latency spike",
                    "severity": "sev1",
                    "summary": "checkout-api p99 latency spiked to 3200ms following high cache miss rate"
                }
            },
            "tool_result": {
                "ok": True,
                "incident_id": "INC-1",
                "title": "INC-1: Checkout latency spike",
                "severity": "sev1",
                "status": "open",
                "created_at": 1792310400000
            },
            "graph_delta": {
                "nodes_added": [
                    {"id": "INC-1", "label": "INC-1: Checkout latency spike", "type": "Incident", "memory_type": "coordination"},
                    {"id": "hyp_cache_stall", "label": "Hypothesis: Redis stall", "type": "Hypothesis", "memory_type": "coordination"},
                    {"id": "evt_triage_alert", "label": "Alert: p99 latency 3200ms", "type": "Event", "memory_type": "episodic"}
                ],
                "edges_added": [
                    {"source": "hyp_cache_stall", "target": "INC-1", "type": "RELATES_TO"},
                    {"source": "evt_triage_alert", "target": "INC-1", "type": "PERTAINS_TO"}
                ]
            },
            "highlight_nodes": ["INC-1", "hyp_cache_stall", "checkout-api", "redis-cache"],
            "explanation": "Triage structures the alert as a typed Incident node and Hypothesis node in FalkorDB rather than dropping loose chat text."
        },
        {
            "step": 2,
            "agent": "agent_triage",
            "role": "triage",
            "title": "Task Created & Dispatched via Handoff",
            "summary": "Triage creates investigation task with a 60s lease and creates a structured Handoff node to investigator with open questions.",
            "tool_call": {
                "tool": "create_handoff",
                "parameters": {
                    "to_agent": "agent_investigator",
                    "context_summary": "Alert on checkout-api latency. Initial hypothesis is Redis cache stall.",
                    "task_id": "task_investigate_cache",
                    "incident_id": "INC-1"
                }
            },
            "tool_result": {
                "ok": True,
                "handoff_id": "hnd_triage_to_inv",
                "from_agent": "agent_triage",
                "to_agent": "agent_investigator",
                "task_id": "task_investigate_cache",
                "status": "pending"
            },
            "graph_delta": {
                "nodes_added": [
                    {"id": "task_investigate_cache", "label": "Investigate cache health", "type": "Task", "memory_type": "coordination", "properties": {"status": "open", "priority": 1, "version": 1}},
                    {"id": "hnd_triage_to_inv", "label": "Handoff: triage -> investigator", "type": "Handoff", "memory_type": "coordination"}
                ],
                "edges_added": [
                    {"source": "task_investigate_cache", "target": "INC-1", "type": "PART_OF"},
                    {"source": "hnd_triage_to_inv", "target": "task_investigate_cache", "type": "HANDS_OFF"}
                ]
            },
            "highlight_nodes": ["task_investigate_cache", "hnd_triage_to_inv"],
            "explanation": "No lost context: The Handoff node carries explicit references to the task, incident, and initial hypothesis."
        },
        {
            "step": 3,
            "agent": "agent_investigator",
            "role": "investigator",
            "title": "Handoff Accepted, Task Claimed & Blast Radius Inspected",
            "summary": "Investigator claims the task with atomic CAS, traverses the service dependency topology (blast radius depth 3), and rules out noisy auth-svc.",
            "tool_call": {
                "tool": "blast_radius",
                "parameters": {
                    "service": "redis-cache",
                    "depth": 3
                }
            },
            "tool_result": {
                "ok": True,
                "service": "redis-cache",
                "impacted_services": [
                    {"name": "checkout-api", "kind": "service", "hops": 1},
                    {"name": "payments-svc", "kind": "service", "hops": 2}
                ],
                "total_impacted": 2
            },
            "graph_delta": {
                "nodes_added": [
                    {"id": "evt_auth_ruled_out", "label": "auth-svc healthy (red herring)", "type": "Event", "memory_type": "episodic"},
                    {"id": "evt_redis_evidence", "label": "Redis connection pool 100% full", "type": "Event", "memory_type": "episodic"}
                ],
                "edges_added": [
                    {"source": "evt_redis_evidence", "target": "hyp_cache_stall", "type": "SUPPORTED_BY"},
                    {"source": "evt_auth_ruled_out", "target": "auth-svc", "type": "PERTAINS_TO"}
                ]
            },
            "highlight_nodes": ["redis-cache", "checkout-api", "evt_redis_evidence", "auth-svc"],
            "explanation": "Click-to-Explain provenance: The hypothesis is now supported by concrete episodic evidence attached via SUPPORTED_BY."
        },
        {
            "step": 4,
            "agent": "agent_remediator",
            "role": "remediator",
            "title": "Runbook Selection & First Attempt (Fails)",
            "summary": "Remediator queries procedural memory: restart-redis v1 ranks #1 (Laplace score 0.75). Remediator attempts restart-redis, but it fails due to an undetected deployment lock.",
            "tool_call": {
                "tool": "find_procedure",
                "parameters": {
                    "situation": "cache latency redis timeout"
                }
            },
            "tool_result": {
                "ok": True,
                "procedures": [
                    {"id": "proc_restart_redis_v1", "name": "restart-redis", "version": 1, "score": 0.75, "success_count": 2, "fail_count": 0},
                    {"id": "proc_rollback_deploy_v1", "name": "rollback-deploy", "version": 1, "score": 0.50, "success_count": 1, "fail_count": 1}
                ]
            },
            "graph_delta": {
                "nodes_added": [
                    {"id": "out_restart_failed", "label": "Outcome: restart-redis failed (deploy in progress)", "type": "Outcome", "memory_type": "procedural"}
                ],
                "edges_added": [
                    {"source": "proc_restart_redis_v1", "target": "out_restart_failed", "type": "RESULTED_IN"}
                ]
            },
            "highlight_nodes": ["proc_restart_redis_v1", "out_restart_failed"],
            "explanation": "Seed trap activated: Agent chose the highest-ranked procedure, but environmental assumptions failed."
        },
        {
            "step": 5,
            "agent": "agent_remediator",
            "role": "remediator",
            "title": "Procedural Learning: Runbook Fork with Precondition",
            "summary": "Remediator records the failure outcome. Procedural memory engine automatically forks restart-redis to v2 with a new precondition.",
            "tool_call": {
                "tool": "record_outcome",
                "parameters": {
                    "procedure_id": "proc_restart_redis_v1",
                    "incident_id": "INC-1",
                    "success": False,
                    "failed_step": 2,
                    "violated_assumption": "cache restart safe during rollout",
                    "new_precondition": "check for deployment in last 30m"
                }
            },
            "tool_result": {
                "ok": True,
                "forked_procedure_id": "proc_restart_redis_v2",
                "version": 2,
                "preconditions": ["check for deployment in last 30m"],
                "old_procedure_demoted": True
            },
            "graph_delta": {
                "nodes_added": [
                    {"id": "proc_restart_redis_v2", "label": "restart-redis v2", "type": "Procedure", "memory_type": "procedural", "properties": {"version": 2, "precondition": "check for deployment in last 30m"}}
                ],
                "edges_added": [
                    {"source": "proc_restart_redis_v2", "target": "proc_restart_redis_v1", "type": "PREVIOUS_VERSION"}
                ]
            },
            "highlight_nodes": ["proc_restart_redis_v2", "proc_restart_redis_v1"],
            "explanation": "Autonomous learning: No human had to rewrite the runbook. Future agents will evaluate the precondition before running."
        },
        {
            "step": 6,
            "agent": "agent_remediator",
            "role": "remediator",
            "title": "Human Gate: Approval Request for Rollback",
            "summary": "Remediator re-queries procedures: rollback-deploy is selected. Because rollback_deploy is a destructive action, Relay blocks execution until authorized by an operator.",
            "tool_call": {
                "tool": "request_approval",
                "parameters": {
                    "task_id": "task_remediate_incident",
                    "action": "rollback_deploy",
                    "target": "checkout-api",
                    "justification": "Faulty build v2.4.1 introduced memory leak; rollback to v2.4.0 required"
                }
            },
            "tool_result": {
                "ok": True,
                "approval_id": "appr_rollback_checkout",
                "status": "approved",
                "decided_by": "admin_sre_lead",
                "reason": "Authorized: deployment was confirmed source of latency spike"
            },
            "graph_delta": {
                "nodes_added": [
                    {"id": "appr_rollback_checkout", "label": "Approval: rollback_deploy (Approved)", "type": "Approval", "memory_type": "coordination", "properties": {"status": "approved", "decided_by": "admin"}}
                ],
                "edges_added": [
                    {"source": "appr_rollback_checkout", "target": "INC-1", "type": "GATES"}
                ]
            },
            "highlight_nodes": ["appr_rollback_checkout", "checkout-api"],
            "explanation": "Human-in-the-loop safety: Risky actions cannot be executed autonomously without cryptographic or admin signoff."
        },
        {
            "step": 7,
            "agent": "agent_remediator",
            "role": "remediator",
            "title": "Rollback Executed & Knowledge Correction Trap",
            "summary": "With approval granted, rollback executes successfully. Remediator discovers that payments-svc owner was erroneously listed as Team Core, corrects it to Team Billing via SUPERSEDES.",
            "tool_call": {
                "tool": "upsert_fact",
                "parameters": {
                    "entity": "payments-svc",
                    "predicate": "owner",
                    "value": "Team Billing"
                }
            },
            "tool_result": {
                "ok": True,
                "fact_id": "fact_payments_owner_v2",
                "superseded_fact_id": "fact_payments_owner_v1",
                "entity": "payments-svc",
                "predicate": "owner",
                "value": "Team Billing"
            },
            "graph_delta": {
                "nodes_added": [
                    {"id": "fact_payments_owner_v2", "label": "Fact: payments-svc.owner = Team Billing", "type": "Fact", "memory_type": "semantic"}
                ],
                "edges_added": [
                    {"source": "fact_payments_owner_v2", "target": "fact_payments_owner_v1", "type": "SUPERSEDES"},
                    {"source": "ent_payments", "target": "fact_payments_owner_v2", "type": "HAS_FACT"}
                ]
            },
            "highlight_nodes": ["fact_payments_owner_v2", "fact_payments_owner_v1", "ent_payments"],
            "explanation": "Non-destructive temporal memory: Team Core is not erased. Historical as-of queries still reconstruct the past faithfully."
        },
        {
            "step": 8,
            "agent": "agent_comms",
            "role": "comms",
            "title": "Incident Resolved, Consolidated & Verified",
            "summary": "Comms agent summarizes the resolution, task is marked completed, and consolidation worker creates durable high-order facts. System passes all verification tests.",
            "tool_call": {
                "tool": "complete_task",
                "parameters": {
                    "task_id": "task_investigate_cache",
                    "summary": "Incident resolved via rollback of checkout-api to v2.4.0. Redis cache recovered."
                }
            },
            "tool_result": {
                "ok": True,
                "task_id": "task_investigate_cache",
                "status": "completed",
                "incident_status": "resolved"
            },
            "graph_delta": {
                "nodes_added": [
                    {"id": "evt_resolution_summary", "label": "Incident INC-1 Resolved", "type": "Event", "memory_type": "episodic"}
                ],
                "edges_added": [
                    {"source": "evt_resolution_summary", "target": "INC-1", "type": "RESOLVES"}
                ]
            },
            "highlight_nodes": ["INC-1", "task_investigate_cache", "evt_resolution_summary"],
            "explanation": "Full closure: From raw alarm to structured incident, leased tasks, empirical evidence, learned runbooks, and verified temporal knowledge."
        }
    ]


def run_replay(tenant_id: str = "acme"):
    """CLI runner to print or execute the replay sequence."""
    steps = get_replay_steps()
    print("=" * 80)
    print(f"  RELAY MEMORY: DETERMINISTIC INCIDENT REPLAY ({len(steps)} STEPS)")
    print("=" * 80)
    for s in steps:
        print(f"\n[Step {s['step']}] {s['title']} ({s['role'].upper()})")
        print(f"  Summary: {s['summary']}")
        print(f"  Tool Call: {s['tool_call']['tool']}({json.dumps(s['tool_call']['parameters'])})")
        print(f"  Outcome: {s['explanation']}")
    print("\nReplay finished successfully.")


if __name__ == "__main__":
    run_replay()
