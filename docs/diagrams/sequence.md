# Workflow Sequence Diagram — Stateful Travel Agent Prototype

Three sequences: happy path, rollback (date change), and crash-resume.

## Happy path — full five-step saga with HITL

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI
    participant Temporal as Temporal Worker
    participant LangGraph as LangGraph Agent
    participant Mem0
    participant MCP_Flight as MCP Flight Server
    participant MCP_Hotel as MCP Hotel Server
    actor Approver as Human Approver

    Note over User,Approver: Step 1 — Collect intent and preferences

    User->>CLI: Trip request (origin, dest, dates, budget)
    CLI->>Temporal: start_workflow(TripBookingWorkflow)
    Temporal->>LangGraph: run_collect_intent activity
    LangGraph->>Mem0: save_preferences(airline, seat, hotel_tier, budget)
    Mem0-->>LangGraph: confirmed
    LangGraph-->>Temporal: StepOutput(success=true, intent)
    Note right of Temporal: ✓ Checkpoint — intent committed

    Note over User,Approver: Step 2 — Outbound flight

    Temporal->>LangGraph: run_flight_step(outbound)
    LangGraph->>Mem0: load_preferences(user_id)
    Mem0-->>LangGraph: preferred_airline, seat_preference
    LangGraph->>MCP_Flight: search_flights(origin, dest, date, prefs)
    MCP_Flight-->>LangGraph: flight options (sorted by preference)
    LangGraph->>MCP_Flight: confirm_flight(flight_id, seat)
    MCP_Flight-->>LangGraph: booking_ref FL0B4ADB
    LangGraph-->>Temporal: StepOutput(success=true, FlightBooking)
    Note right of Temporal: ✓ Checkpoint — outbound flight committed

    Note over User,Approver: Step 3 — Return flight

    Temporal->>LangGraph: run_flight_step(return)
    LangGraph->>Mem0: load_preferences(user_id)
    Mem0-->>LangGraph: preferences
    LangGraph->>MCP_Flight: search_flights(dest, origin, return_date, prefs)
    MCP_Flight-->>LangGraph: flight options
    LangGraph->>MCP_Flight: confirm_flight(flight_id, seat)
    MCP_Flight-->>LangGraph: booking_ref
    LangGraph-->>Temporal: StepOutput(success=true, FlightBooking)
    Note right of Temporal: ✓ Checkpoint — return flight committed

    Note over User,Approver: Step 4 — Hotel

    Temporal->>LangGraph: run_hotel_step
    LangGraph->>Mem0: load_preferences(user_id)
    Mem0-->>LangGraph: hotel_tier, budget_ceiling
    LangGraph->>MCP_Hotel: search_hotels(city, check_in, check_out, prefs)
    MCP_Hotel-->>LangGraph: hotel options (sorted by tier preference)
    LangGraph->>MCP_Hotel: confirm_hotel(hotel_id, dates, room_type)
    MCP_Hotel-->>LangGraph: booking_ref HT858E92
    LangGraph-->>Temporal: StepOutput(success=true, HotelBooking)
    Note right of Temporal: ✓ Checkpoint — hotel committed

    Note over User,Approver: Step 5 — HITL confirmation gate

    Temporal->>Approver: Send itinerary for approval
    Note over Temporal: ⏸ workflow.wait_condition()<br/>Zero compute held<br/>State persists in Temporal server<br/>Can wait hours or days
    Approver->>CLI: approve_itinerary signal
    CLI->>Temporal: signal(approve_itinerary)
    Note over Temporal: ▶ Workflow resumed from durable state
    Temporal-->>CLI: Saga complete {outbound, return, hotel}
    CLI-->>User: Booking confirmed
```

---

## Rollback sequence — user changes return date after hotel is confirmed

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant CLI
    participant Temporal as Temporal Worker
    participant MCP_Flight as MCP Flight Server
    participant MCP_Hotel as MCP Hotel Server

    Note over User,MCP_Hotel: Steps 1–4 complete — outbound flight, return flight, hotel all committed

    User->>CLI: change_return_date(2026-10-12)
    CLI->>Temporal: signal(change_return_date, new_date)

    Note over Temporal: Saga status → COMPENSATING<br/>rollback_from = RETURN_FLIGHT

    rect rgb(250, 236, 231)
        Note over Temporal,MCP_Hotel: Compensation sequence (reverse order)
        Temporal->>MCP_Hotel: cancel_hotel(booking_ref HT858E92)
        MCP_Hotel-->>Temporal: cancelled, refund initiated
        Temporal->>MCP_Flight: cancel_flight(return booking_ref)
        MCP_Flight-->>Temporal: cancelled, refund initiated
    end

    Note over Temporal: intent.return_date updated to 2026-10-12<br/>Saga status → RUNNING

    rect rgb(225, 245, 238)
        Note over Temporal,MCP_Hotel: Replan with updated dates
        Temporal->>MCP_Flight: search + confirm return flight (new date)
        MCP_Flight-->>Temporal: new return booking_ref
        Temporal->>MCP_Hotel: search + confirm hotel (updated check_out)
        MCP_Hotel-->>Temporal: new hotel booking_ref
    end

    Note over Temporal: HITL gate — waiting for approval on updated itinerary
```

---

## Crash and resume — durable state across process kill

```mermaid
sequenceDiagram
    autonumber
    participant CLI
    participant Worker as Temporal Worker (Process)
    participant Temporal as Temporal Server
    participant LangGraph as LangGraph Agent

    CLI->>Temporal: start_workflow(TripBookingWorkflow)
    Temporal->>Worker: dispatch workflow task
    Worker->>LangGraph: run_collect_intent
    LangGraph-->>Worker: intent committed
    Note right of Temporal: State persisted in Temporal server

    Worker->>LangGraph: run_flight_step(outbound)
    LangGraph-->>Worker: outbound flight committed
    Note right of Temporal: State persisted in Temporal server

    Worker->>LangGraph: run_hotel_step
    Note over Worker: ⏸ 30s sleep (demo window)

    Note over Worker: ❌ Worker process killed (Ctrl+C)<br/>All in-memory state gone

    Note right of Temporal: Workflow still RUNNING in Temporal server<br/>State fully preserved<br/>Zero compute consumed while waiting

    Note over Worker: ▶ Worker process restarted

    Worker->>Temporal: Connect and poll task queue
    Temporal->>Worker: Resume hotel activity (same workflow)
    Worker->>LangGraph: run_hotel_step (resumed)
    LangGraph-->>Worker: hotel committed
    Note right of Temporal: ✓ Continued from hotel step<br/>NOT restarted from step 1

    Worker->>Temporal: HITL gate — waiting for approval
```

---

## Notes

**Why durable state matters:** In a conventional workflow engine, killing the worker in the crash-resume sequence would require restarting the entire booking from scratch — re-collecting intent, re-booking the outbound flight, re-booking the return flight. With Temporal, the workflow resumes exactly at the hotel step because every prior step's result is persisted in the Temporal server's database. The worker is stateless; the engine is stateful.

**Why HITL is a durable state, not an interruption:** `workflow.wait_condition()` in Temporal is not a sleep or a poll. It parks the workflow in a persisted waiting state, releases all compute, and resumes the moment the signal arrives — even if that signal comes days later and after multiple worker restarts.

**Why compensation works:** Each forward step registers a compensating action (cancel_hotel, cancel_flight) at definition time. When rollback is triggered, Temporal runs these in inverse order. The prototype demonstrates this with a hotel and flight cancellation; the pattern is identical for reversing a SAP payroll record or closing a ServiceNow IT ticket.
