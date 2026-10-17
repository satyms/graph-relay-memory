"""
Schema and index definitions for tenant graphs.
"""
import time
from server.app.graph import execute_query

TENANT_INDEXES = [
    "CREATE INDEX FOR (t:Task) ON (t.id)",
    "CREATE INDEX FOR (t:Task) ON (t.status)",
    "CREATE INDEX FOR (e:Entity) ON (e.id)",
    "CREATE INDEX FOR (e:Entity) ON (e.name)",
    "CREATE INDEX FOR (f:Fact) ON (f.id)",
    "CREATE INDEX FOR (ev:Event) ON (ev.idem_key)",
    "CREATE INDEX FOR (p:Procedure) ON (p.id)",
    "CREATE INDEX FOR (h:Handoff) ON (h.id)",
    "CREATE INDEX FOR (i:Incident) ON (i.id)",
    "CREATE INDEX FOR (s:Session) ON (s.id)"
]


def init_tenant_schema(graph_name: str, created_at: int = None) -> None:
    """
    Initialize a tenant graph with metadata and all required openCypher indexes.
    """
    now = created_at or int(time.time() * 1000)
    # Ensure graph is instantiated with meta node
    execute_query(graph_name, "MERGE (m:TenantMeta) ON CREATE SET m.initialized_at = $ts", {"ts": now})

    for idx_stmt in TENANT_INDEXES:
        try:
            execute_query(graph_name, idx_stmt)
        except Exception:
            # If index already exists or syntax variation, proceed gracefully
            pass
