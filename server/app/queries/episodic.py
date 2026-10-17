"""
Named Cypher queries for episodic memory (Sessions and Events).
"""
import json
import time
from typing import Any, Dict, List, Optional
import uuid

from server.app.graph import execute_query, execute_ro_query


def start_session(graph_name: str, agent_id: str, role: str) -> Dict[str, Any]:
    """Create a new session node and fetch context for the agent."""
    now = int(time.time() * 1000)
    session_id = f"sess_{uuid.uuid4().hex[:12]}"

    # Ensure Agent node exists and create Session linked via RAN
    cypher = """
    MERGE (a:Agent {id: $agent_id})
    ON CREATE SET a.role = $role, a.created_at = $now
    CREATE (s:Session {id: $session_id, agent_id: $agent_id, started_at: $now})
    CREATE (a)-[:RAN]->(s)
    RETURN s.id AS id
    """
    execute_query(graph_name, cypher, {"agent_id": agent_id, "role": role, "session_id": session_id, "now": now})

    # Retrieve last ended session summary for this agent
    last_summary_cypher = """
    MATCH (a:Agent {id: $agent_id})-[:RAN]->(s:Session)
    WHERE s.id <> $session_id AND s.summary IS NOT NULL
    RETURN s.summary
    ORDER BY s.started_at DESC
    LIMIT 1
    """
    res_sum = execute_ro_query(graph_name, last_summary_cypher, {"agent_id": agent_id, "session_id": session_id})
    last_summary = res_sum.result_set[0][0] if res_sum and res_sum.result_set else None

    # Retrieve open handoffs for this agent
    handoffs_cypher = """
    MATCH (h:Handoff {to_agent: $agent_id, status: 'pending'})
    RETURN h.id, h.from_agent, h.context_summary, h.created_at
    ORDER BY h.created_at DESC
    LIMIT 10
    """
    res_h = execute_ro_query(graph_name, handoffs_cypher, {"agent_id": agent_id})
    open_handoffs = [
        {"id": row[0], "from_agent": row[1], "context_summary": row[2], "created_at": row[3]}
        for row in (res_h.result_set if res_h else [])
    ]

    # Retrieve active tasks claimed by this agent
    tasks_cypher = """
    MATCH (t:Task {owner: $agent_id, status: 'claimed'})
    WHERE t.lease_expires_at > $now
    RETURN t.id, t.title, t.lease_expires_at
    """
    res_t = execute_ro_query(graph_name, tasks_cypher, {"agent_id": agent_id, "now": now})
    open_tasks = [
        {"id": row[0], "title": row[1], "lease_expires_at": row[2]}
        for row in (res_t.result_set if res_t else [])
    ]

    return {
        "session_id": session_id,
        "last_session_summary": last_summary,
        "open_handoffs": open_handoffs,
        "open_tasks_claimed_by_me": open_tasks
    }


def log_event(
    graph_name: str,
    session_id: str,
    event_type: str,
    summary: str,
    payload: Optional[Dict[str, Any]] = None,
    entities: Optional[List[str]] = None,
    idempotency_key: Optional[str] = None
) -> Dict[str, Any]:
    """Append an event to the session timeline idempotently."""
    now = int(time.time() * 1000)
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    idem_key = idempotency_key or f"auto_{event_id}"
    payload_str = json.dumps(payload or {})

    # Compute next sequence number in session
    seq_cypher = """
    MATCH (s:Session {id: $session_id})-[:HAS_EVENT]->(e:Event)
    RETURN count(e) AS cnt
    """
    res_seq = execute_query(graph_name, seq_cypher, {"session_id": session_id})
    seq = (res_seq.result_set[0][0] + 1) if res_seq and res_seq.result_set else 1

    # Insert or retrieve existing event scoped to session by idempotency key
    cypher = """
    MATCH (s:Session {id: $session_id})
    MERGE (s)-[:HAS_EVENT]->(e:Event {idem_key: $idem_key})
    ON CREATE SET e.id = $event_id, e.type = $event_type, e.summary = $summary,
                  e.payload = $payload, e.ts = $now, e.seq = $seq
    RETURN e.id AS id, e.seq AS seq
    """
    res = execute_query(graph_name, cypher, {
        "session_id": session_id,
        "idem_key": idem_key,
        "event_id": event_id,
        "event_type": event_type,
        "summary": summary,
        "payload": payload_str,
        "now": now,
        "seq": seq
    })
    if not res or not res.result_set:
        raise LookupError(f"session {session_id} not found")
    actual_id = res.result_set[0][0]
    actual_seq = res.result_set[0][1]

    # Link MENTIONS edges to entities if provided
    if entities:
        for ent_name in entities:
            ent_id = f"ent_{uuid.uuid4().hex[:8]}"
            ent_cypher = """
            MATCH (e:Event {id: $event_id})
            MERGE (ent:Entity {name: $name})
            ON CREATE SET ent.id = $ent_id, ent.kind = 'service', ent.created_at = $now
            MERGE (e)-[:MENTIONS]->(ent)
            """
            execute_query(graph_name, ent_cypher, {
                "event_id": actual_id,
                "name": ent_name,
                "ent_id": ent_id,
                "now": now
            })

    return {"event_id": actual_id, "seq": actual_seq}


def recall_episodes(
    graph_name: str,
    query: Optional[str] = None,
    entity: Optional[str] = None,
    since: Optional[int] = None,
    until: Optional[int] = None,
    session_id: Optional[str] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Recall events matching criteria, budgeted to limit."""
    safe_limit = max(1, min(limit or 10, 50))
    params: Dict[str, Any] = {"limit": safe_limit}

    match_clause = "MATCH (s:Session)-[:HAS_EVENT]->(e:Event)"
    if entity:
        match_clause += "-[:MENTIONS]->(ent:Entity)"

    where_parts: List[str] = []
    if session_id:
        where_parts.append("s.id = $session_id")
        params["session_id"] = session_id
    if since is not None:
        where_parts.append("e.ts >= $since")
        params["since"] = since
    if until is not None:
        where_parts.append("e.ts <= $until")
        params["until"] = until
    if entity:
        where_parts.append("(ent.name = $entity OR ent.id = $entity)")
        params["entity"] = entity
    if query:
        where_parts.append("toLower(e.summary) CONTAINS toLower($query)")
        params["query"] = query

    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    cypher = f"""
    {match_clause}
    {where_clause}
    RETURN DISTINCT e.id AS event_id, e.ts AS ts, e.type AS type, e.summary AS summary,
                    s.id AS session_id, s.agent_id AS agent_id
    ORDER BY e.ts DESC
    LIMIT $limit
    """
    res = execute_ro_query(graph_name, cypher, params)
    return [
        {
            "event_id": row[0],
            "ts": row[1],
            "type": row[2],
            "summary": row[3],
            "session_id": row[4],
            "agent_id": row[5]
        }
        for row in (res.result_set if res else [])
    ]


def end_session(graph_name: str, session_id: str, summary: str) -> bool:
    """Close a session and store its summary."""
    now = int(time.time() * 1000)
    cypher = """
    MATCH (s:Session {id: $session_id})
    SET s.ended_at = $now, s.summary = $summary
    RETURN s.id
    """
    res = execute_query(graph_name, cypher, {"session_id": session_id, "summary": summary, "now": now})
    return bool(res and res.result_set)
