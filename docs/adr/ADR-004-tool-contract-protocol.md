# ADR-004 — Tool Contract Protocol: MCP

**Status:** Accepted  
**Date:** June 2026  
**Deciders:** Raj Kasumarthi  

---

## Context

The prototype's agents need to call external systems — flight search, flight booking, hotel search, hotel booking, flight cancellation, hotel cancellation. The interface between the agent and these systems needs to be: swappable (mock backend replaceable with real API without touching agent code), governed (defined schema, auditable), and protocol-standard (aligns with the enterprise interoperability layer).

## Decision

Use **MCP (Model Context Protocol)** as the tool contract protocol.

## Options considered

| Option | Strengths | Weaknesses |
|---|---|---|
| **MCP** | Open standard (Anthropic, adopted industry-wide); tool schema in JSON Schema; swappable transport (stdio, HTTP SSE); agent-native design; aligns with enterprise tool contract pattern | Newer standard; stdio transport not suitable for production scale |
| LangChain tools | Same ecosystem; simple decorator pattern | Not a protocol standard; not swappable across frameworks |
| OpenAPI / REST | Universal; mature tooling | Not agent-native; no tool discovery; schema coupling |
| gRPC | Strong typing; efficient | Higher setup cost; not agent-native |
| Direct function calls | Simplest | No governance boundary; tight coupling; not swappable |

## Rationale

**1. MCP is the emerging standard for agent tool contracts.** Adopted by Anthropic, implemented in Claude Code, Claude Desktop, and major agent frameworks, MCP is converging as the standard interface between agents and external systems. Choosing MCP now aligns the prototype with the direction the enterprise tool contract layer is heading.

**2. The interface is the governance boundary.** The most important architectural property of MCP in this context is that the agent calls tools through a defined, versioned interface — not directly into the backend. Swapping the flight backend from a mock to a real Amadeus API requires rewriting the MCP server, not the agent. This is the governance boundary that prevents N×N integration sprawl at scale.

**3. stdio transport is correct for the prototype.** The stdio transport spawns the MCP server as a subprocess and communicates over stdin/stdout. Zero network configuration, zero port management, runs entirely on a MacBook. The transport is swappable to HTTP SSE for production without changing the tool schema or agent code.

**4. Tool discovery maps to the enterprise tool registry.** `tools/list` in MCP returns the available tools and their schemas. This maps to the agent tool registry in the enterprise control plane — agents discover what tools are available rather than having tools hardcoded.

## Transport decision

| Transport | Use case |
|---|---|
| stdio | Local prototype; single machine; zero config |
| HTTP SSE | Production; network-accessible; multiple agents sharing one server |

The prototype uses stdio. Production uses HTTP SSE. The tool schema and agent code do not change between transports.

## Tool contract design

Each MCP server exposes three tools following a consistent pattern:

```
search_{resource}   →  returns options ranked by preference
confirm_{resource}  →  commits a selection, returns booking_ref
cancel_{resource}   →  compensating action, returns confirmation
```

The `cancel_` tools are defined alongside the `confirm_` tools at design time. This enforces the saga compensation requirement: every forward action has a defined inverse before it is deployed.

## Consequences

- MCP client (stdio subprocess management) is a custom implementation in the prototype
- Production deployment requires HTTP SSE transport and an MCP server host
- Tool schemas are defined in Python dicts and should be versioned alongside the server
- The `cancel_` tool pattern must be enforced as a design requirement for all future tool contracts
