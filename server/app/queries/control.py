"""
Named Cypher queries for the control graph.
Manages Tenants, ApiKeys, and AuditEntries.
"""
from typing import Any, Dict, List, Optional
from server.app.graph import execute_query, execute_ro_query

CONTROL_GRAPH = "control"


def init_control_schema() -> None:
    """Create indexes for the control graph."""
    # Ensure control graph exists
    execute_query(CONTROL_GRAPH, "MERGE (s:SystemMeta {name: 'control'})")
    
    # Create indexes; catch already indexed errors safely
    indexes = [
        "CREATE INDEX FOR (t:Tenant) ON (t.id)",
        "CREATE INDEX FOR (k:ApiKey) ON (k.key_hash)",
        "CREATE INDEX FOR (a:AuditEntry) ON (a.id)",
        "CREATE INDEX FOR (a:AuditEntry) ON (a.ts)"
    ]
    for idx_stmt in indexes:
        try:
            execute_query(CONTROL_GRAPH, idx_stmt)
        except Exception:
            pass


def create_tenant(tenant_id: str, name: str, created_at: int) -> Dict[str, Any]:
    """Create or return an existing tenant in the control graph."""
    cypher = """
    MERGE (t:Tenant {id: $tenant_id})
    ON CREATE SET t.name = $name, t.created_at = $created_at
    RETURN t.id AS id, t.name AS name, t.created_at AS created_at
    """
    res = execute_query(CONTROL_GRAPH, cypher, {
        "tenant_id": tenant_id,
        "name": name,
        "created_at": created_at
    })
    if res and res.result_set:
        row = res.result_set[0]
        return {"id": row[0], "name": row[1], "created_at": row[2]}
    return {"id": tenant_id, "name": name, "created_at": created_at}


def get_tenant(tenant_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve tenant info from the control graph."""
    cypher = """
    MATCH (t:Tenant {id: $tenant_id})
    RETURN t.id AS id, t.name AS name, t.created_at AS created_at
    """
    res = execute_ro_query(CONTROL_GRAPH, cypher, {"tenant_id": tenant_id})
    if res and res.result_set:
        row = res.result_set[0]
        return {"id": row[0], "name": row[1], "created_at": row[2]}
    return None


def create_api_key(key_hash: str, tenant_id: str, agent_id: str, role: str, created_at: int) -> bool:
    """Store a hashed API key and link it to the tenant."""
    cypher = """
    MATCH (t:Tenant {id: $tenant_id})
    MERGE (k:ApiKey {key_hash: $key_hash})
    ON CREATE SET k.agent_id = $agent_id, k.role = $role, k.created_at = $created_at, k.revoked = false
    MERGE (k)-[:BELONGS_TO]->(t)
    RETURN k.key_hash
    """
    res = execute_query(CONTROL_GRAPH, cypher, {
        "key_hash": key_hash,
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "role": role,
        "created_at": created_at
    })
    return bool(res and res.result_set)


def lookup_api_key(key_hash: str) -> Optional[Dict[str, Any]]:
    """Resolve a hashed API key to (tenant_id, agent_id, role)."""
    cypher = """
    MATCH (k:ApiKey {key_hash: $key_hash, revoked: false})-[:BELONGS_TO]->(t:Tenant)
    RETURN t.id AS tenant_id, k.agent_id AS agent_id, k.role AS role
    """
    res = execute_ro_query(CONTROL_GRAPH, cypher, {"key_hash": key_hash})
    if res and res.result_set:
        row = res.result_set[0]
        return {
            "tenant_id": row[0],
            "agent_id": row[1],
            "role": row[2]
        }
    return None


def revoke_api_key(key_hash: str) -> bool:
    """Revoke an API key."""
    cypher = """
    MATCH (k:ApiKey {key_hash: $key_hash})
    SET k.revoked = true
    RETURN k.key_hash
    """
    res = execute_query(CONTROL_GRAPH, cypher, {"key_hash": key_hash})
    return bool(res and res.result_set)


def record_audit_entry(
    audit_id: str,
    ts: int,
    agent_id: Optional[str],
    tenant_id: Optional[str],
    tool: str,
    ok: bool,
    error_code: Optional[str]
) -> str:
    """Record an audit entry for a tool or auth invocation."""
    cypher = """
    CREATE (a:AuditEntry {
        id: $audit_id,
        ts: $ts,
        agent_id: $agent_id,
        tenant_id: $tenant_id,
        tool: $tool,
        ok: $ok,
        error_code: $error_code
    })
    WITH a
    OPTIONAL MATCH (t:Tenant {id: $tenant_id})
    FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END | CREATE (a)-[:ABOUT]->(t))
    RETURN a.id AS id
    """
    res = execute_query(CONTROL_GRAPH, cypher, {
        "audit_id": audit_id,
        "ts": ts,
        "agent_id": agent_id or "anonymous",
        "tenant_id": tenant_id or "",
        "tool": tool,
        "ok": ok,
        "error_code": error_code or ""
    })
    return audit_id
