"""
Named Cypher queries for Graph Insight tools:
- blast_radius: Breadth-first reverse dependency traversal on DEPENDS_ON edges
- rank_critical_services: Centrality ranking via FalkorDB algo.pageRank
- explain: Provenance chain from conclusion/fact/hypothesis back to source events/evidence
"""
from typing import Any, Dict, List, Optional
from server.app.graph import execute_ro_query, execute_query


def blast_radius(graph_name: str, service_name: str, depth: int = 3) -> List[Dict[str, Any]]:
    """
    Find all entities impacted if service_name fails, traversing incoming DEPENDS_ON edges up to depth.
    """
    safe_depth = max(1, min(depth or 3, 5))
    # openCypher requires variable-length bounds to be literals in the query string
    cypher = f"""
    MATCH (s:Entity {{name: $service}})<-[:DEPENDS_ON*1..{safe_depth}]-(dep:Entity)
    RETURN DISTINCT dep.name AS impacted, dep.kind AS kind
    """
    res = execute_ro_query(graph_name, cypher, {"service": service_name})
    if not (res and res.result_set):
        return []
    return [
        {"name": row[0], "kind": row[1]}
        for row in res.result_set
    ]


def rank_critical_services(graph_name: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Rank services by network centrality / criticality using FalkorDB algo.pageRank.
    """
    safe_limit = max(1, min(limit or 5, 20))
    cypher = f"""
    CALL algo.pageRank('Entity', 'DEPENDS_ON')
    YIELD node, score
    RETURN node.name AS service, score
    ORDER BY score DESC
    LIMIT {safe_limit}
    """
    res = execute_query(graph_name, cypher)
    if not (res and res.result_set):
        return []
    return [
        {"service": row[0], "score": round(float(row[1]), 5)}
        for row in res.result_set
    ]


def explain(graph_name: str, target_id: str) -> Dict[str, Any]:
    """
    Retrieves the complete provenance chain for a given node id (Fact, Hypothesis, or Task).
    Traces SUPERSEDES, DERIVED_FROM, and SUPPORTED_BY connections.
    """
    # 1. Check if target is a Fact
    q_fact = """
    MATCH (f:Fact {id: $id})
    OPTIONAL MATCH (f)-[:SUPERSEDES]->(old:Fact)
    OPTIONAL MATCH (f)-[:DERIVED_FROM]->(e:Event)
    RETURN f.id, f.predicate, f.value, f.confidence, f.status, old.id, e.id, e.summary
    """
    res_f = execute_ro_query(graph_name, q_fact, {"id": target_id})
    if res_f and res_f.result_set and res_f.result_set[0][0]:
        row = res_f.result_set[0]
        chain = {
            "node_type": "Fact",
            "id": row[0],
            "predicate": row[1],
            "value": row[2],
            "confidence": row[3],
            "status": row[4],
            "supersedes_fact_id": row[5],
            "source_event": {"id": row[6], "summary": row[7]} if row[6] else None
        }
        # If there's a superseded fact, trace it back
        if row[5]:
            ancestor = explain(graph_name, row[5])
            chain["previous_version"] = ancestor
        return {"target_id": target_id, "provenance": chain}

    # 2. Check if target is a Hypothesis
    q_hyp = """
    MATCH (h:Hypothesis {id: $id})
    OPTIONAL MATCH (h)-[r:SUPPORTED_BY]->(e:Event)
    RETURN h.id, h.statement, h.confidence, h.status, collect(e.id), collect(e.summary)
    """
    res_h = execute_ro_query(graph_name, q_hyp, {"id": target_id})
    if res_h and res_h.result_set and res_h.result_set[0][0]:
        row = res_h.result_set[0]
        evidence_list = []
        e_ids, e_sums = row[4] or [], row[5] or []
        for eid, esum in zip(e_ids, e_sums):
            if eid:
                evidence_list.append({"event_id": eid, "summary": esum})
        return {
            "target_id": target_id,
            "provenance": {
                "node_type": "Hypothesis",
                "id": row[0],
                "statement": row[1],
                "confidence": row[2],
                "status": row[3],
                "supporting_evidence": evidence_list
            }
        }

    # 3. Check if target is a Task
    q_task = """
    MATCH (t:Task {id: $id})
    OPTIONAL MATCH (blocker:Task)-[:BLOCKS]->(t)
    RETURN t.id, t.title, t.status, t.claimed_by, collect(blocker.id)
    """
    res_t = execute_ro_query(graph_name, q_task, {"id": target_id})
    if res_t and res_t.result_set and res_t.result_set[0][0]:
        row = res_t.result_set[0]
        return {
            "target_id": target_id,
            "provenance": {
                "node_type": "Task",
                "id": row[0],
                "title": row[1],
                "status": row[2],
                "claimed_by": row[3],
                "blocked_by": [b for b in (row[4] or []) if b]
            }
        }

    return {"target_id": target_id, "provenance": None, "note": "Node not found or has no upstream links"}
