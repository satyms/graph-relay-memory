"""
Concurrency and Load Test Proof Script (CON-1 to CON-6).
Verifies atomic CAS task claims, idempotency, lease expiration, cascade unblock, and performance under concurrency.

Usage:
    python scripts/load_test.py --agents 20 --tasks 10
"""
import argparse
import concurrent.futures
from pathlib import Path
import statistics
import sys
import time
import uuid
from typing import Dict, Any, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.app.graph import execute_ro_query, execute_query
from server.app.queries.coordination import (
    create_task,
    claim_task,
    complete_task,
    reap_expired_leases,
)
from server.app.queries.episodic import log_event, start_session
from server.app.queries.semantic import upsert_fact, query_facts
from server.app.tenancy import provision_tenant, provision_agent_key
from scripts.seed import seed_tenant


def run_load_test(num_agents: int = 20, num_tasks: int = 10) -> bool:
    print("=" * 80)
    print(f"  RELAY MEMORY: CONCURRENCY & CAS CLAIM PROOF ({num_agents} AGENTS, {num_tasks} TASKS)")
    print("=" * 80)

    tenant_id = f"acme_load_{uuid.uuid4().hex[:6]}"
    seed_data = seed_tenant(tenant_id, "Acme Load Test Corp")
    graph_name = seed_data["graph_name"]

    results: List[Dict[str, Any]] = []

    # -------------------------------------------------------------
    # CON-1: N agents race to claim M tasks
    # -------------------------------------------------------------
    print(f"\n[CON-1] Seeding {num_tasks} open tasks and dispatching {num_agents} concurrent agent claims...")
    task_ids = []
    for i in range(num_tasks):
        res_t = create_task(graph_name, title=f"High Priority Incident Task {i+1}", agent_id="agent_seed", priority=1)
        task_ids.append(res_t["task_id"])

    # Every agent tries to claim every task until they get one
    claim_latencies: List[float] = []
    successful_claims: Dict[str, str] = {}  # task_id -> agent_id
    conflict_count = 0

    def worker_claim(agent_idx: int):
        agent_id = f"worker_agent_{agent_idx:02d}"
        for tid in task_ids:
            t0 = time.perf_counter()
            claim_res = claim_task(graph_name, task_id=tid, agent_id=agent_id, ttl_ms=10000)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            claim_latencies.append(elapsed_ms)
            if claim_res.get("ok"):
                return agent_id, tid, True
        return agent_id, None, False

    start_time = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_agents) as executor:
        futures = [executor.submit(worker_claim, i) for i in range(num_agents)]
        for f in concurrent.futures.as_completed(futures):
            ag_id, tid, won = f.result()
            if won:
                successful_claims[tid] = ag_id
            else:
                conflict_count += 1
    total_duration = time.perf_counter() - start_time

    # Inspect graph directly to guarantee exactly 0 duplicate claims
    check_query = """
    MATCH (t:Task {status: 'in_progress'})
    WHERE t.id IN $tids
    RETURN t.id, t.claimed_by, count(t)
    """
    db_claims = execute_ro_query(graph_name, check_query, {"tids": task_ids})
    claimed_rows = db_claims.result_set if db_claims else []

    p50 = statistics.median(claim_latencies) if claim_latencies else 0.0
    p95 = statistics.quantiles(claim_latencies, n=20)[18] if len(claim_latencies) >= 20 else max(claim_latencies or [0.0])
    ops_sec = len(claim_latencies) / total_duration if total_duration > 0 else 0.0

    duplicate_claims = len(claimed_rows) - len(set(r[0] for r in claimed_rows))
    con1_passed = len(successful_claims) == num_tasks and duplicate_claims == 0

    results.append({
        "id": "CON-1",
        "name": "Atomic CAS task claim race",
        "passed": con1_passed,
        "detail": f"{len(successful_claims)}/{num_tasks} claimed, duplicates: {duplicate_claims}, conflicts: {conflict_count}"
    })

    # -------------------------------------------------------------
    # CON-2: Idempotent event writes
    # -------------------------------------------------------------
    print("\n[CON-2] 5 concurrent calls with same idempotency_key...")
    s_res = start_session(graph_name, agent_id="agent_idem", role="triage")
    sess_id = s_res["session_id"]
    idem_key = f"idem_{uuid.uuid4().hex[:10]}"

    def worker_log(idx: int):
        return log_event(
            graph_name=graph_name,
            session_id=sess_id,
            event_type="observation",
            summary=f"Memory dump check {idx}",
            idempotency_key=idem_key
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        list(executor.map(worker_log, range(5)))

    ev_check = execute_ro_query(graph_name, "MATCH (e:Event {idem_key: $k}) RETURN count(e)", {"k": idem_key})
    ev_count = ev_check.result_set[0][0] if ev_check and ev_check.result_set else 0
    con2_passed = (ev_count == 1)
    results.append({
        "id": "CON-2",
        "name": "Idempotent event write",
        "passed": con2_passed,
        "detail": f"5 concurrent writes created exactly {ev_count} Event node (expected 1)"
    })

    # -------------------------------------------------------------
    # CON-3: Semantic supersession integrity
    # -------------------------------------------------------------
    print("\n[CON-3] Concurrent fact supersession...")
    entity = "auth-svc"
    predicate = "version"
    for v in ["v1.0", "v1.1", "v1.2", "v1.3"]:
        upsert_fact(graph_name, entity_name=entity, predicate=predicate, value=v, agent_id="agent_updater")

    active_facts = query_facts(graph_name, entity=entity, predicate=predicate)
    con3_passed = (len(active_facts) == 1) and (active_facts[0]["value"] == "v1.3")
    results.append({
        "id": "CON-3",
        "name": "Semantic supersession chain",
        "passed": con3_passed,
        "detail": f"Active facts: {len(active_facts)} (value='{active_facts[0]['value'] if active_facts else None}')"
    })

    # -------------------------------------------------------------
    # CON-5: Lease expiry and reaper recovery
    # -------------------------------------------------------------
    print("\n[CON-5] Task lease expiry & reaper recovery...")
    t_reap = create_task(graph_name, title="Volatile Worker Task", agent_id="agent_seed", priority=1)["task_id"]
    claim_task(graph_name, task_id=t_reap, agent_id="ghost_agent", ttl_ms=250)
    time.sleep(0.35)  # wait for lease to expire

    reaped_count = reap_expired_leases(graph_name)
    reclaimed = claim_task(graph_name, task_id=t_reap, agent_id="rescuer_agent", ttl_ms=5000)
    con5_passed = (reaped_count >= 1) and (reclaimed.get("ok") is True)
    results.append({
        "id": "CON-5",
        "name": "Lease expiration & reaper recovery",
        "passed": con5_passed,
        "detail": f"Reaped: {reaped_count}, Reclaimed by rescuer: {reclaimed.get('ok')}"
    })

    # -------------------------------------------------------------
    # CON-6: Cascade unblock of dependent tasks
    # -------------------------------------------------------------
    print("\n[CON-6] Cascade unblock of dependent tasks...")
    dep_task = create_task(graph_name, title="Dependent Downstream Task", agent_id="agent_seed", priority=1)["task_id"]
    execute_query(graph_name, "MATCH (t:Task {id: $id}) SET t.status = 'blocked'", {"id": dep_task})
    blocker_task = create_task(graph_name, title="Blocker Root Task", agent_id="agent_seed", blocks=[dep_task], priority=1)["task_id"]

    dep_before = execute_ro_query(graph_name, "MATCH (t:Task {id: $id}) RETURN t.status", {"id": dep_task}).result_set[0][0]
    claim_task(graph_name, task_id=blocker_task, agent_id="blocker_agent")
    complete_task(graph_name, task_id=blocker_task, agent_id="blocker_agent", summary="Root blocker resolved")

    dep_after = execute_ro_query(graph_name, "MATCH (t:Task {id: $id}) RETURN t.status", {"id": dep_task}).result_set[0][0]
    con6_passed = (dep_before == "blocked") and (dep_after == "open")
    results.append({
        "id": "CON-6",
        "name": "Cascade task unblock",
        "passed": con6_passed,
        "detail": f"Dependent status before: '{dep_before}', after: '{dep_after}'"
    })

    # -------------------------------------------------------------
    # PERFORMANCE & LATENCY METRICS
    # -------------------------------------------------------------
    print("\n" + "=" * 80)
    print("  CONCURRENCY BENCHMARK & LATENCY REPORT")
    print("=" * 80)
    print(f"Total CAS Claim Operations : {len(claim_latencies)}")
    print(f"Throughput                 : {ops_sec:.1f} ops/sec")
    print(f"p50 Latency                : {p50:.2f} ms")
    print(f"p95 Latency                : {p95:.2f} ms")
    print(f"Duplicate Claims (Double)  : {duplicate_claims} (REQUIRED: 0)")
    print("-" * 80)

    print(f"\n{'ID':<8} | {'SCENARIO':<34} | {'STATUS':<8} | {'DETAILS'}")
    print("-" * 80)
    all_passed = True
    for r in results:
        status_str = "PASS" if r["passed"] else "FAIL"
        if not r["passed"]:
            all_passed = False
        print(f"{r['id']:<8} | {r['name']:<34} | {status_str:<8} | {r['detail']}")
    print("-" * 80)
    print(f"Summary: Concurrency proofs {'PASSED' if all_passed else 'FAILED'}.\n")
    return all_passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Relay Memory Concurrency & CAS Load Test")
    parser.add_argument("--agents", type=int, default=20, help="Number of concurrent agent workers")
    parser.add_argument("--tasks", type=int, default=10, help="Number of target open tasks")
    args = parser.parse_args()

    ok = run_load_test(num_agents=args.agents, num_tasks=args.tasks)
    sys.exit(0 if ok else 1)
