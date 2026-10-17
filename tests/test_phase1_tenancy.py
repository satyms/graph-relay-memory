"""
Phase 1 verification tests: Graph core, tenancy isolation, and key auth.
"""
import pytest
from server.app.auth import authenticate_bearer, authenticate_key, log_audit, verify_admin_token
from server.app.graph import execute_query, execute_ro_query
from server.app.queries import control as control_queries
from server.app.tenancy import (
    CONTROL_GRAPH,
    get_tenant_graph_name,
    provision_agent_key,
    provision_tenant,
)


@pytest.fixture(scope="module")
def setup_tenants():
    """Provision Acme and Globex tenants for isolation testing."""
    # Ensure fresh control graph
    control_queries.init_control_schema()

    t_acme = provision_tenant("acme", "Acme Corp")
    t_globex = provision_tenant("globex", "Globex Corporation")

    acme_key, acme_hash = provision_agent_key("acme", "agent_triage_acme", "triage")
    globex_key, globex_hash = provision_agent_key("globex", "agent_triage_globex", "triage")

    return {
        "acme": t_acme,
        "globex": t_globex,
        "acme_key": acme_key,
        "acme_hash": acme_hash,
        "globex_key": globex_key,
        "globex_hash": globex_hash,
    }


def test_tenancy_graph_naming():
    assert get_tenant_graph_name("acme") == "tenant_acme"
    assert get_tenant_graph_name("globex") == "tenant_globex"
    assert get_tenant_graph_name("tenant/evil;drop") == "tenant_tenantevildrop"


def test_tenant_creation_and_isolation(setup_tenants):
    acme_data = setup_tenants["acme"]
    globex_data = setup_tenants["globex"]

    assert acme_data["graph_name"] == "tenant_acme"
    assert globex_data["graph_name"] == "tenant_globex"

    # Query control graph to confirm registration
    acme_node = control_queries.get_tenant("acme")
    globex_node = control_queries.get_tenant("globex")

    assert acme_node is not None
    assert acme_node["name"] == "Acme Corp"
    assert globex_node is not None
    assert globex_node["name"] == "Globex Corporation"


def test_key_authentication_and_tenant_resolution(setup_tenants):
    acme_key = setup_tenants["acme_key"]
    globex_key = setup_tenants["globex_key"]

    # Acme key resolution
    ctx_acme, err = authenticate_key(acme_key)
    assert err is None
    assert ctx_acme is not None
    assert ctx_acme.tenant_id == "acme"
    assert ctx_acme.graph_name == "tenant_acme"
    assert ctx_acme.agent_id == "agent_triage_acme"
    assert ctx_acme.role == "triage"

    # Globex key resolution
    ctx_globex, err = authenticate_key(globex_key)
    assert err is None
    assert ctx_globex is not None
    assert ctx_globex.tenant_id == "globex"
    assert ctx_globex.graph_name == "tenant_globex"
    assert ctx_globex.agent_id == "agent_triage_globex"
    assert ctx_globex.role == "triage"

    # Cross-tenant check: Acme key can NEVER resolve to Globex graph
    assert ctx_acme.graph_name != ctx_globex.graph_name


def test_bearer_header_parsing(setup_tenants):
    acme_key = setup_tenants["acme_key"]
    ctx, err = authenticate_bearer(f"Bearer {acme_key}")
    assert err is None
    assert ctx is not None
    assert ctx.tenant_id == "acme"

    # Malformed / missing header
    ctx_bad, err_bad = authenticate_bearer(None)
    assert ctx_bad is None
    assert err_bad == "FORBIDDEN"

    ctx_invalid, err_invalid = authenticate_bearer("Bearer invalid_key_12345")
    assert ctx_invalid is None
    assert err_invalid == "FORBIDDEN"


def test_key_revocation(setup_tenants):
    key, key_h = provision_agent_key("acme", "temp_agent", "investigator")
    ctx, err = authenticate_key(key)
    assert err is None
    assert ctx is not None

    # Revoke key
    control_queries.revoke_api_key(key_h)

    # Subsequent auth should fail
    ctx_revoked, err_revoked = authenticate_key(key)
    assert ctx_revoked is None
    assert err_revoked == "FORBIDDEN"


def test_audit_logging(setup_tenants):
    ctx_acme, _ = authenticate_key(setup_tenants["acme_key"])

    # Log successful tool invocation
    aud_id = log_audit(
        tool="start_session",
        ok=True,
        auth_context=ctx_acme
    )
    assert aud_id.startswith("aud_")

    # Log failed auth attempt
    aud_fail = log_audit(
        tool="claim_task",
        ok=False,
        error_code="FORBIDDEN",
        tenant_id="acme",
        agent_id="unknown_attacker"
    )
    assert aud_fail.startswith("aud_")

    # Verify audit entries exist in control graph
    cypher = "MATCH (a:AuditEntry {id: $id}) RETURN a.id, a.tool, a.ok"
    res = execute_ro_query(CONTROL_GRAPH, cypher, {"id": aud_id})
    assert len(res.result_set) == 1
    assert res.result_set[0][1] == "start_session"
    assert res.result_set[0][2] is True


def test_admin_token_verification():
    assert verify_admin_token("relay-admin-secret-dev-token") is True
    assert verify_admin_token("Bearer relay-admin-secret-dev-token") is True
    assert verify_admin_token("wrong_token") is False
    assert verify_admin_token(None) is False
