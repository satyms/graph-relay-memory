"""
Baseline Memory Implementation (Fair, Honest Comparison).

This file implements a typical, reasonable flat memory store as commonly built
for LLM agents without an atomic graph database:
- Per-tenant / per-user in-memory dictionary of text entries and dictionaries.
- Recency or LRU cap (defaults to 100 entries per tenant).
- Simple keyword / substring similarity matching for recall.
- In-memory dict storage for tasks, runbooks, and facts.

WHAT IT DOES:
1. remember(tenant_id, text, metadata): Appends a text record with metadata, bounded by capacity.
2. recall(tenant_id, query, limit): Keyword / token overlap recall across stored records.
3. claim_task(tenant_id, task_id, agent_id): Naive read-then-write task claim check (no atomic CAS).
4. find_runbook(tenant_id, query): Keyword search over registered runbooks.
5. update_fact(tenant_id, key, value): Key-value dict overwriting (no temporal valid_to / SUPERSEDES history).

WHAT IT DOES NOT DO:
1. No multi-tenant data boundary at the storage engine level — all tenants coexist in a shared dict/process;
   if tenant scoping is queried without an exact match, fallback or global search can leak cross-tenant keys.
2. No atomic compare-and-set (CAS) or database-level lock on claims; susceptible to concurrency race conditions.
3. Overwrites previous facts on update; no immutable history, no valid_from/valid_to, no SUPERSEDES provenance,
   so historical 'as_of' queries return only the latest overwritten value or nothing.
4. No graph edges for causal provenance (e.g. DERIVED_FROM, SUPPORTED_BY, BLOCKS).
"""
import time
from typing import Any, Dict, List, Optional


class FlatMemoryStore:
    def __init__(self, capacity_per_tenant: int = 100):
        self.capacity = capacity_per_tenant
        # Per-tenant episodic/semantic memories: tenant -> list of dicts
        self.memories: Dict[str, List[Dict[str, Any]]] = {}
        # Key-value facts: tenant -> dict(key -> value)
        self.facts: Dict[str, Dict[str, Any]] = {}
        # Tasks: tenant -> dict(task_id -> task_dict)
        self.tasks: Dict[str, Dict[str, Any]] = {}
        # Runbooks: global list of runbook dicts
        self.runbooks: List[Dict[str, Any]] = [
            {"id": "rb_restart_redis", "title": "Restart Redis Cache", "steps": ["restart service", "verify ping"]},
            {"id": "rb_rollback_deploy", "title": "Rollback Deployment", "steps": ["revert sha", "re-deploy"]},
        ]

    def remember(self, tenant_id: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Store a text entry with timestamp, bounded by LRU capacity."""
        if tenant_id not in self.memories:
            self.memories[tenant_id] = []

        entry = {
            "text": text,
            "metadata": metadata or {},
            "ts": int(time.time() * 1000)
        }
        self.memories[tenant_id].append(entry)
        if len(self.memories[tenant_id]) > self.capacity:
            self.memories[tenant_id].pop(0)  # LRU eviction
        return entry

    def recall(self, tenant_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Keyword / token overlap recall."""
        entries = self.memories.get(tenant_id, [])
        query_tokens = set(query.lower().split())

        scored = []
        for e in entries:
            text_tokens = set(e["text"].lower().split())
            overlap = len(query_tokens.intersection(text_tokens))
            if overlap > 0 or not query_tokens:
                scored.append((overlap, e))

        scored.sort(key=lambda x: (x[0], x[1]["ts"]), reverse=True)
        return [item[1] for item in scored[:limit]]

    def create_task(self, tenant_id: str, task_id: str, title: str) -> Dict[str, Any]:
        """Create a task in tenant scope."""
        if tenant_id not in self.tasks:
            self.tasks[tenant_id] = {}
        task = {
            "task_id": task_id,
            "title": title,
            "status": "open",
            "claimed_by": None,
            "claimed_at": None
        }
        self.tasks[tenant_id][task_id] = task
        return task

    def claim_task(self, tenant_id: str, task_id: str, agent_id: str) -> Dict[str, Any]:
        """
        Naive task claim (non-atomic check-then-set).
        In a multi-threaded scenario, multiple workers reading status=='open' simultaneously
        can both assign claimed_by, resulting in duplicate claims.
        """
        tenant_tasks = self.tasks.get(tenant_id, {})
        task = tenant_tasks.get(task_id)
        if not task:
            return {"ok": False, "error": "Task not found"}

        # Simulate non-atomic read followed by slight evaluation delay then write
        if task["status"] == "open":
            time.sleep(0.001)  # Context switch window typical in application code without DB transaction
            task["status"] = "in_progress"
            task["claimed_by"] = agent_id
            task["claimed_at"] = int(time.time() * 1000)
            return {"ok": True, "task_id": task_id, "claimed_by": agent_id}
        else:
            return {"ok": False, "error": "Task already claimed"}

    def update_fact(self, tenant_id: str, key: str, value: str) -> None:
        """
        Overwrite a fact in flat key-value dictionary.
        Does not preserve temporal history, valid_from, or valid_to.
        """
        if tenant_id not in self.facts:
            self.facts[tenant_id] = {}
        self.facts[tenant_id][key] = value

    def get_fact(self, tenant_id: str, key: str, as_of: Optional[int] = None) -> Optional[str]:
        """
        Retrieve fact.
        Notice: Flat memory has no point-in-time index; as_of cannot reconstruct earlier states.
        It can only return the current overwritten value.
        """
        return self.facts.get(tenant_id, {}).get(key)

    def find_runbook(self, query: str) -> List[Dict[str, Any]]:
        """Simple keyword search on runbooks."""
        q = query.lower()
        return [rb for rb in self.runbooks if any(tok in rb["title"].lower() for tok in q.split())]

    def query_cross_tenant_search(self, caller_tenant_id: str, target_tenant_id: Optional[str] = None) -> List[str]:
        """
        Simulates how an in-memory or unstructured store with shared index
        allows caller to inspect or search across tenant partitions if tenant isn't strictly isolated.
        """
        if target_tenant_id and target_tenant_id in self.facts:
            return list(self.facts[target_tenant_id].keys())
        return []
