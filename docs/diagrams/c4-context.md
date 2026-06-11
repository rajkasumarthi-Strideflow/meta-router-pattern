# C4 Context Diagram — Stateful Travel Agent Prototype

Level 1: the system and its external actors. What exists, who uses it, what it depends on.

## Enterprise analog

This diagram maps to the **triggers and external systems** layer of the enterprise architecture. The Traveller is the human prompt trigger; the Human Approver is the HITL gate; Mem0, MCP Servers, and Temporal are the shared substrate components.

## Diagram

```mermaid
C4Context
    title C4 Context — Stateful Travel Agent Prototype

    Person(traveller, "Traveller", "Sends trip requests via CLI or chat. Enterprise analog: employee or customer triggering an agentic workflow.")
    Person(approver, "Human Approver", "Confirms the itinerary at the HITL gate. Enterprise analog: manager, compliance officer, or process owner.")

    System_Boundary(system, "Travel Agent System") {
        System(agent, "Travel Agent", "Orchestrates trip booking across flights and hotels. Demonstrates durable saga, memory, HITL, and compensation.")
    }

    System_Ext(mem0, "Mem0", "Long-term preference store. Persists user preferences across sessions. Enterprise analog: shared context layer.")
    System_Ext(mcp_flight, "MCP Flight Server", "Governed tool contract for flight search and booking. Enterprise analog: CRM / billing system.")
    System_Ext(mcp_hotel, "MCP Hotel Server", "Governed tool contract for hotel search and booking. Enterprise analog: ERP / ITSM system.")
    System_Ext(temporal, "Temporal", "Durable workflow execution engine. Persists saga state, drives step sequencing, handles signals. Enterprise analog: meta-orchestrator.")

    Rel(traveller, agent, "Sends trip request", "CLI / chat")
    Rel(agent, approver, "Sends itinerary for HITL confirmation", "Signal / notification")
    Rel(approver, agent, "Sends approval signal", "Temporal signal")
    Rel(agent, mem0, "Reads and writes user preferences", "Mem0 SDK")
    Rel(agent, mcp_flight, "Calls flight search and booking tools", "MCP stdio")
    Rel(agent, mcp_hotel, "Calls hotel search and booking tools", "MCP stdio")
    Rel(agent, temporal, "Workflow state persistence and signals", "Temporal SDK")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Notes

- All MCP servers are local stubs in the prototype. The interface is real MCP; the backend is deterministic mock data.
- Temporal runs as a local dev server (`temporal server start-dev`) in the prototype. In production this is Temporal Cloud or a self-hosted cluster.
- Mem0 uses an in-process fallback store in the prototype. In production this is Mem0 Cloud or a self-hosted vector DB (Qdrant, Pinecone).
