"""
Checkpoint 1 — Load test: CON-1
20 concurrent agents compete for 10 tasks.
Exactly 10 winners, 0 duplicates.
"""
import threading
import time
from server.app.auth import AuthContext
from server.app.tenancy import provision_tenant, provision_agent_key
from server.app.queries.coordination import create_task, claim_task


def run_load_test():
    tenant_id = f"lt_{int(time.time())}"
    provision_tenant(tenant_id, "Load Test Co")
    graph = f"tenant_{tenant_id}"

    # Create 10 tasks
    task_ids = [create_task(graph, f"Task {i}", "setup_agent")["task_id"] for i in range(10)]

    NUM_AGENTS = 20
    wins = []
    lock = threading.Lock()

    def agent_run(agent_id: str):
        for task_id in task_ids:
            res = claim_task(graph, task_id, agent_id)
            if res["ok"]:
                with lock:
                    wins.append((agent_id, task_id))

    threads = [threading.Thread(target=agent_run, args=(f"agent_{i}",)) for i in range(NUM_AGENTS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly 10 unique tasks claimed, each by exactly one agent
    claimed_tasks = [w[1] for w in wins]
    assert len(claimed_tasks) == 10, f"Expected 10 wins, got {len(claimed_tasks)}: {wins}"
    assert len(set(claimed_tasks)) == 10, f"Duplicate claims detected: {wins}"
    print(f"✓ CON-1 PASSED: {len(wins)} tasks claimed by {len({w[0] for w in wins})} unique agents")
    return wins


if __name__ == "__main__":
    run_load_test()
