# Travel Agent Prototype
### Stateful agentic workflow — LangGraph + Temporal + Mem0 + MCP

Enterprise agentic pattern prototype. Demonstrates durable saga orchestration,
short and long-term memory, HITL gates, and saga compensation (rollback).

---

## Whitepaper
[→ View the Architecture Whitepaper](https://rajkasumarthi-strideflow.github.io/meta-router-pattern/docs/whitepaper.html)

## Enterprise analog map

| Prototype component      | Enterprise analog                              |
|--------------------------|------------------------------------------------|
| Temporal workflow        | Meta-orchestrator (durable saga engine)        |
| Temporal activities      | Async participants (SAP, ServiceNow, identity) |
| LangGraph graph          | Agent reasoning loop (per workflow step)       |
| LangGraph SqliteSaver    | Short-term step state                          |
| Mem0                     | Shared context layer (cross-session prefs)     |
| MCP servers              | Governed tool contracts                        |
| MCP flight server        | CRM / billing system                           |
| MCP hotel server         | ERP / ITSM system                              |
| Temporal compensation    | Saga rollback across committed steps           |
| HITL pause / signal      | Human approval gate                            |

---

## Project structure

```
travel_agent/
├── shared/
│   └── models.py              # Canonical data models (shared across all components)
├── mcp_servers/
│   ├── flight_server.py       # MCP server: flight search + booking tool contracts
│   └── hotel_server.py        # MCP server: hotel search + booking tool contracts
├── langgraph_agent/
│   ├── mcp_client.py          # MCP stdio client (bridges LangGraph to MCP servers)
│   ├── memory.py              # Mem0 preference manager (long-term memory)
│   └── agent.py               # LangGraph graph definition (reasoning loop)
├── temporal_worker/
│   ├── workflow.py            # Temporal workflow + activities (durable saga)
│   └── worker.py              # Worker runner (connects to Temporal server)
└── run.py                     # Demo CLI (smoke test + all scenarios)
```

---

## Setup

```bash
# 1. Install dependencies
pip install langgraph langchain-anthropic langchain-core mem0ai temporalio \
            aiosqlite langgraph-checkpoint-sqlite

# 2. Set API key
export ANTHROPIC_API_KEY=your_key_here

# 3. Install Temporal CLI (macOS)
brew install temporal

# 3. Install Temporal CLI (Linux)
curl -sSf https://temporal.download/cli.sh | sh
```

---

## Running the demos

### Step 1 — Smoke test (no Temporal needed)
Validates MCP servers and Mem0 work in isolation.
```bash
cd /path/to/travel_agent
python run.py --scenario smoke_test
```

### Step 2 — Start Temporal dev server (Terminal 1)
```bash
temporal server start-dev
# Temporal UI: http://localhost:8233
```

### Step 3 — Start worker (Terminal 2)
```bash
export ANTHROPIC_API_KEY=your_key_here
python temporal_worker/worker.py
```

### Step 4 — Run demo scenarios (Terminal 3)

```bash
# Happy path — full saga with HITL approval
python run.py --scenario happy_path

# Crash and resume — THE key demo moment
python run.py --scenario crash_resume
# Follow the instructions printed — manually kill and restart the worker
# while the workflow is mid-flight. Watch it resume in Temporal UI.

# Rollback — change return date after hotel is confirmed
python run.py --scenario rollback

# Returning user — Mem0 pre-fills preferences from prior booking
python run.py --scenario returning_user
```

---

## Key demo moments

### 1. Crash and resume (durable state)
```
1. Start scenario: python run.py --scenario crash_resume
2. Watch workflow reach 'outbound_flight' or 'hotel' step in Temporal UI
3. Kill the worker: Ctrl+C in Terminal 2
4. Observe: workflow is SUSPENDED in Temporal UI — state preserved
5. Restart worker: python temporal_worker/worker.py
6. Observe: workflow RESUMES from same step — not from step 1
```
Enterprise analog: worker restart mid-onboarding. SAP payroll already done.
ServiceNow picks up from where it paused.

### 2. Rollback (saga compensation)
```
1. Start scenario: python run.py --scenario rollback
2. Watch hotel get confirmed (booking ref appears in status)
3. run.py automatically sends change_return_date signal
4. Observe: hotel is CANCELLED, return flight is CANCELLED
5. Observe: return flight re-booked with new date, hotel re-booked
```
Enterprise analog: employee changes start date after IT ticket is created.
Orchestrator compensates committed steps and replans.

### 3. HITL gate (human approval)
The happy path scenario pauses at step 5 and waits for a signal.
```
Enterprise analog: manager approval gate in onboarding workflow.
Workflow holds zero compute while waiting — survives indefinitely.
```

### 4. Returning user (Mem0 long-term memory)
```
1. First booking saves: Delta, aisle seat, business hotel, $2500 budget
2. Second booking uses minimal message — no airline/seat/hotel specified
3. Preferences are retrieved from Mem0 and applied automatically
```
Enterprise analog: employee profile pre-filling a new request form.

---

## Temporal UI
With the dev server running, open http://localhost:8233 to see:
- All workflow executions with their current state
- Each activity (step) with timing and retry count
- Full event history — the complete audit trail
- Signal history — HITL approvals, date changes

This UI is the observability layer analog in the enterprise architecture.
