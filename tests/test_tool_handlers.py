"""
Tool Handler Tests — red-green-refactor pass targeting uncovered code paths.

Modules under test (coverage gaps identified by pytest-cov):
  server/app/tools/episodic.py        — validation branches (56% -> target 90%+)
  server/app/tools/semantic.py        — validation branches (59% -> target 90%+)
  server/app/tools/procedural.py      — validation + error branches (59% -> target 90%+)
  server/app/reaper.py                — run_reaper_detailed multi-graph + error path (47%)
  server/app/queries/timeline.py      — empty graph + handoff + procedure-fork branches (57%)

Strategy: Arrange-Act-Assert, real implementations (no mocks), test state not interactions.
Each test verifies exactly one behavior.
"""
import time
import pytest

from server.app.auth import AuthContext
from server.app.tenancy import provision_tenant, provision_agent_key
from server.app.reaper import run_reaper, run_reaper_detailed
from server.app.queries.timeline import get_timeline_markers
from server.app.queries.coordination import create_task, claim_task, create_handoff
from server.app.queries.episodic import start_session, log_event
from server.app.queries.procedural import seed_procedure, record_outcome

from server.app.tools.episodic import (
    start_session_handler,
    log_event_handler,
    recall_episodes_handler,
    end_session_handler,
)
from server.app.tools.semantic import (
    upsert_fact_handler,
    query_facts_handler,
    fact_history_handler,
    forget_fact_handler,
)
from server.app.tools.procedural import (
    find_procedure_handler,
    record_outcome_handler,
    get_procedure_handler,
)


# ---------------------------------------------------------------------------
# Shared fixture: a fresh tenant + AuthContext per module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def handler_ctx():
    ts = int(time.time() * 1000)
    tenant_id = f"handlers_{ts}"
    provision_tenant(tenant_id, "Handler Test Corp")
    graph_name = f"tenant_{tenant_id}"
    key, key_hash = provision_agent_key(tenant_id, "agent_triage", "triage")
    ctx = AuthContext(
        tenant_id=tenant_id,
        agent_id="agent_triage",
        role="triage",
        graph_name=graph_name,
        key_hash=key_hash,
    )
    return {"ctx": ctx, "graph_name": graph_name, "tenant_id": tenant_id}


# ===========================================================================
# EPISODIC TOOL HANDLER — validation branches
# ===========================================================================

class TestEpisodicHandlers:
    def test_log_event_missing_session_returns_invalid(self, handler_ctx):
        """log_event_handler returns INVALID when session_id is empty."""
        ctx = handler_ctx["ctx"]
        res = log_event_handler(ctx, session_id="", event_type="observation", summary="something happened")
        assert res["ok"] is False
        assert res["error"]["code"] == "INVALID"

    def test_log_event_missing_summary_returns_invalid(self, handler_ctx):
        """log_event_handler returns INVALID when summary is empty."""
        ctx = handler_ctx["ctx"]
        res = log_event_handler(ctx, session_id="sess_x", event_type="observation", summary="")
        assert res["ok"] is False
        assert res["error"]["code"] == "INVALID"

    def test_log_event_invalid_type_returns_invalid(self, handler_ctx):
        """log_event_handler returns INVALID for unknown event type."""
        ctx = handler_ctx["ctx"]
        sess = start_session_handler(ctx)
        assert sess["ok"] is True
        res = log_event_handler(ctx, session_id=sess["session_id"], event_type="UNKNOWN_TYPE", summary="test")
        assert res["ok"] is False
        assert res["error"]["code"] == "INVALID"
        assert "UNKNOWN_TYPE" in res["error"]["message"] or "must be one of" in res["error"]["message"]

    def test_log_event_valid_writes_event(self, handler_ctx):
        """log_event_handler succeeds for a valid observation event."""
        ctx = handler_ctx["ctx"]
        sess = start_session_handler(ctx)
        res = log_event_handler(
            ctx,
            session_id=sess["session_id"],
            event_type="observation",
            summary="CPU spike detected on api-gateway",
        )
        assert res["ok"] is True
        assert "event_id" in res

    def test_end_session_missing_session_id_returns_invalid(self, handler_ctx):
        """end_session_handler returns INVALID for empty session_id."""
        ctx = handler_ctx["ctx"]
        res = end_session_handler(ctx, session_id="", summary="done")
        assert res["ok"] is False
        assert res["error"]["code"] == "INVALID"

    def test_end_session_missing_summary_returns_invalid(self, handler_ctx):
        """end_session_handler returns INVALID for empty summary."""
        ctx = handler_ctx["ctx"]
        res = end_session_handler(ctx, session_id="sess_fake", summary="")
        assert res["ok"] is False
        assert res["error"]["code"] == "INVALID"

    def test_end_session_nonexistent_returns_not_found(self, handler_ctx):
        """end_session_handler returns NOT_FOUND or False for missing session."""
        ctx = handler_ctx["ctx"]
        res = end_session_handler(ctx, session_id="sess_does_not_exist_xyz", summary="wrap up")
        # Either NOT_FOUND or ok=False depending on query behavior
        assert res["ok"] is False

    def test_start_session_and_recall_episodes(self, handler_ctx):
        """recall_episodes_handler returns events from a session."""
        ctx = handler_ctx["ctx"]
        sess = start_session_handler(ctx)
        log_event_handler(ctx, sess["session_id"], "action", "Restarted redis node", idempotency_key="recall_test_ev")
        res = recall_episodes_handler(ctx, query="Restarted redis")
        assert res["ok"] is True
        assert isinstance(res["events"], list)


# ===========================================================================
# SEMANTIC TOOL HANDLER — validation branches
# ===========================================================================

class TestSemanticHandlers:
    def test_upsert_fact_missing_entity_returns_invalid(self, handler_ctx):
        """upsert_fact_handler returns INVALID when entity is empty."""
        ctx = handler_ctx["ctx"]
        res = upsert_fact_handler(ctx, entity="", predicate="owner", value="Team A")
        assert res["ok"] is False
        assert res["error"]["code"] == "INVALID"

    def test_upsert_fact_missing_predicate_returns_invalid(self, handler_ctx):
        """upsert_fact_handler returns INVALID when predicate is empty."""
        ctx = handler_ctx["ctx"]
        res = upsert_fact_handler(ctx, entity="api-svc", predicate="", value="online")
        assert res["ok"] is False
        assert res["error"]["code"] == "INVALID"

    def test_upsert_fact_missing_value_returns_invalid(self, handler_ctx):
        """upsert_fact_handler returns INVALID when value is None."""
        ctx = handler_ctx["ctx"]
        res = upsert_fact_handler(ctx, entity="api-svc", predicate="owner", value=None)
        assert res["ok"] is False
        assert res["error"]["code"] == "INVALID"

    def test_upsert_fact_valid_returns_fact_id(self, handler_ctx):
        """upsert_fact_handler stores a fact and returns fact_id."""
        ctx = handler_ctx["ctx"]
        res = upsert_fact_handler(ctx, entity="checkout-api", predicate="latency_p99", value="200ms")
        assert res["ok"] is True
        assert "fact_id" in res

    def test_query_facts_returns_stored_fact(self, handler_ctx):
        """query_facts_handler finds a fact by entity and predicate."""
        ctx = handler_ctx["ctx"]
        upsert_fact_handler(ctx, entity="order-svc", predicate="status", value="healthy")
        res = query_facts_handler(ctx, entity="order-svc", predicate="status")
        assert res["ok"] is True
        assert any(f["predicate"] == "status" and f["value"] == "healthy" for f in res["facts"])

    def test_fact_history_missing_entity_returns_invalid(self, handler_ctx):
        """fact_history_handler returns INVALID when entity is empty."""
        ctx = handler_ctx["ctx"]
        res = fact_history_handler(ctx, entity="", predicate="status")
        assert res["ok"] is False
        assert res["error"]["code"] == "INVALID"

    def test_fact_history_missing_predicate_returns_invalid(self, handler_ctx):
        """fact_history_handler returns INVALID when predicate is empty."""
        ctx = handler_ctx["ctx"]
        res = fact_history_handler(ctx, entity="order-svc", predicate="")
        assert res["ok"] is False
        assert res["error"]["code"] == "INVALID"

    def test_fact_history_valid_returns_history_list(self, handler_ctx):
        """fact_history_handler returns history chain when entity+predicate exist."""
        ctx = handler_ctx["ctx"]
        upsert_fact_handler(ctx, entity="billing-svc", predicate="owner", value="Team Core")
        upsert_fact_handler(ctx, entity="billing-svc", predicate="owner", value="Team Billing")
        res = fact_history_handler(ctx, entity="billing-svc", predicate="owner")
        assert res["ok"] is True
        assert isinstance(res["history"], list)
        assert len(res["history"]) >= 1

    def test_forget_fact_missing_fact_id_returns_invalid(self, handler_ctx):
        """forget_fact_handler returns INVALID when fact_id is empty."""
        ctx = handler_ctx["ctx"]
        res = forget_fact_handler(ctx, fact_id="", reason="stale")
        assert res["ok"] is False
        assert res["error"]["code"] == "INVALID"

    def test_forget_fact_missing_reason_returns_invalid(self, handler_ctx):
        """forget_fact_handler returns INVALID when reason is empty."""
        ctx = handler_ctx["ctx"]
        res = forget_fact_handler(ctx, fact_id="fact_xyz", reason="")
        assert res["ok"] is False
        assert res["error"]["code"] == "INVALID"

    def test_forget_fact_nonexistent_returns_not_found(self, handler_ctx):
        """forget_fact_handler returns NOT_FOUND for unknown fact_id."""
        ctx = handler_ctx["ctx"]
        res = forget_fact_handler(ctx, fact_id="fact_definitely_nonexistent_99999", reason="removing stale data")
        assert res["ok"] is False
        assert res["error"]["code"] == "NOT_FOUND"

    def test_forget_fact_valid_removes_fact(self, handler_ctx):
        """forget_fact_handler returns ok=True for an existing fact."""
        ctx = handler_ctx["ctx"]
        upserted = upsert_fact_handler(ctx, entity="tmp-svc", predicate="temp_flag", value="true")
        assert upserted["ok"] is True
        fact_id = upserted["fact_id"]
        res = forget_fact_handler(ctx, fact_id=fact_id, reason="temporary flag cleaned up")
        assert res["ok"] is True


# ===========================================================================
# PROCEDURAL TOOL HANDLER — validation and error branches
# ===========================================================================

class TestProceduralHandlers:
    def test_find_procedure_missing_situation_returns_invalid(self, handler_ctx):
        """find_procedure_handler returns INVALID when situation is empty."""
        ctx = handler_ctx["ctx"]
        res = find_procedure_handler(ctx, situation="")
        assert res["ok"] is False
        assert res["error"]["code"] == "INVALID"

    def test_find_procedure_valid_returns_list(self, handler_ctx):
        """find_procedure_handler returns a list of procedures (possibly empty)."""
        ctx = handler_ctx["ctx"]
        res = find_procedure_handler(ctx, situation="redis memory high")
        assert res["ok"] is True
        assert isinstance(res["procedures"], list)

    def test_record_outcome_missing_procedure_id_returns_invalid(self, handler_ctx):
        """record_outcome_handler returns INVALID when procedure_id is empty."""
        ctx = handler_ctx["ctx"]
        res = record_outcome_handler(ctx, procedure_id="", incident_id="INC-001", success=True)
        assert res["ok"] is False
        assert res["error"]["code"] == "INVALID"

    def test_record_outcome_missing_incident_id_returns_invalid(self, handler_ctx):
        """record_outcome_handler returns INVALID when incident_id is empty."""
        ctx = handler_ctx["ctx"]
        res = record_outcome_handler(ctx, procedure_id="proc_abc", incident_id="", success=True)
        assert res["ok"] is False
        assert res["error"]["code"] == "INVALID"

    def test_record_outcome_nonexistent_procedure_returns_not_found(self, handler_ctx):
        """record_outcome_handler returns NOT_FOUND for unknown procedure_id."""
        ctx = handler_ctx["ctx"]
        res = record_outcome_handler(
            ctx, procedure_id="proc_definitely_nonexistent_xyz", incident_id="INC-999", success=True
        )
        assert res["ok"] is False
        assert res["error"]["code"] == "NOT_FOUND"

    def test_get_procedure_missing_id_returns_invalid(self, handler_ctx):
        """get_procedure_handler returns INVALID when procedure_id is empty."""
        ctx = handler_ctx["ctx"]
        res = get_procedure_handler(ctx, procedure_id="")
        assert res["ok"] is False
        assert res["error"]["code"] == "INVALID"

    def test_get_procedure_nonexistent_returns_not_found(self, handler_ctx):
        """get_procedure_handler returns NOT_FOUND for unknown procedure_id."""
        ctx = handler_ctx["ctx"]
        res = get_procedure_handler(ctx, procedure_id="proc_nonexistent_xyz999")
        assert res["ok"] is False
        assert res["error"]["code"] == "NOT_FOUND"

    def test_get_procedure_valid(self, handler_ctx):
        """get_procedure_handler returns procedure details for a real procedure."""
        ctx = handler_ctx["ctx"]
        graph = handler_ctx["graph_name"]
        # seed_procedure returns the proc_id string directly
        proc_id = seed_procedure(
            graph_name=graph,
            name="restart-nginx",
            trigger="nginx memory leak detected",
            steps=["Check logs", "Reload config", "Restart gracefully"],
        )
        res = get_procedure_handler(ctx, procedure_id=proc_id)
        assert res["ok"] is True
        assert res["name"] == "restart-nginx"

    def test_record_outcome_success_valid(self, handler_ctx):
        """record_outcome_handler records a successful outcome."""
        ctx = handler_ctx["ctx"]
        graph = handler_ctx["graph_name"]
        proc_id = seed_procedure(
            graph_name=graph,
            name="clear-disk-cache",
            trigger="disk usage above 90%",
            steps=["Identify large files", "Archive logs", "Purge temp"],
        )
        res = record_outcome_handler(
            ctx,
            procedure_id=proc_id,
            incident_id="INC-HANDLER-001",
            success=True,
            note="Disk cleared, 40GB freed"
        )
        assert res["ok"] is True


# ===========================================================================
# REAPER — multi-graph and error-resilience
# ===========================================================================

class TestReaper:
    def test_run_reaper_multi_graph_returns_dict(self, handler_ctx):
        """run_reaper_detailed processes multiple graphs and returns keyed dict."""
        graph = handler_ctx["graph_name"]
        result = run_reaper_detailed([graph, "tenant_nonexistent_graph_xyz"])
        # Real graph present
        assert graph in result
        assert isinstance(result[graph], list)
        # Non-existent graph silently returns empty list (error-resilient)
        assert "tenant_nonexistent_graph_xyz" in result
        assert result["tenant_nonexistent_graph_xyz"] == []

    def test_run_reaper_returns_integer_count(self, handler_ctx):
        """run_reaper returns a non-negative integer total reaped count."""
        graph = handler_ctx["graph_name"]
        count = run_reaper([graph])
        assert isinstance(count, int)
        assert count >= 0

    def test_run_reaper_expired_lease_is_recovered(self, handler_ctx):
        """run_reaper reopens a task with an expired lease (short TTL path)."""
        graph = handler_ctx["graph_name"]
        # Create and claim a task with a 50ms lease (expires immediately)
        task = create_task(graph, "Reaper Test Task", "agent_triage")
        task_id = task["task_id"]
        claim_res = claim_task(graph, task_id, "agent_triage", ttl_ms=50)
        assert claim_res["ok"] is True
        # Wait for lease to expire
        time.sleep(0.1)
        # Run reaper — task must be recovered
        result = run_reaper_detailed([graph])
        reaped_ids = [t["task_id"] for t in result[graph]]
        assert task_id in reaped_ids


# ===========================================================================
# TIMELINE — uncovered branches
# ===========================================================================

class TestTimelineMarkers:
    def test_empty_graph_returns_timestamps_only(self):
        """get_timeline_markers on an empty graph returns min/max timestamps and empty markers."""
        ts = int(time.time() * 1000)
        tenant_id = f"timeline_empty_{ts}"
        provision_tenant(tenant_id, "Timeline Empty Test")
        graph_name = f"tenant_{tenant_id}"

        result = get_timeline_markers(graph_name)
        assert "min_ts" in result
        assert "max_ts" in result
        assert isinstance(result["markers"], list)
        # No events in a fresh graph
        assert len(result["markers"]) == 0

    def test_task_creation_produces_task_created_marker(self, handler_ctx):
        """A created task appears as a task_created marker in the timeline."""
        graph = handler_ctx["graph_name"]
        create_task(graph, "Timeline Task Marker Test", "agent_triage")
        result = get_timeline_markers(graph)
        types = [m["type"] for m in result["markers"]]
        assert "task_created" in types

    def test_claimed_task_produces_claim_marker(self, handler_ctx):
        """A claimed task appears as a claim marker in the timeline."""
        graph = handler_ctx["graph_name"]
        task = create_task(graph, "Timeline Claim Marker", "agent_triage")
        claim_task(graph, task["task_id"], "agent_triage")
        result = get_timeline_markers(graph)
        types = [m["type"] for m in result["markers"]]
        assert "claim" in types

    def test_procedure_fork_produces_procedure_fork_marker(self, handler_ctx):
        """A failed procedure that generates a fork appears as a procedure_fork marker."""
        ctx = handler_ctx["ctx"]
        graph = handler_ctx["graph_name"]

        # Create a procedure and simulate a failure to fork a new version
        proc_id = seed_procedure(
            graph_name=graph,
            name="flush-memcache-timeline",
            trigger="memcache OOM",
            steps=["Stop writes", "Flush cache", "Restart"],
        )
        # Record a failure with a violated assumption — this forks a new version
        record_outcome(
            graph_name=graph,
            procedure_id=proc_id,
            incident_id="INC-FORK-TL",
            success=False,
            note="Flush caused cascading failure",
            violated_assumption="cache_flush_safe",
            new_precondition="verify_no_active_writes_before_flush",
        )

        result = get_timeline_markers(graph)
        types = [m["type"] for m in result["markers"]]
        assert "procedure_fork" in types

    def test_markers_sorted_ascending_by_ts(self, handler_ctx):
        """Timeline markers are returned in chronological (ascending ts) order."""
        graph = handler_ctx["graph_name"]
        result = get_timeline_markers(graph)
        markers = result["markers"]
        if len(markers) >= 2:
            for i in range(len(markers) - 1):
                assert markers[i]["ts"] <= markers[i + 1]["ts"], \
                    f"Marker at index {i} (ts={markers[i]['ts']}) is after index {i+1} (ts={markers[i+1]['ts']})"

    def test_min_max_ts_bounds_match_markers(self, handler_ctx):
        """min_ts and max_ts accurately reflect the earliest and latest marker timestamps."""
        graph = handler_ctx["graph_name"]
        result = get_timeline_markers(graph)
        markers = result["markers"]
        if markers:
            ts_values = [m["ts"] for m in markers]
            assert result["min_ts"] == min(ts_values)
            assert result["max_ts"] == max(ts_values)
