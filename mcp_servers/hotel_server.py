"""
mcp_servers/hotel_server.py
----------------------------
MCP server exposing hotel search and booking tools.

Enterprise analog: governed tool contract over ERP / ITSM system.
Same pattern as flight_server — real MCP interface, mock backend.
"""

import json
import sys
import asyncio
import hashlib
# Force unbuffered stdout for Python 3.14 subprocess compatibility
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from shared.models import FlightBooking

HOTELS = [
    {"name": "Grand Hyatt",    "tier": "luxury",   "price": 320, "room": "king"},
    {"name": "Marriott Exec",  "tier": "business", "price": 210, "room": "double"},
    {"name": "Holiday Inn",    "tier": "budget",   "price": 120, "room": "standard"},
]


def _nights(check_in: str, check_out: str) -> int:
    from datetime import date
    d1 = date.fromisoformat(check_in)
    d2 = date.fromisoformat(check_out)
    return max(1, (d2 - d1).days)


def _mock_booking_ref(hotel_name: str, check_in: str) -> str:
    return "HT" + hashlib.md5(f"{hotel_name}{check_in}".encode()).hexdigest()[:6].upper()


def search_hotels(
    city: str,
    check_in: str,
    check_out: str,
    hotel_tier: str | None = None,
    budget_ceiling: float | None = None,
) -> dict:
    """
    Search available hotels.
    Applies Mem0 tier preference and budget ceiling if provided.
    """
    nights  = _nights(check_in, check_out)
    results = []
    for h in HOTELS:
        total = h["price"] * nights
        if budget_ceiling and total > budget_ceiling * 0.6:
            continue
        results.append({
            "hotel_id":       h["name"].lower().replace(" ", "_"),
            "hotel_name":     h["name"],
            "city":           city,
            "check_in":       check_in,
            "check_out":      check_out,
            "room_type":      h["room"],
            "tier":           h["tier"],
            "price_per_night":h["price"],
            "total_price":    total,
            "nights":         nights,
        })

    # Surface preferred tier first
    if hotel_tier:
        results.sort(key=lambda h: 0 if h["tier"] == hotel_tier else 1)

    return {"hotels": results[:3], "search_params": {
        "city": city, "check_in": check_in, "check_out": check_out
    }}


def confirm_hotel(
    hotel_id: str,
    hotel_name: str,
    city: str,
    check_in: str,
    check_out: str,
    room_type: str,
    price_per_night: float,
    total_price: float,
) -> dict:
    """
    Confirm (mock-book) a hotel. Returns a booking reference.
    Enterprise analog: create_service_request() in ITSM / procurement system.
    """
    booking_ref = _mock_booking_ref(hotel_name, check_in)
    return {
        "success": True,
        "booking": {
            "booking_ref":    booking_ref,
            "hotel_name":     hotel_name,
            "city":           city,
            "check_in":       check_in,
            "check_out":      check_out,
            "room_type":      room_type,
            "price_per_night":price_per_night,
            "total_price":    total_price,
        }
    }


def cancel_hotel(booking_ref: str) -> dict:
    """
    Cancel a confirmed hotel booking.
    Enterprise analog: compensating activity — reverse a committed ITSM ticket.
    """
    return {
        "success":     True,
        "booking_ref": booking_ref,
        "message":     f"Hotel {booking_ref} cancelled. Refund initiated.",
        "refund":      True,
    }


TOOLS = {
    "search_hotels": {
        "fn": search_hotels,
        "description": "Search available hotels for a city and date range",
        "inputSchema": {
            "type": "object",
            "properties": {
                "city":           {"type": "string"},
                "check_in":       {"type": "string", "description": "YYYY-MM-DD"},
                "check_out":      {"type": "string", "description": "YYYY-MM-DD"},
                "hotel_tier":     {"type": "string"},
                "budget_ceiling": {"type": "number"},
            },
            "required": ["city", "check_in", "check_out"],
        },
    },
    "confirm_hotel": {
        "fn": confirm_hotel,
        "description": "Confirm and book a selected hotel",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hotel_id":       {"type": "string"},
                "hotel_name":     {"type": "string"},
                "city":           {"type": "string"},
                "check_in":       {"type": "string"},
                "check_out":      {"type": "string"},
                "room_type":      {"type": "string"},
                "price_per_night":{"type": "number"},
                "total_price":    {"type": "number"},
            },
            "required": ["hotel_id", "hotel_name", "city",
                         "check_in", "check_out", "room_type",
                         "price_per_night", "total_price"],
        },
    },
    "cancel_hotel": {
        "fn": cancel_hotel,
        "description": "Cancel a confirmed hotel booking (used in rollback)",
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