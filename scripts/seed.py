"""
Seed script:
Provisions synthetic scenario data for Acme (tenant A) and Globex (tenant B).
Sets up:
- Service dependency graph (checkout-api -> payments-svc, redis-cache; payments-svc -> postgres-primary)
- Initial facts (including outdated ownership trap: payments-svc owner = Team Core)
- Seed procedures in tenant and shared_runbooks
- API keys for all 4 roles
"""
import time
from typing import Dict, Any

from server.app.graph import execute_query
from server.app.tenancy import provision_tenant, provision_agent_key
from server.app.queries.semantic import upsert_fact
from server.app.queries.procedural import seed_default_runbooks


def seed_tenant(tenant_id: str, company_name: str) -> Dict[str, Any]:
    """Provision tenant graph, seed services, facts, runbooks, and agent keys."""
    tenant = provision_tenant(tenant_id, company_name)
    graph_name = tenant["graph_name"]
    now = int(time.time() * 1000)

    # 1. Create entities and dependency topology
    services_cypher = """
    MERGE (c:Entity {name: 'checkout-api'}) ON CREATE SET c.id = 'ent_checkout', c.kind = 'service', c.created_at = $now
    MERGE (p:Entity {name: 'payments-svc'}) ON CREATE SET p.id = 'ent_payments', p.kind = 'service', p.created_at = $now
    MERGE (r:Entity {name: 'redis-cache'}) ON CREATE SET r.id = 'ent_redis', r.kind = 'service', r.created_at = $now
    MERGE (db:Entity {name: 'postgres-primary'}) ON CREATE SET db.id = 'ent_pg', db.kind = 'host', db.created_at = $now
    MERGE (a:Entity {name: 'auth-svc'}) ON CREATE SET a.id = 'ent_auth', a.kind = 'service', a.created_at = $now

    MERGE (c)-[:DEPENDS_ON]->(p)
    MERGE (c)-[:DEPENDS_ON]->(r)
    MERGE (p)-[:DEPENDS_ON]->(db)
    """
    execute_query(graph_name, services_cypher, {"now": now})

    # 2. Seed initial semantic facts
    owner_val = "Team Core" if "acme" in tenant_id else "Team Alpha"
    upsert_fact(graph_name, entity_name="payments-svc", predicate="owner", value=owner_val, agent_id="agent_seed")
    upsert_fact(graph_name, entity_name="redis-cache", predicate="cluster_mode", value="standalone", agent_id="agent_seed")
    upsert_fact(graph_name, entity_name="checkout-api", predicate="slo_p99_ms", value="250", agent_id="agent_seed")

    # 3. Seed procedural runbooks
    seed_default_runbooks(graph_name)

    # 4. Generate keys for the 4 roles
    roles = ["triage", "investigator", "remediator", "comms"]
    keys = {}
    for r in roles:
        agent_id = f"agent_{r}"
        raw_key, key_hash = provision_agent_key(tenant_id, agent_id, r)
        keys[r] = {"raw_key": raw_key, "agent_id": agent_id}

    return {
        "tenant_id": tenant_id,
        "graph_name": graph_name,
        "keys": keys
    }


def seed_all():
    print("Seeding Shared Runbooks...")
    seed_default_runbooks("shared_runbooks")

    print("Seeding Tenant Acme (Primary Demo Tenant)...")
    acme_info = seed_tenant("acme", "Acme Corporation")
    print(f"Acme provisioned. Triage Key: {acme_info['keys']['triage']['raw_key']}")

    print("Seeding Tenant Globex (Isolation Competitor Tenant)...")
    globex_info = seed_tenant("globex", "Globex Corporation")
    print(f"Globex provisioned. Triage Key: {globex_info['keys']['triage']['raw_key']}")

    print("\n✓ Seed complete. Both tenants and shared runbooks initialized.")


if __name__ == "__main__":
    seed_all()
