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


def get_explain_provenance(graph_name: str, node_id: str) -> Optional[Dict[str, Any]]:
    """
    Returns full provenance details for node_id including nodes, edges, author,
    timestamps, and a deterministic plain-text 'because' summary.
    Returns None if node not found in this tenant graph.
    """
    # First, find what type of node this is and its properties
    cypher_node = """
    MATCH (n)
    WHERE n.id = $id
    RETURN labels(n), properties(n)
    LIMIT 1
    """
    res = execute_ro_query(graph_name, cypher_node, {"id": node_id})
    if not (res and res.result_set):
        return None

    labels = list(res.result_set[0][0])
    props = res.result_set[0][1]

    nodes_list: List[Dict[str, Any]] = [
        {"id": node_id, "labels": labels, "properties": props}
    ]
    edges_list: List[Dict[str, Any]] = []
    author = props.get("owner_agent") or props.get("created_by") or props.get("claimed_by") or props.get("reporter_id") or "system"
    ts = props.get("valid_from") or props.get("created_at") or props.get("ts") or 0
    because_parts: List[str] = []

    # 1. Fact
    if "Fact" in labels:
        pred = props.get("predicate", "property")
        val = props.get("value", "")
        # SUPERSEDES history
        cypher_sup = """
        MATCH (f:Fact {id: $id})-[:SUPERSEDES*1..5]->(old:Fact)
        RETURN old.id, old.predicate, old.value, old.valid_from, old.valid_to, old.owner_agent
        """
        res_sup = execute_ro_query(graph_name, cypher_sup, {"id": node_id})
        prev_val = None
        if res_sup and res_sup.result_set:
            curr_id = node_id
            for r in res_sup.result_set:
                old_id, o_pred, o_val, o_vf, o_vt, o_author = r
                nodes_list.append({
                    "id": old_id,
                    "labels": ["Fact"],
                    "properties": {"id": old_id, "predicate": o_pred, "value": o_val, "valid_from": o_vf, "valid_to": o_vt, "owner_agent": o_author}
                })
                edges_list.append({
                    "source": curr_id,
                    "target": old_id,
                    "type": "SUPERSEDES"
                })
                if prev_val is None:
                    prev_val = o_val
                curr_id = old_id

        # DERIVED_FROM event
        cypher_der = """
        MATCH (f:Fact {id: $id})-[:DERIVED_FROM]->(e:Event)
        RETURN e.id, e.summary, e.ts, e.type
        """
        res_der = execute_ro_query(graph_name, cypher_der, {"id": node_id})
        source_event_summary = None
        if res_der and res_der.result_set:
            for r in res_der.result_set:
                eid, esum, ets, etype = r
                nodes_list.append({
                    "id": eid,
                    "labels": ["Event"],
                    "properties": {"id": eid, "summary": esum, "ts": ets, "type": etype}
                })
                edges_list.append({
                    "source": node_id,
                    "target": eid,
                    "type": "DERIVED_FROM"
                })
                source_event_summary = esum

        # Compose summary
        summary = f"Believed '{pred} = {val}'"
        if prev_val:
            summary += f" because it superseded earlier belief '{prev_val}'"
        if source_event_summary:
            summary += f" derived from event observation: '{source_event_summary}'"
        summary += f" recorded by {author}."
        because_parts.append(summary)

    # 2. Hypothesis
    elif "Hypothesis" in labels:
        stmt = props.get("statement", "")
        conf = props.get("confidence", 0.5)
        # SUPPORTED_BY evidence
        cypher_ev = """
        MATCH (h:Hypothesis {id: $id})-[r:SUPPORTED_BY]->(e:Event)
        RETURN e.id, e.summary, e.ts, r.note
        """
        res_ev = execute_ro_query(graph_name, cypher_ev, {"id": node_id})
        evidence_summaries = []
        if res_ev and res_ev.result_set:
            for r in res_ev.result_set:
                eid, esum, ets, rnote = r
                nodes_list.append({
                    "id": eid,
                    "labels": ["Event"],
                    "properties": {"id": eid, "summary": esum, "ts": ets}
                })
                edges_list.append({
                    "source": node_id,
                    "target": eid,
                    "type": "SUPPORTED_BY",
                    "properties": {"note": rnote or ""}
                })
                evidence_summaries.append(esum)

        summary = f"Hypothesis '{stmt}' (confidence: {conf}) is supported by {len(evidence_summaries)} event observation(s)"
        if evidence_summaries:
            summary += f": '{evidence_summaries[0]}'"
        summary += "."
        because_parts.append(summary)

    # 3. Task
    elif "Task" in labels:
        title = props.get("title", "")
        status = props.get("status", "open")
        claimed = props.get("claimed_by")
        cypher_blk = """
        MATCH (blocker:Task)-[:BLOCKS]->(t:Task {id: $id})
        RETURN blocker.id, blocker.title, blocker.status
        """
        res_blk = execute_ro_query(graph_name, cypher_blk, {"id": node_id})
        blockers = []
        if res_blk and res_blk.result_set:
            for r in res_blk.result_set:
                bid, btitle, bstatus = r
                nodes_list.append({
                    "id": bid,
                    "labels": ["Task"],
                    "properties": {"id": bid, "title": btitle, "status": bstatus}
                })
                edges_list.append({
                    "source": bid,
                    "target": node_id,
                    "type": "BLOCKS"
                })
                blockers.append(btitle)

        summary = f"Task '{title}' is {status}"
        if claimed:
            summary += f", claimed by {claimed}"
        if blockers:
            summary += f", blocked by: {', '.join(blockers)}"
        summary += "."
        because_parts.append(summary)

    # 4. Procedure
    elif "Procedure" in labels:
        pname = props.get("name", "")
        pver = props.get("version", 1)
        pstatus = props.get("status", "active")
        cypher_prev = """
        MATCH (new:Procedure {id: $id})-[:PREVIOUS_VERSION]->(old:Procedure)
        RETURN old.id, old.name, old.version, old.status, old.violated_assumption
        """
        res_prev = execute_ro_query(graph_name, cypher_prev, {"id": node_id})
        old_info = None
        if res_prev and res_prev.result_set:
            oid, oname, over, ostatus, oassump = res_prev.result_set[0]
            nodes_list.append({
                "id": oid,
                "labels": ["Procedure"],
                "properties": {"id": oid, "name": oname, "version": over, "status": ostatus, "violated_assumption": oassump}
            })
            edges_list.append({
                "source": node_id,
                "target": oid,
                "type": "PREVIOUS_VERSION"
            })
            old_info = (over, oassump)

        summary = f"Procedure '{pname}' version {pver} ({pstatus})"
        if old_info:
            summary += f" forked from v{old_info[0]} after assumption violation: '{old_info[1]}'"
        summary += "."
        because_parts.append(summary)

    else:
        because_parts.append(f"Node {node_id} of type {labels[0]} exists in the graph.")

    return {
        "node_id": node_id,
        "labels": labels,
        "author": author,
        "timestamp": ts,
        "nodes": nodes_list,
        "edges": edges_list,
        "because": " ".join(because_parts)
    }

