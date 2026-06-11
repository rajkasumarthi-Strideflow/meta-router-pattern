"""
run.py
-------
Demo CLI — drives all prototype scenarios.

Usage:
  # Prerequisite: Temporal dev server running
  temporal server start-dev

  # Prerequisite: worker running in another terminal
  python temporal_worker/worker.py

  # Run all demo scenarios
  python run.py

  # Run specific scenario
  python run.py --scenario happy_path
  python run.py --scenario crash_resume
  python run.py --scenario rollback
  python run.py --scenario returning_user

Scenarios:
  happy_path     — full 5-step booking, HITL approval, complete
  crash_resume   — start workflow, simulate worker restart, prove state survives
  rollback       — change return date after hotel is booked, demonstrate compensation
  returning_user — second booking pre-fills preferences from Mem0
"""

import asyncio
import argparse
import json
import time
import uuid
import sys

sys.path.insert(0, "/home/claude/travel_agent")

from temporalio.client import Client


TEMPORAL_HOST = "localhost:7233"
TASK_QUEUE    = "travel-agent"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_header(title: str):
    print(f"\n{'═' * 60}")
    print(f"  {title}")
    print(f"{'═' * 60}")


def _print_step(step: str, msg: str):
    print(f"\n  [{step}] {msg}")


def _print_state(label: str, state: dict):
    print(f"\n  {label}:")
    for k, v in state.items():
        if v:
            print(f"    {k}: {v}")


# ---------------------------------------------------------------------------
# Scenario: happy path
# Demonstrates the full five-step saga with HITL approval.
# Enterprise analog: a nominal long-running workflow completing end to end.
# ---------------------------------------------------------------------------

async def scenario_happy_path(client: Client):
    _print_header("Scenario 1 — Happy path")
    print("  Full 5-step saga: intent → flights → hotel → HITL → complete")

    workflow_id = f"trip-happy-{uuid.uuid4().hex[:8]}"
    user_message = (
        "I want to fly from NYC to LAX, "
        "outbound 2026-08-01, return 2026-08-08, "
        "budget 2000, seat aisle, hotel business"
    )

    _print_step("START", f"Starting workflow {workflow_id}")
    _print_step("MSG", user_message)

    handle = await client.start_workflow(
        "TripBookingWorkflow",
        args=[workflow_id, "user_raj", user_message],
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )

    # Poll status while workflow runs
    for _ in range(20):
        await asyncio.sleep(2)
        try:
            status_json = await handle.execute_update("get_status")
            status = json.loads(status_json)
            _print_step("STATUS", json.dumps(status, indent=4))

            if status.get("status") == "paused_hitl":
                _print_step("HITL", "Workflow paused at confirmation gate")
                _print_step("HITL", "Sending approval signal...")
                await handle.signal("approve_itinerary")
                break

            if status.get("status") in ("complete", "failed"):
                break
        except Exception as e:
            _print_step("POLL", f"Waiting... ({e})")

    # Get final result
    await asyncio.sleep(2)
    result = await handle.result()
    _print_step("COMPLETE", result)


# ---------------------------------------------------------------------------
# Scenario: crash and resume
# THE key demo moment — proves durable state.
# Enterprise analog: worker restart mid-onboarding; workflow resumes at
# the step it was on, not from the beginning.
# ---------------------------------------------------------------------------

async def scenario_crash_resume(client: Client):
    _print_header("Scenario 2 — Crash and resume (durable state)")
    print("  Start workflow → workflow progresses → simulate restart")
    print("  → workflow resumes at last checkpoint, not from step 1")
    print()
    print("  NOTE: This scenario requires you to manually stop and restart")
    print("  the worker (Ctrl+C in the worker terminal, then restart it)")
    print("  while the workflow is mid-flight. The workflow will resume")
    print("  at the step it was on. You can watch this in the Temporal UI:")
    print("  http://localhost:8233")

    workflow_id  = f"trip-crash-{uuid.uuid4().hex[:8]}"
    user_message = (
        "from NYC to SFO out 2026-09-10 back 2026-09-17 "
        "budget 1800 seat window hotel business"
    )

    _print_step("START", f"Starting workflow {workflow_id}")
    handle = await client.start_workflow(
        "TripBookingWorkflow",
        args=[workflow_id, "user_crash_demo", user_message],
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )

    print()
    print("  Workflow started. Open Temporal UI at http://localhost:8233")
    print(f"  Look for workflow ID: {workflow_id}")
    print()
    print("  Steps to demo durable state:")
    print("  1. Watch the workflow reach 'outbound_flight' or 'hotel' step")
    print("  2. Kill the worker (Ctrl+C in worker terminal)")
    print("  3. Note the workflow is SUSPENDED in Temporal UI — state preserved")
    print("  4. Restart the worker: python temporal_worker/worker.py")
    print("  5. Watch the workflow RESUME from the same step — not step 1")
    print()

    # Poll a few times to show it's progressing
    for i in range(6):
        await asyncio.sleep(3)
        try:
            status_json = await handle.execute_update("get_status")
            status = json.loads(status_json)
            _print_step(f"T+{(i+1)*3}s", f"Status: {status.get('status')} | Step: {status.get('current_step')}")
            if status.get("status") in ("paused_hitl",):
                _print_step("HITL", "Approving...")
                await handle.signal("approve_itinerary")
                break
        except Exception as e:
            _print_step("POLL", f"({e})")


# ---------------------------------------------------------------------------
# Scenario: rollback
# User changes return date after hotel is confirmed.
# Demonstrates saga compensation.
# Enterprise analog: user modifies an in-flight procurement request;
# orchestrator compensates committed steps and replans.
# ---------------------------------------------------------------------------

async def scenario_rollback(client: Client):
    _print_header("Scenario 3 — Rollback (saga compensation)")
    print("  Book flights and hotel → change return date → hotel compensated → replan")

    workflow_id  = f"trip-rollback-{uuid.uuid4().hex[:8]}"
    user_message = (
        "from NYC to MIA out 2026-10-05 back 2026-10-10 "
        "budget 1500 seat aisle hotel business"
    )

    _print_step("START", f"Starting workflow {workflow_id}")
    handle = await client.start_workflow(
        "TripBookingWorkflow",
        args=[workflow_id, "user_rollback_demo", user_message],
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )

    # Wait for hotel to be confirmed, then trigger date change
    hotel_booked = False
    for _ in range(25):
        await asyncio.sleep(2)
        try:
            status_json = await handle.execute_update("get_status")
            status      = json.loads(status_json)
            step        = status.get("current_step", "")
            hotel_ref   = status.get("hotel")

            _print_step("STATUS", f"step={step} | hotel={hotel_ref}")

            # Once hotel is confirmed, trigger the date change
            if hotel_ref and not hotel_booked:
                hotel_booked = True
                new_date     = "2026-10-12"
                _print_step("USER", f"Changing return date to {new_date}!")
                _print_step("SAGA", "Sending change_return_date signal...")
                await handle.signal("change_return_date", new_date)
                _print_step("SAGA", "Compensation in progress: cancelling hotel, re-booking return flight + hotel")

            if status.get("status") == "paused_hitl":
                _print_step("HITL", "New itinerary ready. Approving...")
                await handle.signal("approve_itinerary")
                break

            if status.get("status") in ("complete", "failed"):
                break
        except Exception as e:
            _print_step("POLL", f"Waiting... ({e})")

    await asyncio.sleep(2)
    result = await handle.result()
    _print_step("COMPLETE", result)


# ---------------------------------------------------------------------------
# Scenario: returning user
# Demonstrates Mem0 long-term memory — preferences from a prior booking
# are retrieved and applied without re-asking.
# Enterprise analog: shared context layer hydration at workflow entry.
# ---------------------------------------------------------------------------

async def scenario_returning_user(client: Client):
    _print_header("Scenario 4 — Returning user (Mem0 long-term memory)")
    print("  First booking saves preferences → second booking pre-fills them")

    # First booking — establish preferences
    wf1 = f"trip-first-{uuid.uuid4().hex[:8]}"
    _print_step("BOOKING 1", f"First booking ({wf1}) — establishing preferences")
    _print_step("MSG", "from BOS to SEA out 2026-07-15 back 2026-07-22 "
                "budget 2500 seat aisle hotel business airline Delta")

    h1 = await client.start_workflow(
        "TripBookingWorkflow",
        args=[wf1, "user_returning", "from BOS to SEA out 2026-07-15 back 2026-07-22 "
              "budget 2500 seat aisle hotel business airline Delta"],
        id=wf1,
        task_queue=TASK_QUEUE,
    )
    # Let it run a bit to save preferences
    await asyncio.sleep(8)
    try:
        await h1.signal("approve_itinerary")
    except Exception:
        pass

    _print_step("MEM0", "Preferences saved: Delta, aisle, business hotel, budget $2500")

    # Second booking — minimal message, preferences should auto-apply
    wf2 = f"trip-second-{uuid.uuid4().hex[:8]}"
    _print_step("BOOKING 2", f"Second booking ({wf2}) — minimal message, prefs pre-filled")
    _print_step("MSG", "from JFK to ORD out 2026-11-01 back 2026-11-05")
    print()
    print("  Note: no airline, seat, hotel, or budget specified.")
    print("  Mem0 will retrieve stored preferences and apply them.")

    h2 = await client.start_workflow(
        "TripBookingWorkflow",
        args=[wf2, "user_returning", "from JFK to ORD out 2026-11-01 back 2026-11-05"],
        id=wf2,
        task_queue=TASK_QUEUE,
    )

    for _ in range(15):
        await asyncio.sleep(2)
        try:
            status_json = await h2.execute_update("get_status")
            status      = json.loads(status_json)
            _print_step("STATUS", f"step={status.get('current_step')} | "
                        f"outbound={status.get('outbound_flight')}")
            if status.get("status") == "paused_hitl":
                _print_step("HITL", "Approving second booking...")
                await h2.signal("approve_itinerary")
                break
            if status.get("status") in ("complete", "failed"):
                break
        except Exception as e:
            _print_step("POLL", f"({e})")

    await asyncio.sleep(2)
    result = await h2.result()
    _print_step("COMPLETE", result)


# ---------------------------------------------------------------------------
# Offline smoke test — validates MCP servers and LangGraph without Temporal
# Run this first to verify the stack works before starting Temporal.
# ---------------------------------------------------------------------------

async def scenario_smoke_test():
    _print_header("Smoke test — MCP servers + LangGraph (no Temporal needed)")

    from langgraph_agent.mcp_client import MCPClient
    from pathlib import Path

    # Test flight MCP server
    _print_step("MCP", "Testing flight server...")
    _BASE = Path(__file__).parent
    fc = MCPClient(str(_BASE / "mcp_servers" / "flight_server.py"))

    tools = fc.list_tools()
    _print_step("MCP", f"Flight server tools: {[t['name'] for t in tools]}")

    result = fc.call_tool("search_flights", {
        "origin": "NYC", "destination": "LAX",
        "date": "2026-08-01", "direction": "outbound",
        "preferred_airline": "Delta",
    })
    flights = result.get("flights", [])
    _print_step("MCP", f"Found {len(flights)} flights. First: "
                f"{flights[0]['airline']} {flights[0]['flight_id']} ${flights[0]['price']}")

    confirm = fc.call_tool("confirm_flight", {
        "flight_id":     flights[0]["flight_id"],
        "seat_preference":"aisle",
        "direction":     "outbound",
        "airline":       flights[0]["airline"],
        "origin":        "NYC",
        "destination":   "LAX",
        "departure":     flights[0]["departure"],
        "arrival":       flights[0]["arrival"],
        "price":         flights[0]["price"],
    })
    _print_step("MCP", f"Flight confirmed: {confirm['booking']['booking_ref']}")
    fc.close()

    # Test hotel MCP server
    _print_step("MCP", "Testing hotel server...")
    hc = MCPClient(str(_BASE / "mcp_servers" / "hotel_server.py"))

    hotels = hc.call_tool("search_hotels", {
        "city": "Los Angeles", "check_in": "2026-08-01", "check_out": "2026-08-08",
        "hotel_tier": "business",
    })
    h = hotels.get("hotels", [])
    _print_step("MCP", f"Found {len(h)} hotels. First: {h[0]['hotel_name']} ${h[0]['price_per_night']}/night")

    confirm_h = hc.call_tool("confirm_hotel", {
        "hotel_id":       h[0]["hotel_id"],
        "hotel_name":     h[0]["hotel_name"],
        "city":           "Los Angeles",
        "check_in":       "2026-08-01",
        "check_out":      "2026-08-08",
        "room_type":      h[0]["room_type"],
        "price_per_night":h[0]["price_per_night"],
        "total_price":    h[0]["total_price"],
    })
    _print_step("MCP", f"Hotel confirmed: {confirm_h['booking']['booking_ref']}")
    hc.close()

    # Test Mem0 preferences
    _print_step("MEM0", "Testing preference memory...")
    from langgraph_agent.memory import PreferenceMemory
    from shared.models import UserPreferences
    pm = PreferenceMemory()
    prefs = UserPreferences(
        user_id="smoke_test_user",
        preferred_airline="Delta",
        seat_preference="aisle",
        hotel_tier="business",
        budget_ceiling=2000.0,
    )
    pm.save_preferences(prefs)
    loaded = pm.load_preferences("smoke_test_user")
    _print_step("MEM0", f"Saved and loaded: airline={loaded.preferred_airline} "
                f"seat={loaded.seat_preference} hotel={loaded.hotel_tier}")

    print()
    print("  Smoke test complete. MCP servers and Mem0 are working.")
    print("  Start Temporal dev server and the worker to run full scenarios.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Travel agent demo runner")
    parser.add_argument(
        "--scenario",
        choices=["smoke_test", "happy_path", "crash_resume", "rollback", "returning_user", "all"],
        default="smoke_test",
    )
    args = parser.parse_args()

    if args.scenario == "smoke_test":
        await scenario_smoke_test()
        return

    # All other scenarios require Temporal
    try:
        client = await Client.connect(TEMPORAL_HOST)
    except Exception as e:
        print(f"\n  ERROR: Cannot connect to Temporal at {TEMPORAL_HOST}")
        print(f"  Start it with: temporal server start-dev")
        print(f"  ({e})")
        return

    if args.scenario == "happy_path" or args.scenario == "all":
        await scenario_happy_path(client)
    if args.scenario == "crash_resume" or args.scenario == "all":
        await scenario_crash_resume(client)
    if args.scenario == "rollback" or args.scenario == "all":
        await scenario_rollback(client)
    if args.scenario == "returning_user" or args.scenario == "all":
        await scenario_returning_user(client)


if __name__ == "__main__":
    asyncio.run(main())
