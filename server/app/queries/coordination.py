"""
Named Cypher queries for coordination: Tasks, Incidents, Handoffs, and Hypotheses.
"""
import time
import uuid
from typing import Any, Dict, List, Optional

from server.app.graph import execute_query, execute_ro_query

# Default lease duration: 60 seconds
DEFAULT_LEASE_TTL_MS = 60_000


# ─────────────────────── Incidents ───────────────────────

def open_incident(
    graph_name: str,
    title: str,
    severity: str,
    reporter_id: str,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new Incident node. Idempotent on key."""
    now = int(time.time() * 1000)
    incident_id = f"inc_{uuid.uuid4().hex[:12]}"
    idem = idempotency_key or incident_id

    if idempotency_key:
        check = execute_ro_query(
            graph_name,
            "MATCH (i:Incident {idem_key: $k}) RETURN i.id LIMIT 1",
            {"k": idempotency_key},
        )
        if check and check.result_set:
            return {"incident_id": check.result_set[0][0], "created": False}

    execute_query(
        graph_name,
        """
        CREATE (i:Incident {
            id: $id, title: $title, severity: $severity,
            status: 'open', reporter_id: $reporter_id,
            created_at: $now, idem_key: $idem
        })
        """,
        {"id": incident_id, "title": title, "severity": severity,
         "reporter_id": reporter_id, "now": now, "idem": idem},
    )
    return {"incident_id": incident_id, "created": True}


# ─────────────────────── Tasks ───────────────────────

def create_task(
    graph_name: str,
    title: str,
    agent_id: str,
    incident_id: Optional[str] = None,
    blocks: Optional[List[str]] = None,
    priority: int = 5,
) -> Dict[str, Any]:
    """Create a Task node. Optionally link to incident and BLOCKS dependants."""
    now = int(time.time() * 1000)
    task_id = f"task_{uuid.uuid4().hex[:12]}"

    execute_query(
        graph_name,
        """
        CREATE (t:Task {
            id: $id, title: $title, status: 'open',
            created_by: $agent_id, priority: $priority,
            created_at: $now, lease_expires_at: null, claimed_by: null,
            version: 1
        })
        """,
        {"id": task_id, "title": title, "agent_id": agent_id,
         "priority": priority, "now": now},
    )

    if incident_id:
        execute_query(
            graph_name,
            "MATCH (i:Incident {id: $inc}), (t:Task {id: $tid}) MERGE (t)-[:PART_OF]->(i)",
            {"inc": incident_id, "tid": task_id},
        )

    for blocked_id in (blocks or []):
        execute_query(
            graph_name,
            "MATCH (t:Task {id: $tid}), (b:Task {id: $bid}) MERGE (t)-[:BLOCKS]->(b)",
            {"tid": task_id, "bid": blocked_id},
        )

    return {"task_id": task_id}


def list_open_work(graph_name: str, agent_id: Optional[str] = None, limit: int = 20) -> List[Dict]:
    """List open or in-progress tasks, optionally filtered to a specific agent."""
    params: Dict[str, Any] = {"limit": min(limit, 50)}
    where = "t.status IN ['open', 'in_progress']"
    if agent_id:
        where += " AND (t.claimed_by = $agent_id OR t.claimed_by IS NULL)"
        params["agent_id"] = agent_id

    res = execute_ro_query(
        graph_name,
        f"""
        MATCH (t:Task)
        WHERE {where}
        RETURN t.id, t.title, t.status, t.priority, t.claimed_by, t.lease_expires_at
        ORDER BY t.priority ASC, t.created_at ASC
        LIMIT $limit
        """,
        params,
    )
    if not (res and res.result_set):
        return []
    return [
        {"task_id": r[0], "title": r[1], "status": r[2],
         "priority": r[3], "claimed_by": r[4], "lease_expires_at": r[5]}
        for r in res.result_set
    ]


def claim_task(graph_name: str, task_id: str, agent_id: str, ttl_ms: int = DEFAULT_LEASE_TTL_MS) -> Dict[str, Any]:
    """
    Atomic CAS claim: transitions 'open' -> 'in_progress' only if unclaimed.
    Returns ok=True with lease_expires_at, or ok=False with CONFLICT.
    """
    now = int(time.time() * 1000)
    expires = now + ttl_ms

    # Atomic: match only open/unclaimed tasks in one write query
    res = execute_query(
        graph_name,
        """
        MATCH (t:Task {id: $task_id})
        WHERE t.status = 'open' AND t.claimed_by IS NULL
        SET t.status = 'in_progress', t.claimed_by = $agent_id, t.lease_expires_at = $expires,
            t.version = COALESCE(t.version, 0) + 1
        RETURN t.id, t.version
        """,
        {"task_id": task_id, "agent_id": agent_id, "expires": expires},
    )

    if res and res.result_set:
        ver = res.result_set[0][1] if len(res.result_set[0]) > 1 else 1
        return {"ok": True, "task_id": task_id, "lease_expires_at": expires, "version": ver}

    # Check if task exists at all
    check = execute_ro_query(
        graph_name,
        "MATCH (t:Task {id: $task_id}) RETURN t.status, t.claimed_by LIMIT 1",
        {"task_id": task_id},
    )
    if not (check and check.result_set):
        return {"ok": False, "error": {"code": "NOT_FOUND", "message": f"Task {task_id} not found"}}
    return {"ok": False, "error": {"code": "CONFLICT", "message": "Task already claimed or not open"}}


def renew_lease(graph_name: str, task_id: str, agent_id: str, ttl_ms: int = DEFAULT_LEASE_TTL_MS) -> Dict[str, Any]:
    """Extend lease on a task the agent already owns."""
    now = int(time.time() * 1000)
    expires = now + ttl_ms

    res = execute_query(
        graph_name,
        """
        MATCH (t:Task {id: $task_id, claimed_by: $agent_id, status: 'in_progress'})
        SET t.lease_expires_at = $expires
        RETURN t.id
        """,
        {"task_id": task_id, "agent_id": agent_id, "expires": expires},
    )

    if res and res.result_set:
        return {"ok": True, "lease_expires_at": expires}
    return {"ok": False, "error": {"code": "FORBIDDEN", "message": "Not the current leaseholder"}}


def release_task(graph_name: str, task_id: str, agent_id: str) -> Dict[str, Any]:
    """Drop a claim, returning the task to 'open'."""
    res = execute_query(
        graph_name,
        """
        MATCH (t:Task {id: $task_id, claimed_by: $agent_id})
        SET t.status = 'open', t.claimed_by = null, t.lease_expires_at = null
        RETURN t.id
        """,
        {"task_id": task_id, "agent_id": agent_id},
    )
    if res and res.result_set:
        return {"ok": True}
    return {"ok": False, "error": {"code": "FORBIDDEN", "message": "Not the current leaseholder"}}


def complete_task(graph_name: str, task_id: str, agent_id: str, summary: str = "") -> Dict[str, Any]:
    """
    Mark task done. Cascade-unblock: any task blocked only by this one moves to 'open'.
    """
    now = int(time.time() * 1000)

    # Step 1: complete the task
    res = execute_query(
        graph_name,
        """
        MATCH (t:Task {id: $task_id, claimed_by: $agent_id, status: 'in_progress'})
        SET t.status = 'done', t.completed_at = $now, t.summary = $summary,
            t.lease_expires_at = null
        RETURN t.id
        """,
        {"task_id": task_id, "agent_id": agent_id, "now": now, "summary": summary},
    )
    if not (res and res.result_set):
        return {"ok": False, "error": {"code": "FORBIDDEN", "message": "Not the leaseholder or task not in_progress"}}

    # Step 2: cascade unblock — find blocked tasks downstream of this task
    # For each, count remaining non-done blockers (excluding just-completed task).
    # shortcut: two queries instead of EXISTS subquery (FalkorDB openCypher doesn't support EXISTS{})
    candidates = execute_ro_query(
        graph_name,
        "MATCH (done:Task {id: $task_id})-[:BLOCKS]->(blocked:Task {status: 'blocked'}) RETURN blocked.id",
        {"task_id": task_id},
    )
    if candidates and candidates.result_set:
        for (blocked_id,) in candidates.result_set:
            remaining = execute_ro_query(
                graph_name,
                """
                MATCH (other:Task)-[:BLOCKS]->(b:Task {id: $bid})
                WHERE other.id <> $task_id AND other.status <> 'done'
                RETURN count(other)
                """,
                {"bid": blocked_id, "task_id": task_id},
            )
            if remaining and remaining.result_set and remaining.result_set[0][0] == 0:
                execute_query(
                    graph_name,
                    "MATCH (t:Task {id: $id}) SET t.status = 'open'",
                    {"id": blocked_id},
                )
    return {"ok": True}


def reap_expired_leases(graph_name: str) -> int:
    """
    Re-open tasks whose lease_expires_at is in the past.
    Returns count of reaped tasks.
    """
    reaped = reap_expired_leases_detailed(graph_name)
    return len(reaped)


def reap_expired_leases_detailed(graph_name: str) -> List[Dict[str, Any]]:
    """
    Re-open tasks whose lease_expires_at is in the past and return their details.
    """
    now = int(time.time() * 1000)
    res = execute_query(
        graph_name,
        """
        MATCH (t:Task {status: 'in_progress'})
        WHERE t.lease_expires_at IS NOT NULL AND t.lease_expires_at < $now
        SET t.status = 'open', t.claimed_by = null, t.lease_expires_at = null,
            t.version = COALESCE(t.version, 0) + 1
        RETURN t.id, t.title, t.version
        """,
        {"now": now},
    )
    if res and res.result_set:
        return [{"task_id": r[0], "title": r[1], "version": r[2]} for r in res.result_set]
    return []


# ─────────────────────── Hypotheses ───────────────────────

def add_hypothesis(
    graph_name: str,
    incident_id: str,
    statement: str,
    agent_id: str,
    confidence: float = 0.5,
) -> Dict[str, Any]:
    """Attach a Hypothesis node to an Incident."""
    now = int(time.time() * 1000)
    hyp_id = f"hyp_{uuid.uuid4().hex[:12]}"

    execute_query(
        graph_name,
        """
        MATCH (i:Incident {id: $inc_id})
        CREATE (h:Hypothesis {
            id: $id, statement: $statement, agent_id: $agent_id,
            confidence: $conf, status: 'open', created_at: $now
        })
        CREATE (i)-[:HAS_HYPOTHESIS]->(h)
        """,
        {"inc_id": incident_id, "id": hyp_id, "statement": statement,
         "agent_id": agent_id, "conf": float(confidence), "now": now},
    )
    return {"hypothesis_id": hyp_id}


def attach_evidence(
    graph_name: str,
    hypothesis_id: str,
    event_id: str,
    agent_id: str,
    note: str = "",
) -> Dict[str, Any]:
    """Link an Event to a Hypothesis as SUPPORTS evidence."""
    execute_query(
        graph_name,
        """
        MATCH (h:Hypothesis {id: $hid}), (e:Event {id: $eid})
        MERGE (h)-[:SUPPORTED_BY {agent_id: $agent_id, note: $note}]->(e)
        """,
        {"hid": hypothesis_id, "eid": event_id, "agent_id": agent_id, "note": note},
    )
    return {"ok": True}


# ─────────────────────── Handoffs ───────────────────────

def create_handoff(
    graph_name: str,
    from_agent: str,
    to_agent: str,
    task_id: Optional[str],
    context_summary: str,
    incident_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a pending Handoff node between agents."""
    now = int(time.time() * 1000)
    handoff_id = f"ho_{uuid.uuid4().hex[:12]}"

    execute_query(
        graph_name,
        """
        CREATE (h:Handoff {
            id: $id, from_agent: $from_agent, to_agent: $to_agent,
            task_id: $task_id, context_summary: $context_summary,
            status: 'pending', created_at: $now
        })
        """,
        {"id": handoff_id, "from_agent": from_agent, "to_agent": to_agent,
         "task_id": task_id, "context_summary": context_summary, "now": now},
    )

    if incident_id:
        execute_query(
            graph_name,
            "MATCH (i:Incident {id: $inc}), (h:Handoff {id: $hid}) MERGE (h)-[:PART_OF]->(i)",
            {"inc": incident_id, "hid": handoff_id},
        )

    return {"handoff_id": handoff_id}


def accept_handoff(
    graph_name: str,
    handoff_id: str,
    agent_id: str,
) -> Dict[str, Any]:
    """Accept a pending Handoff. Only the intended recipient may accept."""
    now = int(time.time() * 1000)

    res = execute_query(
        graph_name,
        """
        MATCH (h:Handoff {id: $hid, to_agent: $agent_id, status: 'pending'})
        SET h.status = 'accepted', h.accepted_at = $now
        RETURN h.id, h.from_agent, h.task_id, h.context_summary
        """,
        {"hid": handoff_id, "agent_id": agent_id, "now": now},
    )

    if not (res and res.result_set):
        return {"ok": False, "error": {"code": "FORBIDDEN", "message": "Handoff not found or not addressed to you"}}

    row = res.result_set[0]
    return {
        "ok": True,
        "handoff_id": row[0],
        "from_agent": row[1],
        "task_id": row[2],
        "context_summary": row[3],
    }


def get_agent_tasks(graph_name: str, agent_id: str) -> List[Dict[str, Any]]:
    """
    Get all in-progress tasks currently claimed by the specified agent.
    Returns list of dicts with task_id, title, status, and lease_expires_at.
    """
    res = execute_ro_query(
        graph_name,
        """
        MATCH (t:Task {status: 'in_progress', claimed_by: $agent_id})
        RETURN t.id, t.title, t.status, t.lease_expires_at, t.version
        """,
        {"agent_id": agent_id},
    )
    if not (res and res.result_set):
        return []
    return [
        {
            "task_id": r[0],
            "title": r[1],
            "status": r[2],
            "lease_expires_at": r[3],
            "version": r[4] or 1
        }
        for r in res.result_set
    ]
