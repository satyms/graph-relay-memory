"""
Consolidation Worker:
Background/on-demand process that:
1. Synthesizes recent unmerged session events into semantic candidate facts.
2. Links facts with DERIVED_FROM provenance edges back to source events (MEM-4).
3. Decays stale, low-confidence facts whose last verification exceeds the decay threshold (MEM-5).
"""
import time
import logging
from typing import Any, Dict, List, Optional

from server.app.graph import execute_query, execute_ro_query
from server.app.queries.semantic import upsert_fact

log = logging.getLogger("consolidation")

# Default: facts untouched for > 7 days with confidence < 0.6 are marked stale
DEFAULT_DECAY_AGE_MS = 7 * 24 * 3600 * 1000
DEFAULT_DECAY_CONFIDENCE_THRESHOLD = 0.6


def consolidate_session_events(
    graph_name: str,
    session_id: Optional[str] = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    MEM-4: Reads recent session events that mention entities, derives candidate facts,
    and writes them into the graph with DERIVED_FROM provenance links.
    """
    now = int(time.time() * 1000)
    
    # Query events that have entities mentioned and are not yet linked to a Fact
    where = "NOT (e)<-[:DERIVED_FROM]-(:Fact)"
    params: Dict[str, Any] = {"limit": limit}
    if session_id:
        where += " AND s.id = $session_id"
        params["session_id"] = session_id

    cypher = f"""
    MATCH (s:Session)-[:HAS_EVENT]->(e:Event)
    WHERE {where} AND e.type IN ['observation', 'decision']
    RETURN e.id, e.summary, e.payload, s.agent_id
    ORDER BY e.ts DESC
    LIMIT $limit
    """
    res = execute_ro_query(graph_name, cypher, params)
    if not (res and res.result_set):
        return []

    derived_facts = []
    for row in res.result_set:
        event_id, summary, payload_json, agent_id = row
        # Derive factual knowledge from event summaries (heuristic / structured extraction)
        # E.g. "checkout-api latency spiked to 3200ms" -> entity=checkout-api, predicate=last_known_status, value=degraded
        words = summary.lower().split()
        target_entity = None
        for w in words:
            if "-" in w or "_" in w:
                target_entity = w.strip(".,;:()")
                break
        
        if not target_entity:
            target_entity = "system"

        pred = "incident_observation"
        val = summary[:80]
        
        fact_res = upsert_fact(
            graph_name=graph_name,
            entity_name=target_entity,
            predicate=pred,
            value=val,
            agent_id=agent_id or "consolidation_worker",
            confidence=0.75,
            source_event_id=event_id
        )
        derived_facts.append({
            "event_id": event_id,
            "fact_id": fact_res["fact_id"],
            "entity": target_entity,
            "predicate": pred,
            "value": val
        })

    log.info("Consolidated %d events into derived facts in %s", len(derived_facts), graph_name)
    return derived_facts


def decay_stale_facts(
    graph_name: str,
    max_age_ms: int = DEFAULT_DECAY_AGE_MS,
    confidence_threshold: float = DEFAULT_DECAY_CONFIDENCE_THRESHOLD
) -> int:
    """
    MEM-5: Decays active facts whose confidence is below threshold and whose age
    exceeds max_age_ms, setting status = 'stale'.
    Stale facts drop out of default query_facts results unless include_stale=True.
    """
    cutoff = int(time.time() * 1000) - max_age_ms
    cypher = """
    MATCH (f:Fact {status: 'active'})
    WHERE f.confidence < $threshold AND f.valid_from < $cutoff
    SET f.status = 'stale'
    RETURN count(f)
    """
    res = execute_query(graph_name, cypher, {
        "threshold": float(confidence_threshold),
        "cutoff": cutoff
    })
    count = res.result_set[0][0] if (res and res.result_set) else 0
    if count:
        log.info("Decayed %d stale facts in %s", count, graph_name)
    return count


def run_consolidation(
    graph_name: str,
    session_id: Optional[str] = None,
    max_age_ms: int = DEFAULT_DECAY_AGE_MS
) -> Dict[str, Any]:
    """Execute complete consolidation cycle for a tenant graph."""
    derived = consolidate_session_events(graph_name, session_id=session_id)
    decayed = decay_stale_facts(graph_name, max_age_ms=max_age_ms)
    return {
        "ok": True,
        "derived_facts_count": len(derived),
        "decayed_facts_count": decayed,
        "derived_facts": derived
    }
