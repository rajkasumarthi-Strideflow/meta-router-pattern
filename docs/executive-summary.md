# Executive Summary — Enterprise Agentic Architecture

## Meta-Orchestrator Architecture Pattern

### The problem it solves

Enterprise AI adoption in 2025–2026 is producing a fragmented landscape of vendor-native agent runtimes — Salesforce Agentforce, ServiceNow Now Assist, SAP Joule, Microsoft Copilot Studio, and custom agents built on Anthropic, Bedrock, or OpenAI. Each platform conducts its own agents well within its domain. The problem emerges when business processes cross those domains.

An employee onboarding workflow needs HR data from SAP, an IT ticket from ServiceNow, and an identity account from Okta. A procurement workflow needs a PO from SAP, an approval from a manager in Teams, and a vendor record from Salesforce. No single vendor platform naturally orchestrates across the others — and each vendor architecturally wants to be the orchestrator.

Without deliberate architecture, the result is an N×N integration mesh: each workflow builds its own point integrations, its own state management, and its own error handling. Adding the tenth workflow is as expensive as adding the first.

### What the pattern is

The meta-orchestrator pattern introduces a dedicated orchestration tier above the vendor runtimes. It does not replace them — Agentforce still conducts Salesforce agents, ServiceNow still conducts ITSM agents, SAP Joule still conducts ERP agents. The meta-orchestrator conducts across them.

```
                    ┌─────────────────────────────┐
                    │      Meta-orchestrator        │
                    │  (durable saga engine)        │
                    │  owns cross-domain workflow   │
                    │  state, sequence, and         │
                    │  compensation                 │
                    └──────────┬──────────────┬────┘
                               │              │
              ┌────────────────┘              └────────────────┐
              ▼                                                ▼
   ┌──────────────────┐                           ┌──────────────────┐
   │  Agentforce      │                           │  ServiceNow      │
   │  (CRM domain)    │                           │  (ITSM domain)   │
   └──────────────────┘                           └──────────────────┘
              │                                                │
              ▼                                                ▼
       Salesforce CRM                                   ITSM / IT provisioning
```

The meta-orchestrator is responsible for four things no vendor platform handles across boundaries:

**Durable workflow state.** The workflow's position — which steps are complete, which are pending, what each step returned — persists in a store the orchestrator owns. If any component restarts, the workflow resumes from its last checkpoint rather than from the beginning.

**Step sequencing and dependency enforcement.** The orchestrator drives the order of operations: payroll before laptop provisioning, identity account before system access, manager approval before equipment order. It does not execute these steps — it dispatches them to the right runtime and waits for completion.

**Saga compensation on failure.** When a step fails after earlier steps have committed, there is no distributed transaction to roll back. The orchestrator runs compensating actions — reversing each committed step in inverse order — to return the system to a consistent state.

**Cross-platform governance.** The orchestrator is the single place where a cross-domain workflow can be observed, audited, and terminated. Without it, tracing a failed onboarding across SAP, ServiceNow, and Okta requires correlating logs from three systems with no shared identifier.

### When to use it

The meta-orchestrator pattern applies to workflows that meet two criteria: they span more than one vendor runtime or system of record, and they run long enough that process restarts are a realistic concern — meaning anything measured in minutes, hours, or days rather than seconds.

Short-lived transactional workflows — a customer service agent answering a refund question, a lookup agent retrieving account status — do not need the meta-orchestrator. They conduct themselves natively inside one runtime, complete in seconds, and hold no state worth persisting. Routing these through a central orchestrator adds latency and a failure point with no benefit.

The routing decision is based on two axes:

| Workflow shape | Orchestration pattern |
|---|---|
| Single-domain, seconds, synchronous tool calls | Native runtime (Agentforce, ServiceNow, SAP Joule) |
| Cross-domain, minutes to days, async participants | Meta-orchestrator with durable saga |

### The three topology options — and why the answer is hybrid

**Central meta-orchestrator.** One engine above all vendor runtimes. Maximum visibility and governance. Risk: central dependency, vendor resistance, migration cost.

**Federated domain orchestration.** Each vendor conducts its own domain; hand-offs happen at domain boundaries via events or API calls. Low disruption. Risk: state ownership is ambiguous at boundaries; compensation is difficult to coordinate.

**Event choreography.** No conductor. Runtimes react to and emit events on a shared bus. Maximum decoupling. Risk: no single place can answer "where is this workflow right now"; debugging is distributed.

The correct answer for a multi-vendor enterprise is a hybrid: federated for short-lived single-domain flows (let each vendor own its domain), meta-orchestrator for long-running cross-domain sagas. The event backbone connects both tiers and enables event-triggered entry into either.

---

## Durable Execution Pattern

### What it is

Durable execution is a programming model in which workflow state is persisted automatically after every step, so that a workflow can survive any infrastructure failure — process crash, machine restart, network partition, deployment — and resume from its last completed step rather than from the beginning.

In a conventional workflow, state lives in memory. If the process dies, the workflow dies with it and must be restarted from scratch. In a durable execution engine, state lives in an external store owned by the engine. The process is a stateless executor — it picks up work, executes the next step, persists the result, and releases. If it dies at any point, another process picks up the same workflow from the same persisted state.

### Why it matters for enterprise agentic workflows

Enterprise agentic workflows have three properties that make conventional in-memory orchestration inadequate:

**They run across time.** An onboarding workflow spans hours or days. A procurement approval waits for a human. A compliance review blocks on a third-party response. Holding state in memory across these spans is not feasible — it ties up compute, survives neither restarts nor deployments, and cannot be observed or resumed by another process.

**They cross system boundaries.** Each step calls a different system. If step four fails after steps one through three have committed to SAP, ServiceNow, and Okta respectively, the system is in a partially consistent state. Recovery requires knowing exactly what committed and running compensating actions in the right order. This is only possible if the orchestrator has a complete, durable record of what each step did.

**They involve humans.** Human approval gates can last hours or days. The workflow must park — holding zero compute, zero memory, zero open connections — and resume the moment the human acts. This is architecturally impossible without durable state.

### How it works — the saga pattern

A saga is a sequence of steps where each step has a corresponding compensating action. The durable execution engine drives the saga forward, checkpointing after each step. If a step fails, the engine runs the compensating actions for all previously completed steps in reverse order.

```
Forward execution:
  Step 1: Create HR record      →  committed  ✓
  Step 2: Provision IT ticket   →  committed  ✓
  Step 3: Create identity acct  →  FAILED     ✗

Compensation (reverse order):
  Compensate Step 2: Close IT ticket
  Compensate Step 1: Delete HR record
  System returned to consistent state
```

The saga pattern does not guarantee atomicity — it guarantees eventual consistency through compensation. This is the correct tradeoff for long-running workflows across heterogeneous systems where distributed transactions are not available.

### The four capabilities this prototype demonstrates

**Checkpoint and resume.** The prototype kills the worker process mid-workflow and restarts it. The workflow resumes from the hotel booking step — not from intent collection. This demonstrates that durable state in Temporal survives arbitrary process failures.

**HITL as a durable state.** The workflow parks at the itinerary confirmation gate and holds zero compute while waiting for an approval signal. The wait can last indefinitely. When the signal arrives, the workflow resumes with full state intact.

**Saga compensation on user-initiated change.** When the user changes the return date after the hotel is confirmed, the engine runs compensating activities — cancel hotel, cancel return flight — then replans with the updated date. The compensating actions are defined upfront alongside each forward step.

**Cross-session long-term memory.** Mem0 persists user preferences across workflow sessions. A returning user's second booking retrieves their airline preference, seat preference, hotel tier, and budget ceiling without re-asking. This demonstrates the shared context layer that makes agents practically useful across repeated interactions.

### Production implementation options

The durable execution pattern is engine-agnostic. The prototype uses Temporal as the clearest expression of the pattern. In production, the same pattern can be implemented with:

| Engine | Characteristics |
|---|---|
| Temporal | Purpose-built durable execution; strongest saga and signal model; self-hosted or cloud |
| AWS Step Functions | Managed; native AWS integration; lower operational overhead; less expressive |
| Apache Airflow | Strong for data pipeline sagas; less suited for event-driven human-in-the-loop |
| Vendor platform | Agentforce Flows, ServiceNow Flow Designer — within-domain only; no cross-vendor saga |

The workshop's open decision — which engine plays meta-orchestrator in production — is separate from the pattern itself. The pattern is valid regardless of which engine implements it.

---

*Document version: 1.0 — June 2026*  
*Status: Draft — pending workshop alignment*
