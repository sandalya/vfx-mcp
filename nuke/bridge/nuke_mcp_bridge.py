#!/usr/bin/env python
"""
nuke_mcp_bridge.py

Bridge script that Claude runs via `uv run`. Uses the MCP library (fastmcp)
to communicate with Claude over stdio, and relays each command to the Nuke
plugin (nuke_mcp_plugin.py) listening on port 9877. Same role as
houdini_mcp_server.py, for Nuke instead of Houdini -- see README.md for
topology and connection details (host/tunnel not yet finalized).
"""
import sys
import os

# Get the directory where the script is located, and the repo root
# (this script lives at <repo>/nuke/bridge/, two levels down)
script_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.dirname(os.path.dirname(script_dir))

# Add the virtual environment's site-packages to Python's path
venv_site_packages = os.path.join(repo_root, '.venv', 'Lib', 'site-packages')
if os.path.exists(venv_site_packages):
    sys.path.insert(0, venv_site_packages)
    print(f"Added {venv_site_packages} to sys.path", file=sys.stderr)
else:
    print(f"Warning: Virtual environment site-packages not found at {venv_site_packages}", file=sys.stderr)


# For debugging
print("Python path:", sys.path, file=sys.stderr)
import json
import socket
import logging
from dataclasses import dataclass
from typing import Dict, Any
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP, Context
import asyncio


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NukeMCP_StdioServer")


@dataclass
class NukeConnection:
    host: str
    port: int
    sock: socket.socket = None

    def connect(self) -> bool:
        """Connect to the Nuke plugin (which is listening on self.host:self.port)."""
        if self.sock is not None:
            return True  # Already connected
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Nuke at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Nuke: {str(e)}")
            self.sock = None
            return False

    def disconnect(self):
        """Close socket if open."""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Nuke: {str(e)}")
            self.sock = None

    # No slow commands identified yet (scaffold phase, no render tools).
    # Everything uses DEFAULT_TIMEOUT until a command needs its own budget.
    DEFAULT_TIMEOUT = 10.0
    COMMAND_TIMEOUTS = {}

    def send_command(self, cmd_type: str, payload: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Send a newline-delimited JSON command to the Nuke plugin and wait for
        the newline-delimited JSON response. Returns the parsed Python dict
        (e.g. {"ok": true, ...} or {"ok": false, "error": "..."}).
        """
        if not self.connect():
            error_msg = f"Could not connect to Nuke plugin on {self.host}:{self.port}."
            logger.error(error_msg)
            return {"ok": False, "error": error_msg, "origin": "mcp_server_connection"}

        command = {"type": cmd_type, "payload": payload or {}}
        data_out = (json.dumps(command) + "\n").encode("utf-8")
        timeout = self.COMMAND_TIMEOUTS.get(cmd_type, self.DEFAULT_TIMEOUT)

        try:
            self.sock.sendall(data_out)
            logger.info(f"Sent command to Nuke: {command} (timeout={timeout}s)")

            self.sock.settimeout(timeout)
            buffer = b""
            start_time = asyncio.get_event_loop().time()
            while True:
                if asyncio.get_event_loop().time() - start_time > timeout:
                    raise socket.timeout(f"Timeout waiting for Nuke response ({timeout}s)")

                chunk = self.sock.recv(65536)
                if not chunk:
                    if buffer:
                        raise ConnectionAbortedError("Connection closed by Nuke with incomplete data.")
                    else:
                        raise ConnectionAbortedError("Connection closed by Nuke before sending data.")

                buffer += chunk
                if b"\n" not in buffer:
                    continue
                line, _, _rest = buffer.partition(b"\n")
                try:
                    parsed = json.loads(line.decode("utf-8"))
                    logger.info(f"Received response from Nuke: {parsed}")
                    return parsed
                except json.JSONDecodeError:
                    continue
                except UnicodeDecodeError:
                    logger.error("Received non-UTF-8 data from Nuke")
                    raise ValueError("Received non-UTF-8 data from Nuke")

        except socket.timeout:
            error_msg = "Timeout receiving data from Nuke."
            logger.error(error_msg)
            self.disconnect()
            return {"ok": False, "error": error_msg, "origin": "mcp_server_send_command_timeout"}
        except Exception as e:
            error_msg = f"Error during Nuke communication for command '{cmd_type}': {str(e)}"
            logger.error(error_msg)
            self.disconnect()
            return {"ok": False, "error": error_msg, "origin": "mcp_server_send_command"}


# A global Nuke connection object
_nuke_connection: NukeConnection = None

def get_nuke_connection() -> NukeConnection:
    """Get or create a persistent NukeConnection object."""
    global _nuke_connection
    if _nuke_connection is None:
        logger.info("Creating new NukeConnection.")
        _nuke_connection = NukeConnection(host="10.10.10.31", port=9877)

    if not _nuke_connection.connect():
        _nuke_connection = None
        raise ConnectionError("Could not connect to Nuke on 10.10.10.31:9877. Is the plugin running?")

    return _nuke_connection


mcp = FastMCP("NukeMCP")

@asynccontextmanager
async def server_lifespan(app: FastMCP):
    """Startup/shutdown logic. Called automatically by fastmcp."""
    logger.info("Nuke MCP server starting up (stdio).")
    yield {}
    logger.info("Nuke MCP server shutting down.")
    global _nuke_connection
    if _nuke_connection is not None:
        _nuke_connection.disconnect()
        _nuke_connection = None
    logger.info("Connection to Nuke closed.")

mcp.lifespan = server_lifespan


# -------------------------------------------------------------------
# Nuke Script Tools
# -------------------------------------------------------------------
@mcp.tool()
def nuke_ping(ctx: Context) -> str:
    """Check that the Nuke-side plugin is alive and reachable."""
    try:
        conn = get_nuke_connection()
        response = conn.send_command("ping")
        if not response.get("ok"):
            origin = response.get('origin', 'nuke')
            return f"Error ({origin}): {response.get('error', 'Unknown error')}"
        return json.dumps(response, indent=2)
    except ConnectionError as e:
        return f"Connection Error pinging Nuke: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in nuke_ping tool: {str(e)}", exc_info=True)
        return f"Server Error pinging Nuke: {str(e)}"

@mcp.tool()
def nuke_get_script_info(ctx: Context) -> str:
    """Get basic info about the currently open Nuke script: name, node count, frame range."""
    try:
        conn = get_nuke_connection()
        response = conn.send_command("get_script_info")
        if not response.get("ok"):
            origin = response.get('origin', 'nuke')
            return f"Error ({origin}): {response.get('error', 'Unknown error')}"
        return json.dumps(response, indent=2)
    except ConnectionError as e:
        return f"Connection Error getting script info: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in nuke_get_script_info tool: {str(e)}", exc_info=True)
        return f"Server Error getting script info: {str(e)}"

@mcp.tool()
def nuke_list_nodes(ctx: Context, node_class: str = None) -> str:
    """List nodes in the current Nuke script, optionally filtered by class (e.g. 'Read')."""
    try:
        conn = get_nuke_connection()
        params = {"class": node_class} if node_class else {}
        response = conn.send_command("list_nodes", params)
        if not response.get("ok"):
            origin = response.get('origin', 'nuke')
            return f"Error ({origin}): {response.get('error', 'Unknown error')}"
        return json.dumps(response, indent=2)
    except ConnectionError as e:
        return f"Connection Error listing nodes: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in nuke_list_nodes tool: {str(e)}", exc_info=True)
        return f"Server Error listing nodes: {str(e)}"

@mcp.tool()
def nuke_get_nodes_in_view(ctx: Context, node_class: str = None) -> str:
    """
    List which nodes currently fall inside the visible area of the Node
    Graph panel (as opposed to nuke_list_nodes, which returns every node
    regardless of pan/zoom). Useful when the DAG has been scrolled/zoomed
    and only the nodes actually on screen matter. Each node in the result
    has an "in_view" flag; the response also includes the computed
    viewport rect, center, and zoom for reference.
    """
    try:
        conn = get_nuke_connection()
        params = {"class": node_class} if node_class else {}
        response = conn.send_command("get_nodes_in_view", params)
        if not response.get("ok"):
            origin = response.get('origin', 'nuke')
            return f"Error ({origin}): {response.get('error', 'Unknown error')}"
        return json.dumps(response, indent=2)
    except ConnectionError as e:
        return f"Connection Error getting nodes in view: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in nuke_get_nodes_in_view tool: {str(e)}", exc_info=True)
        return f"Server Error getting nodes in view: {str(e)}"

@mcp.tool()
def nuke_get_selected_nodes(ctx: Context, node_class: str = None) -> str:
    """List nodes currently selected in the Nuke Node Graph, optionally
    filtered by class (e.g. 'Read'). Read-class nodes additionally report
    their 'file' knob value."""
    try:
        conn = get_nuke_connection()
        params = {"class": node_class} if node_class else {}
        response = conn.send_command("get_selected_nodes", params)
        if not response.get("ok"):
            origin = response.get('origin', 'nuke')
            return f"Error ({origin}): {response.get('error', 'Unknown error')}"
        return json.dumps(response, indent=2)
    except ConnectionError as e:
        return f"Connection Error getting selected nodes: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in nuke_get_selected_nodes tool: {str(e)}", exc_info=True)
        return f"Server Error getting selected nodes: {str(e)}"

@mcp.tool()
def nuke_get_node_knobs(ctx: Context, names: list = None, only_non_default: bool = True) -> str:
    """Full knob dump (values via knob.toScript()) plus connected inputs
    for the given node names, or the current Node Graph selection if
    `names` is omitted. Use this to capture the exact settings of an
    existing comp pattern (channel mappings, Cryptomatte layer names,
    etc.), not just its topology -- e.g. for documenting a reusable
    layer-branch assembly. only_non_default=True (default) skips knobs
    still at their default value."""
    try:
        conn = get_nuke_connection()
        params = {"only_non_default": only_non_default}
        if names:
            params["names"] = names
        response = conn.send_command("get_node_knobs", params)
        if not response.get("ok"):
            origin = response.get('origin', 'nuke')
            return f"Error ({origin}): {response.get('error', 'Unknown error')}"
        return json.dumps(response, indent=2)
    except ConnectionError as e:
        return f"Connection Error getting node knobs: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in nuke_get_node_knobs tool: {str(e)}", exc_info=True)
        return f"Server Error getting node knobs: {str(e)}"

@mcp.tool()
def nuke_get_env(ctx: Context, prefix: str = "") -> str:
    """Get os.environ entries from the Nuke process whose key starts with
    `prefix`. Empty prefix returns the whole environment -- scaffold phase
    is intentionally permissive here, so pass a specific prefix unless you
    really want everything dumped."""
    try:
        conn = get_nuke_connection()
        params = {"prefix": prefix} if prefix else {}
        response = conn.send_command("get_env", params)
        if not response.get("ok"):
            origin = response.get('origin', 'nuke')
            return f"Error ({origin}): {response.get('error', 'Unknown error')}"
        return json.dumps(response, indent=2)
    except ConnectionError as e:
        return f"Connection Error getting env: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in nuke_get_env tool: {str(e)}", exc_info=True)
        return f"Server Error getting env: {str(e)}"

@mcp.tool()
def nuke_list_render_dir(ctx: Context, path: str = None) -> str:
    """List entries (name + is_dir) of a directory on the Nuke/pc137 side,
    defaulting to $FTRACK_RENDER_PATH (the current shot's render root) when
    `path` is omitted. First step for Function 1 (node init) -- discovering
    what render layer-branches exist before building the 4-Read assembly
    chain for one of them. Runs Nuke-side because pc137 already has working
    SMB access to the render share; this bridge's own host does not."""
    try:
        conn = get_nuke_connection()
        params = {"path": path} if path else {}
        response = conn.send_command("list_render_dir", params)
        if not response.get("ok"):
            origin = response.get('origin', 'nuke')
            return f"Error ({origin}): {response.get('error', 'Unknown error')}"
        return json.dumps(response, indent=2)
    except ConnectionError as e:
        return f"Connection Error listing render dir: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in nuke_list_render_dir tool: {str(e)}", exc_info=True)
        return f"Server Error listing render dir: {str(e)}"

@mcp.tool()
def nuke_execute_code(ctx: Context, code: str) -> str:
    """
    Execute raw Python inside the running Nuke session.
    SCAFFOLD PHASE: unrestricted, no sandboxing on the plugin side yet --
    will be locked down to a safe command set (mirrors Houdini's
    execute_houdini_code security filter) once the round-trip is proven
    and we know what's actually needed.
    """
    try:
        conn = get_nuke_connection()
        response = conn.send_command("execute_code", {"code": code})
        if not response.get("ok"):
            origin = response.get('origin', 'nuke')
            return f"Error ({origin}): {response.get('error', 'Unknown error')}"
        return json.dumps(response, indent=2)
    except ConnectionError as e:
        return f"Connection Error executing code: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in nuke_execute_code tool: {str(e)}", exc_info=True)
        return f"Server Error executing code: {str(e)}"


def main():
    """Run the MCP server on stdio."""
    mcp.run()

if __name__ == "__main__":
    main()
