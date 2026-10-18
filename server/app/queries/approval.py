"""
Named Cypher queries for human-in-the-loop safety approvals.
Manages:
- Approval nodes: {id, action, target, requested_by, status, reason, requested_at, decided_at, decided_by}
- Relationships: (Task)-[:REQUIRES]->(Approval)
- Verification: is_task_approved_for_action checks whether a risky action on a task has been approved.
"""
import time
import uuid
from typing import Any, Dict, List, Optional
from server.app.graph import execute_query, execute_ro_query

RISKY_ACTIONS = {"rollback_deploy", "restart_service", "scale_down"}


def request_approval(
    graph_name: str,
    task_id: str,
    action: str,
    justification: str,
    requested_by: str,
    target: Optional[str] = None
) -> Dict[str, Any]:
    """
    Creates an Approval node in status 'pending' and links (Task)-[:REQUIRES]->(Approval).
    """
    now = int(time.time() * 1000)
    approval_id = f"appr_{uuid.uuid4().hex[:12]}"
    action_target = target or task_id

    # Verify task exists
    check_task = execute_ro_query(graph_name, "MATCH (t:Task {id: $tid}) RETURN t.id LIMIT 1", {"tid": task_id})
    if not (check_task and check_task.result_set):
        raise LookupError(f"Task {task_id} not found")

    cypher = """
    MATCH (t:Task {id: $task_id})
    CREATE (a:Approval {
        id: $id,
        action: $action,
        target: $target,
        requested_by: $requested_by,
        justification: $justification,
        status: 'pending',
        reason: null,
        requested_at: $now,
        decided_at: null,
        decided_by: null
    })
    CREATE (t)-[:REQUIRES]->(a)
    RETURN a.id AS id
    """
    execute_query(graph_name, cypher, {
        "id": approval_id,
        "task_id": task_id,
        "action": action,
        "target": action_target,
        "requested_by": requested_by,
        "justification": justification,
        "now": now
    })

    return {
        "approval_id": approval_id,
        "task_id": task_id,
        "action": action,
        "status": "pending",
        "requested_at": now
    }


def get_approval(graph_name: str, approval_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve an Approval node and its linked Task.
    """
    cypher = """
    MATCH (a:Approval {id: $id})
    OPTIONAL MATCH (t:Task)-[:REQUIRES]->(a)
    RETURN a.id, a.action, a.target, a.requested_by, a.status,
           a.reason, a.justification, a.requested_at, a.decided_at, a.decided_by, t.id
    LIMIT 1
    """
    res = execute_ro_query(graph_name, cypher, {"id": approval_id})
    if not (res and res.result_set):
        return None

    r = res.result_set[0]
    return {
        "approval_id": r[0],
        "action": r[1],
        "target": r[2],
        "requested_by": r[3],
        "status": r[4],
        "reason": r[5],
        "justification": r[6],
        "requested_at": r[7],
        "decided_at": r[8],
        "decided_by": r[9],
        "task_id": r[10]
    }


def list_approvals(graph_name: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List approvals in graph, optionally filtered by status ('pending', 'approved', 'rejected').
    """
    params: Dict[str, Any] = {}
    where = ""
    if status:
        where = "WHERE a.status = $status"
        params["status"] = status

    cypher = f"""
    MATCH (a:Approval)
    {where}
    OPTIONAL MATCH (t:Task)-[:REQUIRES]->(a)
    RETURN a.id, a.action, a.target, a.requested_by, a.status,
           a.reason, a.justification, a.requested_at, a.decided_at, a.decided_by, t.id
    ORDER BY a.requested_at DESC
    """
    res = execute_ro_query(graph_name, cypher, params)
    if not (res and res.result_set):
        return []

    return [
        {
            "approval_id": r[0],
            "action": r[1],
            "target": r[2],
            "requested_by": r[3],
            "status": r[4],
            "reason": r[5],
            "justification": r[6],
            "requested_at": r[7],
            "decided_at": r[8],
            "decided_by": r[9],
            "task_id": r[10]
        }
        for r in res.result_set
    ]


def decide_approval(
    graph_name: str,
    approval_id: str,
    decision: str,
    reason: str,
    decided_by: str = "admin"
) -> Dict[str, Any]:
    """
    Record an admin decision ('approved' or 'rejected') on an Approval node.
    """
    if decision not in {"approved", "rejected"}:
        raise ValueError(f"Decision must be 'approved' or 'rejected', got {decision!r}")

    now = int(time.time() * 1000)
    cypher = """
    MATCH (a:Approval {id: $id, status: 'pending'})
    SET a.status = $decision,
        a.reason = $reason,
        a.decided_at = $now,
        a.decided_by = $decided_by
    RETURN a.id, a.action, a.target, a.status
    """
    res = execute_query(graph_name, cypher, {
        "id": approval_id,
        "decision": decision,
        "reason": reason,
        "decided_by": decided_by,
        "now": now
    })

    if not (res and res.result_set):
        # Check if already decided
        existing = get_approval(graph_name, approval_id)
        if not existing:
            raise LookupError(f"Approval {approval_id} not found")
        return {
            "ok": False,
            "error": f"Approval {approval_id} already decided as {existing['status']}"
        }

    return {
        "ok": True,
        "approval_id": approval_id,
        "status": decision,
        "reason": reason,
        "decided_at": now,
        "decided_by": decided_by
    }


def is_task_approved_for_action(graph_name: str, task_id: str, action: str) -> bool:
    """
    Check if a task has an approved Approval node for the specified action.
    """
    cypher = """
    MATCH (t:Task {id: $tid})-[:REQUIRES]->(a:Approval {action: $action, status: 'approved'})
    RETURN count(a) AS cnt
    """
    res = execute_ro_query(graph_name, cypher, {"tid": task_id, "action": action})
    if res and res.result_set and res.result_set[0][0] > 0:
        return True
    return False
