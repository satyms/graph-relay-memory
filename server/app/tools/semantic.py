"""
Semantic memory tool handlers for agents.
"""
from typing import Any, Dict, Optional
from server.app.auth import AuthContext, log_audit
from server.app.queries import semantic as queries


def upsert_fact_handler(
    ctx: AuthContext,
    entity: str,
    predicate: str,
    value: Any,
    confidence: float = 0.8,
    source_event_id: Optional[str] = None,
    visibility: str = "team",
    idempotency_key: Optional[str] = None
) -> Dict[str, Any]:
    """Handler for upsert_fact tool."""
    if not entity or not predicate or value is None:
        log_audit(tool="upsert_fact", ok=False, error_code="INVALID", auth_context=ctx)
        return {"ok": False, "error": {"code": "INVALID", "message": "entity, predicate, and value required"}}

    try:
        res = queries.upsert_fact(
            graph_name=ctx.graph_name,
            entity_name=entity,
            predicate=predicate,
            value=str(value),
            agent_id=ctx.agent_id,
            confidence=confidence,
            source_event_id=source_event_id,
            visibility=visibility,
            idempotency_key=idempotency_key
        )
        log_audit(tool="upsert_fact", ok=True, auth_context=ctx)
        return {"ok": True, **res}
    except Exception as e:
        log_audit(tool="upsert_fact", ok=False, error_code="UNAVAILABLE", auth_context=ctx)
        return {"ok": False, "error": {"code": "UNAVAILABLE", "message": str(e)}}


def query_facts_handler(
    ctx: AuthContext,
    entity: Optional[str] = None,
    predicate: Optional[str] = None,
    as_of: Optional[int] = None,
    include_stale: bool = False,
    limit: int = 10
) -> Dict[str, Any]:
    """Handler for query_facts tool."""
    try:
        facts = queries.query_facts(
            graph_name=ctx.graph_name,
            entity=entity,
            predicate=predicate,
            as_of=as_of,
            include_stale=include_stale,
            limit=limit
        )
        log_audit(tool="query_facts", ok=True, auth_context=ctx)
        return {"ok": True, "facts": facts}
    except Exception as e:
        log_audit(tool="query_facts", ok=False, error_code="UNAVAILABLE", auth_context=ctx)
        return {"ok": False, "error": {"code": "UNAVAILABLE", "message": str(e)}}


def fact_history_handler(ctx: AuthContext, entity: str, predicate: str) -> Dict[str, Any]:
    """Handler for fact_history tool."""
    if not entity or not predicate:
        log_audit(tool="fact_history", ok=False, error_code="INVALID", auth_context=ctx)
        return {"ok": False, "error": {"code": "INVALID", "message": "entity and predicate required"}}

    try:
        history = queries.fact_history(graph_name=ctx.graph_name, entity=entity, predicate=predicate)
        log_audit(tool="fact_history", ok=True, auth_context=ctx)
        return {"ok": True, "history": history}
    except Exception as e:
        log_audit(tool="fact_history", ok=False, error_code="UNAVAILABLE", auth_context=ctx)
        return {"ok": False, "error": {"code": "UNAVAILABLE", "message": str(e)}}


def forget_fact_handler(ctx: AuthContext, fact_id: str, reason: str) -> Dict[str, Any]:
    """Handler for forget_fact tool."""
    if not fact_id or not reason:
        log_audit(tool="forget_fact", ok=False, error_code="INVALID", auth_context=ctx)
        return {"ok": False, "error": {"code": "INVALID", "message": "fact_id and reason required"}}

    try:
        ok = queries.forget_fact(graph_name=ctx.graph_name, fact_id=fact_id, reason=reason)
        log_audit(tool="forget_fact", ok=ok, auth_context=ctx)
        if ok:
            return {"ok": True}
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": f"fact {fact_id} not found"}}
    except Exception as e:
        log_audit(tool="forget_fact", ok=False, error_code="UNAVAILABLE", auth_context=ctx)
        return {"ok": False, "error": {"code": "UNAVAILABLE", "message": str(e)}}
