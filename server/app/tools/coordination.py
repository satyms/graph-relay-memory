"""
Coordination tool handlers: Tasks, Incidents, Hypotheses, Handoffs.
"""
from typing import Any, Dict, List, Optional
from server.app.auth import AuthContext, log_audit
from server.app.queries import coordination as queries


def _err(tool: str, ctx: AuthContext, code: str, msg: str) -> Dict[str, Any]:
    log_audit(tool=tool, ok=False, error_code=code, auth_context=ctx)
    return {"ok": False, "error": {"code": code, "message": msg}}


def open_incident_handler(
    ctx: AuthContext,
    title: str,
    severity: str,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    if severity not in {"sev1", "sev2", "sev3", "sev4"}:
        return _err("open_incident", ctx, "INVALID", "severity must be sev1-sev4")
    try:
        res = queries.open_incident(ctx.graph_name, title, severity, ctx.agent_id, idempotency_key)
        log_audit(tool="open_incident", ok=True, auth_context=ctx)
        return {"ok": True, **res}
    except Exception as e:
        return _err("open_incident", ctx, "UNAVAILABLE", str(e))


def create_task_handler(
    ctx: AuthContext,
    title: str,
    incident_id: Optional[str] = None,
    blocks: Optional[List[str]] = None,
    priority: int = 5,
) -> Dict[str, Any]:
    if not title:
        return _err("create_task", ctx, "INVALID", "title required")
    try:
        res = queries.create_task(ctx.graph_name, title, ctx.agent_id, incident_id, blocks, priority)
        log_audit(tool="create_task", ok=True, auth_context=ctx)
        return {"ok": True, **res}
    except Exception as e:
        return _err("create_task", ctx, "UNAVAILABLE", str(e))


def list_open_work_handler(ctx: AuthContext, limit: int = 20) -> Dict[str, Any]:
    try:
        tasks = queries.list_open_work(ctx.graph_name, limit=limit)
        log_audit(tool="list_open_work", ok=True, auth_context=ctx)
        return {"ok": True, "tasks": tasks}
    except Exception as e:
        return _err("list_open_work", ctx, "UNAVAILABLE", str(e))


from server.app.config import settings


def claim_task_handler(ctx: AuthContext, task_id: str, ttl_ms: Optional[int] = None) -> Dict[str, Any]:
    if not task_id:
        return _err("claim_task", ctx, "INVALID", "task_id required")
    if ttl_ms is None:
        if settings.demo_mode:
            ttl_ms = settings.chaos_lease_seconds * 1000
        else:
            ttl_ms = queries.DEFAULT_LEASE_TTL_MS
    try:
        res = queries.claim_task(ctx.graph_name, task_id, ctx.agent_id, ttl_ms)
        log_audit(tool="claim_task", ok=res["ok"], error_code=None if res["ok"] else res["error"]["code"], auth_context=ctx)
        return res
    except Exception as e:
        return _err("claim_task", ctx, "UNAVAILABLE", str(e))


def renew_lease_handler(ctx: AuthContext, task_id: str, ttl_ms: int = queries.DEFAULT_LEASE_TTL_MS) -> Dict[str, Any]:
    if not task_id:
        return _err("renew_lease", ctx, "INVALID", "task_id required")
    try:
        res = queries.renew_lease(ctx.graph_name, task_id, ctx.agent_id, ttl_ms)
        log_audit(tool="renew_lease", ok=res["ok"], error_code=None if res["ok"] else res["error"]["code"], auth_context=ctx)
        return res
    except Exception as e:
        return _err("renew_lease", ctx, "UNAVAILABLE", str(e))


def release_task_handler(ctx: AuthContext, task_id: str) -> Dict[str, Any]:
    if not task_id:
        return _err("release_task", ctx, "INVALID", "task_id required")
    try:
        res = queries.release_task(ctx.graph_name, task_id, ctx.agent_id)
        log_audit(tool="release_task", ok=res["ok"], error_code=None if res["ok"] else res["error"]["code"], auth_context=ctx)
        return res
    except Exception as e:
        return _err("release_task", ctx, "UNAVAILABLE", str(e))


def complete_task_handler(
    ctx: AuthContext,
    task_id: str,
    summary: str = "",
    action: Optional[str] = None
) -> Dict[str, Any]:
    if not task_id:
        return _err("complete_task", ctx, "INVALID", "task_id required")

    # If task action is risky, human approval is mandatory
    from server.app.queries.approval import RISKY_ACTIONS, is_task_approved_for_action
    # Detect risky action either passed explicitly or detected from summary/task title
    check_action = action
    if not check_action:
        summary_lower = summary.lower()
        for ra in RISKY_ACTIONS:
            if ra in summary_lower or ra.replace("_", "-") in summary_lower or ra.replace("_", " ") in summary_lower:
                check_action = ra
                break

    if check_action and check_action in RISKY_ACTIONS:
        if not is_task_approved_for_action(ctx.graph_name, task_id, check_action):
            return _err(
                "complete_task",
                ctx,
                "FORBIDDEN",
                f"Action '{check_action}' is restricted and requires an approved Approval gate before completion."
            )

    try:
        res = queries.complete_task(ctx.graph_name, task_id, ctx.agent_id, summary)
        log_audit(tool="complete_task", ok=res["ok"], error_code=None if res["ok"] else res["error"]["code"], auth_context=ctx)
        return res
    except Exception as e:
        return _err("complete_task", ctx, "UNAVAILABLE", str(e))


def request_approval_handler(
    ctx: AuthContext,
    task_id: str,
    action: str,
    justification: str,
    target: Optional[str] = None
) -> Dict[str, Any]:
    """Request human-in-the-loop approval. Role rule: only remediator may request approval."""
    if ctx.role != "remediator":
        return _err("request_approval", ctx, "FORBIDDEN", "Only remediator role may request approval")
    if not task_id or not action or not justification:
        return _err("request_approval", ctx, "INVALID", "task_id, action, and justification required")

    from server.app.queries import approval as appr_queries
    try:
        res = appr_queries.request_approval(
            graph_name=ctx.graph_name,
            task_id=task_id,
            action=action,
            justification=justification,
            requested_by=ctx.agent_id,
            target=target
        )
        log_audit(tool="request_approval", ok=True, auth_context=ctx)
        return {"ok": True, **res}
    except LookupError as le:
        return _err("request_approval", ctx, "NOT_FOUND", str(le))
    except Exception as e:
        return _err("request_approval", ctx, "UNAVAILABLE", str(e))


def check_approval_handler(ctx: AuthContext, approval_id: str) -> Dict[str, Any]:
    """Check approval status by approval_id."""
    if not approval_id:
        return _err("check_approval", ctx, "INVALID", "approval_id required")

    from server.app.queries import approval as appr_queries
    try:
        appr = appr_queries.get_approval(ctx.graph_name, approval_id)
        if not appr:
            return _err("check_approval", ctx, "NOT_FOUND", f"Approval {approval_id} not found")
        log_audit(tool="check_approval", ok=True, auth_context=ctx)
        return {"ok": True, "approval": appr}
    except Exception as e:
        return _err("check_approval", ctx, "UNAVAILABLE", str(e))



def add_hypothesis_handler(
    ctx: AuthContext,
    incident_id: str,
    statement: str,
    confidence: float = 0.5,
) -> Dict[str, Any]:
    if not incident_id or not statement:
        return _err("add_hypothesis", ctx, "INVALID", "incident_id and statement required")
    try:
        res = queries.add_hypothesis(ctx.graph_name, incident_id, statement, ctx.agent_id, confidence)
        log_audit(tool="add_hypothesis", ok=True, auth_context=ctx)
        return {"ok": True, **res}
    except Exception as e:
        return _err("add_hypothesis", ctx, "UNAVAILABLE", str(e))


def attach_evidence_handler(
    ctx: AuthContext,
    hypothesis_id: str,
    event_id: str,
    note: str = "",
) -> Dict[str, Any]:
    if not hypothesis_id or not event_id:
        return _err("attach_evidence", ctx, "INVALID", "hypothesis_id and event_id required")
    try:
        res = queries.attach_evidence(ctx.graph_name, hypothesis_id, event_id, ctx.agent_id, note)
        log_audit(tool="attach_evidence", ok=True, auth_context=ctx)
        return {"ok": True, **res}
    except Exception as e:
        return _err("attach_evidence", ctx, "UNAVAILABLE", str(e))


def create_handoff_handler(
    ctx: AuthContext,
    to_agent: str,
    context_summary: str,
    task_id: Optional[str] = None,
    incident_id: Optional[str] = None,
) -> Dict[str, Any]:
    if not to_agent or not context_summary:
        return _err("create_handoff", ctx, "INVALID", "to_agent and context_summary required")
    try:
        res = queries.create_handoff(ctx.graph_name, ctx.agent_id, to_agent, task_id, context_summary, incident_id)
        log_audit(tool="create_handoff", ok=True, auth_context=ctx)
        return {"ok": True, **res}
    except Exception as e:
        return _err("create_handoff", ctx, "UNAVAILABLE", str(e))


def accept_handoff_handler(ctx: AuthContext, handoff_id: str) -> Dict[str, Any]:
    if not handoff_id:
        return _err("accept_handoff", ctx, "INVALID", "handoff_id required")
    try:
        res = queries.accept_handoff(ctx.graph_name, handoff_id, ctx.agent_id)
        log_audit(tool="accept_handoff", ok=res["ok"], error_code=None if res["ok"] else res["error"]["code"], auth_context=ctx)
        return res
    except Exception as e:
        return _err("accept_handoff", ctx, "UNAVAILABLE", str(e))
