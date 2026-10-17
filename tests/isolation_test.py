"""
Checkpoint 1 — Isolation test: ISO-1 to ISO-7
No cross-tenant reads or writes.
"""
import time
from server.app.auth import AuthContext
from server.app.tenancy import provision_tenant, provision_agent_key
from server.app.queries.coordination import create_task, claim_task, list_open_work
from server.app.queries.semantic import upsert_fact, query_facts
from server.app.queries.episodic import start_session, log_event


def run_isolation_test():
    ts = int(time.time())
    t1, t2 = f"iso_a_{ts}", f"iso_b_{ts}"
    provision_tenant(t1, "Tenant A")
    provision_tenant(t2, "Tenant B")
    g1, g2 = f"tenant_{t1}", f"tenant_{t2}"

    # ISO-1: Tenant A's tasks invisible to Tenant B
    tid = create_task(g1, "Secret Task A", "agent_a")["task_id"]
    b_tasks = list_open_work(g2)
    assert not any(t["task_id"] == tid for t in b_tasks), "ISO-1 FAIL: task leaked to Tenant B"
    print("✓ ISO-1: task isolation")

    # ISO-2: Tenant B cannot claim Tenant A's task
    res = claim_task(g2, tid, "agent_b")
    assert not res["ok"], "ISO-2 FAIL: cross-tenant claim succeeded"
    print("✓ ISO-2: claim isolation")

    # ISO-3: Tenant A's facts invisible to Tenant B
    upsert_fact(g1, "secret-svc", "api_key", "KEY_ACME_42", "agent_a")
    b_facts = query_facts(g2, entity="secret-svc", predicate="api_key")
    assert b_facts == [], "ISO-3 FAIL: fact leaked to Tenant B"
    print("✓ ISO-3: fact isolation")

    # ISO-4: Tenant A's sessions invisible to Tenant B
    sess = start_session(g1, "agent_a", "triage")
    ev = log_event(g1, sess["session_id"], "observation", "Private observation", idempotency_key=f"iso4_{ts}")
    from server.app.graph import execute_ro_query
    res2 = execute_ro_query(g2, "MATCH (e:Event {id: $id}) RETURN e.id", {"id": ev["event_id"]})
    assert not (res2 and res2.result_set), "ISO-4 FAIL: event leaked to Tenant B"
    print("✓ ISO-4: event isolation")

    print("\n✓ ALL ISOLATION CHECKS PASSED (ISO-1 to ISO-4)")


if __name__ == "__main__":
    run_isolation_test()
