"""
mcp_servers/flight_server.py
-----------------------------
MCP server exposing flight search and booking tools as a governed interface.

Enterprise analog: governed tool contract over a CRM / billing system.
The interface is real MCP; the backend is a deterministic mock.
Swap the mock for a real API without changing any agent code — the
tool contract is the governance boundary.

Run standalone:  python mcp_servers/flight_server.py
"""

import json
import sys
import asyncio
from datetime import datetime, timedelta
from typing import Any

# Force unbuffered stdout for Python 3.14 subprocess compatibility
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.models import FlightBooking


# ---------------------------------------------------------------------------
# Mock data generators
# Enterprise analog: system-of-record API responses
# ---------------------------------------------------------------------------

AIRLINES = {
    "Delta":   {"code": "DL", "base_price": 320},
    "United":  {"code": "UA", "base_price": 290},
    "AA":      {"code": "AA", "base_price": 310},
}

def _mock_flights(origin: str, destination: str, date: str,
                  direction: str, preferred_airline: str | None = None) -> list[dict]:
    flights = []
    for airline, info in AIRLINES.items():
        dep_hour = 8 if direction == "outbound" else 14
        flights.append({
            "flight_id":    f"{info['code']}{100 + len(flights)}",
            "airline":      airline,
            "origin":       origin,
            "destination":  destination,
            "departure":    f"{date}T{dep_hour:02d}:00:00",
            "arrival":      f"{date}T{dep_hour + 4:02d}:30:00",
            "seats":        ["aisle", "window", "middle"],
            "price":        info["base_price"] + (20 if direction == "return" else 0),
            "direction":    direction,
        })
        dep_hour += 2

    # Surface preferred airline first — Mem0 preference applied here
    if preferred_airline:
        flights.sort(key=lambda f: 0 if f["airline"] == preferred_airline else 1)
    return flights


def _mock_booking_ref(flight_id: str) -> str:
    import hashlib
    return "FL" + hashlib.md5(flight_id.encode()).hexdigest()[:6].upper()


# ---------------------------------------------------------------------------
# Tool implementations
# These are the functions MCP exposes as callable tools.
# Enterprise analog: API operations on a system-of-record
# ---------------------------------------------------------------------------

def search_flights(
    origin: str,
    destination: str,
    date: str,
    direction: str = "outbound",
    preferred_airline: str | None = None,
    seat_preference: str | None = None,
) -> dict:
    """
    Search available flights.
    Returns up to 3 options sorted by preference then price.
    """
    results = _mock_flights(origin, destination, date, direction, preferred_airline)
    return {"flights": results[:3], "search_params": {
        "origin": origin, "destination": destination,
        "date": date, "direction": direction
    }}


def confirm_flight(
    flight_id: str,
    seat_preference: str = "aisle",
    direction: str = "outbound",
    origin: str = "",
    destination: str = "",
    departure: str = "",
    arrival: str = "",
    airline: str = "",
    price: float = 0.0,
) -> dict:
    """
    Confirm (mock-book) a flight. Returns a booking reference.
    Enterprise analog: process_order() / create_transaction() in billing system.
    """
    booking_ref = _mock_booking_ref(flight_id)
    return {
        "success": True,
        "booking": {
            "booking_ref":   booking_ref,
            "flight_id":     flight_id,
            "airline":       airline,
            "flight_number": flight_id,
            "origin":        origin,
            "destination":   destination,
            "departure":     departure,
            "arrival":       arrival,
            "seat":          seat_preference,
            "price":         price,
            "direction":     direction,
        }
    }


def cancel_flight(booking_ref: str) -> dict:
    """
    Cancel a confirmed flight booking.
    Enterprise analog: compensating transaction — reverses a committed action.
    Used by Temporal during saga rollback.
    """
    return {
        "success":     True,
        "booking_ref": booking_ref,
        "message":     f"Flight {booking_ref} cancelled. Refund initiated.",
        "refund":      True,
    }


# ---------------------------------------------------------------------------
# Minimal stdio MCP server
# Implements the MCP protocol over stdin/stdout (stdio transport).
# Enterprise analog: tool contract boundary — agents call through this
# interface, never directly into the backend.
# ---------------------------------------------------------------------------

TOOLS = {
    "search_flights": {
        "fn": search_flights,
        "description": "Search available flights for a given route and date",
        "inputSchema": {
            "type": "object",
            "properties": {
                "origin":            {"type": "string"},
                "destination":       {"type": "string"},
                "date":              {"type": "string", "description": "YYYY-MM-DD"},
                "direction":         {"type": "string", "enum": ["outbound", "return"]},
                "preferred_airline": {"type": "string"},
                "seat_preference":   {"type": "string"},
            },
            "required": ["origin", "destination", "date"],
        },
    },
    "confirm_flight": {
        "fn": confirm_flight,
        "description": "Confirm and book a selected flight",
        "inputSchema": {
            "type": "object",
            "properties": {
                "flight_id":       {"type": "string"},
                "seat_preference": {"type": "string"},
                "direction":       {"type": "string"},
                "origin":          {"type": "string"},
                "destination":     {"type": "string"},
                "departure":       {"type": "string"},
                "arrival":         {"type": "string"},
                "airline":         {"type": "string"},
                "price":           {"type": "number"},
            },
            "required": ["flight_id"],
        },
    },
    "cancel_flight": {
        "fn": cancel_flight,
        "description": "Cancel a confirmed flight booking (used in rollback)",
        "inputSchema": {
            "type": "object",
            "properties": {"booking_ref": {"type": "string"}},
            "required": ["booking_ref"],
        },
    },
}

def handle_request(request: dict) -> dict:
    method = request.get("method")
    params = request.get("params", {})
    req_id = request.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "flight-server", "version": "0.1.0"},
        }}

    if method == "tools/list":
        tools_list = [
            {"name": name, "description": spec["description"],
             "inputSchema": spec["inputSchema"]}
            for name, spec in TOOLS.items()
        ]
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools_list}}

    if method == "tools/call":
        tool_name = params.get("name")
        args      = params.get("arguments", {})
        if tool_name not in TOOLS:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}}
        result = TOOLS[tool_name]["fn"](**args)
        return {"jsonrpc": "2.0", "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}

    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"}}


def main():
    import io
    stdin  = io.TextIOWrapper(sys.stdin.buffer,  encoding="utf-8")
    stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request  = json.loads(line)
            response = handle_request(request)
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
        except Exception as e:
            stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": str(e)}
            }) + "\n")
            stdout.flush()


if __name__ == "__main__":
    main()