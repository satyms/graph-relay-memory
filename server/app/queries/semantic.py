"""
Named Cypher queries for semantic memory (Entities and Facts with supersession history).
"""
import time
from typing import Any, Dict, List, Optional
import uuid

from server.app.graph import execute_query, execute_ro_query


def upsert_fact(
    graph_name: str,
    entity_name: str,
    predicate: str,
    value: str,
    agent_id: str,
    confidence: float = 0.8,
    source_event_id: Optional[str] = None,
    visibility: str = "team",
    idempotency_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Creates a new fact, closing and superseding any existing active fact
    for the same entity and predicate. Preserves full historical lineage.
    """
    now = int(time.time() * 1000)
    fact_id = f"fact_{uuid.uuid4().hex[:12]}"
    ent_id = f"ent_{uuid.uuid4().hex[:8]}"

    # Ensure Entity node exists
    ent_cypher = """
    MERGE (e:Entity {name: $entity_name})
    ON CREATE SET e.id = $ent_id, e.kind = 'service', e.created_at = $now
    RETURN e.id AS id
    """
    execute_query(graph_name, ent_cypher, {"entity_name": entity_name, "ent_id": ent_id, "now": now})

    # If idempotency_key is provided and already exists for this entity & predicate, return it
    if idempotency_key:
        check_cypher = """
        MATCH (e:Entity {name: $entity_name})-[:HAS_FACT]->(f:Fact {idem_key: $idem_key, predicate: $predicate})
        OPTIONAL MATCH (f)-[:SUPERSEDES]->(old:Fact)
        RETURN f.id AS fact_id, old.id AS old_id
        """
        existing = execute_query(graph_name, check_cypher, {
            "entity_name": entity_name,
            "predicate": predicate,
            "idem_key": idempotency_key
        })
        if existing and existing.result_set:
            return {
                "fact_id": existing.result_set[0][0],
                "superseded_fact_id": existing.result_set[0][1]
            }

    # Step 1: Close currently active fact for this predicate (if any)
    cypher_close = """
    MATCH (e:Entity {name: $entity_name})-[:HAS_FACT]->(old:Fact {predicate: $predicate})
    WHERE old.valid_to IS NULL
    SET old.valid_to = $now, old.status = 'closed'
    RETURN old.id AS old_id
    """
    res_close = execute_query(graph_name, cypher_close, {
        "entity_name": entity_name,
        "predicate": predicate,
        "now": now
    })
    old_fact_id = res_close.result_set[0][0] if (res_close and res_close.result_set) else None

    # Step 2: Create new active fact
    cypher_create = """
    MATCH (e:Entity {name: $entity_name})
    CREATE (e)-[:HAS_FACT]->(new:Fact {
        id: $fact_id,
        predicate: $predicate,
        value: $value,
        confidence: $confidence,
        valid_from: $now,
        valid_to: null,
        status: 'active',
        visibility: $visibility,
        owner_agent: $agent_id,
        idem_key: $idem_key
    })
    RETURN new.id AS id
    """
    execute_query(graph_name, cypher_create, {
        "entity_name": entity_name,
        "predicate": predicate,
        "value": str(value),
        "confidence": float(confidence),
        "fact_id": fact_id,
        "visibility": visibility,
        "agent_id": agent_id,
        "now": now,
        "idem_key": idempotency_key or fact_id
    })

    # Link SUPERSEDES relationship if an older fact was closed
    if old_fact_id:
        cypher_supersedes = """
        MATCH (new:Fact {id: $fact_id}), (old:Fact {id: $old_id})
        MERGE (new)-[:SUPERSEDES]->(old)
        """
        execute_query(graph_name, cypher_supersedes, {"fact_id": fact_id, "old_id": old_fact_id})

    # Link DERIVED_FROM if source event provided
    if source_event_id:
        cypher_derived = """
        MATCH (new:Fact {id: $fact_id}), (ev:Event {id: $source_event_id})
        MERGE (new)-[:DERIVED_FROM]->(ev)
        """
        execute_query(graph_name, cypher_derived, {"fact_id": fact_id, "source_event_id": source_event_id})

    return {
        "fact_id": fact_id,
        "superseded_fact_id": old_fact_id
    }


def query_facts(
    graph_name: str,
    entity: Optional[str] = None,
    predicate: Optional[str] = None,
    as_of: Optional[int] = None,
    include_stale: bool = False,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Query facts active at timestamp as_of (defaulting to current time).
    Enables temporal 'time travel' queries across fact history.
    """
    now = int(time.time() * 1000)
    effective_t = as_of if as_of is not None else now
    safe_limit = max(1, min(limit or 10, 50))
    params: Dict[str, Any] = {"t": effective_t, "limit": safe_limit}

    where_parts: List[str] = [
        "f.valid_from <= $t",
        "(f.valid_to IS NULL OR f.valid_to > $t)"
    ]

    if entity:
        where_parts.append("(e.name = $entity OR e.id = $entity)")
        params["entity"] = entity
    if predicate:
        where_parts.append("f.predicate = $predicate")
        params["predicate"] = predicate

    # If querying current facts (as_of is None) and not include_stale, require status active
    if as_of is None and not include_stale:
        where_parts.append("f.status = 'active'")

    where_clause = " AND ".join(where_parts)

    cypher = f"""
    MATCH (e:Entity)-[:HAS_FACT]->(f:Fact)
    WHERE {where_clause}
    RETURN f.id AS fact_id, e.name AS entity, f.predicate AS predicate, f.value AS value,
           f.confidence AS confidence, f.valid_from AS valid_from, f.valid_to AS valid_to,
           f.status AS status
    ORDER BY f.valid_from DESC
    LIMIT $limit
    """
    res = execute_ro_query(graph_name, cypher, params)
    return [
        {
            "fact_id": row[0],
            "entity": row[1],
            "predicate": row[2],
            "value": row[3],
            "confidence": row[4],
            "valid_from": row[5],
            "valid_to": row[6],
            "status": row[7]
        }
        for row in (res.result_set if res else [])
    ]


def fact_history(graph_name: str, entity: str, predicate: str) -> List[Dict[str, Any]]:
    """Show the complete historical chain for an entity predicate."""
    cypher = """
    MATCH (e:Entity)-[:HAS_FACT]->(f:Fact {predicate: $predicate})
    WHERE e.name = $entity OR e.id = $entity
    OPTIONAL MATCH (f)-[:DERIVED_FROM]->(ev:Event)
    RETURN f.id AS fact_id, f.value AS value, f.confidence AS confidence,
           f.valid_from AS valid_from, f.valid_to AS valid_to, f.status AS status,
           f.owner_agent AS author_agent, ev.id AS source_event_id
    ORDER BY f.valid_from DESC
    """
    res = execute_ro_query(graph_name, cypher, {"entity": entity, "predicate": predicate})
    return [
        {
            "fact_id": row[0],
            "value": row[1],
            "confidence": row[2],
            "valid_from": row[3],
            "valid_to": row[4],
            "status": row[5],
            "author_agent": row[6],
            "source_event_id": row[7]
        }
        for row in (res.result_set if res else [])
    ]


def forget_fact(graph_name: str, fact_id: str, reason: str) -> bool:
    """Soft-close an active fact. History is preserved."""
    now = int(time.time() * 1000)
    cypher = """
    MATCH (f:Fact {id: $fact_id})
    WHERE f.valid_to IS NULL
    SET f.valid_to = $now, f.status = 'closed', f.forget_reason = $reason
    RETURN f.id
    """
    res = execute_query(graph_name, cypher, {"fact_id": fact_id, "reason": reason, "now": now})
    return bool(res and res.result_set)
