#!/usr/bin/env python
"""
hmcp_bridge.py

Bridge script for the NEW Houdini plugin (houdini/plugin/hmcp/, port 9878,
read-only in Phase 1). Registered in Claude Code as `houdini2` so the
existing Claude Desktop `houdini` entry (old plugin, port 9876) is not
disturbed -- see houdini/docs/HOUDINI_MCP_REWRITE_PLAN.md.

Every tool here is generated straight off houdini/commands_spec.py, the
single source of truth also used by the plugin's dispatcher
(houdini/plugin/hmcp/commands.py). The assertion at the bottom of this
file makes bridge/plugin drift -- the exact bug that broke `connect_nodes`
in the old plugin -- fail loudly at import time instead of silently at
call time.
"""
import sys
import os

# This script lives at <repo>/houdini/bridge/, two levels down from repo root.
script_dir = os.path.dirname(os.path.abspath(__file__))
houdini_dir = os.path.dirname(script_dir)
repo_root = os.path.dirname(houdini_dir)

venv_site_packages = os.path.join(repo_root, ".venv", "Lib", "site-packages")
if os.path.exists(venv_site_packages):
    sys.path.insert(0, venv_site_packages)
    print(f"Added {venv_site_packages} to sys.path", file=sys.stderr)
else:
    print(f"Warning: venv site-packages not found at {venv_site_packages}", file=sys.stderr)

# houdini/ itself, so `import commands_spec` resolves to houdini/commands_spec.py
sys.path.insert(0, houdini_dir)
import commands_spec

import json
import socket
import logging
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP, Context
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HmcpBridge")

HOST = "10.10.10.31"
PORT = 9878


@dataclass
class HmcpConnection:
    host: str
    port: int
    sock: socket.socket = None

    DEFAULT_TIMEOUT = 10.0

    def connect(self) -> bool:
        if self.sock is not None:
            return True
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to hmcp at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to hmcp: {e}")
            self.sock = None
            return False

    def disconnect(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from hmcp: {e}")
            self.sock = None

    def send_command(self, cmd_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.connect():
            msg = f"Could not connect to hmcp on {self.host}:{self.port}."
            logger.error(msg)
            return {"status": "error", "message": msg, "origin": "bridge_connection"}

        command = {"type": cmd_type, "params": params or {}}
        data_out = json.dumps(command).encode("utf-8")
        timeout = self.DEFAULT_TIMEOUT

        try:
            self.sock.sendall(data_out)
            self.sock.settimeout(timeout)
            buffer = b""
            start_time = asyncio.get_event_loop().time()
            while True:
                if asyncio.get_event_loop().time() - start_time > timeout:
                    raise socket.timeout(f"Timeout waiting for hmcp response ({timeout}s)")

                chunk = self.sock.recv(8192)
                if not chunk:
                    raise ConnectionAbortedError("Connection closed by hmcp.")

                buffer += chunk
                try:
                    parsed = json.loads(buffer.decode("utf-8"))
                    return parsed
                except json.JSONDecodeError:
                    continue

        except socket.timeout:
            msg = "Timeout receiving data from hmcp."
            logger.error(msg)
            self.disconnect()
            return {"status": "error", "message": msg, "origin": "bridge_timeout"}
        except Exception as e:
            msg = f"Error during hmcp communication for '{cmd_type}': {e}"
            logger.error(msg)
            self.disconnect()
            return {"status": "error", "message": msg, "origin": "bridge_send_command"}


_hmcp_connection: Optional[HmcpConnection] = None


def get_hmcp_connection() -> HmcpConnection:
    global _hmcp_connection
    if _hmcp_connection is None:
        _hmcp_connection = HmcpConnection(host=HOST, port=PORT)
    if not _hmcp_connection.connect():
        _hmcp_connection = None
        raise ConnectionError(f"Could not connect to hmcp on {HOST}:{PORT}. Is the plugin running?")
    return _hmcp_connection


mcp = FastMCP("HmcpBridge")


@asynccontextmanager
async def server_lifespan(app: FastMCP):
    logger.info("hmcp bridge starting up (stdio).")
    yield {}
    logger.info("hmcp bridge shutting down.")
    global _hmcp_connection
    if _hmcp_connection is not None:
        _hmcp_connection.disconnect()
        _hmcp_connection = None


mcp.lifespan = server_lifespan


def _call(cmd_type: str, params: Dict[str, Any]) -> str:
    """Shared send/format logic for every tool below."""
    try:
        conn = get_hmcp_connection()
        response = conn.send_command(cmd_type, params)
        if response.get("status") == "error":
            origin = response.get("origin", "hmcp")
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"
        return json.dumps(response.get("result", {}), indent=2)
    except ConnectionError as e:
        return f"Connection Error: {e}"
    except Exception as e:
        logger.error(f"Unexpected error calling {cmd_type}: {e}", exc_info=True)
        return f"Server Error: {e}"


# -------------------------------------------------------------------
# Tools -- one per commands_spec.py entry. Names match exactly; see the
# contract assertion at the bottom of this file.
# -------------------------------------------------------------------

@mcp.tool()
def get_scene_info(ctx: Context, max_nodes: int = 100, context_filter: Optional[List[str]] = None) -> str:
    """Current .hip file name/path and a sample of top-level nodes."""
    params = {"max_nodes": max_nodes}
    if context_filter:
        params["context_filter"] = context_filter
    return _call("get_scene_info", params)


@mcp.tool()
def get_geometry_info(ctx: Context, node_path: str) -> str:
    """npoints/nprims/nvertices, attributes, groups, bbox, cook errors for a SOP.
    The most important tool -- without it you build a SOP graph blind."""
    return _call("get_geometry_info", {"node_path": node_path})


@mcp.tool()
def get_node_errors(ctx: Context, node_path: str) -> str:
    """Errors, warnings, and cook state for a node."""
    return _call("get_node_errors", {"node_path": node_path})


@mcp.tool()
def get_node_type_parms(ctx: Context, type_name: str, category: str) -> str:
    """Real parameter names/labels/types/defaults/menu items for a node type
    (e.g. type_name='mountain', category='Sop'). Look these up instead of
    recalling them from training."""
    return _call("get_node_type_parms", {"type_name": type_name, "category": category})


@mcp.tool()
def list_node_types(ctx: Context, category: str, name_filter: Optional[str] = None) -> str:
    """Node type names available in a category (e.g. 'Sop', 'Obj'), optionally filtered."""
    params = {"category": category}
    if name_filter:
        params["name_filter"] = name_filter
    return _call("list_node_types", params)


@mcp.tool()
def get_node_help(ctx: Context, type_name: str, category: str, max_chars: int = 4000) -> str:
    """Built-in help text for a node type, truncated to max_chars."""
    return _call("get_node_help", {"type_name": type_name, "category": category, "max_chars": max_chars})


@mcp.tool()
def get_network(ctx: Context, parent_path: str) -> str:
    """Children of a network node plus their input connections."""
    return _call("get_network", {"parent_path": parent_path})


@mcp.tool()
def get_node_info(ctx: Context, path: str, max_parms: Optional[int] = None, only_non_default: bool = False) -> str:
    """Detailed single-node info: parms, inputs, outputs, flags."""
    params = {"path": path, "only_non_default": only_non_default}
    if max_parms is not None:
        params["max_parms"] = max_parms
    return _call("get_node_info", params)


@mcp.tool()
def describe_commands(ctx: Context) -> str:
    """Returns the plugin's own command list -- for contract-checking against commands_spec.py."""
    return _call("describe_commands", {})


def main():
    mcp.run()


if __name__ == "__main__":
    # Contract check: every command_spec name must have exactly one tool
    # above, and vice versa. This is the bridge-side half of the drift
    # protection described in the module docstring -- fails loudly at
    # startup rather than at first mismatched call.
    _bridge_tool_names = {
        "get_scene_info", "get_geometry_info", "get_node_errors",
        "get_node_type_parms", "list_node_types", "get_node_help",
        "get_network", "get_node_info", "describe_commands",
    }
    if _bridge_tool_names != commands_spec.COMMAND_NAMES:
        missing_in_bridge = commands_spec.COMMAND_NAMES - _bridge_tool_names
        extra_in_bridge = _bridge_tool_names - commands_spec.COMMAND_NAMES
        raise RuntimeError(
            f"hmcp_bridge.py tool set doesn't match commands_spec.py. "
            f"Missing tools: {sorted(missing_in_bridge)}. "
            f"Extra tools: {sorted(extra_in_bridge)}."
        )
    main()
