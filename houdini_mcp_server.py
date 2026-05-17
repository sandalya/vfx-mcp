#!/usr/bin/env python
"""
houdini_mcp_server.py

Bridge script that Claude runs via `uv run`. Uses the MCP library (fastmcp)
to communicate with Claude over stdio, and relays each command to the Houdini
plugin listening on port 9876.
"""
import sys
import os
import site

# Get the directory where the script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Add the virtual environment's site-packages to Python's path
venv_site_packages = os.path.join(script_dir, '.venv', 'Lib', 'site-packages')
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
from datetime import datetime
from typing import Dict, Any, List
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP, Context
import asyncio


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HoudiniMCP_StdioServer")


@dataclass
class HoudiniConnection:
    host: str
    port: int
    sock: socket.socket = None

    def connect(self) -> bool:
        """Connect to the Houdini plugin (which is listening on self.host:self.port)."""
        if self.sock is not None:
            return True  # Already connected
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Houdini at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Houdini: {str(e)}")
            self.sock = None
            return False

    def disconnect(self):
        """Close socket if open."""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Houdini: {str(e)}")
            self.sock = None

    def send_command(self, cmd_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Send a JSON command to Houdini's server and wait for the JSON response.
        Returns the parsed Python dict (e.g. {"status": "success", "result": {...}})
        """
        if not self.connect():
            error_msg = "Could not connect to Houdini on port 9876."
            logger.error(error_msg)
            return {"status": "error", "message": error_msg, "origin": "mcp_server_connection"}

        command = {"type": cmd_type, "params": params or {}}
        data_out = json.dumps(command).encode("utf-8")

        try:
            self.sock.sendall(data_out)
            logger.info(f"Sent command to Houdini: {command}")

            self.sock.settimeout(10.0)
            buffer = b""
            start_time = asyncio.get_event_loop().time()
            while True:
                if asyncio.get_event_loop().time() - start_time > 10.0:
                    raise socket.timeout("Timeout waiting for Houdini response")

                chunk = self.sock.recv(8192)
                if not chunk:
                    if buffer:
                        raise ConnectionAbortedError("Connection closed by Houdini with incomplete data.")
                    else:
                        raise ConnectionAbortedError("Connection closed by Houdini before sending data.")

                buffer += chunk
                try:
                    decoded_string = buffer.decode("utf-8")
                    parsed = json.loads(decoded_string)
                    logger.info(f"Received response from Houdini: {parsed}")
                    return parsed
                except json.JSONDecodeError:
                    continue
                except UnicodeDecodeError:
                    logger.error("Received non-UTF-8 data from Houdini")
                    raise ValueError("Received non-UTF-8 data from Houdini")

        except socket.timeout:
            error_msg = "Timeout receiving data from Houdini."
            logger.error(error_msg)
            self.disconnect()
            return {"status": "error", "message": error_msg, "origin": "mcp_server_send_command_timeout"}
        except Exception as e:
            error_msg = f"Error during Houdini communication for command '{cmd_type}': {str(e)}"
            logger.error(error_msg)
            self.disconnect()
            return {"status": "error", "message": error_msg, "origin": "mcp_server_send_command"}


# A global Houdini connection object
_houdini_connection: HoudiniConnection = None

def get_houdini_connection() -> HoudiniConnection:
    """Get or create a persistent HoudiniConnection object."""
    global _houdini_connection
    if _houdini_connection is None:
        logger.info("Creating new HoudiniConnection.")
        _houdini_connection = HoudiniConnection(host="10.10.10.31", port=9876)

    if not _houdini_connection.connect():
        _houdini_connection = None
        raise ConnectionError("Could not connect to Houdini on 10.10.10.31:9876. Is the plugin running?")

    return _houdini_connection


mcp = FastMCP("HoudiniMCP")

@asynccontextmanager
async def server_lifespan(app: FastMCP):
    """Startup/shutdown logic. Called automatically by fastmcp."""
    logger.info("Houdini MCP server starting up (stdio).")
    yield {}
    logger.info("Houdini MCP server shutting down.")
    global _houdini_connection
    if _houdini_connection is not None:
        _houdini_connection.disconnect()
        _houdini_connection = None
    logger.info("Connection to Houdini closed.")

mcp.lifespan = server_lifespan


# -------------------------------------------------------------------
# Project Context (lets Claude Desktop read README)
# -------------------------------------------------------------------
@mcp.tool()
def get_project_context(ctx: Context) -> str:
    """
    Returns project README with full context: topology, security setup,
    available tools, workflow rules, and sync instructions.
    Call this at the start of a conversation to understand the project.
    """
    readme_path = os.path.join(script_dir, "README.md")
    try:
        with open(readme_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "README.md not found at " + readme_path


# -------------------------------------------------------------------
# Cross-agent inbox (CD -> CC handoff)
# -------------------------------------------------------------------
NOTES_DIR = os.path.join(script_dir, "notes")
INBOX_PATH = os.path.join(NOTES_DIR, "cc_inbox.md")
INBOX_CATEGORIES = {"bug", "observation", "question", "note"}

@mcp.tool()
def forward_to_cc(ctx: Context, title: str, body: str, category: str = "note") -> str:
    """
    Forward a structured note to the Claude Code inbox so the local-side
    agent can pick it up across sessions. Use this whenever Claude Desktop
    finds something worth acting on: a plugin bug, a parm pattern that
    belongs in the SAFE_PARMS whitelist, a scene anomaly, a question that
    needs research, a hypothesis to verify.

    Writes append-only to vfx-mcp/notes/cc_inbox.md.

    category: one of 'bug', 'observation', 'question', 'note' (default 'note').
    title: short headline, 1 line.
    body: full context — what was observed, where, suggested action if known.
    """
    if category not in INBOX_CATEGORIES:
        return f"Invalid category '{category}'. Must be one of: {sorted(INBOX_CATEGORIES)}"
    if not title or not title.strip():
        return "Title cannot be empty."
    if not body or not body.strip():
        return "Body cannot be empty."
    try:
        os.makedirs(NOTES_DIR, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="seconds")
        entry = f"\n## [{category}] {title.strip()}\n_{timestamp}_\n\n{body.rstrip()}\n\n---\n"
        with open(INBOX_PATH, "a", encoding="utf-8") as f:
            f.write(entry)
        return f"Forwarded to CC inbox ({category}): {title.strip()}"
    except Exception as e:
        logger.error(f"forward_to_cc failed: {e}", exc_info=True)
        return f"Failed to forward: {type(e).__name__}: {e}"

@mcp.tool()
def read_cc_inbox(ctx: Context, max_chars: int = 50000) -> str:
    """
    Read the current CC inbox (vfx-mcp/notes/cc_inbox.md).
    Useful to check what's already been forwarded before adding a duplicate,
    or to remind yourself of context from earlier in the session.
    """
    if not os.path.exists(INBOX_PATH):
        return "(inbox is empty)"
    try:
        with open(INBOX_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        if len(content) > max_chars:
            return content[:max_chars] + f"\n\n... (truncated; full size {len(content)} chars)"
        return content
    except Exception as e:
        return f"Failed to read inbox: {type(e).__name__}: {e}"


# -------------------------------------------------------------------
# Houdini Scene Tools
# -------------------------------------------------------------------
@mcp.tool()
def get_scene_info(ctx: Context, max_nodes: int = 100, context_filter: List[str] = None) -> str:
    """
    Ask Houdini for scene info. Returns JSON as a string.
    max_nodes: cap on returned top-level nodes (default 100).
    context_filter: optional list of contexts to inspect (e.g. ["obj"]); defaults to all.
    """
    try:
        conn = get_houdini_connection()
        params = {"max_nodes": max_nodes}
        if context_filter:
            params["context_filter"] = context_filter
        response = conn.send_command("get_scene_info", params)
        if response.get("status") == "error":
            origin = response.get('origin', 'houdini')
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"
        return json.dumps(response.get("result", {}), indent=2)
    except ConnectionError as e:
         return f"Connection Error getting scene info: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in get_scene_info tool: {str(e)}", exc_info=True)
        return f"Server Error retrieving scene info: {str(e)}"

@mcp.tool()
def create_node(ctx: Context, node_type: str, parent_path: str = "/obj", name: str = None, parameters: Dict[str, Any] = None) -> str:
    """
    Create a new node in Houdini. Optional `parameters` dict sets whitelisted
    parm values on the created node (only existing parms are set; rest ignored).
    """
    try:
        conn = get_houdini_connection()
        params = { "node_type": node_type, "parent_path": parent_path }
        if name: params["name"] = name
        if parameters: params["parameters"] = parameters
        response = conn.send_command("create_node", params)

        if response.get("status") == "error":
            origin = response.get('origin', 'houdini')
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"
        return f"Node created: {json.dumps(response.get('result', {}), indent=2)}"
    except ConnectionError as e:
         return f"Connection Error creating node: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in create_node tool: {str(e)}", exc_info=True)
        return f"Server Error creating node: {str(e)}"

@mcp.tool()
def get_node_info(ctx: Context, path: str, max_parms: int = None, only_non_default: bool = False) -> str:
    """
    Return detailed info about a single node: type, position, color, flags,
    parameters, inputs and outputs.
    max_parms: optional cap on returned parameter entries (omit for unlimited).
    only_non_default: if true, skip parameters that hold their template default —
                     useful for distilling "what's actually configured" on a node.
    """
    try:
        conn = get_houdini_connection()
        params = {"path": path}
        if max_parms is not None:
            params["max_parms"] = max_parms
        if only_non_default:
            params["only_non_default"] = True
        response = conn.send_command("get_node_info", params)
        if response.get("status") == "error":
            origin = response.get('origin', 'houdini')
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"
        return json.dumps(response.get("result", {}), indent=2)
    except ConnectionError as e:
        return f"Connection Error getting node info: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in get_node_info tool: {str(e)}", exc_info=True)
        return f"Server Error getting node info: {str(e)}"

@mcp.tool()
def set_node_parameter(ctx: Context, node_path: str, parm_name: str, value: Any) -> str:
    """
    Set a single whitelisted parameter on a node. Allowed parms include
    transforms (tx/ty/tz/rx/ry/rz/sx/sy/sz/scale), pivot (px/py/pz),
    basic geometry (rad/radx/rady/radz/sizex/sizey/sizez/rows/cols/type/orient),
    and display/render flags. Other parm names are rejected by the plugin.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("set_node_parameter", {
            "path": node_path,
            "parm_name": parm_name,
            "value": value,
        })
        if response.get("status") == "error":
            origin = response.get('origin', 'houdini')
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"
        return f"Parameter set: {json.dumps(response.get('result', {}), indent=2)}"
    except ConnectionError as e:
        return f"Connection Error setting parameter: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in set_node_parameter tool: {str(e)}", exc_info=True)
        return f"Server Error setting parameter: {str(e)}"

@mcp.tool()
def execute_houdini_code(ctx: Context, code: str) -> str:
    """
    [DISABLED BY PLUGIN HARDENING] Arbitrary Python execution inside Houdini.

    The plugin dispatcher explicitly rejects 'execute_code'. Use the narrow
    tools instead — `set_node_parameter`, `create_node`, `get_node_info`.
    If you need a capability they don't cover, forward_to_cc a request and
    we'll either add a narrow tool or expand SAFE_PARMS.

    Returns immediately — no socket round-trip — to avoid the 4-minute
    MCP client timeout on the disabled path.
    """
    return (
        "execute_houdini_code is DISABLED by plugin hardening. "
        "Use set_node_parameter / create_node / get_node_info instead. "
        "If you need broader access, forward_to_cc a request describing the use case."
    )


# -------------------------------------------------------------------
# Rendering Tools
# -------------------------------------------------------------------
@mcp.tool()
def render_single_view(ctx: Context,
                       orthographic: bool = False,
                       rotation: List[float] = [0, 90, 0],
                       render_path: str = "C:/temp/",
                       render_engine: str = "opengl",
                       karma_engine: str = "cpu") -> str:
    """
    Render a single view inside Houdini and return the rendered image path.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("render_single_view", {
            "orthographic": orthographic,
            "rotation": rotation,
            "render_path": render_path,
            "render_engine": render_engine,
            "karma_engine": karma_engine,
        })

        if response.get("status") == "error":
            origin = response.get("origin", "houdini")
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"

        return response.get("result", "Render completed but no output path returned.")
    except Exception as e:
        logger.error(f"render_single_view failed: {e}", exc_info=True)
        return f"Render failed: {str(e)}"

@mcp.tool()
def render_quad_views(ctx: Context,
                      render_path: str = "C:/temp/",
                      render_engine: str = "opengl",
                      karma_engine: str = "cpu") -> str:
    """
    Render 4 canonical views from Houdini and return the image paths.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("render_quad_view", {
            "render_path": render_path,
            "render_engine": render_engine,
            "karma_engine": karma_engine,
        })

        if response.get("status") == "error":
            origin = response.get("origin", "houdini")
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"

        return response.get("result", "Render completed but no output returned.")
    except Exception as e:
        logger.error(f"render_quad_views failed: {e}", exc_info=True)
        return f"Render failed: {str(e)}"

@mcp.tool()
def render_specific_camera(ctx: Context,
                           camera_path: str,
                           render_path: str = "C:/temp/",
                           render_engine: str = "opengl",
                           karma_engine: str = "cpu") -> str:
    """
    Render from a specific camera path in the Houdini scene.
    """
    try:
        conn = get_houdini_connection()
        response = conn.send_command("render_specific_camera", {
            "camera_path": camera_path,
            "render_path": render_path,
            "render_engine": render_engine,
            "karma_engine": karma_engine,
        })

        if response.get("status") == "error":
            origin = response.get("origin", "houdini")
            return f"Error ({origin}): {response.get('message', 'Unknown error')}"

        return response.get("result", "Render completed but no output path returned.")
    except Exception as e:
        logger.error(f"render_specific_camera failed: {e}", exc_info=True)
        return f"Render failed: {str(e)}"


def main():
    """Run the MCP server on stdio."""
    mcp.run()

if __name__ == "__main__":
    main()
