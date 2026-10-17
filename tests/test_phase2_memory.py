"""
Phase 2 verification tests: Episodic and Semantic Memory.
Verifies MEM-1, MEM-2, CON-2, and tenant memory isolation.
"""
import time
import uuid
import pytest
from server.app.auth import authenticate_key
from server.app.graph import execute_ro_query
from server.app.tenancy import provision_agent_key, provision_tenant
from server.app.tools.episodic import (
    end_session_handler,
    log_event_handler,
    recall_episodes_handler,
    start_session_handler,
)
from server.app.tools.semantic import (
    fact_history_handler,
    forget_fact_handler,
    query_facts_handler,
    upsert_fact_handler,
)


@pytest.fixture(scope="module")
def memory_fixture():
    run_id = uuid.uuid4().hex[:6]
    t_acme = f"mem_acme_{run_id}"
    t_globex = f"mem_globex_{run_id}"

    provision_tenant(t_acme, "Acme Memory Corp")
    provision_tenant(t_globex, "Globex Memory Corp")

    acme_key, _ = provision_agent_key(t_acme, "agent_tri_1", "triage")
    globex_key, _ = provision_agent_key(t_globex, "agent_tri_2", "triage")

    ctx_acme, _ = authenticate_key(acme_key)
    ctx_globex, _ = authenticate_key(globex_key)

    return {
        "ctx_acme": ctx_acme,
        "ctx_globex": ctx_globex
    }


def test_episodic_session_and_events(memory_fixture):
    ctx = memory_fixture["ctx_acme"]

    # 1. Start Session 1
    s1 = start_session_handler(ctx)
    assert s1["ok"] is True
    s1_id = s1["session_id"]
    assert s1_id.startswith("sess_")

    # 2. Log events
    e1 = log_event_handler(
        ctx,
        session_id=s1_id,
        event_type="observation",
        summary="High checkout latency observed on payments-svc",
        entities=["payments-svc"]
    )
    assert e1["ok"] is True
    assert e1["event_id"].startswith("evt_")
    assert e1["seq"] == 1

    e2 = log_event_handler(
        ctx,
        session_id=s1_id,
        event_type="action",
        summary="Investigated redis cache",
        entities=["redis-cache"]
    )
    assert e2["ok"] is True
    assert e2["seq"] == 2

    # End session 1
    end_res = end_session_handler(ctx, session_id=s1_id, summary="Completed initial triage of checkout latency")
    assert end_res["ok"] is True

    # 3. Simulate process restart / new session 2 (MEM-1)
    s2 = start_session_handler(ctx)
    assert s2["ok"] is True
    assert s2["session_id"] != s1_id
    assert s2["last_session_summary"] == "Completed initial triage of checkout latency"

    # Recall past episodes for payments-svc
    recall = recall_episodes_handler(ctx, entity="payments-svc")
    assert recall["ok"] is True
    assert len(recall["events"]) == 1
    assert recall["events"][0]["event_id"] == e1["event_id"]


def test_idempotent_event_writes(memory_fixture):
    """CON-2: Repeating log_event with the same idempotency_key returns identical node."""
    ctx = memory_fixture["ctx_acme"]
    s = start_session_handler(ctx)
    s_id = s["session_id"]

    fixed_idem_key = "idem_tx_retry_999"
    res1 = log_event_handler(
        ctx,
        session_id=s_id,
        event_type="observation",
        summary="Network latency burst",
        idempotency_key=fixed_idem_key
    )
    assert res1["ok"] is True
    first_evt_id = res1["event_id"]

    # Retry 4 times
    for _ in range(4):
        retry_res = log_event_handler(
            ctx,
            session_id=s_id,
            event_type="observation",
            summary="Network latency burst",
            idempotency_key=fixed_idem_key
        )
        assert retry_res["ok"] is True
        assert retry_res["event_id"] == first_evt_id

    # Count nodes in graph with this idem_key
    cypher = "MATCH (e:Event {idem_key: $key}) RETURN count(e) AS cnt"
    count_res = execute_ro_query(ctx.graph_name, cypher, {"key": fixed_idem_key})
    assert count_res.result_set[0][0] == 1


def test_semantic_memory_supersession_and_time_travel(memory_fixture):
    """MEM-2: Fact supersession, history tracking, and as_of time-travel queries."""
    ctx = memory_fixture["ctx_acme"]

    # 1. Record initial belief: payments-svc owner is Team Core
    time.sleep(0.01)

    f1 = upsert_fact_handler(
        ctx,
        entity="payments-svc",
        predicate="owner",
        value="Team Core",
        confidence=0.9
    )
    assert f1["ok"] is True
    f1_id = f1["fact_id"]
    assert f1["superseded_fact_id"] is None

    time.sleep(0.02)
    t_between = int(time.time() * 1000)
    time.sleep(0.02)

    # 2. Correct ownership: payments-svc owner is now Team Billing
    f2 = upsert_fact_handler(
        ctx,
        entity="payments-svc",
        predicate="owner",
        value="Team Billing",
        confidence=0.95
    )
    assert f2["ok"] is True
    f2_id = f2["fact_id"]
    assert f2["superseded_fact_id"] == f1_id

    # 3. Query current facts (now): should return Team Billing
    current = query_facts_handler(ctx, entity="payments-svc", predicate="owner")
    assert current["ok"] is True
    assert len(current["facts"]) == 1
    assert current["facts"][0]["value"] == "Team Billing"
    assert current["facts"][0]["fact_id"] == f2_id

    # 4. Time travel query at t_between: should return Team Core
    as_of_res = query_facts_handler(ctx, entity="payments-svc", predicate="owner", as_of=t_between)
    assert as_of_res["ok"] is True
    assert len(as_of_res["facts"]) == 1
    assert as_of_res["facts"][0]["value"] == "Team Core"
    assert as_of_res["facts"][0]["fact_id"] == f1_id

    # 5. Verify SUPERSEDES edge in graph
    cypher_sup = "MATCH (new:Fact {id: $f2})-[:SUPERSEDES]->(old:Fact {id: $f1}) RETURN count(*)"
    sup_res = execute_ro_query(ctx.graph_name, cypher_sup, {"f2": f2_id, "f1": f1_id})
    assert sup_res.result_set[0][0] == 1

    # 6. Fact history
    hist = fact_history_handler(ctx, entity="payments-svc", predicate="owner")
    assert hist["ok"] is True
    assert len(hist["history"]) == 2
    assert hist["history"][0]["value"] == "Team Billing"
    assert hist["history"][1]["value"] == "Team Core"


def test_forget_fact(memory_fixture):
    ctx = memory_fixture["ctx_acme"]

    fact_res = upsert_fact_handler(ctx, entity="cache-host", predicate="ip", value="10.0.0.42")
    f_id = fact_res["fact_id"]

    # Active initially
    res_before = query_facts_handler(ctx, entity="cache-host", predicate="ip")
    assert len(res_before["facts"]) == 1

    # Forget fact
    forget_res = forget_fact_handler(ctx, fact_id=f_id, reason="Decommissioned server")
    assert forget_res["ok"] is True

    # No longer returned in default queries
    res_after = query_facts_handler(ctx, entity="cache-host", predicate="ip")
    assert len(res_after["facts"]) == 0


def test_cross_tenant_memory_isolation(memory_fixture):
    """Confirm Acme's facts and episodes are completely invisible to Globex."""
    ctx_acme = memory_fixture["ctx_acme"]
    ctx_globex = memory_fixture["ctx_globex"]

    # Acme writes secret fact
    upsert_fact_handler(ctx_acme, entity="vault", predicate="secret_code", value="ACME_42")

    # Globex queries for vault secret_code
    globex_facts = query_facts_handler(ctx_globex, entity="vault", predicate="secret_code")
    assert globex_facts["ok"] is True
    assert len(globex_facts["facts"]) == 0
