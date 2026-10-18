"""
Feature 2 Tests: Time-Travel Slider.
Tests:
- Create fact v1, then fact v2 (superseding v1).
- Query GET /admin/graph/{tenant}?as_of=<epoch_ms>:
  * as_of before anything: returns no fact.
  * as_of between v1 and v2: returns v1 only.
  * as_of after v2: returns v2 only (with valid_to=None).
- Query GET /admin/timeline/{tenant}:
  * Returns min_ts, max_ts, and markers including fact supersessions.
  * Requires admin token.
"""
import time
import pytest
from fastapi.testclient import TestClient

from server.app.main import app
from server.app.config import settings
from server.app.tenancy import provision_tenant, provision_agent_key
from server.app.queries.semantic import upsert_fact


@pytest.fixture(scope="module")
def timetravel_fixture():
    tenant_id = f"tt_{int(time.time())}"
    provision_tenant(tenant_id, "Time Travel Corp")
    graph_name = f"tenant_{tenant_id}"
    key, key_hash = provision_agent_key(tenant_id, "agent_triage", "triage")

    return {
        "tenant_id": tenant_id,
        "graph_name": graph_name,
    }


def test_time_travel_as_of_fact_snapshots(timetravel_fixture):
    client = TestClient(app)
    tenant_id = timetravel_fixture["tenant_id"]
    graph_name = timetravel_fixture["graph_name"]

    t0 = int(time.time() * 1000)
    time.sleep(0.05)

    # 1. Create Fact v1: payments-svc owner = Team Core
    f1 = upsert_fact(
        graph_name=graph_name,
        entity_name="payments-svc",
        predicate="owner",
        value="Team Core",
        agent_id="agent_triage"
    )
    assert f1["fact_id"] is not None

    time.sleep(0.05)
    t_between = int(time.time() * 1000)
    time.sleep(0.05)

    # 2. Create Fact v2: payments-svc owner = Team Billing (supersedes v1)
    f2 = upsert_fact(
        graph_name=graph_name,
        entity_name="payments-svc",
        predicate="owner",
        value="Team Billing",
        agent_id="agent_triage"
    )
    assert f2["fact_id"] is not None
    assert f2["superseded_fact_id"] == f1["fact_id"]

    time.sleep(0.05)
    t_after = int(time.time() * 1000)

    # Check 1: as_of BEFORE anything (t0) -> returns no fact for payments-svc
    res_before = client.get(f"/admin/graph/{tenant_id}?as_of={t0}")
    assert res_before.status_code == 200
    facts_before = [n for n in res_before.json()["nodes"] if n["type"] == "Fact"]
    assert len(facts_before) == 0

    # Check 2: as_of BETWEEN v1 and v2 (t_between) -> returns v1 only
    res_between = client.get(f"/admin/graph/{tenant_id}?as_of={t_between}")
    assert res_between.status_code == 200
    facts_between = [n for n in res_between.json()["nodes"] if n["type"] == "Fact"]
    assert len(facts_between) == 1
    assert facts_between[0]["properties"]["value"] == "Team Core"

    # Check 3: as_of AFTER v2 (t_after) -> returns v2 only
    res_after = client.get(f"/admin/graph/{tenant_id}?as_of={t_after}")
    assert res_after.status_code == 200
    facts_after = [n for n in res_after.json()["nodes"] if n["type"] == "Fact"]
    assert len(facts_after) == 1
    assert facts_after[0]["properties"]["value"] == "Team Billing"


def test_timeline_endpoint(timetravel_fixture):
    client = TestClient(app)
    tenant_id = timetravel_fixture["tenant_id"]

    # Verify forbidden without admin token
    bad = client.get(f"/admin/timeline/{tenant_id}")
    assert bad.status_code == 403

    # With admin token
    headers = {"Authorization": f"Bearer {settings.admin_token}"}
    res = client.get(f"/admin/timeline/{tenant_id}", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "min_ts" in data
    assert "max_ts" in data
    assert "markers" in data
    assert len(data["markers"]) >= 2
    types = [m["type"] for m in data["markers"]]
    assert "fact_created" in types
    assert "fact_supersession" in types
