# C4 Container Diagram — Stateful Travel Agent Prototype

Level 2: inside the system boundary. Each container is a deployable unit with a distinct responsibility.

## Enterprise analog

Each container maps to a distinct architectural concern in the enterprise reference architecture. The Temporal Worker is the meta-orchestrator runtime; the LangGraph Agent is the per-step reasoning loop; the MCP Clients are the governed tool contract clients; Mem0 is the shared context layer.

## Diagram

```mermaid
C4Container
    title C4 Container — Stateful Travel Agent Prototype

    Person(traveller, "Traveller", "Sends trip requests")
    Person(approver, "Human Approver", "Approves itinerary at HITL gate")

    System_Boundary(system, "Travel Agent System") {

        Container(cli, "CLI / Chat UI", "Python CLI", "Entry point for user input. Starts workflows and sends signals via Temporal client. Enterprise analog: channel layer — web, chat, voice, portal.")

        Container(temporal_worker, "Temporal Worker", "Python / Temporal SDK", "Hosts the TripBookingWorkflow saga definition. Drives step sequencing, holds durable state, coordinates HITL, executes compensation. Enterprise analog: meta-orchestrator runtime.")

        Container(langgraph_agent, "LangGraph Agent", "Python / LangGraph", "Reasoning loop executed inside each Temporal activity. Nodes: load_memory → reason → call_tool. Checkpoints state via SqliteSaver after each node. Enterprise analog: per-step agent reasoning loop.")

        Container(mem0_client, "Mem0 Client", "Python / Mem0 SDK", "Reads and writes user preferences across sessions. Called at the start of each step to hydrate context. Enterprise analog: shared context layer — cross-session user profile.")

        Container(mcp_flight, "MCP Flight Client + Server", "Python / MCP stdio", "Governed tool contract for flight search and booking. search_flights, confirm_flight, cancel_flight. Enterprise analog: CRM / billing tool contract.")

        Container(mcp_hotel, "MCP Hotel Client + Server", "Python / MCP stdio", "Governed tool contract for hotel search and booking. search_hotels, confirm_hotel, cancel_hotel. Enterprise analog: ERP / ITSM tool contract.")

        ContainerDb(pg_checkpointer, "SQLite Checkpointer", "SQLite / LangGraph SqliteSaver", "Persists LangGraph agent state within a saga step. Short-term state — scoped to one step execution. Enterprise analog: step-level working memory.")

        ContainerDb(temporal_server, "Temporal Server", "Temporal dev server", "Persists durable saga state across all in-flight workflows. Owns workflow position, activity results, signal history. Enterprise analog: meta-orchestrator state store.")

        Container(hitl_endpoint, "HITL Signal", "Temporal signal via CLI", "Human approver sends approval signal to resume the paused workflow. Enterprise analog: human approval gate — manager click in HR portal, compliance sign-off.")
    }

    Rel(traveller, cli, "Sends trip request", "CLI input")
    Rel(cli, temporal_worker, "Starts workflow, sends signals", "Temporal SDK")
    Rel(temporal_worker, langgraph_agent, "Calls run_step() per saga step", "Python function call inside activity")
    Rel(langgraph_agent, mem0_client, "Reads preferences at step entry", "Mem0 SDK")
    Rel(langgraph_agent, mcp_flight, "Calls flight tools", "MCP stdio")
    Rel(langgraph_agent, mcp_hotel, "Calls hotel tools", "MCP stdio")
    Rel(langgraph_agent, pg_checkpointer, "Checkpoints graph state", "SQLite")
    Rel(temporal_worker, temporal_server, "Persists saga state, polls for tasks", "Temporal gRPC")
    Rel(approver, hitl_endpoint, "Sends approval", "CLI signal command")
    Rel(hitl_endpoint, temporal_worker, "Resume signal", "Temporal signal")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Container responsibilities

| Container | Owns | Does not own |
|---|---|---|
| Temporal Worker | Saga position, step sequence, compensation | Step-level reasoning, tool selection |
| LangGraph Agent | Reasoning within a step, tool dispatch | Saga position, cross-step state |
| Mem0 Client | Cross-session user preferences | In-step working memory |
| SQLite Checkpointer | In-step graph state | Cross-step saga state |
| Temporal Server | All durable saga state | Reasoning, tool calls |
| MCP Servers | Tool contract interface | Business logic, agent state |

## Key design principle

No container holds state that belongs to another. Temporal owns saga position. LangGraph owns step-level reasoning state. Mem0 owns cross-session preferences. The separation is deliberate — each can be replaced, scaled, or swapped independently.
