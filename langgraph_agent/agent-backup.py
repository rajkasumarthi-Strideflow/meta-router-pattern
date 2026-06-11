"""
langgraph_agent/agent.py
-------------------------
LangGraph agent graph — the reasoning loop executed inside each
Temporal workflow activity.

Enterprise analog: per-step agent reasoning loop. LangGraph's graph
structure (nodes + edges) maps directly onto the architecture diagrams:
each node is a discrete reasoning or tool-call action; edges are the
conditional paths the agent takes based on what it finds.

The graph is stateful via SqliteSaver checkpointing. If the reasoning
loop crashes mid-step, it resumes at the last checkpoint — not from
the beginning of the step.

Architecture:
  START
    └─> load_memory          (retrieve Mem0 preferences)
          └─> reason          (Claude decides what to do next)
                └─> [tool_call | respond]
                      tool_call ──> call_tool ──> reason  (loop)
                      respond   ──> END
"""

import os
import json
import sqlite3
from pathlib import Path
from typing import Annotated, Any, TypedDict, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import (
    AIMessage, HumanMessage, SystemMessage, ToolMessage, BaseMessage
)
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite import SqliteSaver

from langgraph_agent.mcp_client import MCPClient
from langgraph_agent.memory import preference_memory
from shared.models import (
    TripSagaState, SagaStep, UserPreferences,
    FlightBooking, HotelBooking
)


# ---------------------------------------------------------------------------
# LangGraph state schema
# Enterprise analog: short-term step state — lives only for the duration
# of this saga step. Temporal owns the durable saga-level state.
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    saga_state: TripSagaState          # passed in from Temporal activity
    step: SagaStep                     # which saga step this invocation handles
    preferences: dict                  # loaded from Mem0 at graph entry
    result: dict                       # populated when step completes


# ---------------------------------------------------------------------------
# MCP tool clients
# Enterprise analog: tool contract clients — one per governed system
# ---------------------------------------------------------------------------

_FLIGHT_SERVER = Path(__file__).parent.parent / "mcp_servers" / "flight_server.py"
_HOTEL_SERVER  = Path(__file__).parent.parent / "mcp_servers" / "hotel_server.py"

_flight_client: MCPClient | None = None
_hotel_client:  MCPClient | None = None


def get_flight_client() -> MCPClient:
    global _flight_client
    if _flight_client is None:
        _flight_client = MCPClient(str(_FLIGHT_SERVER))
    return _flight_client


def get_hotel_client() -> MCPClient:
    global _hotel_client
    if _hotel_client is None:
        _hotel_client = MCPClient(str(_HOTEL_SERVER))
    return _hotel_client


# ---------------------------------------------------------------------------
# LangChain tool wrappers over MCP clients
# These are the tools Claude can call during reasoning.
# Enterprise analog: tool definitions registered in the tool registry
# ---------------------------------------------------------------------------

@tool
def search_flights(
    origin: str, destination: str, date: str,
    direction: str = "outbound",
    preferred_airline: str = "", seat_preference: str = ""
) -> str:
    """Search available flights for a route and date."""
    result = get_flight_client().call_tool("search_flights", {
        "origin": origin, "destination": destination, "date": date,
        "direction": direction,
        **({"preferred_airline": preferred_airline} if preferred_airline else {}),
        **({"seat_preference": seat_preference} if seat_preference else {}),
    })
    return json.dumps(result)


@tool
def confirm_flight(
    flight_id: str, seat_preference: str = "aisle",
    direction: str = "outbound",
    origin: str = "", destination: str = "",
    departure: str = "", arrival: str = "",
    airline: str = "", price: float = 0.0
) -> str:
    """Confirm and book a selected flight."""
    result = get_flight_client().call_tool("confirm_flight", {
        "flight_id": flight_id, "seat_preference": seat_preference,
        "direction": direction, "origin": origin, "destination": destination,
        "departure": departure, "arrival": arrival,
        "airline": airline, "price": price,
    })
    return json.dumps(result)


@tool
def cancel_flight(booking_ref: str) -> str:
    """Cancel a confirmed flight booking. Used during saga rollback."""
    result = get_flight_client().call_tool("cancel_flight", {"booking_ref": booking_ref})
    return json.dumps(result)


@tool
def search_hotels(
    city: str, check_in: str, check_out: str,
    hotel_tier: str = "", budget_ceiling: float = 0.0
) -> str:
    """Search available hotels for a city and date range."""
    args: dict = {"city": city, "check_in": check_in, "check_out": check_out}
    if hotel_tier:       args["hotel_tier"]     = hotel_tier
    if budget_ceiling:   args["budget_ceiling"] = budget_ceiling
    result = get_hotel_client().call_tool("search_hotels", args)
    return json.dumps(result)


@tool
def confirm_hotel(
    hotel_id: str, hotel_name: str, city: str,
    check_in: str, check_out: str, room_type: str,
    price_per_night: float, total_price: float
) -> str:
    """Confirm and book a selected hotel."""
    result = get_hotel_client().call_tool("confirm_hotel", {
        "hotel_id": hotel_id, "hotel_name": hotel_name, "city": city,
        "check_in": check_in, "check_out": check_out, "room_type": room_type,
        "price_per_night": price_per_night, "total_price": total_price,
    })
    return json.dumps(result)


@tool
def cancel_hotel(booking_ref: str) -> str:
    """Cancel a confirmed hotel booking. Used during saga rollback."""
    result = get_hotel_client().call_tool("cancel_hotel", {"booking_ref": booking_ref})
    return json.dumps(result)


# Tool registry — maps step to the tools available during that step
STEP_TOOLS: dict[SagaStep, list] = {
    SagaStep.OUTBOUND_FLIGHT: [search_flights, confirm_flight],
    SagaStep.RETURN_FLIGHT:   [search_flights, confirm_flight],
    SagaStep.HOTEL:           [search_hotels, confirm_hotel],
}


# ---------------------------------------------------------------------------
# System prompt builder
# Enterprise analog: policy and guardrail enforcement at the agent layer
# ---------------------------------------------------------------------------

def _system_prompt(step: SagaStep, saga: TripSagaState, prefs: dict) -> str:
    intent = saga.intent
    base = f"""You are a travel booking agent completing ONE step of a multi-step trip planning workflow.

Current step: {step.value}
Traveller: {intent.traveller_name if intent else 'Unknown'}
Trip: {intent.origin if intent else '?'} → {intent.destination if intent else '?'}
Dates: {intent.outbound_date if intent else '?'} to {intent.return_date if intent else '?'}
Budget: USD {intent.budget if intent else 'not set'}

Stored preferences (from long-term memory):
{json.dumps(prefs, indent=2)}

Already confirmed:
- Outbound flight: {saga.outbound_flight.booking_ref if saga.outbound_flight else 'not yet booked'}
- Return flight:   {saga.return_flight.booking_ref if saga.return_flight else 'not yet booked'}
- Hotel:           {saga.hotel.booking_ref if saga.hotel else 'not yet booked'}

Instructions:
1. Complete ONLY the current step: {step.value}
2. Use the available tools to search and then confirm a booking
3. Apply preferences when calling search tools
4. When a booking is confirmed, respond with a JSON result in this exact format:
   {{"step_complete": true, "booking_type": "<flight|hotel>", "booking": {{...booking details...}}}}
5. Be concise — this is a workflow step, not a conversation."""
    return base


# ---------------------------------------------------------------------------
# Graph nodes
# Each node is a discrete action in the reasoning loop.
# Enterprise analog: reasoning loop stages
# ---------------------------------------------------------------------------

def load_memory_node(state: AgentState) -> AgentState:
    """
    Node 1: Load long-term preferences from Mem0.
    Enterprise analog: context hydration at workflow step entry.
    Called once per step invocation.
    """
    saga  = state["saga_state"]
    prefs = preference_memory.load_preferences(saga.user_id)
    prefs_dict = {
        "preferred_airline": prefs.preferred_airline,
        "seat_preference":   prefs.seat_preference,
        "hotel_tier":        prefs.hotel_tier,
        "budget_ceiling":    prefs.budget_ceiling,
        "dietary":           prefs.dietary,
    }
    return {**state, "preferences": prefs_dict}


def reason_node(state: AgentState) -> AgentState:
    """
    Node 2: Claude reasons and decides whether to call a tool or respond.
    Enterprise analog: LLM reasoning — the intelligence layer.
    This node loops back from tool results until the step is complete.
    """
    step    = state["step"]
    saga    = state["saga_state"]
    prefs   = state.get("preferences", {})
    tools   = STEP_TOOLS.get(step, [])

    llm = ChatAnthropic(
        model="claude-haiku-4-5",
        api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        max_tokens=1024,
    ).bind_tools(tools)

    messages = [
        SystemMessage(content=_system_prompt(step, saga, prefs)),
        *state["messages"],
    ]
    rtry:
        response = llm.invoke(messages)
    except Exception as e:
        print(f">>> LLM ERROR: {e}", flush=True)
        raise
    return {**state, "messages": [response]}


def call_tool_node(state: AgentState) -> AgentState:
    step     = state["step"]
    tools    = STEP_TOOLS.get(step, [])
    tool_map = {t.name: t for t in tools}
    messages = state["messages"]

    last_msg = messages[-1]
    if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
        return state

    tool_results = []
    result_dict  = {}

    for tc in last_msg.tool_calls:
        fn   = tool_map.get(tc["name"])
        args = tc["args"]
        if fn is None:
            output = json.dumps({"error": f"Unknown tool: {tc['name']}"})
        else:
            try:
                output = fn.invoke(args)
                parsed = json.loads(output) if isinstance(output, str) else output
                # Booking confirmed — extract from nested booking key
                if tc["name"] in ("confirm_flight", "confirm_hotel") and parsed.get("success"):
                    booking = parsed.get("booking", {})
                    if booking.get("booking_ref"):
                        result_dict = booking
                        result_dict["tool"] = tc["name"]
            except Exception as e:
                output = json.dumps({"error": str(e)})

        tool_results.append(ToolMessage(
            content=output if isinstance(output, str) else json.dumps(output),
            tool_call_id=tc["id"],
        ))

    new_state = {**state, "messages": tool_results}
    if result_dict:
        new_state["result"] = result_dict
    return new_state


def respond_node(state: AgentState) -> AgentState:
    """
    Node 4: Extract the final result from Claude's response.
    Parses the JSON booking result and stores it in state["result"].
    """
    messages = state["messages"]
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            # Try to parse JSON result from Claude's final message
            try:
                start = content.find("{")
                end   = content.rfind("}") + 1
                if start >= 0 and end > start:
                    parsed = json.loads(content[start:end])
                    if parsed.get("step_complete"):
                        return {**state, "result": parsed.get("booking", {})}
            except (json.JSONDecodeError, ValueError):
                pass
    return state


# ---------------------------------------------------------------------------
# Routing logic
# Enterprise analog: conditional branching in the reasoning loop
# ---------------------------------------------------------------------------

def route_after_reason(state: AgentState) -> Literal["call_tool", "respond"]:
    """Route: if Claude wants to call a tool, go to call_tool; else respond."""
    messages = state["messages"]
    last_msg = messages[-1] if messages else None
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        return "call_tool"
    return "respond"


def route_after_tool(state: AgentState) -> Literal["reason", END]:
    """After a tool call, if a confirmed booking is in result, end. Else keep reasoning."""
    result = state.get("result", {})
    if result and result.get("booking_ref"):
        return END
    # Safety valve — if messages are getting long, stop
    if len(state.get("messages", [])) > 20:
        return END
    return "reason"


# ---------------------------------------------------------------------------
# Graph construction
# Enterprise analog: workflow step definition — the reasoning graph
# is the explicit, auditable record of how the agent makes decisions.
# ---------------------------------------------------------------------------

def build_agent_graph(checkpointer=None) -> Any:
    """
    Build and compile the LangGraph agent graph.
    
    checkpointer: SqliteSaver or None
    Enterprise analog: step-level state backend (short-term memory).
    """
    graph = StateGraph(AgentState)

    # Nodes
    graph.add_node("load_memory", load_memory_node)
    graph.add_node("reason",      reason_node)
    graph.add_node("call_tool",   call_tool_node)
    graph.add_node("respond",     respond_node)

    # Edges
    graph.add_edge(START,         "load_memory")
    graph.add_edge("load_memory", "reason")
    graph.add_conditional_edges("reason", route_after_reason, {
        "call_tool": "call_tool",
        "respond":   "respond",
    })
    graph.add_conditional_edges("call_tool", route_after_tool, {
        "reason": "reason",
        END:      END,
    })
    graph.add_edge("respond", END)

    return graph.compile(checkpointer=checkpointer)


# ---------------------------------------------------------------------------
# Step runner
# Called by Temporal activities — executes one saga step via the graph.
# Enterprise analog: activity executor — runs reasoning loop for one step,
# returns structured result back to the meta-orchestrator.
# ---------------------------------------------------------------------------

def run_step(
    saga_state: TripSagaState,
    step: SagaStep,
    user_message: str,
    thread_id: str,
) -> dict:
    """
    Execute one saga step through the LangGraph agent graph.
    
    Returns the step result dict (booking or preference data).
    Temporal calls this inside an activity — any exception triggers retry.
    """
    db_path = f"/tmp/langgraph_{saga_state.workflow_id}.db"
    conn = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)

    graph = build_agent_graph(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": thread_id}}

    initial_state: AgentState = {
        "messages":   [HumanMessage(content=user_message)],
        "saga_state": saga_state,
        "step":       step,
        "preferences":{},
        "result":     {},
    }

    final_state = graph.invoke(initial_state, config=config)
    conn.close()
    return final_state.get("result", {})
