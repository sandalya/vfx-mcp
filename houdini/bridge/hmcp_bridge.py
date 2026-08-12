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

HOST = os.environ.get("HMCP_HOST", "10.10.10.31")
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


# -------------------------------------------------------------------
# Phase 2: write tools. Every one refuses unless the open Houdini scene
# already lives under C:/houdini_mcp_sandbox/ (save_scene_as is the one
# exception -- it's how a fresh scene gets into the sandbox in the first
# place). See houdini/plugin/hmcp/guards.py for the full safety layer.
# -------------------------------------------------------------------

@mcp.tool()
def create_node(ctx: Context, parent_path: str, node_type: str, name: Optional[str] = None) -> str:
    """Create a node under parent_path (e.g. parent_path='/obj', node_type='geo').
    Restricted to Sop/Object categories. No parameters dict -- call set_parm
    afterwards. Requires a sandbox scene."""
    params = {"parent_path": parent_path, "node_type": node_type}
    if name is not None:
        params["name"] = name
    return _call("create_node", params)


@mcp.tool()
def connect_nodes(ctx: Context, from_path: str, to_path: str, input_index: int = 0) -> str:
    """Wire from_path's output into to_path's input_index-th input. Requires a sandbox scene."""
    return _call("connect_nodes", {"from_path": from_path, "to_path": to_path, "input_index": input_index})


@mcp.tool()
def set_parm(ctx: Context, node_path: str, parm_name: str, value) -> str:
    """Set a single parameter value. Refuses output-path parms (sopoutput etc.),
    Python/callback/script parms, and any file-type parm other than
    file/filepath. Requires a sandbox scene."""
    return _call("set_parm", {"node_path": node_path, "parm_name": parm_name, "value": value})


@mcp.tool()
def set_expression(ctx: Context, node_path: str, parm_name: str, expression: str) -> str:
    """Set an HScript expression on a parameter. Never Python. Requires a sandbox scene."""
    return _call("set_expression", {"node_path": node_path, "parm_name": parm_name, "expression": expression})


@mcp.tool()
def delete_node(ctx: Context, node_path: str) -> str:
    """Destroy a node -- only if this agent created it earlier in the current
    session. Requires a sandbox scene."""
    return _call("delete_node", {"node_path": node_path})


@mcp.tool()
def rename_node(ctx: Context, node_path: str, new_name: str) -> str:
    """Rename a node. Requires a sandbox scene."""
    return _call("rename_node", {"node_path": node_path, "new_name": new_name})


@mcp.tool()
def set_position(ctx: Context, node_path: str, x: float, y: float) -> str:
    """Set a node's network-view position. Requires a sandbox scene."""
    return _call("set_position", {"node_path": node_path, "x": x, "y": y})


@mcp.tool()
def set_color(ctx: Context, node_path: str, r: float, g: float, b: float) -> str:
    """Set a node's network-view color (0-1 floats). Requires a sandbox scene."""
    return _call("set_color", {"node_path": node_path, "r": r, "g": g, "b": b})


@mcp.tool()
def set_comment(ctx: Context, node_path: str, comment: str) -> str:
    """Set a node's comment text. Requires a sandbox scene."""
    return _call("set_comment", {"node_path": node_path, "comment": comment})


@mcp.tool()
def layout_children(ctx: Context, parent_path: str) -> str:
    """Auto-layout a network's children. Requires a sandbox scene."""
    return _call("layout_children", {"parent_path": parent_path})


@mcp.tool()
def set_display_flag(ctx: Context, node_path: str, on: bool) -> str:
    """Set/clear a node's display flag. Requires a sandbox scene."""
    return _call("set_display_flag", {"node_path": node_path, "on": on})


@mcp.tool()
def set_render_flag(ctx: Context, node_path: str, on: bool) -> str:
    """Set/clear a node's render flag. Requires a sandbox scene."""
    return _call("set_render_flag", {"node_path": node_path, "on": on})


@mcp.tool()
def set_bypass(ctx: Context, node_path: str, on: bool) -> str:
    """Set/clear a node's bypass flag. Requires a sandbox scene."""
    return _call("set_bypass", {"node_path": node_path, "on": on})


@mcp.tool()
def save_scene_as(ctx: Context) -> str:
    """Bootstrap a never-saved scene into the sandbox
    (C:/houdini_mcp_sandbox/mcp_<timestamp>.hip). No arguments. Only works
    from a scene that has never been saved -- the one write command that
    does NOT require an existing sandbox scene."""
    return _call("save_scene_as", {})


@mcp.tool()
def viewport_snapshot(ctx: Context) -> str:
    """OpenGL viewport snapshot of the current SceneViewer. No arguments.
    Requires a sandbox scene and a pre-existing
    C:/houdini_mcp_sandbox/_snapshots/ directory."""
    return _call("viewport_snapshot", {})


# -------------------------------------------------------------------
# Stage 2: camera control. get_viewport_info is read-only; the rest move
# the viewport/its camera and require a sandbox scene plus a viewport not
# locked to a camera.
# -------------------------------------------------------------------

@mcp.tool()
def get_viewport_info(ctx: Context) -> str:
    """Viewport/camera state: name, type, pivot/translation, camera-lock
    status, and snapshot_ready (whether the current update_mode allows
    viewport_snapshot to succeed right now). No arguments, no sandbox
    requirement -- read-only."""
    return _call("get_viewport_info", {})


@mcp.tool()
def viewport_frame_node(ctx: Context, node_path: str) -> str:
    """Aim the Houdini viewport at this node, the equivalent of selecting
    it and pressing Home. Call this before viewport_snapshot -- the
    snapshot only captures whatever the viewport already shows. Accepts a
    SOP or an Object node. Does not change the user's selection. Requires
    a sandbox scene."""
    return _call("viewport_frame_node", {"node_path": node_path})


@mcp.tool()
def viewport_frame_all(ctx: Context) -> str:
    """Frame the viewport on the entire scene's visible geometry -- the
    'I'm lost' recovery button. No arguments. Requires a sandbox scene."""
    return _call("viewport_frame_all", {})


@mcp.tool()
def viewport_set_view(ctx: Context, view: str) -> str:
    """Switch the viewport to a named preset view: 'perspective', 'top',
    'bottom', 'front', 'back', 'right', or 'left'. Requires a sandbox
    scene."""
    return _call("viewport_set_view", {"view": view})


@mcp.tool()
def viewport_orbit(ctx: Context, dx_degrees: float = 0.0, dy_degrees: float = 0.0) -> str:
    """Orbit the viewport camera around its current pivot by relative
    angle deltas (not absolute angles). No clamping -- rotation wraps, so
    out-of-range values are harmless. Requires a sandbox scene."""
    return _call("viewport_orbit", {"dx_degrees": dx_degrees, "dy_degrees": dy_degrees})


@mcp.tool()
def viewport_dolly(ctx: Context, factor: float) -> str:
    """Move the viewport camera toward/away from its pivot by a
    multiplicative factor (< 1 zooms in, > 1 zooms out), pivot fixed.
    Requires a sandbox scene."""
    return _call("viewport_dolly", {"factor": factor})


# -------------------------------------------------------------------
# Stage 3: non-blocking render. render_snapshot spawns a background
# Karma render and returns immediately; render_status polls it.
# -------------------------------------------------------------------

@mcp.tool()
def render_snapshot(ctx: Context, renderer: str = "karma", quality: str = "draft", camera: str = "viewport") -> str:
    """Render a still frame in the background and return immediately --
    call render_status() to poll it. renderer: only 'karma'. quality:
    'draft' (512x512) or 'preview' (960x540). camera: 'viewport'
    (default, GUI only, copies the SceneViewer's current camera -- call
    a viewport_* command first to frame it) or 'fit' (headless-safe,
    frames every displayed /obj node automatically). Requires a sandbox
    scene and a pre-existing c:/houdini_mcp_sandbox/_renders/ directory."""
    return _call("render_snapshot", {"renderer": renderer, "quality": quality, "camera": camera})


@mcp.tool()
def render_status(ctx: Context) -> str:
    """Poll the single pending render_snapshot slot. No arguments.
    Returns done/path/seconds_elapsed/errors/warnings, or pending: false
    if nothing is pending. Never raises -- call this in a loop after
    render_snapshot until done is true, then Read the path."""
    return _call("render_status", {})


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
        # Phase 2 write tools
        "create_node", "connect_nodes", "set_parm", "set_expression",
        "delete_node", "rename_node", "set_position", "set_color",
        "set_comment", "layout_children", "set_display_flag",
        "set_render_flag", "set_bypass", "save_scene_as", "viewport_snapshot",
        # Stage 2 write tools
        "get_viewport_info", "viewport_frame_node", "viewport_frame_all",
        "viewport_set_view", "viewport_orbit", "viewport_dolly",
        # Stage 3: non-blocking render
        "render_snapshot", "render_status",
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
