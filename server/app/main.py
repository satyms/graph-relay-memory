"""
FastAPI Server and Admin API for Relay Memory.
Provides:
- Graph snapshot endpoint (/admin/graph/{tenant_id})
- Server-Sent Events (SSE) feed (/admin/stream)
- Interactive Scenario & Proof execution endpoints
- Static file serving for the Relay Web Dashboard
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from server.app.auth import verify_admin_token, AuthContext
from server.app.graph import execute_ro_query, execute_query
from server.app.tenancy import get_tenant_graph_name
from server.app.queries.semantic import query_facts
from server.app.queries.coordination import list_open_work, get_agent_tasks, claim_task
from server.app.tools.episodic import log_event_handler
from server.app.reaper import run_reaper
from agents.scenario import run_full_incident_scenario

log = logging.getLogger("server")
logging.basicConfig(level=logging.INFO)

# Global in-memory SSE event bus
_event_subscribers: List[asyncio.Queue] = []


def broadcast_event(event_type: str, data: Dict[str, Any]):
    """Broadcast an SSE event to all connected dashboard clients."""
    payload = json.dumps({"type": event_type, "data": data})
    for q in list(_event_subscribers):
        try:
            q.put_nowait(payload)
        except Exception:
            pass


async def _reaper_background_loop():
    """Background lease reaper sweeping expired task leases."""
    while True:
        try:
            from server.app.reaper import run_reaper_detailed
            reaped_map = run_reaper_detailed(["tenant_acme"])
            for gn, tasks in reaped_map.items():
                for t in tasks:
                    broadcast_event("lease_expired", {"graph_name": gn, "task_id": t["task_id"], "title": t.get("title")})
                    broadcast_event("task_reopened", {"graph_name": gn, "task_id": t["task_id"], "version": t.get("version")})
        except Exception:
            pass
        await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background task lease reaper for default tenant
    reaper_task = asyncio.create_task(_reaper_background_loop())
    yield
    reaper_task.cancel()


app = FastAPI(title="Relay Memory Engine", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "relay-memory", "version": "1.0.0"}


def _determine_memory_type(labels: List[str]) -> str:
    lbl_set = set(labels)
    if "Session" in lbl_set or "Event" in lbl_set:
        return "episodic"
    if "Fact" in lbl_set:
        return "semantic"
    if "Procedure" in lbl_set or "Step" in lbl_set or "Outcome" in lbl_set:
        return "procedural"
    if any(l in lbl_set for l in ("Incident", "Task", "Hypothesis", "Handoff", "Approval")):
        return "coordination"
    if "Entity" in lbl_set:
        return "topology"
    return "other"


@app.get("/admin/graph/{tenant_id}")
def get_graph_snapshot(tenant_id: str, as_of: Optional[int] = Query(None)) -> Dict[str, Any]:
    """
    Returns graph nodes and edges categorized by memory type for visualization.
    If as_of epoch ms is provided, filters facts to those valid at that time,
    and filters events, tasks, and handoffs created at or before as_of.
    """
    try:
        graph_name = get_tenant_graph_name(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Fetch nodes
    cypher_nodes = "MATCH (n) RETURN id(n), labels(n), properties(n)"
    res_nodes = execute_ro_query(graph_name, cypher_nodes)

    nodes = []
    id_map = {}
    valid_internal_ids = set()

    if res_nodes and res_nodes.result_set:
        for row in res_nodes.result_set:
            internal_id, labels, props = row
            labels_list = list(labels) if labels else ["Node"]
            mem_type = _determine_memory_type(labels_list)
            
            # Apply as_of filtering if specified
            if as_of is not None:
                # Fact filtering: valid_from <= as_of and (valid_to is null or valid_to > as_of)
                if "Fact" in labels_list:
                    vf = props.get("valid_from")
                    vt = props.get("valid_to")
                    if vf is not None and vf > as_of:
                        continue
                    if vt is not None and vt <= as_of:
                        continue
                # Event filtering: ts <= as_of
                elif "Event" in labels_list:
                    ts = props.get("ts")
                    if ts is not None and ts > as_of:
                        continue
                # Task filtering: created_at <= as_of
                elif "Task" in labels_list:
                    created_at = props.get("created_at")
                    if created_at is not None and created_at > as_of:
                        continue
                # Handoff filtering: created_at <= as_of
                elif "Handoff" in labels_list:
                    created_at = props.get("created_at")
                    if created_at is not None and created_at > as_of:
                        continue
                # Session filtering: started_at <= as_of
                elif "Session" in labels_list:
                    started_at = props.get("started_at")
                    if started_at is not None and started_at > as_of:
                        continue
                # Incident filtering: created_at <= as_of
                elif "Incident" in labels_list:
                    created_at = props.get("created_at")
                    if created_at is not None and created_at > as_of:
                        continue

            valid_internal_ids.add(internal_id)

            # Choose display label
            name = (
                props.get("name")
                or props.get("title")
                or props.get("id")
                or props.get("summary")
                or labels_list[0]
            )
            node_id = str(props.get("id") or internal_id)
            id_map[internal_id] = node_id

            # Determine if fact is currently superseded in this snapshot
            is_superseded = False
            if "Fact" in labels_list and props.get("valid_to") is not None:
                is_superseded = True

            nodes.append({
                "id": node_id,
                "internal_id": internal_id,
                "label": name,
                "type": labels_list[0],
                "labels": labels_list,
                "memory_type": mem_type,
                "properties": props,
                "is_superseded": is_superseded
            })

    # Fetch edges
    cypher_edges = "MATCH (a)-[r]->(b) RETURN id(a), id(b), type(r), properties(r)"
    res_edges = execute_ro_query(graph_name, cypher_edges)

    edges = []
    if res_edges and res_edges.result_set:
        for row in res_edges.result_set:
            src_internal, tgt_internal, rel_type, rel_props = row
            # Only include edge if both endpoints are in the filtered node set
            if as_of is not None:
                if src_internal not in valid_internal_ids or tgt_internal not in valid_internal_ids:
                    continue
            src_id = id_map.get(src_internal, str(src_internal))
            tgt_id = id_map.get(tgt_internal, str(tgt_internal))
            edges.append({
                "source": src_id,
                "target": tgt_id,
                "type": rel_type,
                "properties": rel_props or {}
            })

    return {
        "tenant_id": tenant_id,
        "graph_name": graph_name,
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges)
        }
    }


@app.get("/admin/timeline/{tenant_id}")
def get_timeline(tenant_id: str, authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """
    Returns min/max timestamps and key change markers for a tenant's timeline.
    Protected by admin token check.
    """
    if not verify_admin_token(authorization):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Invalid admin token"})

    try:
        graph_name = get_tenant_graph_name(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail={"code": "INVALID", "message": str(e)})

    from server.app.queries.timeline import get_timeline_markers
    res = get_timeline_markers(graph_name)
    return {
        "tenant_id": tenant_id,
        "graph_name": graph_name,
        **res
    }


@app.get("/admin/explain/{tenant_id}/{node_id}")
def explain_node(tenant_id: str, node_id: str, authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """
    Returns the provenance chain and deterministic 'because' explanation for node_id.
    Validates admin token and strictly enforces tenant boundary.
    Returns 404 NOT_FOUND if node does not exist or belongs to another tenant.
    """
    if not verify_admin_token(authorization):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Invalid admin token"})

    try:
        graph_name = get_tenant_graph_name(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail={"code": "INVALID", "message": str(e)})

    from server.app.queries.insight import get_explain_provenance
    res = get_explain_provenance(graph_name, node_id)
    if not res:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"Node {node_id} not found in tenant {tenant_id}"})

    return {
        "ok": True,
        "tenant_id": tenant_id,
        **res
    }


class ApprovalDecisionRequest(BaseModel):
    decision: str
    reason: str


@app.get("/admin/approvals")
def get_approvals(tenant: str = Query(...), status: Optional[str] = Query(None), authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """
    Get approvals for a tenant, optionally filtered by status.
    Protected by admin token check.
    """
    if not verify_admin_token(authorization):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Invalid admin token"})

    try:
        graph_name = get_tenant_graph_name(tenant)
    except Exception as e:
        raise HTTPException(status_code=400, detail={"code": "INVALID", "message": str(e)})

    from server.app.queries import approval as appr_queries
    approvals = appr_queries.list_approvals(graph_name, status=status)
    return {
        "ok": True,
        "tenant": tenant,
        "approvals": approvals
    }


@app.post("/admin/approvals/{approval_id}/decide")
def decide_approval_endpoint(
    approval_id: str,
    req: ApprovalDecisionRequest,
    tenant: str = Query(...),
    authorization: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """
    Record an admin human decision ('approved' or 'rejected') on a pending Approval gate.
    Protected by admin token check. The admin identity is recorded, never an agent key.
    Broadcasts SSE approval_decided event.
    """
    if not verify_admin_token(authorization):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Invalid admin token"})

    try:
        graph_name = get_tenant_graph_name(tenant)
    except Exception as e:
        raise HTTPException(status_code=400, detail={"code": "INVALID", "message": str(e)})

    from server.app.queries import approval as appr_queries
    try:
        res = appr_queries.decide_approval(
            graph_name=graph_name,
            approval_id=approval_id,
            decision=req.decision,
            reason=req.reason,
            decided_by="admin"
        )
        if not res.get("ok"):
            raise HTTPException(status_code=400, detail={"code": "CONFLICT", "message": res.get("error")})

        broadcast_event("approval_decided", {
            "tenant": tenant,
            "approval_id": approval_id,
            "status": req.decision,
            "reason": req.reason,
            "decided_by": "admin"
        })

        return res
    except LookupError as le:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(le)})
    except ValueError as ve:
        raise HTTPException(status_code=400, detail={"code": "INVALID", "message": str(ve)})


@app.get("/admin/compare/latest")
def get_latest_comparison(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """
    Returns the latest Relay vs. Baseline Flat Memory comparison benchmark results.
    Protected by admin token check.
    """
    if not verify_admin_token(authorization):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Invalid admin token"})

    from scripts.compare_baseline import RESULTS_FILE, run_comparison
    if RESULTS_FILE.exists():
        try:
            with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # If no results cached, run comparison live
    return run_comparison()


@app.get("/admin/stream")
async def stream_events(request: Request):
    """Server-Sent Events (SSE) stream for live real-time graph and agent updates."""
    queue = asyncio.Queue()
    _event_subscribers.append(queue)

    async def event_generator():
        try:
            # Send initial connected event
            yield f"event: ping\ndata: {json.dumps({'status': 'connected'})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: update\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat
                    yield f"event: ping\ndata: {json.dumps({'time': int(asyncio.get_event_loop().time())})}\n\n"
        finally:
            if queue in _event_subscribers:
                _event_subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/admin/run-scenario")
async def trigger_scenario(tenant_id: str = "acme"):
    """Trigger the complete 4-agent incident response scenario with learning verification."""
    try:
        broadcast_event("scenario_started", {"tenant_id": tenant_id})
        res = run_full_incident_scenario(tenant_id=tenant_id)
        broadcast_event("scenario_completed", {"tenant_id": tenant_id, "result": res})
        return res
    except Exception as e:
        log.exception("Scenario execution failed: %s", e)
        broadcast_event("scenario_failed", {"tenant_id": tenant_id, "error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/run-isolation-test")
async def trigger_isolation_test():
    """Run the 7 cross-tenant isolation proofs and return results."""
    from scripts.isolation_test import run_isolation_tests
    # Run in thread pool to avoid blocking async event loop
    loop = asyncio.get_event_loop()
    passed = await loop.run_in_executor(None, run_isolation_tests)
    broadcast_event("isolation_test_finished", {"passed": passed})
    return {"ok": passed, "message": "All 7 isolation proofs passed" if passed else "Isolation test failed"}


@app.post("/admin/run-load-test")
async def trigger_load_test(agents: int = Query(20), tasks: int = Query(10)):
    """Run the concurrency CAS load test and return metrics."""
    from scripts.load_test import run_load_test
    loop = asyncio.get_event_loop()
    passed = await loop.run_in_executor(None, run_load_test, agents, tasks)
    broadcast_event("load_test_finished", {"passed": passed, "agents": agents, "tasks": tasks})
    return {"ok": passed, "agents": agents, "tasks": tasks}


class KillAgentRequest(BaseModel):
    tenant: str
    agent_role: str


class ReclaimTaskRequest(BaseModel):
    tenant: str
    agent_role: str
    task_id: str


@app.post("/admin/chaos/kill-agent")
async def kill_agent(req: KillAgentRequest, authorization: Optional[str] = Header(None)):
    """
    Simulate agent failure mid-task (Chaos Button).
    Stops running loops for that agent without releasing claims so the lease must expire naturally.
    Returns which task(s) the agent held and broadcasts SSE events.
    """
    if not verify_admin_token(authorization):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Invalid admin token"})

    try:
        graph_name = get_tenant_graph_name(req.tenant)
    except Exception as e:
        raise HTTPException(status_code=400, detail={"code": "INVALID", "message": str(e)})

    agent_id = f"agent_{req.agent_role}" if not req.agent_role.startswith("agent_") else req.agent_role
    held_tasks = get_agent_tasks(graph_name, agent_id)

    broadcast_event("agent_killed", {
        "tenant": req.tenant,
        "agent_id": agent_id,
        "agent_role": req.agent_role,
        "held_tasks": held_tasks
    })

    return {
        "ok": True,
        "killed_agent": agent_id,
        "agent_role": req.agent_role,
        "tenant": req.tenant,
        "held_tasks": held_tasks
    }


@app.post("/admin/chaos/reclaim-task")
async def reclaim_task(req: ReclaimTaskRequest, authorization: Optional[str] = Header(None)):
    """
    Allows a surviving or restarted agent to pick up a reopened task,
    log a recovery event in graph memory, and broadcast task_reclaimed.
    """
    if not verify_admin_token(authorization):
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Invalid admin token"})

    try:
        graph_name = get_tenant_graph_name(req.tenant)
    except Exception as e:
        raise HTTPException(status_code=400, detail={"code": "INVALID", "message": str(e)})

    agent_id = f"agent_{req.agent_role}" if not req.agent_role.startswith("agent_") else req.agent_role

    claim_res = claim_task(graph_name, req.task_id, agent_id)
    if not claim_res.get("ok"):
        return {"ok": False, "error": claim_res.get("error")}

    # Log recovery event to agent's episodic session
    ctx = AuthContext(
        tenant_id=req.tenant,
        agent_id=agent_id,
        role=req.agent_role,
        graph_name=graph_name,
        key_hash=f"hash_{agent_id}"
    )
    try:
        log_event_handler(
            ctx,
            event_type="action",
            summary=f"Surviving agent {agent_id} recovered and reclaimed task {req.task_id} after lease expiration.",
            entities=[req.task_id]
        )
    except Exception as ex:
        log.warning("Could not log recovery event: %s", ex)

    broadcast_event("task_reclaimed", {
        "tenant": req.tenant,
        "task_id": req.task_id,
        "claimed_by": agent_id,
        "version": claim_res.get("version"),
        "lease_expires_at": claim_res.get("lease_expires_at")
    })

    return {
        "ok": True,
        "task_id": req.task_id,
        "claimed_by": agent_id,
        "version": claim_res.get("version")
    }



# Mount dashboard static directory
dashboard_dir = Path(__file__).resolve().parent.parent.parent / "dashboard"
if dashboard_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")


@app.get("/")
def root():
    return HTMLResponse("""
    <html>
      <head><meta http-equiv="refresh" content="0; url=/dashboard/" /></head>
      <body>Redirecting to <a href="/dashboard/">Relay Dashboard</a>...</body>
    </html>
    """)
