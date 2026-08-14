#!/usr/bin/env python
"""
mcp_client_test_hmcp.py

Real MCP-protocol smoke test for houdini/bridge/hmcp_bridge.py -- spawns
it as a stdio subprocess (exactly how Claude Code would) and talks to it
through mcp.client.stdio + ClientSession: initialize, list_tools,
call_tool. Same pattern as mcp_client_test_nuke.py.

Exercises the full MCP path (stdio protocol -> bridge -> plugin) end to
end; see houdini/docs/HMCP_DESIGN.md section 9.
"""
import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
BRIDGE = os.path.join(REPO_ROOT, "houdini", "bridge", "hmcp_bridge.py")
PYTHON = os.path.join(REPO_ROOT, ".venv", "Scripts", "python.exe")


async def call(session, name, args=None):
    r = await session.call_tool(name, args or {})
    for c in r.content:
        print(c.text if hasattr(c, "text") else c)


async def main():
    params = StdioServerParameters(command=PYTHON, args=[BRIDGE])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("Tools exposed:", [t.name for t in tools.tools])

            print("\n--- 1. get_scene_info ---")
            await call(session, "get_scene_info", {"max_nodes": 20})

            print("\n--- 2. get_geometry_info on /obj (not a SOP, should error cleanly) ---")
            await call(session, "get_geometry_info", {"node_path": "/obj"})

            print("\n--- 3. get_node_type_parms('mountain', 'Sop') ---")
            await call(session, "get_node_type_parms", {"type_name": "mountain", "category": "Sop"})

            print("\n--- 4. get_node_errors on a nonexistent path ---")
            await call(session, "get_node_errors", {"node_path": "/obj/does_not_exist"})

            print("\n--- 5. list_node_types('Sop', name_filter='mountain') ---")
            await call(session, "list_node_types", {"category": "Sop", "name_filter": "mountain"})

            print("\n--- 6. get_network('/obj') ---")
            await call(session, "get_network", {"parent_path": "/obj"})

            print("\n--- 7. describe_commands ---")
            await call(session, "describe_commands", {})


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
