# Meta-Orchestrator Pattern — Enterprise Agentic Architecture

A reference architecture and working prototype demonstrating how to orchestrate dozens of varied, multi-channel, human-triggered, and event-triggered agentic workflows at scale across heterogeneous enterprise platforms.

## What this repo contains

| Path | Contents |
|---|---|
| `docs/executive-summary.md` | Architecture pattern overview — meta-orchestrator and durable execution |
| `docs/pdr/` | Prototype Design Record — scope, C4 diagrams, sequence, decisions |
| `docs/diagrams/` | C4 Context, Container, and Sequence diagrams in Mermaid |
| `docs/adr/` | Architecture Decision Records — one per key decision |
| `prototype/` | Working prototype — LangGraph + Temporal + Mem0 + MCP |

## The core problem

Enterprise AI adoption produces dozens of agentic workflows across vendor-native platforms — Agentforce, ServiceNow, SAP Joule, and custom agents — each conducting its own agents inside its own walled garden. As workflow count grows, the architecture collapses into an N×N integration mesh with no central governance, no cross-platform tracing, and no durable state for long-running processes.

## The architectural answer

Two-tier orchestration matched to workflow shape:

```
Short-lived transactional    →  Native runtime conducting  (Agentforce, ServiceNow, SAP Joule)
Long-running cross-domain    →  Meta-orchestrator + durable saga  (Temporal pattern)
```

All workflows share a common substrate: governed tool contracts (MCP), a canonical data layer, an event backbone, and a unified control plane.

## The prototype

A working travel booking agent that demonstrates four enterprise patterns:

| Demo scenario | Pattern demonstrated | Enterprise analog |
|---|---|---|
| Happy path | Full saga orchestration + HITL | Onboarding, procurement approval |
| Crash and resume | Durable state across process restarts | Worker restart mid-onboarding |
| Rollback | Saga compensation across committed steps | User changes request after partial completion |
| Returning user | Cross-session long-term memory | Employee profile pre-filling a new request |

## Stack

| Component | Tool | Enterprise analog |
|---|---|---|
| Saga orchestrator | Temporal | Meta-orchestrator |
| Reasoning loop | LangGraph | Agent reasoning per workflow step |
| Long-term memory | Mem0 | Shared context layer |
| Tool contracts | MCP | Governed API surface |
| Systems | Mock MCP servers | CRM, ERP, ITSM, Billing |

## Quick start

```bash
# 1. Install dependencies
pip install langgraph langchain-anthropic langchain-core mem0ai temporalio \
            aiosqlite langgraph-checkpoint-sqlite

# 2. Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# 3. Create package init files
touch shared/__init__.py mcp_servers/__init__.py \
      langgraph_agent/__init__.py temporal_worker/__init__.py

# 4. Smoke test (no Temporal needed)
python run.py --scenario smoke_test

# 5. Start Temporal dev server (Terminal 1)
temporal server start-dev

# 6. Start worker (Terminal 2)
ANTHROPIC_API_KEY=sk-ant-... python temporal_worker/worker.py

# 7. Run scenarios (Terminal 3)
python run.py --scenario happy_path
python run.py --scenario crash_resume
python run.py --scenario rollback
python run.py --scenario returning_user
```

## Architecture documentation

- [Executive Summary](docs/executive-summary.md)
- [Prototype Design Record](docs/pdr/PDR-001-travel-agent-prototype.md)
- [C4 Context Diagram](docs/diagrams/c4-context.md)
- [C4 Container Diagram](docs/diagrams/c4-container.md)
- [Workflow Sequence Diagram](docs/diagrams/sequence.md)
- [ADR-001 Orchestration Engine](docs/adr/ADR-001-orchestration-engine.md)
- [ADR-002 Agent Reasoning Framework](docs/adr/ADR-002-agent-reasoning-framework.md)
- [ADR-003 Long-Term Memory Layer](docs/adr/ADR-003-long-term-memory.md)
- [ADR-004 Tool Contract Protocol](docs/adr/ADR-004-tool-contract-protocol.md)
- [ADR-005 Prototype Domain](docs/adr/ADR-005-prototype-domain.md)
