# Relay — 3-Minute Demo Video Recording Guide

Follow this guide to record your **3-minute** submission video for **Track 02: Agent Memory and Coordination**.

---

## 🖥️ Screen Layout Setup

Open **two windows side by side**:
- **Left Window (65% width)**: Browser at `http://localhost:8080/dashboard/` (showing the live force-directed graph, handoff feed, task board, and proofs).
- **Right Window (35% width)**: Terminal with active virtual environment ready to run commands.

---

## 🎬 3-Minute Storyboard & Script

| Timestamp | Visual Action | What to Say (Spoken Narration) |
|---|---|---|
| **0:00 – 0:15** | Show Dashboard header and topology graph. | *"Autonomous agent teams suffer from memory amnesia and collision. Flat vector stores discard relationships and causal history. We built Relay: a shared graph memory and coordination engine for agent fleets powered entirely by FalkorDB."* |
| **0:15 – 0:50** | Click **"▶ Run Incident Scenario"** button in dashboard.<br>Watch nodes appear: Incident `INC-1`, tasks, hypothesis, and the Handoff node to Investigator. | *"When an alert strikes, Triage doesn't dump a chat log into context. It writes an incident node, an initial hypothesis, and an explicit handoff carrying structured context and open questions directly to the Investigator."* |
| **0:50 – 1:20** | Point out the Investigator node claiming the task, running BFS blast radius for `redis-cache`, and linking evidence ruling out `auth-svc`. | *"The Investigator claims the task with an atomic lease, runs a topology blast radius query, and rules out auth-svc as a red herring—attaching proven evidence to the hypothesis before handing off to the Remediator."* |
| **1:20 – 1:55** | Watch Remediator execute `restart-redis v1` (fails on deploy trap), fork `v2` with precondition, and re-rank to `rollback-deploy` (succeeds). | *"Here is the procedural learning moment. Remediator selects restart-redis, but it fails because a deploy 20 minutes ago broke the schema. Rather than vanishing into chat logs, Relay records the violated assumption, retires v1, and forks v2 with a new precondition. The re-ranked procedure chooses rollback-deploy and succeeds!"* |
| **1:55 – 2:15** | Switch to the **Fact Lineage** tab on the sidebar. Show current owner (`Team Billing`) vs historical belief (`Team Core`). | *"We also solve fact supersession. When service ownership was updated from Team Core to Team Billing, a SUPERSEDES edge was created. Using bi-temporal queries, an agent can ask: 'What did the team believe at 2:00 PM before the incident?' and receive the historical truth."* |
| **2:15 – 2:40** | Switch to terminal and run:<br>`pytest -v tests/test_e2e_scenario.py` | *"Relay guarantees persistence across processes. Restarting agent processes restores complete situational awareness from FalkorDB. All tasks transition to done, handoffs are accepted, and procedural lineage is verified."* |
| **2:40 – 2:55** | In terminal, run:<br>`python scripts/load_test.py --agents 20 --tasks 10`<br>Then run:<br>`python scripts/isolation_test.py` | *"Under concurrency, 20 agents race for 10 tasks via single-statement Compare-and-Set claims: exactly 10 winners, 0 duplicates, over 1,900 ops/second. In our isolation tests across 7 scenarios, 0 cross-tenant reads occurred."* |
| **2:55 – 3:00** | Return to dashboard or title slide. | *"Relay gives AI agent fleets persistent memory, race-free coordination, and continuous learning in FalkorDB. Track 02."* |

---

## ⚡ Quick Pre-Flight Commands

Before hitting record, run:
```bash
# Terminal 1: FalkorDB (if not running)
docker run -p 6379:6379 -d --name falkordb-relay falkordb/falkordb:latest

# Terminal 2: Start server and dashboard
.\.venv\Scripts\activate
uvicorn server.app.main:app --port 8080

# Terminal 3: Ready for tests
.\.venv\Scripts\activate
python scripts/seed.py
```
Open **`http://localhost:8080/dashboard/`** in your browser and you are ready to record!
