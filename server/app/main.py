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

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from server.app.graph import execute_ro_query, execute_query
from server.app.tenancy import get_tenant_graph_name
from server.app.queries.semantic import query_facts
from server.app.queries.coordination import list_open_work
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
            run_reaper(["tenant_acme"])
        except Exception:
            pass
        await asyncio.sleep(5)


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
    if any(l in lbl_set for l in ("Incident", "Task", "Hypothesis", "Handoff")):
        return "coordination"
    if "Entity" in lbl_set:
        return "topology"
    return "other"


@app.get("/admin/graph/{tenant_id}")
def get_graph_snapshot(tenant_id: str) -> Dict[str, Any]:
    """
    Returns graph nodes and edges categorized by memory type for visualization.
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
    if res_nodes and res_nodes.result_set:
        for row in res_nodes.result_set:
            internal_id, labels, props = row
            labels_list = list(labels) if labels else ["Node"]
            mem_type = _determine_memory_type(labels_list)
            
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

            nodes.append({
                "id": node_id,
                "internal_id": internal_id,
                "label": name,
                "type": labels_list[0],
                "labels": labels_list,
                "memory_type": mem_type,
                "properties": props
            })

    # Fetch edges
    cypher_edges = "MATCH (a)-[r]->(b) RETURN id(a), id(b), type(r), properties(r)"
    res_edges = execute_ro_query(graph_name, cypher_edges)

    edges = []
    if res_edges and res_edges.result_set:
        for row in res_edges.result_set:
            src_internal, tgt_internal, rel_type, rel_props = row
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
