"""
shared/models.py
----------------
Canonical data models shared across LangGraph agent, Temporal workflow,
and MCP servers.

Enterprise analog: canonical data model in the shared substrate layer.
All components speak the same entity vocabulary — no per-component
interpretation of what a 'booking' or 'trip state' means.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import date


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SagaStep(str, Enum):
    """
    Ordered steps in the trip-planning saga.
    Enterprise analog: workflow step registry in the meta-orchestrator.
    """
    COLLECT_INTENT   = "collect_intent"
    OUTBOUND_FLIGHT  = "outbound_flight"
    RETURN_FLIGHT    = "return_flight"
    HOTEL            = "hotel"
    CONFIRM          = "confirm"
    COMPLETE         = "complete"
    COMPENSATING     = "compensating"   # rollback in progress


class SagaStatus(str, Enum):
    RUNNING      = "running"
    PAUSED_HITL  = "paused_hitl"       # waiting for human approval signal
    APPROVED     = "approved"
    COMPLETE     = "complete"
    COMPENSATING = "compensating"
    FAILED       = "failed"


# ---------------------------------------------------------------------------
# User preferences  (persisted in Mem0 across sessions)
# Enterprise analog: shared context layer — cross-session user profile
# ---------------------------------------------------------------------------

@dataclass
class UserPreferences:
    user_id: str
    preferred_airline: Optional[str] = None   # e.g. "Delta"
    seat_preference: Optional[str]  = None    # e.g. "aisle"
    hotel_tier: Optional[str]       = None    # e.g. "business", "budget"
    budget_ceiling: Optional[float] = None    # total trip budget USD
    dietary: Optional[str]          = None    # e.g. "vegetarian"


# ---------------------------------------------------------------------------
# Trip intent  (collected in step 1, drives all downstream steps)
# Enterprise analog: initial workflow input / trigger payload
# ---------------------------------------------------------------------------

@dataclass
class TripIntent:
    origin: str
    destination: str
    outbound_date: str          # ISO date string  YYYY-MM-DD
    return_date: str
    budget: Optional[float] = None
    traveller_name: str = "Traveller"


# ---------------------------------------------------------------------------
# Booking records  (produced by MCP servers, stored in saga state)
# Enterprise analog: activity output — result returned by an async participant
# ---------------------------------------------------------------------------

@dataclass
class FlightBooking:
    booking_ref: str
    airline: str
    flight_number: str
    origin: str
    destination: str
    departure: str              # ISO datetime
    arrival: str
    seat: str
    price: float
    direction: str              # "outbound" | "return"


@dataclass
class HotelBooking:
    booking_ref: str
    hotel_name: str
    city: str
    check_in: str               # ISO date
    check_out: str
    room_type: str
    price_per_night: float
    total_price: float


# ---------------------------------------------------------------------------
# Saga state  (owned by Temporal, threaded through LangGraph steps)
# Enterprise analog: durable workflow state record in the meta-orchestrator
# ---------------------------------------------------------------------------

@dataclass
class TripSagaState:
    workflow_id: str
    user_id: str
    current_step: SagaStep          = SagaStep.COLLECT_INTENT
    status: SagaStatus              = SagaStatus.RUNNING

    intent: Optional[TripIntent]            = None
    preferences: Optional[UserPreferences]  = None
    outbound_flight: Optional[FlightBooking]= None
    return_flight: Optional[FlightBooking]  = None
    hotel: Optional[HotelBooking]           = None

    # Compensation log: records what has been committed so Temporal
    # knows what to undo on rollback.
    # Enterprise analog: saga compensation ledger
    committed_steps: list = field(default_factory=list)

    # Tracks if a date change triggered rollback from which step
    rollback_from: Optional[SagaStep] = None

    error: Optional[str] = None
