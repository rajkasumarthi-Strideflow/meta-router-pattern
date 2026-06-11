# ADR-003 — Long-Term Memory Layer: Mem0

**Status:** Accepted  
**Date:** June 2026  
**Deciders:** Raj Kasumarthi  

---

## Context

The prototype requires persistent user preferences that survive across workflow sessions — a returning user's second booking should pre-fill their airline preference, seat preference, hotel tier, and budget ceiling without re-asking. This is the long-term memory layer: distinct from the in-step working memory (LangGraph SqliteSaver) and from the saga state (Temporal).

## Decision

Use **Mem0** as the long-term memory layer.

## Options considered

| Option | Strengths | Weaknesses |
|---|---|---|
| **Mem0** | Purpose-built for agent memory; selective retrieval (not full history in prompt); hybrid vector + structured search; cloud and self-hosted options | Newer library; in-process store not supported in v2.0 |
| Redis | Fast; simple key-value | No semantic search; manual preference schema management |
| Postgres + pgvector | Full control; production ready | More setup; no agent-native API |
| LangChain Memory | Same ecosystem | Deprecated in newer LangChain versions; less control |
| Full context window | Simplest | Does not scale; every session reloads all history |
| Custom vector store | Full control | Build and maintain cost |

## Rationale

**1. Selective retrieval is the enterprise-critical property.** Mem0 retrieves only the preferences relevant to the current query rather than loading the full interaction history into the prompt. This is what makes agent memory practical at enterprise scale — an employee with three years of IT service history cannot have that history loaded into every prompt. Mem0's semantic search surfaces the relevant context.

**2. The API maps cleanly to the shared context layer pattern.** `memory.add()` on write and `memory.search()` on read is a clean, auditable interface that maps directly to the shared context layer in the enterprise architecture. The pattern is: write preferences at workflow entry, retrieve at each step entry.

**3. Hybrid storage supports both exact and semantic retrieval.** Preferences like "preferred airline: Delta" benefit from exact retrieval. Preferences like "prefers direct flights when available for business trips under 3 hours" benefit from semantic search. Mem0's hybrid approach handles both.

**4. Cloud and self-hosted options match enterprise deployment requirements.** Mem0 Cloud for low-friction adoption; self-hosted with Qdrant or Pinecone for data residency and compliance requirements. The prototype uses the in-process fallback; production uses the appropriate deployment.

## Three-layer memory architecture

The prototype implements a deliberate three-layer memory architecture:

| Layer | Component | Scope | Lifespan |
|---|---|---|---|
| Working memory | LangGraph state | Within one reasoning step | Seconds |
| Saga state | Temporal | Across steps within one workflow | Hours to days |
| Long-term memory | Mem0 | Across all workflows for a user | Persistent |

Each layer is owned by a different component. No component holds state that belongs to another layer. This separation is what allows each layer to be scaled, replaced, or swapped independently.

## Consequences

- Mem0 SDK is a dependency
- In-process fallback store is used for the prototype (Mem0 v2.0 dropped the `memory` vector store provider)
- Production deployment requires a vector store (Qdrant recommended for self-hosted)
- Preference schema is implicit in the stored text — consider formalizing with structured memory in later iterations
