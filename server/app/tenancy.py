"""
Tenant graph lifecycle and isolation management.
Ensures every tenant is mapped to an isolated graph inside FalkorDB.
"""
import hashlib
import time
import uuid
from typing import Any, Dict, Tuple
from server.app.queries import control as control_queries
from server.app.queries import schema as schema_queries

CONTROL_GRAPH = "control"
SHARED_RUNBOOKS_GRAPH = "shared_runbooks"


def hash_key(raw_key: str) -> str:
    """Compute deterministic SHA-256 hash of an API key."""
    return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()


def get_tenant_graph_name(tenant_id: str) -> str:
    """
    Format the isolated graph name for a given tenant.
    Never accepts user override; strictly enforced as tenant_<id>.
    """
    # Sanitize tenant_id to allow alphanumeric and underscores
    clean_id = "".join(c for c in tenant_id if c.isalnum() or c in ("_", "-"))
    return f"tenant_{clean_id}"


def provision_tenant(tenant_id: str, name: str) -> Dict[str, Any]:
    """
    Create tenant in control graph, initialize tenant graph with indexes.
    Returns tenant descriptor.
    """
    control_queries.init_control_schema()
    now = int(time.time() * 1000)
    
    # 1. Register in control graph
    tenant = control_queries.create_tenant(tenant_id=tenant_id, name=name, created_at=now)
    
    # 2. Provision and index the tenant's individual graph
    graph_name = get_tenant_graph_name(tenant_id)
    schema_queries.init_tenant_schema(graph_name, created_at=now)
    
    return {
        "tenant_id": tenant_id,
        "name": name,
        "graph_name": graph_name,
        "created_at": now
    }


def provision_agent_key(tenant_id: str, agent_id: str, role: str) -> Tuple[str, str]:
    """
    Generate and persist a bearer API key for an agent in a tenant.
    Returns (raw_key, key_hash). The raw_key is only returned once upon creation.
    """
    raw_key = f"rel_{uuid.uuid4().hex}"
    key_h = hash_key(raw_key)
    now = int(time.time() * 1000)
    
    control_queries.create_api_key(
        key_hash=key_h,
        tenant_id=tenant_id,
        agent_id=agent_id,
        role=role,
        created_at=now
    )
    return raw_key, key_h
