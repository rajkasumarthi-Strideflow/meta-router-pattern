# PDR-001 — Stateful Travel Agent Prototype

**Type:** Prototype Design Record  
**Status:** Approved — implementation complete  
**Author:** Raj Kasumarthi  
**Date:** June 2026  
**Stack:** LangGraph · Temporal · Mem0 · MCP  

---

## 1. Purpose

This prototype demonstrates the **durable saga orchestration pattern** using a travel booking agent as the domain. The domain is deliberately simple and universally understood — enabling the architecture patterns to be visible without requiring enterprise system knowledge.

Every component is chosen to be an explicit analog of a production enterprise architecture concern. The prototype argues for the **pattern**, not the implementation stack.

---

## 2. Context

The enterprise architecture engagement requires demonstrating to architects and engineering leads that:

1. Long-running cross-domain agentic workflows can be orchestrated durably across vendor runtimes
2. Agent memory can operate at two layers — short-term (within a workflow step) and long-term (across sessions)
3. Saga compensation is a viable pattern for rollback across committed steps in heterogeneous systems
4. Human-in-the-loop gates can be first-class durable workflow states, not interruptions
5. Tool contracts (MCP) are the correct governance boundary between agents and systems of record

Architecture diagrams alone do not make these behaviors tangible. A running prototype does.

---

## 3. Enterprise mapping

| Prototype component | Enterprise analog |
|---|---|
| Temporal workflow | Meta-orchestrator (durable saga engine) |
| Temporal activities | Async participants (SAP, ServiceNow, identity) |
| LangGraph graph | Agent reasoning loop (per workflow step) |
| LangGraph SqliteSaver | Short-term step state |
| Mem0 | Shared context layer (cross-session preferences) |
| MCP servers | Governed tool contracts |
| MCP flight server | CRM / billing system |
| MCP hotel server | ERP / ITSM system |
| Temporal compensation | Saga rollback across committed steps |
| HITL pause / signal | Human approval gate |

---

## 4. Scope

### In scope — minimal viable prototype

- Collect trip intent: destination, dates, budget (writes preferences to Mem0)
- Search and confirm outbound flight via MCP flight server
- Search and confirm return flight via MCP flight server
- Search and confirm hotel via MCP hotel server
- HITL confirmation gate — workflow pauses, resumes on approval signal
- Rollback scenario — user changes return date after hotel confirmed; compensation + replan
- Crash-and-resume demo — kill process mid-saga, restart, prove state durability
- Preference retrieval — returning user gets pre-filled preferences from Mem0

### Out of scope — explicitly excluded

- Real payment processing or actual booking APIs
- Multi-user or concurrent session management
- Production security, auth, or rate limiting
- UI beyond CLI
- Error handling beyond happy path + one rollback scenario
- Multi-agent coordination (single agent scope)
- Observability stack (Langfuse, Prometheus) — stubs only

### Mock boundary

All MCP servers are local stubs returning deterministic mock data. No real APIs are called. The MCP interface is real; the backend is mocked. The tool contract pattern is genuine even though the backend is not.

---

## 5. Demo scenarios

| Scenario | Command | What it proves |
|---|---|---|
| Happy path | `python run.py --scenario happy_path` | Full saga + HITL gate |
| Crash and resume | `python run.py --scenario crash_resume` | Durable state across process kill |
| Rollback | `python run.py --scenario rollback` | Saga compensation |
| Returning user | `python run.py --scenario returning_user` | Mem0 cross-session memory |

### Key demo moment — crash and resume

1. Start scenario: `python run.py --scenario crash_resume`
2. Watch worker terminal — when `HOTEL STEP STARTING` appears, kill the worker (`Ctrl+C`)
3. Open Temporal UI at `http://localhost:8233` — workflow shows Running but suspended
4. Restart the worker
5. Watch the workflow resume from the hotel step — not from step 1

This single demonstration makes durable state tangible to any audience.

---

## 6. Open decisions

| Decision | Chosen | Rationale |
|---|---|---|
| LangGraph state backend | SqliteSaver | Zero infra; swap to Postgres for production |
| Temporal hosting | Local dev server | No account needed; same API surface |
| Mem0 hosting | In-process fallback | No external dependency for prototype |
| MCP server transport | stdio | Simplest for local prototype |
| HITL mechanism | Temporal signal via CLI | Real pattern without building a UI |
| LLM for reasoning | Deterministic for prototype | Removes API dependency from demo scenarios |

---

## 7. Parking lot

| Item | Status |
|---|---|
| Workshop preparedness | Pending |
| Production runtime selection (Agentforce vs neutral orchestrator) | Workshop decision |
| Observability stack (Langfuse + Prometheus) | Post-prototype |
| Multi-agent coordination pattern | Out of prototype scope |
| Security and identity propagation design | Enterprise design phase |
| Layer Claude reasoning back into LangGraph agent | Next prototype iteration |

---

## 8. References

- [Executive Summary](../executive-summary.md)
- [C4 Context Diagram](../diagrams/c4-context.md)
- [C4 Container Diagram](../diagrams/c4-container.md)
- [Workflow Sequence Diagram](../diagrams/sequence.md)
- [ADR-001 Orchestration Engine](../adr/ADR-001-orchestration-engine.md)
