"""
Procedural memory tool handlers for agents:
- find_procedure_handler
- record_outcome_handler
- get_procedure_handler
"""
from typing import Any, Dict, List, Optional
from server.app.auth import AuthContext, log_audit
from server.app.queries import procedural as queries


def _err(tool: str, ctx: AuthContext, code: str, msg: str) -> Dict[str, Any]:
    log_audit(tool=tool, ok=False, error_code=code, auth_context=ctx)
    return {"ok": False, "error": {"code": code, "message": msg}}


def find_procedure_handler(
    ctx: AuthContext,
    situation: str,
    limit: int = 10
) -> Dict[str, Any]:
    """Find runbooks matching situation, ranked by smoothed success rate."""
    if not situation:
        return _err("find_procedure", ctx, "INVALID", "situation required")
    try:
        results = queries.find_procedure(
            graph_name=ctx.graph_name,
            situation=situation,
            limit=limit
        )
        log_audit(tool="find_procedure", ok=True, auth_context=ctx)
        return {"ok": True, "procedures": results}
    except Exception as e:
        return _err("find_procedure", ctx, "UNAVAILABLE", str(e))


def record_outcome_handler(
    ctx: AuthContext,
    procedure_id: str,
    incident_id: str,
    success: bool,
    note: str = "",
    failed_step: Optional[int] = None,
    violated_assumption: Optional[str] = None,
    new_precondition: Optional[str] = None
) -> Dict[str, Any]:
    """Record an outcome. Forks a new procedure version on failure."""
    if not procedure_id or not incident_id:
        return _err("record_outcome", ctx, "INVALID", "procedure_id and incident_id required")
    try:
        res = queries.record_outcome(
            graph_name=ctx.graph_name,
            procedure_id=procedure_id,
            incident_id=incident_id,
            success=success,
            note=note,
            failed_step=failed_step,
            violated_assumption=violated_assumption,
            new_precondition=new_precondition
        )
        log_audit(tool="record_outcome", ok=True, auth_context=ctx)
        return {"ok": True, **res}
    except LookupError as e:
        return _err("record_outcome", ctx, "NOT_FOUND", str(e))
    except Exception as e:
        return _err("record_outcome", ctx, "UNAVAILABLE", str(e))


def get_procedure_handler(
    ctx: AuthContext,
    procedure_id: str,
    include_history: bool = False
) -> Dict[str, Any]:
    """Get full procedure details and step list."""
    if not procedure_id:
        return _err("get_procedure", ctx, "INVALID", "procedure_id required")
    try:
        proc = queries.get_procedure(
            graph_name=ctx.graph_name,
            procedure_id=procedure_id,
            include_history=include_history
        )
        log_audit(tool="get_procedure", ok=True, auth_context=ctx)
        return {"ok": True, **proc}
    except LookupError as e:
        return _err("get_procedure", ctx, "NOT_FOUND", str(e))
    except Exception as e:
        return _err("get_procedure", ctx, "UNAVAILABLE", str(e))
