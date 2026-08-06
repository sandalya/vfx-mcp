#!/usr/bin/env python
"""
mcp_client_test_nuke.py

Real MCP-protocol smoke test for nuke_mcp_bridge.py -- spawns it as a
stdio subprocess (exactly how Claude Desktop/Code would) and talks to it
through mcp.client.stdio + ClientSession: initialize, list_tools,
call_tool. This exercises the actual JSON-RPC framing and FastMCP's
Context injection, unlike importing the module and calling the function
directly.
"""
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(os.path.dirname(SCRIPT_DIR), "nuke_mcp_bridge.py")
PYTHON = os.path.join(os.path.dirname(SCRIPT_DIR), ".venv", "Scripts", "python.exe")


async def main():
    params = StdioServerParameters(command=PYTHON, args=[BRIDGE])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("Tools exposed:", [t.name for t in tools.tools])

            print("\n--- call nuke_ping ---")
            r = await session.call_tool("nuke_ping", {})
            for c in r.content:
                print(c.text if hasattr(c, "text") else c)

            print("\n--- call nuke_get_script_info ---")
            r = await session.call_tool("nuke_get_script_info", {})
            for c in r.content:
                print(c.text if hasattr(c, "text") else c)

            print("\n--- call nuke_list_nodes ---")
            r = await session.call_tool("nuke_list_nodes", {})
            for c in r.content:
                print(c.text if hasattr(c, "text") else c)

            print("\n--- call nuke_get_nodes_in_view ---")
            r = await session.call_tool("nuke_get_nodes_in_view", {})
            for c in r.content:
                print(c.text if hasattr(c, "text") else c)

            print("\n--- call nuke_execute_code ---")
            r = await session.call_tool("nuke_execute_code", {"code": "result = nuke.NUKE_VERSION_STRING"})
            for c in r.content:
                print(c.text if hasattr(c, "text") else c)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
