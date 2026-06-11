# ADR-001 — Orchestration Engine: Temporal

**Status:** Accepted  
**Date:** June 2026  
**Deciders:** Raj Kasumarthi  

---

## Context

The prototype requires a durable saga orchestrator to demonstrate the meta-orchestrator pattern. The orchestrator must: persist workflow state across process restarts, sequence async activities across multiple systems, support human-in-the-loop pause and resume via signals, and execute compensating actions on rollback.

The enterprise context is a multi-vendor landscape with Agentforce, ServiceNow, and SAP Joule each conducting domain-specific agents. The meta-orchestrator sits above these runtimes and coordinates cross-domain long-running workflows.

## Decision

Use **Temporal** as the meta-orchestrator for the prototype.

## Options considered

| Option | Strengths | Weaknesses |
|---|---|---|
| **Temporal** | Purpose-built durable execution; strongest saga and signal model; deterministic replay; rich SDK; local dev server; Temporal UI for observability | Self-hosted operational complexity in production; steeper learning curve |
| AWS Step Functions | Managed; native AWS integration; low operational overhead | Vendor lock-in; less expressive workflow language; weak local dev story |
| Apache Airflow | Strong ecosystem; good for data pipeline sagas | Not designed for event-driven HITL; poor real-time signal model |
| Agentforce Flows | Already in enterprise stack | Cannot orchestrate across non-Salesforce systems; not cross-vendor |
| Custom state machine | Full control | High build and maintenance cost; reinventing solved problems |
| LangGraph alone | Already in stack; graph state | Not designed for durable cross-process persistence at saga level |

## Rationale

Temporal was chosen for five reasons:

**1. Durable execution is the pattern, not a feature.** Temporal's entire design is built around the guarantee that workflow state survives any infrastructure failure. This is not a feature flag — it is the architectural commitment. AWS Step Functions and Airflow treat durability as an implementation detail.

**2. The signal model maps directly to HITL.** Temporal's `workflow.wait_condition()` and `workflow.signal()` are exact implementations of the HITL gate pattern — the workflow parks in a persisted state and resumes on an external signal without polling or holding compute. No other option in the list has an equivalent.

**3. Deterministic replay enables the crash-resume demo.** Temporal replays workflow history on worker restart. This is what makes the crash-resume scenario work — and what makes it demonstrable to a live audience. Kill the worker, restart it, watch the workflow continue from exactly where it stopped.

**4. The local dev server eliminates infrastructure setup.** `temporal server start-dev` gives a fully functional Temporal server with UI in one command. This is critical for a prototype that needs to run on a MacBook in a workshop room.

**5. The Temporal UI provides instant observability.** The web UI at `localhost:8233` shows workflow state, event history, activity results, and signal history without any additional instrumentation. This is the observability layer demo artifact.

## Enterprise translation

In production, the meta-orchestrator role could be filled by Temporal Cloud (managed), a self-hosted Temporal cluster, or a vendor platform that provides equivalent durable execution semantics. The pattern is engine-agnostic. The prototype uses Temporal as the clearest and most accessible expression of the pattern.

The workshop's open decision — which engine plays meta-orchestrator in production — is deferred to the architecture alignment session. This ADR establishes the pattern and its requirements; the production engine selection is a separate decision.

## Consequences

- Temporal SDK is a dependency of the prototype
- Worker must be running alongside the Temporal server for workflows to execute
- Workflow code must comply with Temporal's determinism requirements (no random, no datetime.now(), no filesystem calls inside workflow class)
- Activities can be non-deterministic and are the correct place for external calls, LLM invocations, and file I/O
