"""
LLM Adapter supporting OpenVINO (Qwen2.5-7B-Instruct INT4 via local OpenAI-compatible endpoint)
with automatic fallback to Gemini API (google-genai SDK).

Standardized format:
generate_with_tools(system_prompt, messages, tools) -> {"content": str, "tool_calls": [...]}
"""
import json
import os
from typing import Any, Dict, List, Optional
import httpx

from dotenv import load_dotenv
load_dotenv()

from server.app.config import settings

# Load configuration with defaults
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "openvino").lower()
OPENVINO_BASE_URL = os.getenv("OPENVINO_BASE_URL", "http://localhost:8000/v1")
OPENVINO_MODEL = os.getenv("OPENVINO_MODEL", "Qwen/Qwen2.5-7B-Instruct")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")


def call_openvino(
    system_prompt: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    timeout: float = 30.0
) -> Dict[str, Any]:
    """
    Call local OpenVINO model (e.g. Qwen2.5-7B-Instruct INT4 served via vLLM / llama.cpp / openvino-genai-server)
    using the standard OpenAI chat completions API.
    """
    url = f"{OPENVINO_BASE_URL.rstrip('/')}/chat/completions"
    formatted_msgs = [{"role": "system", "content": system_prompt}] + messages
    
    payload: Dict[str, Any] = {
        "model": OPENVINO_MODEL,
        "messages": formatted_msgs,
        "temperature": 0.1,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    headers = {"Content-Type": "application/json"}
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    choice = data["choices"][0]["message"]
    tool_calls = []
    if "tool_calls" in choice and choice["tool_calls"]:
        for tc in choice["tool_calls"]:
            fn = tc.get("function", {})
            args = fn.get("arguments", "{}")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            tool_calls.append({
                "id": tc.get("id", f"call_{len(tool_calls)}"),
                "name": fn.get("name"),
                "arguments": args
            })

    return {
        "content": choice.get("content") or "",
        "tool_calls": tool_calls,
        "provider": "openvino"
    }


def call_gemini(
    system_prompt: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Fallback call to Google Gemini API using google-genai SDK.
    """
    from google import genai
    from google.genai import types

    api_key = GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is required for Gemini fallback")

    client = genai.Client(api_key=api_key)

    # Format tools for Gemini SDK function declarations
    gemini_tools = None
    if tools:
        declarations = []
        for t in tools:
            fn = t.get("function", t)
            decl = {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters")
            }
            declarations.append(decl)
        gemini_tools = [types.Tool(function_declarations=declarations)]

    # Format conversation history
    contents = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        content_text = m.get("content") or ""
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=content_text)]))

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=0.1,
        tools=gemini_tools
    )

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents if contents else "Begin investigation",
        config=config
    )

    tool_calls = []
    text_content = ""
    if response.candidates and response.candidates[0].content:
        for part in response.candidates[0].content.parts:
            if part.text:
                text_content += part.text
            if part.function_call:
                fc = part.function_call
                args = dict(fc.args) if fc.args else {}
                tool_calls.append({
                    "id": f"call_{len(tool_calls)}",
                    "name": fc.name,
                    "arguments": args
                })

    return {
        "content": text_content,
        "tool_calls": tool_calls,
        "provider": "gemini"
    }


def generate(
    system_prompt: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    preferred_provider: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate model completion with tool support.
    Tries OpenVINO local first (if provider=openvino or default);
    if unreachable or error, falls back to Gemini API.
    """
    provider = (preferred_provider or MODEL_PROVIDER).lower()

    if provider == "openvino":
        try:
            return call_openvino(system_prompt, messages, tools)
        except Exception as exc:
            # Fallback to Gemini
            return call_gemini(system_prompt, messages, tools)
    elif provider == "gemini":
        return call_gemini(system_prompt, messages, tools)
    else:
        # Default try openvino then gemini
        try:
            return call_openvino(system_prompt, messages, tools)
        except Exception:
            return call_gemini(system_prompt, messages, tools)
