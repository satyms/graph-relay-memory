# AI Disclosure

## Hackathon Track
**Track 02 — Agent Coordination, Collaboration & Shared Graph Memory**

---

## 1. Runtime AI Models
In the Relay execution runtime, AI models power the agent reasoning loop (Triage, Investigator, Remediator, Comms):
- **Primary Runtime Engine**: **OpenVINO™ Toolkit** serving **Qwen2.5-7B-Instruct (INT4 compressed)** locally on device via an OpenAI-compatible FastAPI inference server (`server_openvino.py`).
- **Cloud Fallback Engine**: **Google Gemini API** (`gemini-2.5-flash` / `gemini-3.8-flash`) via `google-genai` SDK for environments without local acceleration hardware.
- **Model Adapter**: `agents/llm_adapter.py` seamlessly handles tool calling, structured JSON argument parsing, and failover between local OpenVINO and cloud fallback.

---

## 2. Assisted Development Disclosure
During the design and implementation of Relay, the development team utilized AI coding tools (Antigravity with Google DeepMind / Anthropic Claude models) as an interactive pair-programming assistant for:
- Accelerating FalkorDB openCypher query prototyping and syntax verification.
- Drafting comprehensive unit, concurrency, and cross-tenant isolation test suites.
- Scaffolding FastAPI routes and the real-time D3.js force-directed dashboard.

All graph schema designs, Cypher query algorithms (atomic CAS task claims, temporal fact supersession, Laplace-smoothed procedural ranking), security isolation boundaries, and architectural choices were conceived, directed, verified, and audited by the project developers.

---

## 3. Human Component Understanding & Ownership
Every teammate has complete architectural mastery and can explain any module in depth:
- **Control Graph & Tenancy**: SHA-256 bearer key authentication and strict tenant graph isolation (`server/app/auth.py`, `server/app/tenancy.py`).
- **Episodic & Semantic Memory**: Temporal intervals (`valid_from`, `valid_to`), bi-temporal time-travel queries, and idempotent event logging (`server/app/queries/episodic.py`, `server/app/queries/semantic.py`).
- **Procedural Memory & Learning**: Historical Laplace smoothing ($s = \frac{k+1}{n+2}$), failure forking with `PREVIOUS_VERSION` lineage, and precondition synthesis (`server/app/queries/procedural.py`).
- **Multi-Agent Coordination**: Atomic single-statement CAS task claims with lease expiry and cascade unblocking (`server/app/queries/coordination.py`).
- **Graph Topology & Insights**: Native FalkorDB `algo.pageRank` entity centrality and BFS blast radius calculation (`server/app/queries/insight.py`).
