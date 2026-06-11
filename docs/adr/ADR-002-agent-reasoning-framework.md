# ADR-002 — Agent Reasoning Framework: LangGraph

**Status:** Accepted  
**Date:** June 2026  
**Deciders:** Raj Kasumarthi  

---

## Context

Each Temporal activity needs an agent reasoning loop to execute its step — load context, select a tool, call it, interpret the result, and return a structured output. The reasoning framework must: support stateful multi-step reasoning within a step, checkpoint state so a crashed step can resume mid-reasoning, expose tool calls as a visible graph structure that maps to architecture diagrams, and integrate with MCP tool clients.

## Decision

Use **LangGraph** as the agent reasoning framework for each workflow step.

## Options considered

| Option | Strengths | Weaknesses |
|---|---|---|
| **LangGraph** | Graph structure maps directly to architecture diagrams; SqliteSaver checkpointing; explicit state schema; tool-calling support; active development | More verbose than simple chains |
| LangChain LCEL | Simpler syntax; same ecosystem | Less explicit state management; no native graph structure |
| AutoGen | Multi-agent out of the box | Overkill for single-agent steps; more complex |
| Direct API calls | Maximum simplicity | No graph structure; no checkpointing; no state schema |
| CrewAI | Good multi-agent UX | Less control over graph structure; weaker checkpointing |

## Rationale

**1. The graph structure is the architecture made visible.** LangGraph's nodes and edges map directly onto the architecture diagrams built during the design phase. `load_memory → reason → call_tool → END` is both the code and the diagram. This is the strongest argument for LangGraph in a prototype whose purpose is to make architecture patterns tangible.

**2. SqliteSaver provides step-level checkpointing.** LangGraph's checkpointer persists the agent's state after each node. If the reasoning loop crashes mid-step, it resumes at the last node — not from the beginning of the step. This maps to the short-term state layer in the enterprise architecture: distinct from Temporal's saga-level durability and from Mem0's cross-session memory.

**3. Explicit state schema enforces the contract.** The `AgentState` TypedDict defines exactly what the reasoning loop produces and consumes. This makes the interface between Temporal activities and the LangGraph agent explicit and testable.

**4. Tool-calling integrates cleanly with MCP clients.** LangGraph's tool node pattern wraps MCP client calls naturally. The `call_tool_node` dispatches to MCP servers through the same interface the architecture specifies — governed tool contracts, not direct API calls.

## Implementation note

The prototype uses LangGraph in **deterministic mode** for the initial demo scenarios — the reasoning node selects tools based on the saga step rather than calling Claude. This removes the Anthropic API dependency from the demo, allowing all four Temporal scenarios to run cleanly without an internet connection or API availability concern.

Claude reasoning is the next iteration: restore the `reason_node` to call Claude Haiku with the step context, preferences, and available tools, and let Claude select and parameterize the tool call. The graph structure does not change — only the `reason_node` implementation changes.

## Consequences

- LangGraph and langchain-core are dependencies
- Each saga step creates a SqliteSaver database file in `/tmp/`
- The `AgentState` TypedDict is the interface contract between Temporal and LangGraph
- Adding Claude reasoning requires only modifying `reason_node` — no graph structural changes
