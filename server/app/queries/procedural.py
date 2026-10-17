"""
Named Cypher queries for procedural memory:
- find_procedure: searches tenant graph first, then shared_runbooks with smoothed ranking
- record_outcome: increments counters, links Outcome, forks v+1 on failure with new precondition
- get_procedure: retrieves procedure, ordered steps, and version lineage
- seed_procedures: seeds initial runbooks into a graph
"""
import json
import time
import uuid
from typing import Any, Dict, List, Optional

from server.app.graph import execute_query, execute_ro_query


def init_procedure_schema(graph_name: str) -> None:
    """Ensure indexes exist for procedures and steps."""
    for stmt in [
        "CREATE INDEX FOR (p:Procedure) ON (p.id)",
        "CREATE INDEX FOR (p:Procedure) ON (p.name)",
        "CREATE INDEX FOR (p:Procedure) ON (p.status)",
    ]:
        try:
            execute_query(graph_name, stmt)
        except Exception:
            pass


def seed_procedure(
    graph_name: str,
    name: str,
    trigger: str,
    steps: List[str],
    success_count: int = 0,
    fail_count: int = 0,
    preconditions: Optional[List[str]] = None,
    version: int = 1,
    status: str = "active"
) -> str:
    """Helper to seed a procedure node and its ordered Step nodes."""
    pid = f"proc_{name.replace(' ', '_').lower()}_v{version}"
    precond_json = json.dumps(preconditions or [])
    
    cypher_proc = """
    MERGE (p:Procedure {id: $pid})
    SET p.name = $name,
        p.trigger = $trigger,
        p.version = $version,
        p.status = $status,
        p.success_count = $sc,
        p.fail_count = $fc,
        p.preconditions = $precond
    RETURN p.id
    """
    execute_query(graph_name, cypher_proc, {
        "pid": pid, "name": name, "trigger": trigger, "version": version,
        "status": status, "sc": success_count, "fc": fail_count,
        "precond": precond_json
    })

    # Clear old steps if any, then link new steps
    execute_query(graph_name, "MATCH (p:Procedure {id: $pid})-[r:HAS_STEP]->(s) DELETE r, s", {"pid": pid})
    for idx, step_text in enumerate(steps, start=1):
        sid = f"{pid}_step_{idx}"
        execute_query(graph_name, """
        MATCH (p:Procedure {id: $pid})
        CREATE (s:Step {id: $sid, idx: $idx, text: $text})
        CREATE (p)-[:HAS_STEP]->(s)
        """, {"pid": pid, "sid": sid, "idx": idx, "text": step_text})

    return pid


def seed_default_runbooks(graph_name: str) -> None:
    """Seed the standard hackathon demo runbooks."""
    init_procedure_schema(graph_name)
    seed_procedure(
        graph_name=graph_name,
        name="restart-redis",
        trigger="cache latency redis memory spike",
        steps=[
            "Verify redis memory usage via cli",
            "Flush temporary keys if non-persistent",
            "Execute graceful restart of redis-cache container"
        ],
        success_count=2,
        fail_count=0,
        preconditions=[]
    )
    seed_procedure(
        graph_name=graph_name,
        name="rollback-deploy",
        trigger="recent deploy latency after deploy 500 errors",
        steps=[
            "Identify last successful deploy commit hash",
            "Trigger deployment pipeline rollback",
            "Verify health endpoints on checkout-api and payments-svc"
        ],
        success_count=1,
        fail_count=1,
        preconditions=[]
    )
    seed_procedure(
        graph_name=graph_name,
        name="scale-db-pool",
        trigger="connection exhaustion postgres connection timeout",
        steps=[
            "Inspect postgres-primary active connection count",
            "Increase max_connections parameter in pool config by 25%",
            "Monitor connection wait time"
        ],
        success_count=0,
        fail_count=0,
        preconditions=[]
    )


def find_procedure(
    graph_name: str,
    situation: str,
    limit: int = 10,
    shared_graph: str = "shared_runbooks"
) -> List[Dict[str, Any]]:
    """
    Find procedures matching situation trigger words, ranked by smoothed score:
    score = (success_count + 1) / (success_count + fail_count + 2)
    Searches tenant graph first, then shared_runbooks for any not already found.
    """
    words = [w.lower().strip() for w in situation.split() if len(w.strip()) > 2]
    safe_limit = max(1, min(limit or 10, 50))

    def _query_graph(g_name: str, source_tag: str) -> List[Dict[str, Any]]:
        # Fetch active procedures and steps
        cypher = """
        MATCH (p:Procedure {status: 'active'})
        OPTIONAL MATCH (p)-[:HAS_STEP]->(s:Step)
        RETURN p.id, p.name, p.trigger, p.version, p.preconditions,
               p.success_count, p.fail_count, s.idx, s.text
        ORDER BY p.id, s.idx ASC
        """
        res = execute_ro_query(g_name, cypher)
        if not (res and res.result_set):
            return []

        # Group steps by procedure
        procs_map: Dict[str, Dict[str, Any]] = {}
        for row in res.result_set:
            pid, name, trigger, ver, precond_str, sc, fc, s_idx, s_text = row
            if pid not in procs_map:
                try:
                    preconds = json.loads(precond_str) if precond_str else []
                except Exception:
                    preconds = [precond_str] if precond_str else []
                
                sc_int = int(sc or 0)
                fc_int = int(fc or 0)
                # Smoothed Laplace score: (success + 1) / (success + fail + 2)
                score = (sc_int + 1.0) / (sc_int + fc_int + 2.0)
                procs_map[pid] = {
                    "procedure_id": pid,
                    "name": name,
                    "trigger": trigger or "",
                    "version": int(ver or 1),
                    "preconditions": preconds,
                    "score": round(score, 4),
                    "success_count": sc_int,
                    "fail_count": fc_int,
                    "source": source_tag,
                    "steps": []
                }
            if s_text is not None:
                procs_map[pid]["steps"].append(s_text)

        results = []
        for p in procs_map.values():
            trig_lower = p["trigger"].lower()
            name_lower = p["name"].lower()
            # Match if any token is contained in trigger or name
            match = any(w in trig_lower or w in name_lower for w in words) if words else True
            if match:
                results.append(p)
        return results

    tenant_procs = _query_graph(graph_name, "tenant")
    seen_names = {p["name"] for p in tenant_procs}

    shared_procs = []
    if graph_name != shared_graph:
        all_shared = _query_graph(shared_graph, "shared")
        shared_procs = [p for p in all_shared if p["name"] not in seen_names]

    combined = tenant_procs + shared_procs
    combined.sort(key=lambda x: x["score"], reverse=True)
    return combined[:safe_limit]


def record_outcome(
    graph_name: str,
    procedure_id: str,
    incident_id: str,
    success: bool,
    note: str = "",
    failed_step: Optional[int] = None,
    violated_assumption: Optional[str] = None,
    new_precondition: Optional[str] = None
) -> Dict[str, Any]:
    """
    Record an execution outcome for a procedure.
    If success=False:
      1. Increments fail_count.
      2. Creates Outcome node and links to Incident.
      3. Retires the old version (status = 'retired').
      4. Forks a new Procedure version (version + 1, status = 'active').
      5. Links (new)-[:PREVIOUS_VERSION]->(old).
      6. Inherits steps and adds new_precondition to preconditions.
    """
    now = int(time.time() * 1000)
    outcome_id = f"out_{uuid.uuid4().hex[:12]}"

    # Fetch existing procedure details and steps
    cypher_get = """
    MATCH (p:Procedure {id: $pid})
    OPTIONAL MATCH (p)-[:HAS_STEP]->(s:Step)
    RETURN p.id, p.name, p.trigger, p.version, p.status, p.success_count,
           p.fail_count, p.preconditions, s.idx, s.text
    ORDER BY s.idx ASC
    """
    res = execute_query(graph_name, cypher_get, {"pid": procedure_id})
    if not (res and res.result_set):
        raise LookupError(f"Procedure {procedure_id} not found")

    first_row = res.result_set[0]
    p_id, p_name, p_trigger, p_version, p_status, sc, fc, precond_raw, s_idx, s_text = first_row
    sc = int(sc or 0)
    fc = int(fc or 0)
    p_ver = int(p_version or 1)
    
    try:
        preconditions = json.loads(precond_raw) if precond_raw else []
    except Exception:
        preconditions = []

    steps = [row[9] for row in res.result_set if row[9] is not None]

    # Create Outcome node and link to Incident and Procedure
    cypher_outcome = """
    MATCH (p:Procedure {id: $pid})
    CREATE (o:Outcome {
        id: $oid,
        ts: $now,
        success: $success,
        note: $note,
        failed_step: $failed_step,
        violated_assumption: $violated_assumption
    })
    CREATE (p)-[:RESULTED_IN]->(o)
    """
    execute_query(graph_name, cypher_outcome, {
        "pid": procedure_id,
        "oid": outcome_id,
        "now": now,
        "success": bool(success),
        "note": note or "",
        "failed_step": failed_step,
        "violated_assumption": violated_assumption or ""
    })

    if incident_id:
        execute_query(graph_name, """
        MATCH (o:Outcome {id: $oid}), (i:Incident {id: $inc_id})
        CREATE (o)-[:USED_IN]->(i)
        """, {"oid": outcome_id, "inc_id": incident_id})

    new_proc_id = None

    if success:
        # Increment success_count
        execute_query(graph_name, """
        MATCH (p:Procedure {id: $pid})
        SET p.success_count = p.success_count + 1
        """, {"pid": procedure_id})
    else:
        # Increment fail_count on old procedure and retire it
        execute_query(graph_name, """
        MATCH (p:Procedure {id: $pid})
        SET p.fail_count = p.fail_count + 1,
            p.status = 'retired',
            p.violated_assumption = $violated_assumption
        """, {"pid": procedure_id, "violated_assumption": violated_assumption or ""})

        # Build v+1 preconditions
        new_preconds = list(preconditions)
        if new_precondition and new_precondition not in new_preconds:
            new_preconds.append(new_precondition)

        new_ver = p_ver + 1
        new_proc_id = f"proc_{p_name.replace(' ', '_').lower()}_v{new_ver}"
        
        # New version starts with 0 successes, 0 failures, status 'active'
        cypher_fork = """
        MATCH (old:Procedure {id: $old_id})
        CREATE (new:Procedure {
            id: $new_id,
            name: $name,
            trigger: $trigger,
            version: $new_ver,
            status: 'active',
            success_count: 0,
            fail_count: 0,
            preconditions: $preconds,
            forked_from_assumption: $violated_assumption
        })
        CREATE (new)-[:PREVIOUS_VERSION]->(old)
        RETURN new.id
        """
        execute_query(graph_name, cypher_fork, {
            "old_id": procedure_id,
            "new_id": new_proc_id,
            "name": p_name,
            "trigger": p_trigger,
            "new_ver": new_ver,
            "preconds": json.dumps(new_preconds),
            "violated_assumption": violated_assumption or ""
        })

        # Copy existing steps to new version
        for idx, step_text in enumerate(steps, start=1):
            sid = f"{new_proc_id}_step_{idx}"
            execute_query(graph_name, """
            MATCH (p:Procedure {id: $pid})
            CREATE (s:Step {id: $sid, idx: $idx, text: $text})
            CREATE (p)-[:HAS_STEP]->(s)
            """, {"pid": new_proc_id, "sid": sid, "idx": idx, "text": step_text})

    return {
        "outcome_id": outcome_id,
        "new_procedure_id": new_proc_id
    }


def get_procedure(
    graph_name: str,
    procedure_id: str,
    include_history: bool = False
) -> Dict[str, Any]:
    """Retrieve a procedure with its steps and optional version history."""
    cypher = """
    MATCH (p:Procedure {id: $pid})
    OPTIONAL MATCH (p)-[:HAS_STEP]->(s:Step)
    RETURN p.id, p.name, p.trigger, p.version, p.status,
           p.success_count, p.fail_count, p.preconditions,
           s.idx, s.text
    ORDER BY s.idx ASC
    """
    res = execute_ro_query(graph_name, cypher, {"pid": procedure_id})
    if not (res and res.result_set):
        raise LookupError(f"Procedure {procedure_id} not found")

    first = res.result_set[0]
    try:
        preconditions = json.loads(first[7]) if first[7] else []
    except Exception:
        preconditions = []

    steps = [row[9] for row in res.result_set if row[9] is not None]
    sc = int(first[5] or 0)
    fc = int(first[6] or 0)
    score = (sc + 1.0) / (sc + fc + 2.0)

    data: Dict[str, Any] = {
        "procedure_id": first[0],
        "name": first[1],
        "trigger": first[2],
        "version": int(first[3] or 1),
        "status": first[4],
        "success_count": sc,
        "fail_count": fc,
        "score": round(score, 4),
        "preconditions": preconditions,
        "steps": steps
    }

    if include_history:
        hist_cypher = """
        MATCH (current:Procedure {id: $pid})-[:PREVIOUS_VERSION*1..5]->(prev:Procedure)
        RETURN prev.id, prev.version, prev.status, prev.fail_count, prev.violated_assumption
        ORDER BY prev.version DESC
        """
        h_res = execute_ro_query(graph_name, hist_cypher, {"pid": procedure_id})
        history = [
            {"procedure_id": r[0], "version": r[1], "status": r[2], "fail_count": r[3], "violated_assumption": r[4]}
            for r in (h_res.result_set if h_res else [])
        ]
        data["history"] = history

    return data
