"""
Base Agent Loop:
Executes the tool-use loop over the MCP tools with OpenVINO / Gemini adapter.
Handles session initialization, role-specific system prompt injection, and tool calling turns.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from server.app.auth import AuthContext
from agents.llm_adapter import generate
from agents.tools_registry import TOOL_DEFINITIONS, dispatch_tool_call

log = logging.getLogger("agent")


class RelayAgent:
    def __init__(self, ctx: AuthContext, role_prompt: str, name: str):
        self.ctx = ctx
        self.role_prompt = role_prompt
        self.name = name
        self.session_id: Optional[str] = None
        self.messages: List[Dict[str, Any]] = []

    def start(self) -> Dict[str, Any]:
        """Initialize session in graph and retrieve initial context."""
        sess_res = dispatch_tool_call(self.ctx, "start_session", {})
        if sess_res.get("ok"):
            self.session_id = sess_res.get("session_id")
        return sess_res

    def run_turn(self, instruction: str, max_steps: int = 5) -> List[Dict[str, Any]]:
        """
        Run an instruction through the LLM tool-calling loop.
        Executes model function calls against Relay graph memory until done.
        """
        self.messages.append({"role": "user", "content": instruction})
        history_actions = []

        system_instruction = f"""
You are {self.name}, an AI operations agent in an incident response team.
Your tenant graph: {self.ctx.graph_name}
Your agent id: {self.ctx.agent_id}
Your active session id: {self.session_id or 'none'}

{self.role_prompt}

Guidelines:
- Prefer using tools to take concrete actions in the shared graph memory.
- If you find an issue, add hypotheses and attach evidence.
- If you complete work, mark tasks complete or create a handoff to the next agent.
- Keep tool arguments precise.
"""

        for step in range(max_steps):
            response = generate(
                system_prompt=system_instruction,
                messages=self.messages,
                tools=TOOL_DEFINITIONS
            )

            tool_calls = response.get("tool_calls", [])
            content = response.get("content", "")

            if not tool_calls:
                # LLM finished its actions or provided final message
                self.messages.append({"role": "assistant", "content": content})
                break

            # Process tool calls
            for tc in tool_calls:
                tool_name = tc["name"]
                tool_args = tc["arguments"]
                
                # Auto-inject session_id if missing in log_event
                if tool_name == "log_event" and "session_id" not in tool_args and self.session_id:
                    tool_args["session_id"] = self.session_id

                tool_result = dispatch_tool_call(self.ctx, tool_name, tool_args)
                history_actions.append({
                    "step": step,
                    "tool": tool_name,
                    "args": tool_args,
                    "result": tool_result
                })

                # Append result for model context
                self.messages.append({
                    "role": "assistant",
                    "content": f"Executed {tool_name} with args {json.dumps(tool_args)}"
                })
                self.messages.append({
                    "role": "user",
                    "content": f"Tool {tool_name} response: {json.dumps(tool_result)}"
                })

        return history_actions
