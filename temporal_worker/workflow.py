"""
temporal_worker/workflow.py
----------------------------
Temporal workflow definition — the durable saga orchestrator.

Enterprise analog: meta-orchestrator saga definition.
One workflow class manages the full trip-planning saga end to end:
- Sequences the five steps
- Holds durable state (survives restarts)
- Coordinates LangGraph agent activities
- Handles HITL pause/resume
- Executes compensation on rollback

Key Temporal concepts used:
  @workflow.defn    — marks a class as a Temporal workflow
  @activity.defn    — marks a function as a Temporal activity (retryable unit)
  workflow.execute_activity()  — dispatches an activity and awaits completion
  workflow.wait_condition()    — durable pause (HITL gate)
  workflow.signal()            — external signal to resume a paused workflow
  workflow.update()            — user sends a mutation mid-workflow (date change)
"""

import asyncio
import dataclasses
import json
import os
from datetime import timedelta
from typing import Optional
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from shared.models import (
    TripSagaState, TripIntent, UserPreferences,
    FlightBooking, HotelBooking, SagaStep, SagaStatus
)


# ---------------------------------------------------------------------------
# Activity input/output types
# Each activity is a discrete, retryable unit of work.
# Enterprise analog: async participant — SAP, ServiceNow, identity system
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class StepInput:
    saga_state_json: str   # serialized TripSagaState
    step: str              # SagaStep value
    user_message: str
    thread_id: str


@dataclasses.dataclass
class StepOutput:
    success: bool
    result_json: str       # serialized booking result
    error: Optional[str] = None


@dataclasses.dataclass
class CompensateInput:
    booking_ref: str
    booking_type: str      # "flight" | "hotel"


# ---------------------------------------------------------------------------
# Activities
# Each activity wraps one LangGraph agent step invocation.
# Temporal retries activities automatically on failure.
# Enterprise analog: async participant activity with at-least-once delivery
# ---------------------------------------------------------------------------

@activity.defn(name="run_collect_intent")
async def run_collect_intent(inp: StepInput) -> StepOutput:
    """
    Step 1: Collect trip intent and load/save preferences via Mem0.
    In the prototype this parses the user's message directly.
    Enterprise analog: intake form processing, initial data capture.
    """
    try:
        saga = _deserialize_saga(inp.saga_state_json)

        # Parse intent from user message (simplified for prototype)
        # In production: run through LangGraph with an intent-extraction graph
        msg = inp.user_message

        # Demo-friendly defaults if not fully specified
        intent = TripIntent(
            origin         = _extract(msg, "from", "NYC"),
            destination    = _extract(msg, "to",   "LAX"),
            outbound_date  = _extract(msg, "out",  "2026-08-01"),
            return_date    = _extract(msg, "back", "2026-08-08"),
            budget         = float(_extract(msg, "budget", "2000")),
            traveller_name = saga.user_id,
        )
        saga.intent = intent

        # Save preferences from message to Mem0
        # Enterprise analog: write to shared context layer
        from langgraph_agent.memory import preference_memory
        prefs = UserPreferences(
            user_id           = saga.user_id,
            preferred_airline = _extract(msg, "airline", None),
            seat_preference   = _extract(msg, "seat",    "aisle"),
            hotel_tier        = _extract(msg, "hotel",   "business"),
            budget_ceiling    = intent.budget,
        )
        preference_memory.save_preferences(prefs)
        saga.preferences = prefs

        return StepOutput(
            success     = True,
            result_json = json.dumps(dataclasses.asdict(intent)),
        )
    except Exception as e:
        return StepOutput(success=False, result_json="{}", error=str(e))


@activity.defn(name="run_flight_step")
async def run_flight_step(inp: StepInput) -> StepOutput:
    """
    Steps 2 & 3: Search and confirm a flight via LangGraph agent.
    Enterprise analog: async participant activity — calls governed tool contract,
    returns structured result to meta-orchestrator.
    """
    try:
        from langgraph_agent.agent import run_step, SagaStep as LS
        saga   = _deserialize_saga(inp.saga_state_json)
        step   = SagaStep(inp.step)
        ls_step = LS(inp.step)

        result = run_step(saga, ls_step, inp.user_message, inp.thread_id)
        return StepOutput(success=True, result_json=json.dumps(result))
    except Exception as e:
        return StepOutput(success=False, result_json="{}", error=str(e))


@activity.defn(name="run_hotel_step")
async def run_hotel_step(inp: StepInput) -> StepOutput:
    """
    Step 4: Search and confirm a hotel via LangGraph agent.
    Same pattern as flight step — different tool contracts, same orchestration.
    """
    import sys
    import logging
    print(">>> HOTEL STEP STARTING — Ctrl+C Terminal 2 NOW <<<", file=sys.stderr, flush=True)
    activity.logger.info("HOTEL STEP STARTING — kill the worker now for crash-resume demo")
    await asyncio.sleep(30)

    try:
        from langgraph_agent.agent import run_step
        from shared.models import SagaStep as LS
        saga    = _deserialize_saga(inp.saga_state_json)
        ls_step = LS(inp.step)

        result = run_step(saga, ls_step, inp.user_message, inp.thread_id)
        return StepOutput(success=True, result_json=json.dumps(result))
    except Exception as e:
        return StepOutput(success=False, result_json="{}", error=str(e))


@activity.defn(name="compensate_booking")
async def compensate_booking(inp: CompensateInput) -> StepOutput:
    """
    Compensation activity — undoes a committed booking.
    Enterprise analog: compensating transaction in the saga pattern.
    Called by Temporal when the user triggers a rollback (date change).

    This is the activity that makes the rollback demo work:
    kill the hotel booking, replan from return flight step.
    """
    try:
        from langgraph_agent.mcp_client import MCPClient

        if inp.booking_type == "flight":
            server = str(_PROJECT_ROOT / "mcp_servers" / "flight_server.py")
            client = MCPClient(server)
            result = client.call_tool("cancel_flight", {"booking_ref": inp.booking_ref})
        else:
            server = str(_PROJECT_ROOT / "mcp_servers" / "hotel_server.py")
            client = MCPClient(server)
            result = client.call_tool("cancel_hotel", {"booking_ref": inp.booking_ref})

        client.close()
        activity.logger.info(f"Compensated {inp.booking_type} booking {inp.booking_ref}: {result}")
        return StepOutput(success=True, result_json=json.dumps(result))
    except Exception as e:
        return StepOutput(success=False, result_json="{}", error=str(e))


# ---------------------------------------------------------------------------
# Workflow definition
# The durable saga — survives process restarts, manages step sequencing,
# holds state, coordinates HITL, and compensates on rollback.
#
# Enterprise analog: meta-orchestrator saga definition.
# One instance of this class = one trip booking in flight.
# The Temporal server persists its state; the worker executes it.
# ---------------------------------------------------------------------------

@workflow.defn(name="TripBookingWorkflow")
class TripBookingWorkflow:
    """
    Durable saga for trip booking.

    Signals:
      approve_itinerary  — human approver sends this to resume from HITL gate
      change_return_date — user requests date change, triggers compensation + replan

    Updates:
      get_status         — caller can query current saga state at any time
    """

    def __init__(self):
        self._state    = TripSagaState(workflow_id="", user_id="")
        self._approved = False
        self._new_return_date: Optional[str] = None

    # -----------------------------------------------------------------------
    # Signals
    # Enterprise analog: external events that mutate a running workflow
    # -----------------------------------------------------------------------

    @workflow.signal
    def approve_itinerary(self) -> None:
        """
        HITL approval signal.
        Enterprise analog: manager clicks 'Approve' in the HR portal.
        Temporal receives this signal and unblocks wait_condition().
        """
        workflow.logger.info("Itinerary approved by human approver")
        self._approved = True

    @workflow.signal
    def change_return_date(self, new_date: str) -> None:
        """
        User requests a return date change mid-workflow.
        Triggers compensation of confirmed hotel + replan from return flight.
        Enterprise analog: user modifies a submitted request, triggering
        a partial rollback and replan.
        """
        workflow.logger.info(f"Return date change requested: {new_date}")
        self._new_return_date = new_date

    # -----------------------------------------------------------------------
    # Updates (queryable mid-workflow)
    # Enterprise analog: workflow status API
    # -----------------------------------------------------------------------

    @workflow.update
    def get_status(self) -> str:
        return json.dumps({
            "workflow_id":   self._state.workflow_id,
            "current_step":  self._state.current_step.value,
            "status":        self._state.status.value,
            "outbound_flight": self._state.outbound_flight.booking_ref
                               if self._state.outbound_flight else None,
            "return_flight":   self._state.return_flight.booking_ref
                               if self._state.return_flight else None,
            "hotel":           self._state.hotel.booking_ref
                               if self._state.hotel else None,
        })

    # -----------------------------------------------------------------------
    # Main workflow run method
    # -----------------------------------------------------------------------

    @workflow.run
    async def run(self, workflow_id: str, user_id: str, user_message: str) -> str:
        """
        Execute the full trip booking saga.
        Returns a summary JSON string when complete.
        """
        self._state = TripSagaState(
            workflow_id = workflow_id,
            user_id     = user_id,
            status      = SagaStatus.RUNNING,
        )

        retry_policy = RetryPolicy(
            maximum_attempts        = 3,
            initial_interval        = timedelta(seconds=1),
            maximum_interval        = timedelta(seconds=10),
            backoff_coefficient     = 2.0,
        )

        # -------------------------------------------------------------------
        # Step 1: Collect intent + preferences
        # -------------------------------------------------------------------
        workflow.logger.info("Step 1: collecting trip intent")
        self._state.current_step = SagaStep.COLLECT_INTENT

        out = await workflow.execute_activity(
            run_collect_intent,
            StepInput(
                saga_state_json = _serialize_saga(self._state),
                step            = SagaStep.COLLECT_INTENT.value,
                user_message    = user_message,
                thread_id       = f"{workflow_id}-intent",
            ),
            start_to_close_timeout = timedelta(seconds=30),
            retry_policy           = retry_policy,
        )
        if not out.success:
            self._state.status = SagaStatus.FAILED
            self._state.error  = out.error
            return json.dumps({"error": out.error})

        intent_data = json.loads(out.result_json)
        self._state.intent = TripIntent(**intent_data)
        self._state.committed_steps.append(SagaStep.COLLECT_INTENT.value)

        # -------------------------------------------------------------------
        # Step 2: Outbound flight
        # -------------------------------------------------------------------
        await self._run_flight_step(
            SagaStep.OUTBOUND_FLIGHT, "outbound", retry_policy
        )
        if self._state.status == SagaStatus.FAILED:
            return json.dumps({"error": self._state.error})

        # Check for date-change signal before continuing
        if self._new_return_date:
            await self._handle_date_change(retry_policy)

        # -------------------------------------------------------------------
        # Step 3: Return flight
        # -------------------------------------------------------------------
        await self._run_flight_step(
            SagaStep.RETURN_FLIGHT, "return", retry_policy
        )
        if self._state.status == SagaStatus.FAILED:
            return json.dumps({"error": self._state.error})

        # -------------------------------------------------------------------
        # Step 4: Hotel
        # -------------------------------------------------------------------
        workflow.logger.info("Step 4: booking hotel")
        self._state.current_step = SagaStep.HOTEL
        intent = self._state.intent

        out = await workflow.execute_activity(
            run_hotel_step,
            StepInput(
                saga_state_json = _serialize_saga(self._state),
                step            = SagaStep.HOTEL.value,
                user_message    = (
                    f"Book a hotel in {intent.destination} "
                    f"from {intent.outbound_date} to {intent.return_date}"
                ),
                thread_id       = f"{workflow_id}-hotel",
            ),
            start_to_close_timeout = timedelta(minutes=2),
            retry_policy           = retry_policy,
        )
        if out.success:
            booking_data = json.loads(out.result_json)
            workflow.logger.info("Hotel booking data: %s", booking_data)
            if booking_data.get("booking_ref"):
                self._state.hotel = HotelBooking(
                    booking_ref     = booking_data.get("booking_ref", ""),
                    hotel_name      = booking_data.get("hotel_name", ""),
                    city            = booking_data.get("city", ""),
                    check_in        = booking_data.get("check_in", ""),
                    check_out       = booking_data.get("check_out", ""),
                    room_type       = booking_data.get("room_type", ""),
                    price_per_night = float(booking_data.get("price_per_night", 0.0)),
                    total_price     = float(booking_data.get("total_price", 0.0)),
                )
                self._state.committed_steps.append(SagaStep.HOTEL.value)
        else:
            self._state.status = SagaStatus.FAILED
            self._state.error  = out.error
            return json.dumps({"error": out.error})

        # Check for date-change signal after hotel is booked
        # This is the rollback demo scenario
        if self._new_return_date:
            await self._handle_date_change(retry_policy)
            # Rerun return flight and hotel with new date
            await self._run_flight_step(SagaStep.RETURN_FLIGHT, "return", retry_policy)
            await self._rerun_hotel(retry_policy)

        # -------------------------------------------------------------------
        # Step 5: HITL confirmation gate
        # Enterprise analog: human approval gate — workflow parks here,
        # holds zero compute, waits for an external signal.
        # -------------------------------------------------------------------
        workflow.logger.info("Step 5: waiting for HITL approval")
        self._state.current_step = SagaStep.CONFIRM
        self._state.status       = SagaStatus.PAUSED_HITL

        # Durable pause — Temporal persists this wait state.
        # The workflow can be restarted and it will re-enter this wait.
        await workflow.wait_condition(
            lambda: self._approved,
            timeout=timedelta(hours=24),
        )

        self._state.status       = SagaStatus.COMPLETE
        self._state.current_step = SagaStep.COMPLETE

        workflow.logger.info("Workflow complete")
        return json.dumps({
            "workflow_id":   workflow_id,
            "status":        "complete",
            "outbound":      self._state.outbound_flight.booking_ref
                             if self._state.outbound_flight else None,
            "return":        self._state.return_flight.booking_ref
                             if self._state.return_flight else None,
            "hotel":         self._state.hotel.booking_ref
                             if self._state.hotel else None,
        })

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    async def _run_flight_step(
        self, step: SagaStep, direction: str, retry_policy: RetryPolicy
    ) -> None:
        workflow.logger.info(f"Running {step.value}")
        self._state.current_step = step
        intent = self._state.intent

        msg = (
            f"Search and book the {direction} flight "
            f"from {intent.origin} to {intent.destination} "
            f"on {intent.outbound_date if direction == 'outbound' else intent.return_date}"
        )

        out = await workflow.execute_activity(
            run_flight_step,
            StepInput(
                saga_state_json = _serialize_saga(self._state),
                step            = step.value,
                user_message    = msg,
                thread_id       = f"{self._state.workflow_id}-{step.value}",
            ),
            start_to_close_timeout = timedelta(minutes=2),
            retry_policy           = retry_policy,
        )

        if out.success:
            booking_data = json.loads(out.result_json)
            workflow.logger.info("Flight booking data: %s", booking_data)
            if booking_data.get("booking_ref"):
                fb = FlightBooking(
                    direction = direction,
                    booking_ref   = booking_data.get("booking_ref", ""),
                    airline       = booking_data.get("airline", ""),
                    flight_number = booking_data.get("flight_number", ""),
                    origin        = booking_data.get("origin", ""),
                    destination   = booking_data.get("destination", ""),
                    departure     = booking_data.get("departure", ""),
                    arrival       = booking_data.get("arrival", ""),
                    seat          = booking_data.get("seat", ""),
                    price         = float(booking_data.get("price", 0.0)),
                )
                if direction == "outbound":
                    self._state.outbound_flight = fb
                else:
                    self._state.return_flight = fb
                self._state.committed_steps.append(step.value)
        else:
            self._state.status = SagaStatus.FAILED
            self._state.error  = out.error

    async def _handle_date_change(self, retry_policy: RetryPolicy) -> None:
        """
        Compensation sequence on date change.
        Enterprise analog: saga rollback — compensate committed steps,
        update intent, replan from the affected step.
        """
        workflow.logger.info(
            f"Handling date change to {self._new_return_date} — running compensation"
        )
        self._state.status       = SagaStatus.COMPENSATING
        self._state.rollback_from = SagaStep.RETURN_FLIGHT

        # Compensate hotel if already booked
        if self._state.hotel:
            await workflow.execute_activity(
                compensate_booking,
                CompensateInput(
                    booking_ref  = self._state.hotel.booking_ref,
                    booking_type = "hotel",
                ),
                start_to_close_timeout = timedelta(seconds=30),
                retry_policy           = retry_policy,
            )
            self._state.hotel = None
            if SagaStep.HOTEL.value in self._state.committed_steps:
                self._state.committed_steps.remove(SagaStep.HOTEL.value)

        # Compensate return flight if already booked
        if self._state.return_flight:
            await workflow.execute_activity(
                compensate_booking,
                CompensateInput(
                    booking_ref  = self._state.return_flight.booking_ref,
                    booking_type = "flight",
                ),
                start_to_close_timeout = timedelta(seconds=30),
                retry_policy           = retry_policy,
            )
            self._state.return_flight = None
            if SagaStep.RETURN_FLIGHT.value in self._state.committed_steps:
                self._state.committed_steps.remove(SagaStep.RETURN_FLIGHT.value)

        # Update intent with new return date
        self._state.intent.return_date = self._new_return_date
        self._new_return_date          = None
        self._state.status             = SagaStatus.RUNNING

    async def _rerun_hotel(self, retry_policy: RetryPolicy) -> None:
        """Re-book hotel after a date change and compensation."""
        intent = self._state.intent
        self._state.current_step = SagaStep.HOTEL

        out = await workflow.execute_activity(
            run_hotel_step,
            StepInput(
                saga_state_json = _serialize_saga(self._state),
                step            = SagaStep.HOTEL.value,
                user_message    = (
                    f"Book a hotel in {intent.destination} "
                    f"from {intent.outbound_date} to {intent.return_date} "
                    f"(updated dates after date change)"
                ),
                thread_id = f"{self._state.workflow_id}-hotel-replan",
            ),
            start_to_close_timeout = timedelta(minutes=2),
            retry_policy           = retry_policy,
        )
        if out.success:
            booking_data = json.loads(out.result_json)
            if booking_data.get("booking_ref"):
                self._state.hotel = HotelBooking(
                    booking_ref     = booking_data.get("booking_ref", ""),
                    hotel_name      = booking_data.get("hotel_name", ""),
                    city            = booking_data.get("city", ""),
                    check_in        = booking_data.get("check_in", ""),
                    check_out       = booking_data.get("check_out", ""),
                    room_type       = booking_data.get("room_type", ""),
                    price_per_night = float(booking_data.get("price_per_night", 0.0)),
                    total_price     = float(booking_data.get("total_price", 0.0)),
                )
                self._state.committed_steps.append(SagaStep.HOTEL.value)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_saga(saga: TripSagaState) -> str:
    d = dataclasses.asdict(saga)
    d["current_step"] = saga.current_step.value
    d["status"]       = saga.status.value
    if saga.rollback_from:
        d["rollback_from"] = saga.rollback_from.value
    return json.dumps(d)


def _deserialize_saga(json_str: str) -> TripSagaState:
    d = json.loads(json_str)
    d["current_step"] = SagaStep(d["current_step"])
    d["status"]       = SagaStatus(d["status"])
    if d.get("rollback_from"):
        d["rollback_from"] = SagaStep(d["rollback_from"])
    if d.get("intent"):
        d["intent"] = TripIntent(**d["intent"])
    if d.get("preferences"):
        d["preferences"] = UserPreferences(**d["preferences"])
    if d.get("outbound_flight"):
        d["outbound_flight"] = FlightBooking(**d["outbound_flight"])
    if d.get("return_flight"):
        d["return_flight"] = FlightBooking(**d["return_flight"])
    if d.get("hotel"):
        d["hotel"] = HotelBooking(**d["hotel"])
    return TripSagaState(**d)


def _extract(msg: str, key: str, default) -> str:
    """
    Minimal keyword extraction from user message.
    In production this would be a structured LangGraph intent graph.
    """
    import re
    patterns = {
        "from":    r"from\s+([A-Z]{3})",
        "to":      r"to\s+([A-Z]{3})",
        "out":     r"out(?:bound)?\s+([\d]{4}-[\d]{2}-[\d]{2})",
        "back":    r"back|return\s+([\d]{4}-[\d]{2}-[\d]{2})",
        "budget":  r"budget\s+(\d+)",
        "airline": r"airline\s+(\w+)",
        "seat":    r"seat\s+(\w+)",
        "hotel":   r"hotel\s+(\w+)",
    }
    if key in patterns:
        m = re.search(patterns[key], msg, re.IGNORECASE)
        if m:
            return m.group(1)
    return default
