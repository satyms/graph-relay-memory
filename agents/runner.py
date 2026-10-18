"""
Runner script for incident response agent team.
Coordinates Triage -> Investigator -> Remediator -> Comms workflow for a tenant.
Demonstrates:
- Memory persistence & retrieval across agents
- Atomic task claims
- Failure catching and procedural learning fork (v1 -> v2)
- Explicit Handoff nodes
"""
import argparse
import logging
import os
import sys

from server.app.auth import AuthContext
from agents.base import RelayAgent
from agents.prompts import (
    TRIAGE_PROMPT,
    INVESTIGATOR_PROMPT,
    REMEDIATOR_PROMPT,
    COMMS_PROMPT
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("runner")


def run_incident_team(tenant_id: str):
    log.info("Starting incident response team for tenant: %s", tenant_id)

    # Resolve context for each role in tenant
    def _get_ctx(role: str) -> AuthContext:
        agent_id = f"agent_{role}"
        return AuthContext(
            tenant_id=tenant_id,
            agent_id=agent_id,
            role=role,
            graph_name=f"tenant_{tenant_id}",
            key_hash=f"hash_{agent_id}"
        )

    # 1. Triage Phase
    log.info("=== STEP 1: TRIAGE ===")
    triage = RelayAgent(_get_ctx("triage"), TRIAGE_PROMPT, "Triage Agent")
    triage.start()
    triage_actions = triage.run_turn(
        "Alert: p99 latency on checkout-api spiked to 3200ms. "
        "Open a sev1 incident 'INC-1: Checkout latency spike', form initial hypothesis, "
        "create tasks, and hand off to agent_investigator."
    )
    log.info("Triage executed %d actions in graph memory.", len(triage_actions))

    # 2. Investigator Phase
    log.info("=== STEP 2: INVESTIGATOR ===")
    inv = RelayAgent(_get_ctx("investigator"), INVESTIGATOR_PROMPT, "Investigator Agent")
    inv.start()
    inv_actions = inv.run_turn(
        "Accept the triage handoff. Claim the investigation task. "
        "Inspect dependency topology and facts for payments-svc, redis-cache, and auth-svc. "
        "Attach evidence for high cache miss rates, rule out auth-svc, and hand off to agent_remediator."
    )
    log.info("Investigator executed %d actions in graph memory.", len(inv_actions))

    # 3. Remediator Phase
    log.info("=== STEP 3: REMEDIATOR ===")
    rem = RelayAgent(_get_ctx("remediator"), REMEDIATOR_PROMPT, "Remediator Agent")
    rem.start()
    rem_actions = rem.run_turn(
        "Accept the handoff. Find applicable runbooks for 'redis cache latency'. "
        "Execute restart-redis procedure. Notice that it fails because of a recent deployment 20m ago. "
        "Record the failure outcome with violated_assumption 'assumed stale cache but deployment broke schema' "
        "and new_precondition 'check for a deployment in the last 30 minutes before restarting cache'. "
        "Then execute rollback-deploy, complete the task, and resolve the blockage."
    )
    log.info("Remediator executed %d actions in graph memory.", len(rem_actions))

    # 4. Comms Phase
    log.info("=== STEP 4: COMMS ===")
    comms = RelayAgent(_get_ctx("comms"), COMMS_PROMPT, "Comms Agent")
    comms.start()
    comms_actions = comms.run_turn(
        "Review the incident timeline, check current facts and procedure versions. "
        "Log a summary event with the resolution and learnings."
    )
    log.info("Comms executed %d actions in graph memory.", len(comms_actions))

    log.info("✓ Full 4-agent incident lifecycle completed successfully for tenant %s.", tenant_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="acme", help="Tenant ID to run (default: acme)")
    args = parser.parse_args()
    run_incident_team(args.tenant)
