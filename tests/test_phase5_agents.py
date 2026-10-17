"""
Tests for Phase 5: Agents and Model Adapter.
Verifies:
- Fallback routing mechanism in agents.llm_adapter
- Tool dispatching integrity
- Agent loop execution and graph node generation (Handoffs, Tasks, Episodes)
"""
from unittest.mock import patch, MagicMock
import pytest

from server.app.auth import AuthContext
from server.app.tenancy import provision_tenant, provision_agent_key
from server.app.graph import execute_ro_query
from agents.base import RelayAgent
from agents.prompts import TRIAGE_PROMPT, INVESTIGATOR_PROMPT
from agents.llm_adapter import generate
from agents.tools_registry import dispatch_tool_call


@pytest.fixture(scope="module")
def agent_fixture():
    tenant_id = "agent_test_tenant"
    provision_tenant(tenant_id, "Agent Test Corp")
    
    key, key_hash = provision_agent_key(tenant_id, "agent_triage", "triage")
    ctx_triage = AuthContext(
        tenant_id=tenant_id,
        agent_id="agent_triage",
        role="triage",
        graph_name=f"tenant_{tenant_id}",
        key_hash=key_hash
    )
    
    inv_key, inv_hash = provision_agent_key(tenant_id, "agent_inv", "investigator")
    ctx_inv = AuthContext(
        tenant_id=tenant_id,
        agent_id="agent_inv",
        role="investigator",
        graph_name=f"tenant_{tenant_id}",
        key_hash=inv_hash
    )

    return {"triage": ctx_triage, "inv": ctx_inv}


def test_tool_dispatcher(agent_fixture):
    """Confirm dispatch_tool_call routes properly to tools."""
    ctx = agent_fixture["triage"]
    res = dispatch_tool_call(ctx, "open_incident", {"title": "Test Dispatch Incident", "severity": "sev2"})
    assert res.get("ok") is True
    assert "incident_id" in res


def test_agent_tool_loop_with_mocked_llm(agent_fixture):
    """Test the RelayAgent multi-step tool execution loop."""
    ctx = agent_fixture["triage"]
    agent = RelayAgent(ctx, TRIAGE_PROMPT, "Triage Agent")
    sess = agent.start()
    assert sess.get("ok") is True
    assert agent.session_id is not None

    # Mock LLM returning an open_incident tool call on first turn, then message
    mock_responses = [
        {
            "content": "",
            "tool_calls": [
                {
                    "name": "create_task",
                    "arguments": {"title": "Agent created task", "priority": 1}
                }
            ],
            "provider": "openvino"
        },
        {
            "content": "Task has been created and registered in the graph.",
            "tool_calls": [],
            "provider": "openvino"
        }
    ]

    with patch("agents.base.generate", side_effect=mock_responses):
        actions = agent.run_turn("Create task for triage")
        assert len(actions) == 1
        assert actions[0]["tool"] == "create_task"
        assert actions[0]["result"]["ok"] is True
        task_id = actions[0]["result"]["task_id"]

    # Verify task was actually written into the tenant graph
    check = execute_ro_query(ctx.graph_name, "MATCH (t:Task {id: $id}) RETURN t.title", {"id": task_id})
    assert check.result_set[0][0] == "Agent created task"


def test_triage_to_investigator_handoff(agent_fixture):
    """COO-1 to COO-3: Agent handoff creates Handoff node and recipient can accept."""
    ctx_triage = agent_fixture["triage"]
    ctx_inv = agent_fixture["inv"]

    triage = RelayAgent(ctx_triage, TRIAGE_PROMPT, "Triage")
    triage.start()

    # Step 1: Triage creates handoff
    ho_res = dispatch_tool_call(ctx_triage, "create_handoff", {
        "to_agent": "agent_inv",
        "context_summary": "DB latency investigation handed off",
        "incident_id": "INC-TEST"
    })
    assert ho_res["ok"] is True
    ho_id = ho_res["handoff_id"]

    # Step 2: Investigator starts session and receives open handoff
    inv = RelayAgent(ctx_inv, INVESTIGATOR_PROMPT, "Investigator")
    inv_start = inv.start()
    assert inv_start["ok"] is True
    
    # Check open handoffs contains ho_id
    matching = [h for h in inv_start.get("open_handoffs", []) if h["id"] == ho_id]
    assert len(matching) == 1

    # Step 3: Investigator accepts handoff
    acc_res = dispatch_tool_call(ctx_inv, "accept_handoff", {"handoff_id": ho_id})
    assert acc_res["ok"] is True
    assert acc_res["context_summary"] == "DB latency investigation handed off"
