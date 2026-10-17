"""
Standard tool schemas formatted for LLM function calling (OpenAI & Gemini format).
Maps each tool directly to its Python handler in server.app.tools.*.
"""
from typing import Any, Dict, List
from server.app.auth import AuthContext

from server.app.tools.episodic import (
    start_session_handler,
    log_event_handler,
    recall_episodes_handler,
    end_session_handler
)
from server.app.tools.semantic import (
    upsert_fact_handler,
    query_facts_handler,
    fact_history_handler,
    forget_fact_handler
)
from server.app.tools.coordination import (
    open_incident_handler,
    create_task_handler,
    list_open_work_handler,
    claim_task_handler,
    renew_lease_handler,
    release_task_handler,
    complete_task_handler,
    add_hypothesis_handler,
    attach_evidence_handler,
    create_handoff_handler,
    accept_handoff_handler
)
from server.app.tools.procedural import (
    find_procedure_handler,
    record_outcome_handler,
    get_procedure_handler
)

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "start_session",
            "description": "Start an agent working session and get recent context, handoffs, and tasks.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "log_event",
            "description": "Log an event observation, action, or decision to session timeline.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "event_type": {"type": "string", "enum": ["observation", "action", "decision", "message"]},
                    "summary": {"type": "string"},
                    "payload": {"type": "object"},
                    "entities": {"type": "array", "items": {"type": "string"}},
                    "idempotency_key": {"type": "string"}
                },
                "required": ["session_id", "event_type", "summary"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_facts",
            "description": "Query semantic facts about entities (services, hosts, teams).",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "predicate": {"type": "string"},
                    "as_of": {"type": "integer"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_fact",
            "description": "Create or update a durable belief/fact about an entity. Supersedes older facts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "predicate": {"type": "string"},
                    "value": {"type": "string"},
                    "confidence": {"type": "number"},
                    "source_event_id": {"type": "string"}
                },
                "required": ["entity", "predicate", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_incident",
            "description": "Open a new incident record in the shared coordination graph.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "severity": {"type": "string", "enum": ["sev1", "sev2", "sev3", "sev4"]}
                },
                "required": ["title", "severity"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create a task in the incident work breakdown.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "incident_id": {"type": "string"},
                    "priority": {"type": "integer"}
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "claim_task",
            "description": "Atomic claim on a task with lease.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "ttl_ms": {"type": "integer"}
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Complete a task and cascade unblock downstream tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "summary": {"type": "string"}
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_hypothesis",
            "description": "Record a working hypothesis regarding the incident.",
            "parameters": {
                "type": "object",
                "properties": {
                    "incident_id": {"type": "string"},
                    "statement": {"type": "string"},
                    "confidence": {"type": "number"}
                },
                "required": ["incident_id", "statement"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "attach_evidence",
            "description": "Attach an observation event as evidence supporting a hypothesis.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hypothesis_id": {"type": "string"},
                    "event_id": {"type": "string"},
                    "note": {"type": "string"}
                },
                "required": ["hypothesis_id", "event_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_handoff",
            "description": "Create a handoff passing incident context and questions to another agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to_agent": {"type": "string"},
                    "context_summary": {"type": "string"},
                    "task_id": {"type": "string"},
                    "incident_id": {"type": "string"}
                },
                "required": ["to_agent", "context_summary"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "accept_handoff",
            "description": "Accept a pending handoff addressed to this agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "handoff_id": {"type": "string"}
                },
                "required": ["handoff_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_procedure",
            "description": "Find relevant runbooks/procedures for an issue, ranked by smoothed success rate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "situation": {"type": "string"}
                },
                "required": ["situation"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "record_outcome",
            "description": "Record procedure execution outcome. If failed, automatically forks v+1 with preconditions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "procedure_id": {"type": "string"},
                    "incident_id": {"type": "string"},
                    "success": {"type": "boolean"},
                    "note": {"type": "string"},
                    "failed_step": {"type": "integer"},
                    "violated_assumption": {"type": "string"},
                    "new_precondition": {"type": "string"}
                },
                "required": ["procedure_id", "incident_id", "success"]
            }
        }
    }
]


def dispatch_tool_call(ctx: AuthContext, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a tool handler by name using the agent's AuthContext."""
    dispatch = {
        "start_session": lambda: start_session_handler(ctx),
        "log_event": lambda: log_event_handler(ctx, **args),
        "query_facts": lambda: query_facts_handler(ctx, **args),
        "upsert_fact": lambda: upsert_fact_handler(ctx, **args),
        "open_incident": lambda: open_incident_handler(ctx, **args),
        "create_task": lambda: create_task_handler(ctx, **args),
        "claim_task": lambda: claim_task_handler(ctx, **args),
        "complete_task": lambda: complete_task_handler(ctx, **args),
        "add_hypothesis": lambda: add_hypothesis_handler(ctx, **args),
        "attach_evidence": lambda: attach_evidence_handler(ctx, **args),
        "create_handoff": lambda: create_handoff_handler(ctx, **args),
        "accept_handoff": lambda: accept_handoff_handler(ctx, **args),
        "find_procedure": lambda: find_procedure_handler(ctx, **args),
        "record_outcome": lambda: record_outcome_handler(ctx, **args)
    }
    if name not in dispatch:
        return {"ok": False, "error": f"Unknown tool: {name}"}
    return dispatch[name]()
