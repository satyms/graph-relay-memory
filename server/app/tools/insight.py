"""
Graph Insight Tool Handlers:
- blast_radius_handler
- rank_critical_services_handler
- explain_handler
"""
from typing import Any, Dict, Optional
from server.app.auth import AuthContext, log_audit
from server.app.queries import insight as queries


def _err(tool: str, ctx: AuthContext, code: str, msg: str) -> Dict[str, Any]:
    log_audit(tool=tool, ok=False, error_code=code, auth_context=ctx)
    return {"ok": False, "error": {"code": code, "message": msg}}


def blast_radius_handler(ctx: AuthContext, service: str, depth: int = 3) -> Dict[str, Any]:
    """Find upstream services impacted if a service fails."""
    if not service:
        return _err("blast_radius", ctx, "INVALID", "service required")
    try:
        impacted = queries.blast_radius(ctx.graph_name, service, depth)
        log_audit(tool="blast_radius", ok=True, auth_context=ctx)
        return {"ok": True, "service": service, "impacted_services": impacted}
    except Exception as e:
        return _err("blast_radius", ctx, "UNAVAILABLE", str(e))


def rank_critical_services_handler(ctx: AuthContext, limit: int = 5) -> Dict[str, Any]:
    """Rank services by PageRank network centrality."""
    try:
        ranked = queries.rank_critical_services(ctx.graph_name, limit)
        log_audit(tool="rank_critical_services", ok=True, auth_context=ctx)
        return {"ok": True, "critical_services": ranked}
    except Exception as e:
        return _err("rank_critical_services", ctx, "UNAVAILABLE", str(e))


def explain_handler(ctx: AuthContext, node_id: str) -> Dict[str, Any]:
    """Explain why the system holds a belief or task state."""
    if not node_id:
        return _err("explain", ctx, "INVALID", "node_id required")
    try:
        res = queries.explain(ctx.graph_name, node_id)
        log_audit(tool="explain", ok=True, auth_context=ctx)
        return {"ok": True, **res}
    except Exception as e:
        return _err("explain", ctx, "UNAVAILABLE", str(e))
