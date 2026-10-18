"""
Named Cypher queries for timeline extraction and temporal markers.
Provides:
- get_timeline_markers: collects key historical change markers (fact supersessions,
  handoffs, task claims, procedure forks) and min/max timestamps.
"""
import time
from typing import Any, Dict, List, Optional
from server.app.graph import execute_ro_query


def get_timeline_markers(graph_name: str) -> Dict[str, Any]:
    """
    Extract key change markers across facts, handoffs, tasks, and procedures.
    Returns:
    {
      "min_ts": int,
      "max_ts": int,
      "markers": [
         {"ts": int, "type": str, "label": str, "node_id": str, "details": dict}
      ]
    }
    """
    markers: List[Dict[str, Any]] = []

    # 1. Fact creation and supersessions
    cypher_facts = """
    MATCH (f:Fact)
    OPTIONAL MATCH (f)-[:SUPERSEDES]->(old:Fact)
    RETURN f.id, f.predicate, f.value, f.valid_from, f.valid_to, old.id, old.value
    """
    res_facts = execute_ro_query(graph_name, cypher_facts)
    if res_facts and res_facts.result_set:
        for r in res_facts.result_set:
            fid, pred, val, vf, vt, old_id, old_val = r
            if vf:
                if old_id:
                    markers.append({
                        "ts": int(vf),
                        "type": "fact_supersession",
                        "label": f"Fact updated: {pred} -> {val} (superseded {old_val})",
                        "node_id": str(fid),
                        "details": {"predicate": pred, "new_value": val, "superseded_id": old_id}
                    })
                else:
                    markers.append({
                        "ts": int(vf),
                        "type": "fact_created",
                        "label": f"Fact established: {pred} = {val}",
                        "node_id": str(fid),
                        "details": {"predicate": pred, "value": val}
                    })

    # 2. Handoffs
    cypher_handoffs = """
    MATCH (h:Handoff)
    RETURN h.id, h.from_agent, h.to_agent, h.status, h.created_at
    """
    res_handoffs = execute_ro_query(graph_name, cypher_handoffs)
    if res_handoffs and res_handoffs.result_set:
        for r in res_handoffs.result_set:
            hid, from_a, to_a, status, created_at = r
            if created_at:
                markers.append({
                    "ts": int(created_at),
                    "type": "handoff",
                    "label": f"Handoff: {from_a} -> {to_a} ({status})",
                    "node_id": str(hid),
                    "details": {"from_agent": from_a, "to_agent": to_a, "status": status}
                })

    # 3. Tasks (creation and claims)
    cypher_tasks = """
    MATCH (t:Task)
    RETURN t.id, t.title, t.status, t.claimed_by, t.created_at
    """
    res_tasks = execute_ro_query(graph_name, cypher_tasks)
    if res_tasks and res_tasks.result_set:
        for r in res_tasks.result_set:
            tid, title, status, claimed_by, created_at = r
            if created_at:
                label = f"Task created: {title}"
                if claimed_by:
                    label += f" (claimed by {claimed_by})"
                markers.append({
                    "ts": int(created_at),
                    "type": "claim" if claimed_by else "task_created",
                    "label": label,
                    "node_id": str(tid),
                    "details": {"title": title, "claimed_by": claimed_by, "status": status}
                })

    # 4. Procedure forks
    cypher_proc = """
    MATCH (new:Procedure)-[:PREVIOUS_VERSION]->(old:Procedure)
    RETURN new.id, new.name, new.version, old.id, old.version, new.forked_from_assumption
    """
    res_proc = execute_ro_query(graph_name, cypher_proc)
    if res_proc and res_proc.result_set:
        now = int(time.time() * 1000)
        for r in res_proc.result_set:
            nid, name, nver, oid, over, assumption = r
            # Find the outcome timestamp if available
            cypher_out = """
            MATCH (p:Procedure {id: $oid})-[:RESULTED_IN]->(o:Outcome)
            RETURN o.ts
            ORDER BY o.ts DESC LIMIT 1
            """
            res_out = execute_ro_query(graph_name, cypher_out, {"oid": oid})
            ts = res_out.result_set[0][0] if (res_out and res_out.result_set) else now
            markers.append({
                "ts": int(ts),
                "type": "procedure_fork",
                "label": f"Procedure fork: {name} v{over} -> v{nver}",
                "node_id": str(nid),
                "details": {"procedure": name, "new_version": nver, "assumption": assumption}
            })

    # Sort markers by timestamp
    markers.sort(key=lambda m: m["ts"])

    if markers:
        min_ts = markers[0]["ts"]
        max_ts = markers[-1]["ts"]
    else:
        now = int(time.time() * 1000)
        min_ts = now
        max_ts = now

    return {
        "min_ts": min_ts,
        "max_ts": max_ts,
        "markers": markers
    }
