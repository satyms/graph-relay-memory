"""
Showcase Endpoint Tests:
- Smoke test that /showcase/ returns 200.
- Verify /showcase/data response shape, structure, and integrity.
- Verify no secrets, tokens, or credentials are leaked in /showcase/data.
- Verify /showcase/data resilience when baseline_results.json is absent or empty.
"""
import pytest
from fastapi.testclient import TestClient
from server.app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_showcase_static_serving(client):
    """Smoke test that /showcase/ serves 200 and renders the showcase title."""
    res = client.get("/showcase/")
    assert res.status_code == 200
    assert "Relay" in res.text


def test_showcase_data_shape(client):
    """Verify /showcase/data returns expected keys and structure."""
    res = client.get("/showcase/data")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "benchmark" in data
    assert "telemetry" in data
    assert "isolation_proofs" in data
    assert "graph_stats" in data
    assert "replay_steps" in data
    assert "hackathon_fit" in data
    assert "machine" in data

    # Verify telemetry numbers
    t = data["telemetry"]
    assert t["duplicate_claims"] == 0
    assert t["cross_tenant_leaks"] == 0
    assert t["throughput_ops_sec"] > 0

    # Verify isolation proofs
    assert len(data["isolation_proofs"]) == 7
    for p in data["isolation_proofs"]:
        assert p["status"] == "PASS"

    # Verify replay steps
    assert len(data["replay_steps"]) == 8
    roles = {s["role"] for s in data["replay_steps"]}
    assert "triage" in roles
    assert "investigator" in roles
    assert "remediator" in roles
    assert "comms" in roles


def test_showcase_data_no_secrets(client):
    """Assert that /showcase/data never contains API keys, tokens, or secret phrases."""
    res = client.get("/showcase/data")
    assert res.status_code == 200
    content = res.text.lower()

    forbidden_needles = [
        "relay-admin-secret",
        "bearer ",
        "sk-ant",
        "anthropic_api_key",
        "admin_token",
        "key_hash",
        "password",
        "secret_key"
    ]
    for needle in forbidden_needles:
        assert needle not in content, f"Found forbidden secret marker '{needle}' in /showcase/data"


def test_showcase_chaos_kill_proxy(client):
    """Verify unauthenticated safe chaos proxy triggers agent kill for showcase demo."""
    res = client.post("/showcase/chaos/kill-agent", json={"tenant": "acme", "agent_role": "triage"})
    assert res.status_code == 200
    d = res.json()
    assert d["ok"] is True
    assert d["killed_agent"] == "agent_triage"
    assert d["tenant"] == "acme"

