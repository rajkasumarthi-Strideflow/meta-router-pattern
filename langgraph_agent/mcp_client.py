"""
langgraph_agent/mcp_client.py
------------------------------
Bridges LangGraph tool calls to MCP server processes over stdio.
Fixed for Python 3.14 subprocess buffering changes.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


class MCPClient:
    def __init__(self, server_script: str):
        self.server_script = server_script
        self._proc: subprocess.Popen | None = None
        self._req_id = 0

    def _start(self):
        if self._proc is None or self._proc.poll() is not None:
            self._proc = subprocess.Popen(
                [sys.executable, "-u", self.server_script],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,          # unbuffered
            )
            self._send({"method": "initialize", "params": {}})

    def _send(self, payload: dict) -> dict:
        self._req_id += 1
        payload["jsonrpc"] = "2.0"
        payload["id"]      = self._req_id
        line = json.dumps(payload) + "\n"
        self._proc.stdin.write(line.encode("utf-8"))
        self._proc.stdin.flush()
        response_line = self._proc.stdout.readline().decode("utf-8")
        if not response_line.strip():
            # Read stderr to surface the real error
            err = self._proc.stderr.read(2048).decode("utf-8", errors="replace")
            raise RuntimeError(f"MCP server returned empty response. stderr: {err}")
        return json.loads(response_line.strip())

    def list_tools(self) -> list[dict]:
        self._start()
        resp = self._send({"method": "tools/list", "params": {}})
        return resp.get("result", {}).get("tools", [])

    def call_tool(self, tool_name: str, arguments: dict) -> Any:
        self._start()
        resp = self._send({
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })
        if "error" in resp:
            raise RuntimeError(f"MCP tool error: {resp['error']}")
        content = resp.get("result", {}).get("content", [])
        if content and content[0].get("type") == "text":
            return json.loads(content[0]["text"])
        return resp.get("result")

    def close(self):
        if self._proc:
            self._proc.terminate()
            self._proc = None