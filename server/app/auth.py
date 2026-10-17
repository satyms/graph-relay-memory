"""
Authentication and Tenant Resolution Layer.
Maps incoming bearer keys to (tenant_id, agent_id, role, graph_name).
Strictly prevents callers from injecting or overriding tenant identity.
"""
from dataclasses import dataclass
import time
from typing import Optional, Tuple
import uuid

from server.app.config import settings
from server.app.queries import control as control_queries
from server.app.tenancy import get_tenant_graph_name, hash_key


@dataclass(frozen=True)
class AuthContext:
    tenant_id: str
    agent_id: str
    role: str
    graph_name: str
    key_hash: str


def authenticate_key(raw_key: str) -> Tuple[Optional[AuthContext], Optional[str]]:
    """
    Authenticate an API key.
    Returns (AuthContext, None) on success, or (None, error_code) on failure.
    """
    if not raw_key or not raw_key.strip():
        return None, "FORBIDDEN"

    key_h = hash_key(raw_key)
    lookup = control_queries.lookup_api_key(key_h)
    if not lookup:
        return None, "FORBIDDEN"

    tenant_id = lookup["tenant_id"]
    agent_id = lookup["agent_id"]
    role = lookup["role"]
    graph_name = get_tenant_graph_name(tenant_id)

    ctx = AuthContext(
        tenant_id=tenant_id,
        agent_id=agent_id,
        role=role,
        graph_name=graph_name,
        key_hash=key_h
    )
    return ctx, None


def authenticate_bearer(header_val: Optional[str]) -> Tuple[Optional[AuthContext], Optional[str]]:
    """Parse 'Bearer <key>' and authenticate."""
    if not header_val:
        return None, "FORBIDDEN"
    parts = header_val.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return authenticate_key(parts[1])
    # Fallback if raw key was passed
    return authenticate_key(header_val)


def verify_admin_token(token: Optional[str]) -> bool:
    """Validate administrative secret token."""
    if not token:
        return False
    parts = token.strip().split()
    candidate = parts[1] if (len(parts) == 2 and parts[0].lower() == "bearer") else token.strip()
    return candidate == settings.admin_token


def log_audit(
    tool: str,
    ok: bool,
    error_code: Optional[str] = None,
    auth_context: Optional[AuthContext] = None,
    tenant_id: Optional[str] = None,
    agent_id: Optional[str] = None
) -> str:
    """
    Record an immutable audit entry in the control graph.
    Returns the audit_id.
    """
    t_id = auth_context.tenant_id if auth_context else tenant_id
    a_id = auth_context.agent_id if auth_context else agent_id
    audit_id = f"aud_{uuid.uuid4().hex[:12]}"
    now = int(time.time() * 1000)

    try:
        control_queries.record_audit_entry(
            audit_id=audit_id,
            ts=now,
            agent_id=a_id,
            tenant_id=t_id,
            tool=tool,
            ok=ok,
            error_code=error_code
        )
    except Exception:
        # Audit failure must not crash the operational path, but is recorded
        pass
    return audit_id
