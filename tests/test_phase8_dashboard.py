"""
Phase 8 Dashboard & Admin Endpoints Verification Tests.
Tests FastAPI server endpoints, graph snapshot serialization, and proof runners.
"""
import pytest
from fastapi.testclient import TestClient
from server.app.main import app
from scripts.seed import seed_tenant, seed_default_runbooks


@pytest.fixture(scope="module")
def client():
    seed_default_runbooks("shared_runbooks")
    seed_tenant("acme_dash_test", "Acme Dash Corp")
    with TestClient(app) as test_client:
        yield test_client


def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"


def test_graph_snapshot_endpoint(client):
    res = client.get("/admin/graph/acme_dash_test")
    assert res.status_code == 200
    data = res.json()
    assert "nodes" in data
    assert "edges" in data
    assert data["stats"]["total_nodes"] > 0

    # Verify memory type categorization
    mem_types = {n["memory_type"] for n in data["nodes"]}
    assert "topology" in mem_types
    assert "procedural" in mem_types


def test_dashboard_static_serving(client):
    res = client.get("/dashboard/")
    assert res.status_code == 200
    assert "Relay Graph Memory" in res.text


def test_admin_isolation_test_runner(client):
    res = client.post("/admin/run-isolation-test")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True


def test_admin_load_test_runner(client):
    res = client.post("/admin/run-load-test?agents=5&tasks=3")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
