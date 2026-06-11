# ADR-005 — Prototype Domain: Travel Booking Agent

**Status:** Accepted  
**Date:** June 2026  
**Deciders:** Raj Kasumarthi  

---

## Context

The prototype needs a domain to demonstrate the durable saga orchestration pattern. Two candidates were evaluated: **employee onboarding** (high enterprise relevance, touches HR/IT/identity systems) and **travel booking** (universally understood, self-contained, forgiving to mock). The domain choice affects demo credibility, mock complexity, rollback naturalness, and audience comprehension.

## Decision

Use **travel booking** as the prototype domain.

## Options considered

| Criterion | Employee onboarding | Travel booking |
|---|---|---|
| Enterprise relevance | Very high — directly maps to production workflows | Moderate — requires translation to enterprise context |
| Mock complexity | High — SAP, ServiceNow, Okta stubs feel incomplete | Low — flight and hotel stubs are universally understood |
| Rollback naturalness | Moderate — "undo payroll record" requires explanation | High — "cancel hotel after date change" is immediately understood |
| HITL naturalness | High — manager approval is familiar | High — itinerary confirmation is familiar |
| Audience comprehension | Requires enterprise domain knowledge | Zero domain knowledge required |
| Demo speed | Slower — more explanation needed | Faster — audience focuses on the pattern not the domain |
| Pattern coverage | All five patterns | All five patterns |

## Rationale

**1. The domain is the vehicle, not the argument.** Both domains demonstrate identical patterns: durable saga, HITL gate, compensation, long-term memory, crash-resume. The domain choice affects how quickly the audience understands what they're watching — not what they're watching.

**2. Universally understood domains make the pattern visible.** When an audience watches a hotel get cancelled and a new one booked after a date change, they immediately grasp compensation — without needing to understand SAP payroll reversal semantics. The simpler the domain, the more cognitive bandwidth the audience has for the architectural insight.

**3. The rollback scenario is uniquely compelling in travel.** "I need to change my return date after I've already booked a hotel" is something every person in a conference room has experienced. The parallel to "I need to update my onboarding start date after IT has already been provisioned" is immediately obvious — and can be stated explicitly during the demo.

**4. The article reference aligned with travel.** The system design article used in the discovery phase ([ai-agent-memory](https://newsletter.systemdesign.one/p/ai-agent-memory)) used travel booking as its primary illustration of agent memory patterns. The prototype and the reference material reinforce each other.

**5. Mock backends are credible.** A mock Amadeus flight API returning three flights is immediately credible. A mock SAP payroll API returning an employee record requires more explanation to feel legitimate.

## Enterprise translation script

The following translations are stated explicitly during the prototype demo to close the enterprise relevance gap:

| Travel booking | Enterprise analog |
|---|---|
| Trip intent collection | Employee onboarding intake form |
| Flight search and confirm | IT equipment provisioning request |
| Hotel search and confirm | Workspace allocation request |
| Return date change | Employee start date change after IT ticket created |
| Hotel cancellation + rebook | Close IT ticket, reopen with updated dates |
| HITL itinerary approval | Manager approval gate in onboarding workflow |
| Returning user preferences | Employee profile pre-filling a new service request |
| Crash and resume | Worker restart mid-onboarding — workflow continues from IT step |

## Consequences

- The prototype does not directly demonstrate Agentforce, ServiceNow, or SAP Joule integration
- Enterprise translation requires an explicit bridging statement during the demo presentation
- The travel domain is not suitable as a production prototype — it exists solely to demonstrate patterns
- Follow-on work: rebuild one workflow in the onboarding domain using the same stack once patterns are approved
