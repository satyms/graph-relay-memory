"""
Episodic memory tool handlers for agents.
"""
from typing import Any, Dict, List, Optional
from server.app.auth import AuthContext, log_audit
from server.app.queries import episodic as queries


def start_session_handler(ctx: AuthContext) -> Dict[str, Any]:
    """Handler for start_session tool."""
    try:
        res = queries.start_session(
            graph_name=ctx.graph_name,
            agent_id=ctx.agent_id,
            role=ctx.role
        )
        log_audit(tool="start_session", ok=True, auth_context=ctx)
        return {"ok": True, **res}
    except Exception as e:
        log_audit(tool="start_session", ok=False, error_code="UNAVAILABLE", auth_context=ctx)
        return {"ok": False, "error": {"code": "UNAVAILABLE", "message": str(e)}}


def log_event_handler(
    ctx: AuthContext,
    session_id: str,
    event_type: str,
    summary: str,
    payload: Optional[Dict[str, Any]] = None,
    entities: Optional[List[str]] = None,
    idempotency_key: Optional[str] = None
) -> Dict[str, Any]:
    """Handler for log_event tool."""
    if not session_id or not summary:
        log_audit(tool="log_event", ok=False, error_code="INVALID", auth_context=ctx)
        return {"ok": False, "error": {"code": "INVALID", "message": "session_id and summary required"}}

    valid_types = {"observation", "action", "decision", "message"}
    if event_type not in valid_types:
        log_audit(tool="log_event", ok=False, error_code="INVALID", auth_context=ctx)
        return {"ok": False, "error": {"code": "INVALID", "message": f"type must be one of {valid_types}"}}

    try:
        res = queries.log_event(
            graph_name=ctx.graph_name,
            session_id=session_id,
            event_type=event_type,
            summary=summary,
            payload=payload,
            entities=entities,
            idempotency_key=idempotency_key
        )
        log_audit(tool="log_event", ok=True, auth_context=ctx)
        return {"ok": True, **res}
    except LookupError as e:
        log_audit(tool="log_event", ok=False, error_code="NOT_FOUND", auth_context=ctx)
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": str(e)}}
    except Exception as e:
        log_audit(tool="log_event", ok=False, error_code="UNAVAILABLE", auth_context=ctx)
        return {"ok": False, "error": {"code": "UNAVAILABLE", "message": str(e)}}


def recall_episodes_handler(
    ctx: AuthContext,
    query: Optional[str] = None,
    entity: Optional[str] = None,
    since: Optional[int] = None,
    until: Optional[int] = None,
    session_id: Optional[str] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """Handler for recall_episodes tool."""
    try:
        events = queries.recall_episodes(
            graph_name=ctx.graph_name,
            query=query,
            entity=entity,
            since=since,
            until=until,
            session_id=session_id,
            limit=limit
        )
        log_audit(tool="recall_episodes", ok=True, auth_context=ctx)
        return {"ok": True, "events": events}
    except Exception as e:
        log_audit(tool="recall_episodes", ok=False, error_code="UNAVAILABLE", auth_context=ctx)
        return {"ok": False, "error": {"code": "UNAVAILABLE", "message": str(e)}}


def end_session_handler(ctx: AuthContext, session_id: str, summary: str) -> Dict[str, Any]:
    """Handler for end_session tool."""
    if not session_id or not summary:
        log_audit(tool="end_session", ok=False, error_code="INVALID", auth_context=ctx)
        return {"ok": False, "error": {"code": "INVALID", "message": "session_id and summary required"}}

    try:
        ok = queries.end_session(graph_name=ctx.graph_name, session_id=session_id, summary=summary)
        log_audit(tool="end_session", ok=ok, auth_context=ctx)
        if ok:
            return {"ok": True}
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": "session not found"}}
    except Exception as e:
        log_audit(tool="end_session", ok=False, error_code="UNAVAILABLE", auth_context=ctx)
        return {"ok": False, "error": {"code": "UNAVAILABLE", "message": str(e)}}
