"""
nuke_mcp_plugin.py

Minimal TCP command server that runs INSIDE Nuke, mirroring the
houdini-mcp plugin pattern already working on PC-137 (Houdini uses
port 9876). This listens on a separate port so both can run at once.

STATUS: scaffold only. No restrictions applied yet -- see _is_allowed()
below. Fill that in once there's something real to test against
(mirrors the SAFE_PARMS whitelist we ended up with for Houdini).

INSTALL (on PC-137)
    1. Copy this file to a folder on NUKE_PATH, e.g.:
       C:\\Users\\Admin\\.nuke\\nuke_mcp_plugin.py
    2. Add to C:\\Users\\Admin\\.nuke\\menu.py:
           import nuke_mcp_plugin
           nuke_mcp_plugin.start_server()
    3. Restart Nuke, check Script Editor output for
       "nuke-mcp listening on 0.0.0.0:9877"

NETWORKING
    Bind to 0.0.0.0, not 127.0.0.1 -- this is the exact bug that broke
    the first Houdini plugin attempt. Reuse the existing Loky VPN + SSH
    tunnel to PC-137; just add a second local port-forward for 9877
    alongside the existing 9876 one (see bridge script for the config
    line to add).
"""

import json
import random
import re
import socket
import sys
import threading
import datetime
import importlib
import os

import nuke

HOST = "0.0.0.0"
PORT = 9877
AUDIT_LOG = os.path.join(os.path.expanduser("~"), "nuke_mcp_audit.log")

# Empty for now (permissive scaffold phase). Once locked down, this
# becomes e.g. {"10.10.11.43"} -- same idea as Houdini's ALLOWED_CLIENTS.
ALLOWED_CLIENTS = set()


def _audit(cmd_type, payload, ok):
    try:
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat()}\t{cmd_type}\t"
                     f"ok={ok}\t{json.dumps(payload)[:500]}\n")
    except Exception:
        pass  # logging must never break the server


def _is_allowed(cmd_type, payload):
    """
    TODO: injection point for restrictions once we know what actually
    needs locking down. For now: allow everything. Same role as the
    SAFE_PARMS / blocked-import-pattern check in Houdini's server.py.
    """
    return True


def _summarize_payload(payload, limit=300):
    if not payload:
        return ""
    s = json.dumps(payload, default=str)
    return s if len(s) <= limit else s[:limit] + "...(truncated)"


def _print_to_editor(msg):
    """Runs on Nuke's main thread so it lands in the Script Editor output."""
    print(msg)


# ---- command handlers (executed on Nuke's main thread) --------------

def cmd_ping(payload):
    return {"pong": True}


def cmd_print(payload):
    """Print a message to Nuke's Script Editor output. Whitelisted stand-in
    for execute_code -- for the hotkey-overlay PoC, which only ever needs
    to print, not run arbitrary code."""
    message = str(payload.get("message", ""))
    print(message)
    return {"printed": message}


def cmd_get_script_info(payload):
    root = nuke.root()
    return {
        "script": root.name() or "(unsaved)",
        "node_count": len(nuke.allNodes()),
        "frame_range": [root.firstFrame(), root.lastFrame()],
    }


def cmd_list_nodes(payload):
    node_class = payload.get("class")
    nodes = nuke.allNodes(node_class) if node_class else nuke.allNodes()
    return {"nodes": [{"name": n.name(), "class": n.Class()} for n in nodes]}


def _dag_viewport_rect():
    """(center, zoom, vis_rect) for the frontmost open Node Graph panel --
    shared by cmd_get_nodes_in_view and the version-stepping "nothing
    selected" fallback (_working_read_nodes) below. Nuke has no built-in
    "is this node on screen" API, so this reconstructs the viewport rect
    from nuke.center()/nuke.zoom() (DAG pan/zoom, in world units) and the
    pixel size of the DAG's Qt widget.

    Caveat: if multiple Node Graph panels/tabs are open, this grabs the
    first "DAG_Window" Qt widget found -- not necessarily the one the user
    is looking at. Raises RuntimeError if none is found (no Node Graph
    panel open)."""
    try:
        from PySide2 import QtWidgets
    except ImportError:
        from PySide6 import QtWidgets

    center = nuke.center()
    zoom = nuke.zoom()

    app = QtWidgets.QApplication.instance()
    w_px = h_px = None
    for w in app.allWidgets():
        if w.metaObject().className() == "DAG_Window":
            geo = w.geometry()
            w_px, h_px = geo.width(), geo.height()
            break

    if w_px is None:
        raise RuntimeError("no DAG_Window widget found -- is a Node Graph panel open?")

    half_w = (w_px / zoom) / 2.0
    half_h = (h_px / zoom) / 2.0
    vis_rect = {
        "x_min": center[0] - half_w, "x_max": center[0] + half_w,
        "y_min": center[1] - half_h, "y_max": center[1] + half_h,
    }
    return center, zoom, (w_px, h_px), vis_rect


def _nodes_in_view(node_class=None):
    """Nodes of node_class (or all classes) whose bounding box intersects
    the visible Node Graph viewport -- see _dag_viewport_rect. Returns
    Node objects directly (not the JSON-friendly dicts cmd_get_nodes_in_view
    builds), for in-process callers like _working_read_nodes."""
    _center, _zoom, _widget_px, vis_rect = _dag_viewport_rect()
    all_nodes = nuke.allNodes(node_class) if node_class else nuke.allNodes()

    def intersects(x0, y0, x1, y1):
        return not (x1 < vis_rect["x_min"] or x0 > vis_rect["x_max"]
                    or y1 < vis_rect["y_min"] or y0 > vis_rect["y_max"])

    result = []
    for n in all_nodes:
        try:
            sw, sh = n.screenWidth(), n.screenHeight()
        except Exception:
            sw, sh = 80, 18
        x, y = n.xpos(), n.ypos()
        if intersects(x, y, x + sw, y + sh):
            result.append(n)
    return result


def cmd_get_nodes_in_view(payload):
    """
    Which nodes currently fall inside the visible area of the Node Graph
    panel -- unlike cmd_list_nodes, which returns every node regardless of
    pan/zoom. See _dag_viewport_rect for how the viewport rect itself is
    reconstructed.
    """
    center, zoom, (w_px, h_px), vis_rect = _dag_viewport_rect()

    node_class = payload.get("class")
    all_nodes = nuke.allNodes(node_class) if node_class else nuke.allNodes()

    def intersects(x0, y0, x1, y1):
        return not (x1 < vis_rect["x_min"] or x0 > vis_rect["x_max"]
                    or y1 < vis_rect["y_min"] or y0 > vis_rect["y_max"])

    nodes = []
    for n in all_nodes:
        try:
            sw, sh = n.screenWidth(), n.screenHeight()
        except Exception:
            sw, sh = 80, 18
        x, y = n.xpos(), n.ypos()
        nodes.append({
            "name": n.name(), "class": n.Class(),
            "x": x, "y": y, "w": sw, "h": sh,
            "in_view": intersects(x, y, x + sw, y + sh),
        })

    return {
        "center": list(center), "zoom": zoom,
        "widget_px": [w_px, h_px], "visible_rect": vis_rect,
        "nodes": nodes,
    }


def cmd_execute_code(payload):
    """
    Raw exec -- scaffold phase only, no sandboxing yet.
    TODO: restrict the same way as Houdini's execute_houdini_code once
    this is actually in use (block os/subprocess/sys/eval/exec/open,
    or replace with a whitelisted command set entirely).
    """
    code = payload.get("code", "")
    local_ns = {"nuke": nuke, "result": None}
    exec(code, {}, local_ns)
    return {"result": repr(local_ns.get("result"))}


def cmd_get_selected_nodes(payload):
    """Nodes currently selected in the Node Graph. Optional payload["class"]
    filters by class (e.g. "Read"), mirroring cmd_list_nodes. Read-class
    nodes additionally report their `file` knob -- the anchor point later
    branch-detection work needs (selection -> disk path)."""
    node_class = payload.get("class")
    selected = nuke.selectedNodes(node_class) if node_class else nuke.selectedNodes()

    nodes = []
    for n in selected:
        entry = {"name": n.name(), "class": n.Class()}
        if n.Class() == "Read":
            try:
                entry["file"] = n["file"].value()
            except Exception:
                entry["file"] = None
        nodes.append(entry)
    return {"nodes": nodes}


# Env-var name substrings that mark a value as a secret, checked
# case-insensitively against the full key name. Applied regardless of the
# requested `prefix` -- a caller can't route around this by asking for a
# different prefix that happens to still match a secret's name (e.g.
# prefix="FTRACK" matched FTRACK_API_KEY and leaked a live ftrack API key
# in full over the socket the first time this ran against a real scene).
SENSITIVE_ENV_NAME_PATTERNS = (
    "KEY", "TOKEN", "SECRET", "PASSWORD", "PWD", "CREDENTIAL", "AUTH", "COOKIE",
)


def _is_sensitive_env_name(name):
    upper = name.upper()
    return any(pattern in upper for pattern in SENSITIVE_ENV_NAME_PATTERNS)


def cmd_get_node_knobs(payload):
    """Full knob dump for named nodes (payload["names"], list of node names)
    or nuke.selectedNodes() if omitted -- for documenting/reverse-engineering
    an existing comp pattern down to exact knob values (channel mappings,
    Cryptomatte layer names, etc.), not just topology. Read-only, so no
    restriction beyond what's already exposed by reading the node in the
    Properties panel -- same reasoning as get_node_info in the Houdini
    plugin having no read-side whitelist, only writes are gated.

    payload["only_non_default"] (default True) mirrors the Houdini
    plugin's only_non_default flag on get_node_info -- skips knobs still
    at their default value to keep the dump readable. Values come from
    knob.toScript(), Nuke's own canonical serialization (the same format
    written to .nk files), so complex knob types (channel lists, matrices)
    come back reconstructable instead of repr() noise.

    Also reports each node's `inputs` (list of connected node names, None
    for an empty input) since knob values alone don't show topology."""
    names = payload.get("names")
    only_non_default = payload.get("only_non_default", True)

    if names:
        nodes = [nuke.toNode(n) for n in names]
        nodes = [n for n in nodes if n is not None]
    else:
        nodes = nuke.selectedNodes()

    result = []
    for n in nodes:
        knobs = {}
        for kname, k in n.knobs().items():
            if only_non_default:
                try:
                    if not k.notDefault():
                        continue
                except Exception:
                    pass  # some knob types don't support notDefault() -- include them
            try:
                knobs[kname] = k.toScript()
            except Exception:
                try:
                    knobs[kname] = str(k.value())
                except Exception:
                    knobs[kname] = None

        inputs = []
        for i in range(n.inputs()):
            inp = n.input(i)
            inputs.append(inp.name() if inp else None)

        result.append({"name": n.name(), "class": n.Class(), "knobs": knobs, "inputs": inputs})

    return {"nodes": result}


def cmd_get_env(payload):
    """os.environ entries whose key startswith(payload["prefix"]). Scaffold-
    phase note: an empty/omitted prefix returns the ENTIRE environment --
    intentionally permissive for now (matches _is_allowed()'s "allow
    everything" stance), so pass a specific prefix unless you really want
    everything dumped.

    Values for keys matching SENSITIVE_ENV_NAME_PATTERNS are redacted (key
    still shown, so callers know the var exists) -- see the comment above
    the pattern list for why."""
    prefix = payload.get("prefix", "")
    env = {}
    for k, v in os.environ.items():
        if not k.startswith(prefix):
            continue
        env[k] = "<redacted>" if _is_sensitive_env_name(k) else v
    return {"env": env}


def cmd_list_render_dir(payload):
    """listdir() on payload["path"], defaulting to $FTRACK_RENDER_PATH -- the
    first step of Function 1 (node init, see docs/NUKE_COMP_LAYER_ASSEMBLY.md),
    which needs to see what render layer-branches exist on disk before it can
    build the 4-Read assembly chain for one of them. Runs Nuke-side because
    pc137's Nuke process already has working SMB access to the render share
    under the ftrack-launched domain session -- the Claude Code host does not
    (tested 2026-08-07: VPN/TCP reachable, but not domain-joined, so no creds
    for loky.plarium.local).

    Confirmed by Sashok: $FTRACK_RENDER_PATH itself contains only layer
    subfolders, no per-frame files -- so no sequence-collapsing needed here."""
    path = payload.get("path") or os.environ.get("FTRACK_RENDER_PATH")
    if not path:
        raise ValueError("no path given and $FTRACK_RENDER_PATH is not set")

    entries = []
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        entries.append({
            "name": name,
            "is_dir": os.path.isdir(full),
            "mtime": os.path.getmtime(full),  # lets callers sort by
            # recency -- added for the layer-branch picker HUD, which
            # wants the most recently touched layer-branch folder first
            # (a new version subfolder landing inside it bumps the
            # branch folder's own mtime on Windows/NTFS).
        })

    return {"path": path, "entries": entries}


DISPATCH = {
    "ping": cmd_ping,
    "print": cmd_print,
    "get_script_info": cmd_get_script_info,
    "list_nodes": cmd_list_nodes,
    "get_nodes_in_view": cmd_get_nodes_in_view,
    "get_selected_nodes": cmd_get_selected_nodes,
    "get_node_knobs": cmd_get_node_knobs,
    "get_env": cmd_get_env,
    "list_render_dir": cmd_list_render_dir,
    "execute_code": cmd_execute_code,
}


# ---- Nuke-side hotkey menu (dev-loop testing) --------------------------
# OS-level global hotkeys (keyboard pkg's WH_KEYBOARD_LL hook, then raw
# RegisterHotKey) never fired -- likely swallowed by AV/EDR, since that
# hook shape is exactly what keyloggers use. Nuke's own menu shortcut
# system doesn't have that problem, so hotkeys live here instead.
#
# menu.py only needs to call register_menu() once, at Nuke startup:
#     import nuke_mcp_plugin
#     nuke_mcp_plugin.register_menu()
#
# The registered shortcut's command string reloads this module and calls
# a function *by name* -- so once registered, iterating just means: edit
# this file, deploy, press the hotkey. No menu.py edits, no Nuke restart.

MENU_PATH = "Little Helpers/Unused/Quick Print Test"
MCP_MENU_PATH = "Little Helpers/MCP Server"
LAYER_PICKER_MENU_PATH = "Little Helpers/Create Layer Branch"
VERSION_HUD_MENU_PATH = "Little Helpers/Change Layer Version"
SPLIT_LAYERS_MENU_PATH = "Little Helpers/Split Layers"

# Bump this by hand and redeploy to prove the reload loop actually picks
# up new code, without restarting Nuke.
TEST_ITERATION = 2


def cmd_print_test():
    """Triggered by the alt+shift+p Nuke menu shortcut (see register_menu).
    Not part of DISPATCH -- this only ever runs Nuke-side, never over the
    socket."""
    message = f"Hotkey -> cmd_print works! iteration={TEST_ITERATION}"
    print(message)
    return message


def register_menu():
    """Idempotent -- safe to call repeatedly without piling up duplicate
    menu entries (removes the old item at MENU_PATH first, if present)."""
    menu = nuke.menu("Nodes")
    if menu.findItem(MENU_PATH):
        menu.removeItem(MENU_PATH)
    menu.addCommand(
        MENU_PATH,
        "import importlib, nuke_mcp_plugin; importlib.reload(nuke_mcp_plugin); "
        "nuke_mcp_plugin.show_hud()",
        # No hotkey here anymore -- ctrl+shift+a moved to the layer-branch
        # picker below. Still reachable from the menu.
    )

    if menu.findItem(MCP_MENU_PATH):
        menu.removeItem(MCP_MENU_PATH)
    menu.addCommand(
        MCP_MENU_PATH,
        "import importlib, nuke_mcp_plugin; importlib.reload(nuke_mcp_plugin); "
        "nuke_mcp_plugin.toggle_mcp_hud()",
        "ctrl+shift+t",
    )

    if menu.findItem(LAYER_PICKER_MENU_PATH):
        menu.removeItem(LAYER_PICKER_MENU_PATH)
    menu.addCommand(
        LAYER_PICKER_MENU_PATH,
        "import importlib, nuke_mcp_plugin; importlib.reload(nuke_mcp_plugin); "
        "nuke_mcp_plugin.show_layer_picker()",
        "shift+a",
    )

    if menu.findItem(VERSION_HUD_MENU_PATH):
        menu.removeItem(VERSION_HUD_MENU_PATH)
    menu.addCommand(
        VERSION_HUD_MENU_PATH,
        "import importlib, nuke_mcp_plugin; importlib.reload(nuke_mcp_plugin); "
        "nuke_mcp_plugin.show_version_hud()",
        # Plain "shift+d" silently loses to Nuke's own BUILT-IN Viewer menu
        # item "Go to nextkeyframe" (also Shift+D, native to Nuke -- not
        # something in menu.py); Ctrl+Shift+D worked but felt awkward to
        # Sashok. Confirmed live 2026-08-07 via a full nuke.menu() scan of
        # Nuke/Nodes/Viewer/Edit/Preferences/Player: shift+e is unbound
        # anywhere in the app.
        "shift+e",
    )

    if menu.findItem(SPLIT_LAYERS_MENU_PATH):
        menu.removeItem(SPLIT_LAYERS_MENU_PATH)
    menu.addCommand(
        SPLIT_LAYERS_MENU_PATH,
        "import importlib, nuke_mcp_plugin; importlib.reload(nuke_mcp_plugin); "
        "nuke_mcp_plugin.show_split_layers()",
        "F10",
    )


# ---- transparent HUD ----------------------------------------------------
# Nuke is itself a Qt app (PySide6 as of Nuke 16), so the HUD widget runs
# straight inside Nuke's own Qt event loop -- no separate process, no
# socket, no OS-level hotkey. Ported from the standalone nuke_overlay.py
# PoC (already visually verified there: real transparency, rounded panel
# via manual paintEvent since QSS backgrounds don't reliably paint on a
# top-level frameless+translucent QWidget).

try:
    from PySide6 import QtWidgets, QtCore, QtGui
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui

_hud = None  # module-level ref -- keeps the widget alive; without it,
             # Python would GC the shown window as soon as show_hud() returns


class _PrintHUD(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Tool
        )
        # No WA_TranslucentBackground: that renders via a per-pixel-alpha
        # layered window (UpdateLayeredWindow on Windows), and over RDP to
        # pc137 that combo reliably ate mouse clicks while keyboard events
        # (Esc, arrow keys) still reached the widget fine -- consistent
        # with known RDP/DWM issues where layered-window hit-testing gets
        # lost in the remoting pipeline even though painting still works.
        # setMask() below gives the same rounded silhouette through a
        # plain GDI window region instead, which RDP treats like any other
        # opaque window (real OS-level hit-testing, no alpha involved).
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)

        self.setStyleSheet("""
            QLabel { color: rgba(230, 230, 230, 230); font-size: 11px; }
            QLineEdit {
                background-color: rgba(255, 255, 255, 20);
                color: white;
                border: 1px solid rgba(255, 255, 255, 60);
                border-radius: 6px;
                padding: 6px;
            }
            QPushButton {
                background-color: rgba(70, 130, 220, 210);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: rgba(90, 150, 240, 230); }
            QPushButton:pressed { background-color: rgba(50, 100, 180, 230); }
            #status { color: rgba(150, 220, 150, 230); font-size: 10px; }
        """)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        title = QtWidgets.QLabel("Nuke quick print")
        title.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.DemiBold))
        layout.addWidget(title)

        self.input = QtWidgets.QLineEdit()
        self.input.setPlaceholderText("message...")
        self.input.returnPressed.connect(self.send_print)
        layout.addWidget(self.input)

        btn = QtWidgets.QPushButton("Print to Script Editor")
        # NoFocus so a click doesn't steal focus from self.input and, on
        # _McpHud's buttons, from the top-level widget itself -- see the
        # detailed root-cause comment above the "MCP server control HUD"
        # section below.
        btn.setFocusPolicy(QtCore.Qt.NoFocus)
        btn.clicked.connect(self.send_print)
        layout.addWidget(btn)

        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("status")
        layout.addWidget(self.status)

        self.resize(260, 130)

    def resizeEvent(self, event):
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(self.rect()), 12, 12)
        self.setMask(QtGui.QRegion(path.toFillPolygon().toPolygon()))
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        path = QtGui.QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)
        painter.fillPath(path, QtGui.QColor(25, 25, 28, 255))
        painter.setPen(QtGui.QColor(255, 255, 255, 40))
        painter.drawPath(path)
        super().paintEvent(event)

    def send_print(self):
        message = self.input.text().strip() or "(hello from HUD)"
        print(message)
        self.status.setText("printed ✓")
        QtCore.QTimer.singleShot(500, self.hide)

    def show_near_cursor(self):
        pos = QtGui.QCursor.pos()
        self.move(pos.x() - self.width() // 2, pos.y() - self.height() - 10)
        self.input.clear()
        self.status.setText("")
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def focusOutEvent(self, event):
        self.hide()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)


def show_hud():
    """Triggered by the Nuke-side hotkey (see register_menu). Creates the
    HUD once and reuses it across calls within the same reload -- but
    every hotkey press reloads this module first, which resets `_hud` to
    None and replaces any still-open widget with a fresh one."""
    global _hud
    if _hud is None:
        _hud = _PrintHUD()
    _hud.show_near_cursor()


# ---- Layer-branch picker (Ctrl+Shift+A) ---------------------------------
# Lists the render root's layer subfolders (same data list_render_dir
# returns); picking one drops the "Function 1 init" node chain documented
# in docs/NUKE_COMP_LAYER_ASSEMBLY.md -- 4 Read nodes + the ShuffleCopy/
# Copy assembly + an empty Cryptomatte pick point + a StickyNote label.
# Each Read's version + frame range is resolved by scanning disk per-pass
# (see _resolve_pass/_collapse_sequence below).
#
# Picker is a phone-timer-style vertical spinner (_WheelPicker below),
# per Sashok's ask for something better than one-button-per-folder once
# the render root grew past a handful of branches -- scroll or Up/Down
# to the value you want, confirm with the Build button, Enter, or a
# double-click. Names are sorted by folder mtime, freshest first, with
# the freshest one pre-selected on open -- per Sashok's ask, since
# picking up whatever branch was just re-rendered is the common case.
# (An earlier revision also had a plain QListWidget view with a toggle
# to switch between the two; removed once the wheel alone proved to be
# everything Sashok wanted -- see BACKLOG.md if it needs resurrecting.)

_layer_picker_hud = None  # rebuilt fresh every open -- the folder list can
                          # change between opens, so caching would go
                          # stale (same reasoning _mcp_hud below documents).


class _WheelPicker(QtWidgets.QWidget):
    """Vertical phone-timer-style picker: the centered row is the current
    selection, rows above/below shrink and fade with distance. Moves in
    whole-item steps only, no drag/momentum -- matches the rest of this
    file's click-and-keyboard-first interaction style (drag-based UI has
    a history of being unreliable over RDP here, see the eventFilter/
    focus comments elsewhere in this file). Confirm via the `activated`
    signal (Enter or double-click) -- scrolling alone only browses."""

    ROW_HEIGHT = 26
    VISIBLE_ROWS = 5  # odd, so there's a true center row

    activated = QtCore.Signal(str)

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self._items = list(items)
        self._index = 0
        self.setFixedHeight(self.ROW_HEIGHT * self.VISIBLE_ROWS)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

    def current_name(self):
        return self._items[self._index] if self._items else None

    def set_current(self, name):
        if name in self._items:
            self._index = self._items.index(name)
            self.update()

    def _step(self, delta):
        if not self._items:
            return
        self._index = max(0, min(len(self._items) - 1, self._index + delta))
        self.update()

    def wheelEvent(self, event):
        self._step(-1 if event.angleDelta().y() > 0 else 1)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Up:
            self._step(-1)
        elif event.key() == QtCore.Qt.Key_Down:
            self._step(1)
        elif event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if self.current_name() is not None:
                self.activated.emit(self.current_name())
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        # Tapping any visible row (not just the centered one) jumps
        # straight to it -- the shortcut real wheel pickers give you
        # instead of forcing one scroll step per row.
        try:
            y = event.position().y()  # Qt6/PySide6
        except AttributeError:
            y = event.y()  # Qt5/PySide2
        row_under_cursor = int(y // self.ROW_HEIGHT)
        self._step(row_under_cursor - self.VISIBLE_ROWS // 2)

    def mouseDoubleClickEvent(self, event):
        if self.current_name() is not None:
            self.activated.emit(self.current_name())

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        center_row = self.VISIBLE_ROWS // 2

        band = QtGui.QPainterPath()
        band.addRoundedRect(
            QtCore.QRectF(4, center_row * self.ROW_HEIGHT, self.width() - 8, self.ROW_HEIGHT), 6, 6
        )
        painter.fillPath(band, QtGui.QColor(70, 130, 220, 90))

        for row in range(self.VISIBLE_ROWS):
            item_index = self._index + (row - center_row)
            if not (0 <= item_index < len(self._items)):
                continue
            distance = abs(row - center_row)
            alpha = max(60, 230 - distance * 70)
            point_size = 11 if distance == 0 else max(8, 11 - distance * 2)
            font = QtGui.QFont("Segoe UI", point_size)
            font.setWeight(QtGui.QFont.DemiBold if distance == 0 else QtGui.QFont.Normal)
            painter.setFont(font)
            painter.setPen(QtGui.QColor(230, 230, 230, alpha))
            rect = QtCore.QRectF(0, row * self.ROW_HEIGHT, self.width(), self.ROW_HEIGHT)
            painter.drawText(rect, QtCore.Qt.AlignCenter, self._items[item_index])
        super().paintEvent(event)


# Sashok's ask: Build button reads a random one of these instead of the
# same static label every time -- purely cosmetic, re-rolled on every HUD
# open (see _LayerPickerHUD.__init__).
_BUILD_BTN_LABELS = (
    "ЄБАШ",
    "АНУКА",
    "МЕНІ ПОВЕЗЕ",
    "БУДЬ ДОБРІШЕ",
    "ОТАКО",
    "ГАТІ",
    "А ТАК МОЖНА БУЛО?",
    "ГОЦ",
    "БАЦ",
)


class _LayerPickerHUD(QtWidgets.QWidget):
    def __init__(self, layer_names):
        super().__init__()
        self.layer_names = layer_names  # already sorted freshest-first
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)

        self.setStyleSheet("""
            QLabel { color: rgba(230, 230, 230, 230); font-size: 11px; }
            QCheckBox { color: rgba(230, 230, 230, 230); font-size: 11px; }
            QPushButton {
                background-color: rgba(70, 130, 220, 210);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px;
                font-weight: 600;
                text-align: left;
            }
            QPushButton:hover { background-color: rgba(90, 150, 240, 230); }
            QPushButton:pressed { background-color: rgba(50, 100, 180, 230); }
            #status { color: rgba(220, 150, 150, 230); font-size: 10px; }
        """)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        self.wheel = _WheelPicker(self.layer_names)
        self.wheel.activated.connect(self._pick)
        layout.addWidget(self.wheel)

        self.split_checkbox = QtWidgets.QCheckBox("Split layers")
        self.split_checkbox.setChecked(False)
        self.split_checkbox.setFocusPolicy(QtCore.Qt.NoFocus)
        layout.addWidget(self.split_checkbox)

        self.build_btn = QtWidgets.QPushButton(random.choice(_BUILD_BTN_LABELS))
        self.build_btn.setFocusPolicy(QtCore.Qt.NoFocus)
        self.build_btn.clicked.connect(lambda: self._pick(self._current_selection()))
        layout.addWidget(self.build_btn)

        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("status")
        layout.addWidget(self.status)

        self.setFixedWidth(240)
        self.adjustSize()

    def _current_selection(self):
        return self.wheel.current_name()

    def _pick(self, layer_name):
        if not layer_name:
            return
        try:
            last_node = build_layer_branch(layer_name)
        except Exception as exc:
            self.status.setText(str(exc))
            print(f"build_layer_branch({layer_name!r}) failed: {exc}")
            return
        if self.split_checkbox.isChecked():
            try:
                _run_split_layers(last_node)
            except Exception as exc:
                self.status.setText(str(exc))
                print(f"_run_split_layers({last_node.name()!r}) failed: {exc}")
        self.hide()

    def resizeEvent(self, event):
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(self.rect()), 12, 12)
        self.setMask(QtGui.QRegion(path.toFillPolygon().toPolygon()))
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        path = QtGui.QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)
        painter.fillPath(path, QtGui.QColor(25, 25, 28, 255))
        painter.setPen(QtGui.QColor(255, 255, 255, 40))
        painter.drawPath(path)
        super().paintEvent(event)

    def show_near_cursor(self):
        pos = QtGui.QCursor.pos()
        self.move(pos.x() - self.width() // 2, pos.y() - self.height() - 10)
        self.show()
        self.raise_()
        self.activateWindow()
        # focusOutEvent alone isn't reliable for a Qt.Tool widget over RDP
        # -- clicking the DAG doesn't always transfer focus away cleanly,
        # so it stayed open (same issue found on _VersionHUD, fixed the
        # same way there). App-wide mouse filter instead: any press
        # outside our own rect closes us, regardless of focus semantics.
        QtWidgets.QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.MouseButtonPress:
            try:
                global_pos = event.globalPosition().toPoint()  # Qt6/PySide6
            except AttributeError:
                global_pos = event.globalPos()  # Qt5/PySide2
            if not self.geometry().contains(global_pos):
                self.hide()
        return super().eventFilter(obj, event)

    def focusOutEvent(self, event):
        self.hide()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        # Up/Down/Enter handled here, not on self.wheel directly --
        # everything in this HUD is NoFocus specifically so keyboard
        # focus stays on `self` (see the comment above _McpHud: a
        # focused child stealing focus fires our own focusOutEvent ->
        # hide() before a click/keypress on it can be processed). Same
        # reasoning applies to giving the wheel widget real focus, so
        # arrow-key stepping is dispatched from here instead.
        if event.key() == QtCore.Qt.Key_Escape:
            self.hide()
        elif event.key() == QtCore.Qt.Key_Up:
            self.wheel._step(-1)
        elif event.key() == QtCore.Qt.Key_Down:
            self.wheel._step(1)
        elif event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self._pick(self._current_selection())
        else:
            super().keyPressEvent(event)


def show_layer_picker():
    """Triggered by the Nuke-side hotkey (see register_menu). Always builds
    a fresh HUD -- see the comment on _layer_picker_hud above for why."""
    global _layer_picker_hud
    try:
        result = cmd_list_render_dir({})
    except Exception as exc:
        print(f"show_layer_picker: list_render_dir failed: {exc}")
        return
    dirs = [e for e in result["entries"] if e["is_dir"]]
    dirs.sort(key=lambda e: e["mtime"], reverse=True)  # freshest first
    layer_names = [e["name"] for e in dirs]
    _layer_picker_hud = _LayerPickerHUD(layer_names)
    _layer_picker_hud.show_near_cursor()


_LAYER_BRANCH_PASSES = ("lights", "beauty", "tech", "crypto")


_VERSION_DIR_RE = re.compile(r"^v(\d+)$", re.IGNORECASE)
_FRAME_FILE_RE_TMPL = r"^{pass_name}_product\.(\d+)\.([A-Za-z0-9]+)$"


def _collapse_sequence(dirpath, pass_name):
    """Scan dirpath for '<pass_name>_product.<frame>.<ext>' files and
    collapse them into one printf-style pattern + frame range. Returns
    None if no matching files exist in dirpath, otherwise a dict with
    pattern/first/last/missing (missing = sorted list of frame numbers
    absent inside [first, last])."""
    pattern = re.compile(_FRAME_FILE_RE_TMPL.format(pass_name=re.escape(pass_name)))
    frames = []
    ext = None
    pad = None
    for name in os.listdir(dirpath):
        m = pattern.match(name)
        if not m:
            continue
        frame_str, ext = m.group(1), m.group(2)
        frames.append(int(frame_str))
        pad = len(frame_str)
    if not frames:
        return None
    frames.sort()
    first, last = frames[0], frames[-1]
    missing = sorted(set(range(first, last + 1)) - set(frames))
    return {
        # "####"-style padding, not "%04d" -- confirmed working on pc137
        # (Sashok fixed a broken Read by hand this way); %04d combined
        # with the UNC path apparently doesn't resolve the same way.
        "pattern": f"{pass_name}_product.{'#' * pad}.{ext}",
        "first": first,
        "last": last,
        "missing": missing,
    }


def _available_versions(layer_dir, pass_name):
    """List every version folder directly under layer_dir that actually
    contains files for pass_name, as a list of (version_int, version_str)
    sorted ascending. Versions are resolved per-pass, independently --
    per docs/NUKE_COMP_LAYER_ASSEMBLY.md, the 4 passes of a layer-branch
    are not guaranteed to move in lock-step (e.g. beauty/lights at v007
    while tech/crypto sit at v006 in one recorded shot)."""
    candidates = []
    for name in os.listdir(layer_dir):
        full = os.path.join(layer_dir, name)
        if not os.path.isdir(full):
            continue
        m = _VERSION_DIR_RE.match(name)
        if m:
            candidates.append((int(m.group(1)), name))
    candidates.sort()

    found = []
    for num, vname in candidates:
        # Plain "/" join, not os.path.join -- this path's root is a UNC
        # network path (//loky.plarium.local/...) already on forward
        # slashes; os.path.join on Windows mixes in backslashes, which
        # broke Nuke's Read for lights/tech/crypto (confirmed 2026-08-07:
        # beauty worked once Sashok hand-fixed it to all-forward-slash).
        if _collapse_sequence(f"{layer_dir}/{vname}", pass_name):
            found.append((num, vname))
    return found


def _resolve_pass(layer_dir, pass_name):
    """Highest-numbered version (see _available_versions) for pass_name,
    collapsed into a sequence. Raises ValueError if no version folder
    under layer_dir has any files for pass_name at all."""
    versions = _available_versions(layer_dir, pass_name)
    if not versions:
        raise ValueError(f"no '{pass_name}_product' sequence found under {layer_dir} (any version)")
    _, vname = versions[-1]
    return vname, _collapse_sequence(f"{layer_dir}/{vname}", pass_name)


def _apply_read_sequence(read, pass_name, version, seq, layer_dir):
    """Set a Read node's file/frame-range knobs from a resolved (version,
    seq) pair, and flag missing frames (orange tile_color + label) instead
    of silently building a wrong range. Shared by build_layer_branch (new
    Read nodes) and _bump_read_version (existing ones).

    postage_stamp defaults off here -- with a full layer-branch (4 live
    Reads) plus up to 6 history Reads per branch, leaving every one of
    them generating a live thumbnail every frame change is a real
    playback-performance hit. The two call sites that build/bump the
    *live* beauty Read (the one artists actually look at) turn it back on
    afterward -- everything else (lights/tech/crypto, and every history
    Read regardless of pass) stays off."""
    read["file"].setValue(f"{layer_dir}/{version}/{seq['pattern']}")
    read["first"].setValue(seq["first"])
    read["last"].setValue(seq["last"])
    read["origfirst"].setValue(seq["first"])
    read["origlast"].setValue(seq["last"])
    read["postage_stamp"].setValue(False)

    if seq["missing"]:
        missing_preview = ", ".join(str(f) for f in seq["missing"][:8])
        if len(seq["missing"]) > 8:
            missing_preview += ", ..."
        read["label"].setValue(f"{version}  MISSING FRAMES: {missing_preview}")
        read["tile_color"].setValue(0xD08000FF)  # orange -- catches the eye
        print(
            f"_apply_read_sequence: {pass_name} ({version}) missing "
            f"{len(seq['missing'])} frame(s): {missing_preview}"
        )
    else:
        read["label"].setValue(version)
        read["tile_color"].setValue(0)  # clear any stale missing-frames flag


def build_layer_branch(layer_name):
    """Function 1 init, per docs/NUKE_COMP_LAYER_ASSEMBLY.md: 4 Read nodes
    (lights/beauty/tech/crypto) + the ShuffleCopy/Copy assembly chain + an
    empty Cryptomatte pick point + a StickyNote label, centered on the
    current Node Graph view (nuke.createNode's default placement when
    nothing is selected).

    Each pass's version + frame range is resolved independently by
    scanning disk (see _resolve_pass/_collapse_sequence above) -- highest
    version folder that actually has files for that pass wins. Read nodes
    whose sequence has gaps get flagged (label + orange tile_color) rather
    than silently built with a wrong frame range."""
    root = os.environ.get("FTRACK_RENDER_PATH")
    if not root:
        raise ValueError("$FTRACK_RENDER_PATH is not set")

    layer_dir = f"{root}/{layer_name}"

    for n in nuke.allNodes():
        n.setSelected(False)

    def make(node_class, **knobs):
        node = nuke.createNode(node_class, inpanel=False)
        for k, v in knobs.items():
            node[k].setValue(v)
        return node

    reads = {}
    for pass_name in _LAYER_BRANCH_PASSES:
        version, seq = _resolve_pass(layer_dir, pass_name)
        read = make("Read")
        _apply_read_sequence(read, pass_name, version, seq, layer_dir)
        if pass_name == "beauty":
            read["postage_stamp"].setValue(True)  # the one Read artists
            # actually look at -- everything else in the branch stays off
        reads[pass_name] = read

    # Relative (dx, dy) offsets lifted directly from the captured sh320/bg
    # v014 reference (docs/NUKE_COMP_LAYER_ASSEMBLY.md), anchored on the
    # lights Read at (0, 0) -- Nuke's DAG convention here is top-to-bottom
    # flow (sources at low y, result at high y), NOT left-to-right, so this
    # must stay vertical to actually resemble the template.
    anchor_x, anchor_y = reads["lights"].xpos(), reads["lights"].ypos()
    reads["beauty"].setXYpos(anchor_x - 129, anchor_y + 129)
    reads["tech"].setXYpos(anchor_x - 129, anchor_y + 307)
    reads["crypto"].setXYpos(anchor_x - 281, anchor_y + 467)

    shuffle_rgba = make("ShuffleCopy", red="red", green="green", blue="blue",
                         label="RGBA IN")
    shuffle_rgba.setInput(0, reads["lights"])
    shuffle_rgba.setInput(1, reads["beauty"])
    shuffle_rgba.setXYpos(anchor_x, anchor_y + 166)

    shuffle_dir = make("ShuffleCopy", **{
        "in": "direct_emission", "alpha": "alpha2", "black": "red",
        "white": "green", "red2": "blue", "out2": "direct_emission",
    }, label="DIR EMISSION")
    shuffle_dir.setInput(0, shuffle_rgba)
    shuffle_dir.setInput(1, reads["beauty"])
    shuffle_dir.setXYpos(anchor_x, anchor_y + 202)

    shuffle_indir = make("ShuffleCopy", **{
        "in": "indirect_emission", "alpha": "alpha2", "black": "red",
        "white": "green", "red2": "blue", "out2": "indirect_emission",
    }, label="INDIR EMISSION")
    shuffle_indir.setInput(0, shuffle_dir)
    shuffle_indir.setInput(1, reads["beauty"])
    shuffle_indir.setXYpos(anchor_x, anchor_y + 238)

    copy_tech = make("Copy", **{
        "from0": "Zc.X", "to0": "depth.Z",
        "from1": "Zg.X", "to1": "Zg.X",
        "from2": "mv.X", "to2": "mv.X",
        "from3": "mv.Y", "to3": "mv.Y",
        "mix": 0.48,
    })
    copy_tech.setInput(0, shuffle_indir)
    copy_tech.setInput(1, reads["tech"])
    copy_tech.setXYpos(anchor_x, anchor_y + 319)

    shuffle_pos = make("ShuffleCopy", **{
        "in": "Pg", "alpha": "alpha2", "black": "red", "white": "green",
        "red2": "blue", "out2": "Pg",
    }, label="POS IN")
    shuffle_pos.setInput(0, copy_tech)
    shuffle_pos.setInput(1, reads["tech"])
    shuffle_pos.setXYpos(anchor_x, anchor_y + 391)

    dot = make("Dot")
    dot.setInput(0, reads["crypto"])
    dot.setXYpos(anchor_x - 247, anchor_y + 603)

    # Left empty on purpose (no matteList/pickerAdd) -- a ready pick point
    # for the artist, mirroring the doc's captured init template.
    cryptomatte = make("Cryptomatte")
    cryptomatte.setInput(0, dot)
    cryptomatte.setXYpos(anchor_x - 149, anchor_y + 600)

    copy_matte = make("Copy", **{"from0": "rgba.alpha", "to0": "mask.a"})
    copy_matte.setInput(0, shuffle_pos)
    copy_matte.setInput(1, cryptomatte)
    copy_matte.setXYpos(anchor_x, anchor_y + 594)

    sticky = make(
        "StickyNote",
        label=layer_name.upper(),
        tile_color=0x353535FF,
        gl_color=0x797979FF,
        note_font_size=222,
    )
    sticky.setXYpos(anchor_x + 286, anchor_y + 210)

    return copy_matte


# ---- Split layers hookup (Function 1 checkbox + standalone F10) ---------
# Calls the standalone split_layers tool (nuke/split_layers/, deployed
# alongside this file to <.nuke>/split_layers/) unmodified -- per Sashok's
# explicit ask, this is thin glue only (path setup + optional node
# selection + the call), no split_layers logic ported in here. Isolating
# *which* layers to split stays manual, inside that tool's own panel.

_SPLIT_LAYERS_DIR = os.path.join(os.path.dirname(__file__), "split_layers")


def _import_split_layers():
    if _SPLIT_LAYERS_DIR not in sys.path:
        sys.path.insert(0, _SPLIT_LAYERS_DIR)
    # Reload dependencies before split_layers itself, so its `from models
    # import ...` / `from uii import ...` rebind to the fresh modules --
    # mirrors this file's own edit-deploy-hotkey reload loop.
    for mod_name in ("models", "uii", "nuke_actions", "split_layers"):
        mod = sys.modules.get(mod_name)
        if mod is not None:
            importlib.reload(mod)
    import split_layers
    return split_layers


def _run_split_layers(node):
    """Used by Function 1's "Split layers" checkbox -- selects `node`
    (the branch's last node) before launching the tool on it."""
    split_layers = _import_split_layers()
    for n in nuke.allNodes():
        n.setSelected(False)
    node.setSelected(True)
    split_layers.main()


def show_split_layers():
    """Triggered by the F10 hotkey (see register_menu) -- standalone entry
    point, independent of Function 1. Launches split_layers on whatever's
    already selected in Nuke, same as running the tool by hand always has."""
    _import_split_layers().main()


# ---- Version support for existing Read nodes (Shift+E) ------------------
# Function 2, first slice: jump-to-latest / step version up / step version
# down on whatever Read node(s) are selected, each resolved independently
# against its own (layer, pass) -- same per-pass-independent rule as
# build_layer_branch above. No shared "current branch" detection here (that
# was the fuller Function 2 scope from docs/NUKE_COMP_LAYER_ASSEMBLY.md);
# this only ever touches nodes the artist has actually selected.

_READ_PATH_RE = re.compile(
    r"^(?P<layer_dir>.+)/(?P<version>v\d+)/(?P<pass_name>\w+)_product\.",
    re.IGNORECASE,
)


def _parse_read_file(file_value):
    """Pull (layer_dir, version, pass_name) back out of a Read node's
    current file path, per the convention build_layer_branch writes
    (.../<layer>/<version>/<pass>_product.<frame-token>.<ext>). Not tied
    to _LAYER_BRANCH_PASSES -- matches whatever pass name actually
    precedes "_product.", so real production paths and hand-edited ones
    parse too, regardless of %04d vs #### frame-token style. Returns None
    if file_value doesn't match the convention at all."""
    m = _READ_PATH_RE.match(file_value)
    if not m:
        return None
    return m.group("layer_dir"), m.group("version"), m.group("pass_name")


_HISTORY_COUNTS = {"lights": 1, "beauty": 5}  # .get(pass_name, 0) -- 0
# (tech/crypto, or anything unrecognized) means "no history row for this
# pass". Matches the row of disconnected old-version Read nodes Sashok
# already builds by hand next to a live branch (confirmed on sh320/bg:
# 5 old beauty Reads, 1 old lights Read, none for tech/crypto).

# Reload-safe (same reasoning as _server_thread etc. further down --
# importlib.reload() re-runs this module's top level on every hotkey
# press, so a plain `_HISTORY_ENABLED = True` here would silently reset
# the artist's checkbox choice back to on every time). Controls the
# "History" checkbox in _VersionHUD: True keeps _sync_history_reads
# running on every bump (original always-on behavior); False stops new
# history rows from being created (see bump_selected_reads) and, via
# _set_history_enabled, removes any that already exist.
if '_HISTORY_ENABLED' not in globals():
    _HISTORY_ENABLED = True

_HISTORY_SPACING = 110  # px between history-node slots, cosmetic only --
# splits the difference between the two spacings actually observed on disk
# (a hand-built history lights Read sat -116px from its live Read, a
# history beauty Read -108/-109px from its live Read). Safe to retune:
# these are disconnected reference nodes, moving them changes nothing.

_HISTORY_TILE_COLOR = 0x2E3B4EFF  # muted blue-gray -- distinguishes a
# history node from a live Read (default tile_color) at a glance, but
# applied only when that node's own sequence has no missing frames --
# the orange missing-frames flag _apply_read_sequence sets takes priority.


def _is_live_read(read):
    """True if read feeds something other than a Viewer. A plain
    node.dependent() check isn't enough on its own -- confirmed live:
    Read7 (a beauty history Read, tile_color already the history-node
    gray, postage_stamp already off) was still reported as "live" and got
    flagged/bumped, because Sashok had it plugged into a Viewer for visual
    comparison -- exactly the normal, expected use of a history Read.
    Viewer connections don't make a Read part of the actual comp, so they
    don't count here."""
    return any(d.Class() != "Viewer" for d in read.dependent())


def _working_read_nodes():
    """Read nodes version-stepping operates on: the current selection if
    there is one, else every Read node visible in the current Node Graph
    viewport (see _nodes_in_view) -- framing the view on a branch becomes
    an implicit "work on this" the same way explicitly selecting nodes
    does, per Sashok's ask. Further filtering (_is_live_read, the file-
    path convention) stays on the callers, same as it already was for an
    explicit selection."""
    selected = nuke.selectedNodes()
    if selected:
        return [n for n in selected if n.Class() == "Read"]
    try:
        return _nodes_in_view("Read")
    except Exception as e:
        print(f"_working_read_nodes: nodes-in-view fallback failed -- {e}")
        return []


def _history_candidates(live_read, layer_dir, pass_name):
    """Read nodes elsewhere in the script that show the same (layer_dir,
    pass_name) as live_read but aren't it and have nothing downstream --
    i.e. the orphaned history/comparison Reads artists already build by
    hand (docs/NUKE_COMP_LAYER_ASSEMBLY.md: 'old versions are not
    deleted'). Deliberately NOT name-based -- Nuke's auto-numbered
    Read78/Read77 etc. carry no semantic meaning, only file path + graph
    topology do. A node counts as orphaned iff _is_live_read() is False --
    the same thing you'd check by eye to tell a live Read from a history
    one. Sorted by descending xpos so index 0 is closest to live_read
    (highest version-below-current slot)."""
    candidates = []
    for n in nuke.allNodes("Read"):
        if n is live_read:
            continue
        parsed = _parse_read_file(n["file"].value())
        if parsed is None:
            continue
        n_layer_dir, _n_version, n_pass_name = parsed
        if n_layer_dir != layer_dir or n_pass_name != pass_name:
            continue
        if _is_live_read(n):
            continue
        candidates.append(n)
    candidates.sort(key=lambda n: -n.xpos())
    return candidates


def _sync_history_reads(live_read, layer_dir, pass_name, current_num):
    """Called after a successful version bump on a beauty/lights live Read
    (see _HISTORY_COUNTS) to keep its row of old-version Read nodes in
    sync. _bump_read_version mutates live_read's own knobs in place rather
    than creating a new node, so there's no stored record of "what used to
    be live" to diff against -- every call re-derives the desired version
    list from disk instead of trying to track it. Reuses existing
    orphaned Reads first (adopting hand-built ones the first time this
    ever runs on a branch), creates new Read nodes only for any shortfall,
    and never deletes a node even if more orphans exist than currently
    wanted -- deletion needs its own explicit confirmation, out of scope
    here."""
    wanted = _HISTORY_COUNTS.get(pass_name, 0)
    if wanted <= 0:
        return

    versions = _available_versions(layer_dir, pass_name)  # ascending
    below = [v for v in versions if v[0] < current_num]
    targets = below[-wanted:]  # top `wanted` versions strictly below current
    targets.reverse()          # descending: targets[0] = closest-to-live

    candidates = _history_candidates(live_read, layer_dir, pass_name)

    for rank, (_version_num, version_name) in enumerate(targets, start=1):
        node = candidates[rank - 1] if rank - 1 < len(candidates) else \
            nuke.createNode("Read", inpanel=False)

        node.setXYpos(live_read.xpos() - rank * _HISTORY_SPACING, live_read.ypos())

        seq = _collapse_sequence(f"{layer_dir}/{version_name}", pass_name)
        _apply_read_sequence(node, pass_name, version_name, seq, layer_dir)
        if not seq["missing"]:
            node["tile_color"].setValue(_HISTORY_TILE_COLOR)


def _set_history_enabled(enabled):
    """Backing function for _VersionHUD's "History" checkbox. Applies
    immediately to whatever _working_read_nodes() currently resolves to
    (selection, or nodes-in-view fallback), same working set the bump
    buttons use -- turning the checkbox on/off is itself the action, not
    just a setting for the next bump. Sets the _HISTORY_ENABLED flag
    (gates future bumps in bump_selected_reads) either way."""
    global _HISTORY_ENABLED
    _HISTORY_ENABLED = enabled

    reads = [n for n in _working_read_nodes() if _is_live_read(n)]
    touched = 0
    for read in reads:
        parsed = _parse_read_file(read["file"].value())
        if parsed is None:
            continue
        layer_dir, current_version, pass_name = parsed
        if _HISTORY_COUNTS.get(pass_name, 0) <= 0:
            continue  # tech/crypto/unrecognized -- no history row either way
        touched += 1
        if enabled:
            current_num = int(_VERSION_DIR_RE.match(current_version).group(1))
            _sync_history_reads(read, layer_dir, pass_name, current_num)
        else:
            for node in _history_candidates(read, layer_dir, pass_name):
                nuke.delete(node)

    print(f"_set_history_enabled({enabled}): applied to {touched} live Read(s) "
          f"with a history-eligible pass")


def _bump_read_version(read, direction):
    """direction: "latest" | "up" | "down". Returns (status, detail,
    parsed) where status is "updated" or "skipped", and parsed is
    (layer_dir, pass_name, target_num) on "updated" else None -- handed
    back so the caller can sync history Reads (see _sync_history_reads)
    without re-parsing the now-mutated file knob."""
    file_value = read["file"].value()
    parsed = _parse_read_file(file_value)
    if parsed is None:
        return "skipped", "unrecognized path", None
    layer_dir, current_version, pass_name = parsed

    versions = _available_versions(layer_dir, pass_name)
    if not versions:
        return "skipped", "no versions found on disk", None

    current_num = int(_VERSION_DIR_RE.match(current_version).group(1))

    if direction == "latest":
        target_num, target_vname = versions[-1]
        if target_num == current_num:
            return "skipped", "already at latest", None
    elif direction == "up":
        higher = [(n, v) for n, v in versions if n > current_num]
        if not higher:
            return "skipped", "no higher version available", None
        target_num, target_vname = higher[0]
    elif direction == "down":
        lower = [(n, v) for n, v in versions if n < current_num]
        if not lower:
            return "skipped", "no lower version available", None
        target_num, target_vname = lower[-1]
    else:
        raise ValueError(f"unknown direction {direction!r}")

    seq = _collapse_sequence(f"{layer_dir}/{target_vname}", pass_name)
    _apply_read_sequence(read, pass_name, target_vname, seq, layer_dir)
    if pass_name == "beauty":
        read["postage_stamp"].setValue(True)  # this is the live main Read,
        # not a history one -- see _apply_read_sequence's postage_stamp note
    return "updated", f"{current_version} -> {target_vname}", (layer_dir, pass_name, target_num)


def bump_selected_reads(direction):
    """Triggered by a _VersionHUD button. Acts on _working_read_nodes()
    (current selection, or everything visible in the Node Graph viewport
    if nothing's selected), filtered to Read nodes, each resolved
    independently -- prints a one-line summary to the Script Editor (same
    feedback channel used elsewhere in this file). Also keeps each
    bumped beauty/lights Read's history row in sync (see
    _sync_history_reads), and restores the original graph selection
    afterward: nuke.createNode() (used there when a new history node is
    needed) resets the selection as a side effect, which would otherwise
    leave the artist's selection pointing at a random history Read
    instead of what they actually picked -- and _VersionHUD's status
    refresh reads _working_read_nodes() right after this returns, so a
    wrong selection there would report on the wrong nodes too."""
    original_selection = nuke.selectedNodes()
    reads = _working_read_nodes()
    updated = 0
    skipped = 0
    for read in reads:
        if not _is_live_read(read):
            # Not live -- nothing downstream, so this is itself a history/
            # reference Read (docs/NUKE_COMP_LAYER_ASSEMBLY.md's "old
            # versions kept, not deleted" pattern). History Reads sit right
            # next to their live sibling, so a box-select/shift-click on
            # the branch easily grabs them too -- bumping one directly
            # would make it its own "live" head, and _sync_history_reads
            # would then build IT a history row too, cascading extra
            # nodes (confirmed live: a co-selected old history Read spun
            # off its own history chain). Skip outright rather than only
            # skipping the sync, so a stray history Read's own version
            # never changes underneath the artist either.
            skipped += 1
            print(f"bump_selected_reads({direction!r}): {read.name()} skipped -- "
                  f"not live (no downstream connections, looks like a history Read)")
            continue
        status, detail, parsed = _bump_read_version(read, direction)
        if status == "updated":
            updated += 1
            layer_dir, pass_name, target_num = parsed
            if _HISTORY_COUNTS.get(pass_name, 0) > 0 and _HISTORY_ENABLED:
                _sync_history_reads(read, layer_dir, pass_name, target_num)
        else:
            skipped += 1
        print(f"bump_selected_reads({direction!r}): {read.name()} {status} -- {detail}")
    print(f"bump_selected_reads({direction!r}): {updated} updated, {skipped} skipped")

    for n in nuke.selectedNodes():
        n.setSelected(False)
    for n in original_selection:
        n.setSelected(True)


def _read_status(read):
    """Outdated / missing-frames / shot-range-incomplete flags for a
    single Read, reusing the same convention-parsing + disk scan
    _bump_read_version already does. Returns None for Read nodes that
    don't match the layer-branch file convention at all.

    "incomplete" is the check _collapse_sequence's missing-frames list
    can't do on its own: a Read whose file knob only ever pointed at one
    rendered frame (first == last, no internal gap possible) still might
    cover only 1 of the shot's N frames -- confirmed live on sh320/bg's
    beauty Read (v008, first=last=1001 against a 1001-1029 shot range).

    "outdated" is only ever checked for the beauty pass -- per
    docs/NUKE_COMP_LAYER_ASSEMBLY.md the 4 passes version independently
    and are routinely NOT lock-step on purpose (e.g. beauty re-rendered
    for a fix while lights/tech/crypto sit untouched), so flagging
    lights/tech/crypto as "outdated" whenever beauty moves ahead is just
    noise, not a real problem -- confirmed by Sashok live (a lights Read
    a version behind its branch's beauty got flagged and shouldn't have
    been)."""
    parsed = _parse_read_file(read["file"].value())
    if parsed is None:
        return None
    layer_dir, current_version, pass_name = parsed
    current_num = int(_VERSION_DIR_RE.match(current_version).group(1))

    outdated = False
    latest_vname = current_version
    if pass_name == "beauty":
        versions = _available_versions(layer_dir, pass_name)
        latest_num, latest_vname = versions[-1] if versions else (current_num, current_version)
        outdated = latest_num > current_num

    seq = _collapse_sequence(f"{layer_dir}/{current_version}", pass_name)
    root = nuke.root()
    root_first, root_last = root.firstFrame(), root.lastFrame()

    return {
        "pass_name": pass_name,
        "current_version": current_version,
        "latest_version": latest_vname,
        "outdated": outdated,
        "missing": seq["missing"] if seq else [],
        "incomplete": bool(seq) and (seq["first"] > root_first or seq["last"] < root_last),
        "seq": seq,
        "root_range": (root_first, root_last),
    }


_version_hud = None  # rebuilt fresh every open, same reasoning as
                     # _layer_picker_hud above.


class _VersionHUD(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)

        self.setStyleSheet("""
            QLabel { color: rgba(230, 230, 230, 230); font-size: 11px; }
            QPushButton {
                background-color: rgba(70, 130, 220, 210);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px;
                font-weight: 600;
                text-align: left;
            }
            QPushButton:hover { background-color: rgba(90, 150, 240, 230); }
            QPushButton:pressed { background-color: rgba(50, 100, 180, 230); }
            #info { color: rgba(180, 180, 180, 200); font-size: 10px; }
            QCheckBox { color: rgba(230, 230, 230, 230); font-size: 11px; }
        """)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        title = QtWidgets.QLabel("Change version")
        title.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.DemiBold))
        layout.addWidget(title)

        for label, direction in (
            ("Latest version", "latest"),
            ("Version +", "up"),
            ("Version -", "down"),
        ):
            btn = QtWidgets.QPushButton(label)
            btn.setFocusPolicy(QtCore.Qt.NoFocus)
            btn.clicked.connect(lambda checked=False, d=direction: self._on_bump_clicked(d))
            layout.addWidget(btn)

        # History checkbox -- checked keeps the row of old-version Read
        # nodes next to the live one (see _HISTORY_COUNTS) in sync;
        # unchecked removes whatever history Reads already exist for the
        # current working set and stops new ones from being created on
        # future bumps. Reflects the reload-safe _HISTORY_ENABLED global
        # so it stays correct across HUD re-opens, not just this instance.
        self.history_cb = QtWidgets.QCheckBox("History")
        self.history_cb.setFocusPolicy(QtCore.Qt.NoFocus)
        self.history_cb.setChecked(_HISTORY_ENABLED)
        self.history_cb.toggled.connect(self._on_history_toggled)
        layout.addWidget(self.history_cb)

        # Status panel -- outdated-version / missing-frames / shot-range-
        # incomplete flags for the current selection (see _read_status).
        # Was reserved empty per Sashok's original "just leave room for
        # it" ask; now wired.
        self.info = QtWidgets.QLabel("")
        self.info.setObjectName("info")
        self.info.setMinimumHeight(28)
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        self.setFixedWidth(220)  # keep the HUD's width; height grows to
        # fit however many selected Reads have something to report
        self._refresh_info()  # show current-selection status immediately on open

    def resizeEvent(self, event):
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(self.rect()), 12, 12)
        self.setMask(QtGui.QRegion(path.toFillPolygon().toPolygon()))
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        path = QtGui.QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)
        painter.fillPath(path, QtGui.QColor(25, 25, 28, 255))
        painter.setPen(QtGui.QColor(255, 255, 255, 40))
        painter.drawPath(path)
        super().paintEvent(event)

    def show_near_cursor(self):
        pos = QtGui.QCursor.pos()
        self.move(pos.x() - self.width() // 2, pos.y() - self.height() - 10)
        self.show()
        self.raise_()
        self.activateWindow()
        # focusOutEvent alone isn't reliable here: this is a Qt.Tool
        # widget, and clicking the DAG (part of the same main-window focus
        # chain) doesn't reliably fire a focus-out on us the way a normal
        # top-level window losing activation would -- this HUD stayed open
        # after clicking away, confirmed by Sashok. An app-wide mouse
        # event filter, closing on any press outside our own rect, works
        # regardless of Nuke's/RDP's focus quirks (this file already has a
        # history of exactly that kind of quirk -- see the WA_Translucent-
        # Background and NoFocus-button comments above).
        QtWidgets.QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.MouseButtonPress:
            try:
                global_pos = event.globalPosition().toPoint()  # Qt6/PySide6
            except AttributeError:
                global_pos = event.globalPos()  # Qt5/PySide2
            if not self.geometry().contains(global_pos):
                self.hide()
        return super().eventFilter(obj, event)

    def focusOutEvent(self, event):
        self.hide()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def _on_bump_clicked(self, direction):
        bump_selected_reads(direction)
        self._refresh_info()

    def _on_history_toggled(self, checked):
        _set_history_enabled(checked)
        self._refresh_info()

    def _refresh_info(self):
        """Recompute + display status for the current Nuke selection (same
        selectedNodes()->Read filter bump_selected_reads uses). Runs on
        HUD open and again after every button click, so this never shows
        a stale snapshot from before the last bump. Full per-node detail
        always goes to the Script Editor too -- same convention
        bump_selected_reads already uses -- this label stays compact
        since the HUD is only 220px wide."""
        # Same working-set + "live only" logic as bump_selected_reads --
        # falls back to nodes-in-view when nothing's selected, and a
        # selected/visible history Read (no downstream connections) isn't
        # something this HUD manages, so it shouldn't show up as "needs
        # attention" either.
        reads = [n for n in _working_read_nodes() if _is_live_read(n)]
        if not reads:
            self.info.setStyleSheet("")  # neutral -- falls back to the #info QSS
            self.info.setText("No live Read selected")
            self._resize_to_content()
            return

        # Short tags only in the label -- full detail (latest version,
        # exact missing-frame count, exact range) still goes to the
        # Script Editor, same split bump_selected_reads already uses.
        # Keeps the HUD itself scannable at a glance instead of a wall of
        # text.
        lines = []
        for read in reads:
            status = _read_status(read)
            if status is None:
                continue
            tags = []
            if status["outdated"]:
                tags.append("outdated")
            if status["missing"]:
                tags.append("gaps")
            if status["incomplete"]:
                tags.append("short range")
            if tags:
                lines.append(f"{read.name()}: {', '.join(tags)}")
                r0, r1 = status["root_range"]
                print(f"_VersionHUD: {read.name()} ({status['pass_name']}, "
                      f"{status['current_version']}) -- outdated={status['outdated']} "
                      f"(latest {status['latest_version']}), missing={status['missing']}, "
                      f"range={status['seq']['first']}-{status['seq']['last']} vs shot {r0}-{r1}")

        if not lines:
            self.info.setStyleSheet("color: #57C25E;")  # green -- all clear
            self.info.setText("OK")
        else:
            self.info.setStyleSheet("color: #E2554A;")  # red -- needs attention
            shown = lines[:4]
            more = "\n..." if len(lines) > 4 else ""
            self.info.setText("\n".join(shown) + more)
        self._resize_to_content()

    def _resize_to_content(self):
        self.info.adjustSize()
        self.adjustSize()


def show_version_hud():
    """Triggered by the Nuke-side hotkey (see register_menu). Stays open
    after a button click (unlike show_layer_picker) so +/- can be pressed
    repeatedly to step through versions -- closes on Esc or a click
    anywhere outside the HUD itself (see eventFilter above)."""
    global _version_hud
    _version_hud = _VersionHUD()
    _version_hud.show_near_cursor()


# ---- MCP server control HUD ---------------------------------------------
# Start/Restart/Stop, rebuilt on 2026-08-07 on top of a minimal single-
# button version that isolated the real click bug: QPushButton's default
# focus policy takes keyboard focus on click, show_near_cursor() below
# puts focus on `self` (the top-level widget, nothing else to hold it) --
# so a click transferred focus from self to the button, firing
# self.focusOutEvent() -> self.hide() mid-click, before mouseReleaseEvent
# could complete the button's press-release gesture. clicked() never got
# emitted; the window was already gone by the time the release happened.
# Every button below sets NoFocus to stop that. (Red herring ruled out
# along the way: WA_TranslucentBackground/layered-window RDP hit-testing
# -- that was never the actual problem, though the setMask() rounded-
# corner approach it left behind is harmless and stays.)
#
# _mcp_hud used to be deliberately reload-safe (`if '_mcp_hud' not in
# globals()`) so toggle_mcp_hud() could tell whether the HUD was still
# visible from the *previous* press and close it on a second press. That
# backfired during active iteration: since every hotkey press reloads this
# module first, the surviving _mcp_hud kept pointing at the OLD widget
# instance built by the OLD __init__ -- reload() replaces the code in the
# module namespace, but an already-constructed object doesn't get rebuilt,
# so the stale Start/Restart/Stop layout kept showing no matter how many
# times the file was redeployed and reloaded. Simpler and matches `_hud`
# above now: always build a fresh instance. Costs the press-to-close
# toggle (Esc still closes) but guarantees the latest code is what's on
# screen.

_mcp_hud = None


class _McpHud(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)

        self.setStyleSheet("""
            QPushButton {
                background-color: rgba(70, 130, 220, 210);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 18px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover { background-color: rgba(90, 150, 240, 230); }
            QPushButton:pressed { background-color: rgba(50, 100, 180, 230); }
            #stopBtn { background-color: rgba(210, 80, 70, 210); }
            #stopBtn:hover { background-color: rgba(230, 100, 90, 230); }
            #stopBtn:pressed { background-color: rgba(180, 60, 50, 230); }
            #status { color: rgba(150, 220, 150, 230); font-size: 10px; }
        """)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        start_btn = QtWidgets.QPushButton("Start")
        start_btn.setFocusPolicy(QtCore.Qt.NoFocus)
        start_btn.clicked.connect(self._do_start)
        layout.addWidget(start_btn)

        restart_btn = QtWidgets.QPushButton("Restart")
        restart_btn.setFocusPolicy(QtCore.Qt.NoFocus)
        restart_btn.clicked.connect(self._do_restart)
        layout.addWidget(restart_btn)

        stop_btn = QtWidgets.QPushButton("Stop")
        stop_btn.setObjectName("stopBtn")
        stop_btn.setFocusPolicy(QtCore.Qt.NoFocus)
        stop_btn.clicked.connect(self._do_stop)
        layout.addWidget(stop_btn)

        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("status")
        self.status.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.status)

        self.resize(140, 150)

    def resizeEvent(self, event):
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(self.rect()), 12, 12)
        self.setMask(QtGui.QRegion(path.toFillPolygon().toPolygon()))
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        path = QtGui.QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)
        painter.fillPath(path, QtGui.QColor(25, 25, 28, 255))
        painter.setPen(QtGui.QColor(255, 255, 255, 40))
        painter.drawPath(path)
        super().paintEvent(event)

    def _do_start(self):
        already = _server_thread is not None and _server_thread.is_alive()
        start_server()
        self._flash("already running" if already else "started ✓")

    def _do_restart(self):
        stop_server()
        start_server()
        self._flash("restarted ✓")

    def _do_stop(self):
        was_running = _server_thread is not None and _server_thread.is_alive()
        stop_server()
        self._flash("stopped ✓" if was_running else "was not running")

    def _flash(self, text):
        """Immediate feedback right on the HUD -- doesn't depend on the
        Script Editor being visible or on background-thread prints landing
        (see the executeInMainThreadWithResult note in _serve())."""
        self.status.setText(text)
        QtCore.QTimer.singleShot(700, self.hide)

    def show_near_cursor(self):
        pos = QtGui.QCursor.pos()
        # Centered on the cursor in both axes -- with Start/Restart/Stop
        # stacked in that order, this puts Restart (the middle button)
        # closest to the cursor's actual position.
        self.move(pos.x() - self.width() // 2, pos.y() - self.height() // 2)
        self.status.setText("")
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def focusOutEvent(self, event):
        self.hide()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        # Keyboard fallback, kept alongside the now-working mouse path --
        # Up = Start (above cursor), Down = Stop (below), Enter/Space =
        # Restart (the one at the cursor).
        key = event.key()
        if key == QtCore.Qt.Key_Escape:
            self.hide()
        elif key == QtCore.Qt.Key_Up:
            self._do_start()
        elif key == QtCore.Qt.Key_Down:
            self._do_stop()
        elif key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Space):
            self._do_restart()
        else:
            super().keyPressEvent(event)


def show_mcp_hud():
    """Always builds a fresh _McpHud -- see the comment above _mcp_hud for
    why reusing an instance across reloads was actively harmful during
    iteration."""
    global _mcp_hud
    _mcp_hud = _McpHud()
    _mcp_hud.show_near_cursor()


def toggle_mcp_hud():
    """Named for the menu/hotkey wiring (register_menu() calls this by
    name) -- no longer an actual open/close toggle, see show_mcp_hud()."""
    show_mcp_hud()


# ---- socket server ----------------------------------------------------

def _handle_client(conn, addr):
    if ALLOWED_CLIENTS and addr[0] not in ALLOWED_CLIENTS:
        conn.close()
        return

    with conn:
        buf = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
            if b"\n" not in buf:
                continue
            line, buf = buf.split(b"\n", 1)
            if not line.strip():
                continue

            cmd_type = None
            payload = {}
            try:
                req = json.loads(line.decode("utf-8"))
                cmd_type = req.get("type")
                payload = req.get("payload", {})

                if not _is_allowed(cmd_type, payload):
                    resp = {"ok": False, "error": "not allowed"}
                else:
                    handler = DISPATCH.get(cmd_type)
                    if handler is None:
                        resp = {"ok": False, "error": f"unknown command: {cmd_type}"}
                    else:
                        try:
                            result = nuke.executeInMainThreadWithResult(handler, payload)
                            resp = {"ok": True, **result}
                        except Exception as handler_exc:
                            resp = {"ok": False, "error": str(handler_exc)}
            except Exception as e:
                resp = {"ok": False, "error": str(e)}

            ts = datetime.datetime.now().strftime("%H:%M:%S")
            outcome = "ok" if resp.get("ok") else f"ERROR: {resp.get('error')}"
            log_line = f"[nuke-mcp {ts}] {addr[0]} -> {cmd_type}({_summarize_payload(payload)}) -> {outcome}"
            try:
                nuke.executeInMainThreadWithResult(_print_to_editor, (log_line,))
            except Exception:
                pass  # printing must never break the response path
            _audit(cmd_type, payload, resp.get("ok", False))

            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))


def _serve():
    global _server_socket
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(5)
    _server_socket = srv
    # print() from this background thread doesn't reach the Script Editor --
    # only the main thread's stdout is captured there (see _handle_client's
    # use of the same executeInMainThreadWithResult(_print_to_editor, ...)
    # trick for the same reason).
    nuke.executeInMainThreadWithResult(_print_to_editor, (f"nuke-mcp listening on {HOST}:{PORT}",))
    try:
        while True:
            try:
                conn, addr = srv.accept()
            except OSError:
                if _stop_requested.is_set():
                    # stop_server() closed srv on purpose to unblock accept()
                    # -- not an error, exit quietly.
                    break
                raise
            threading.Thread(target=_handle_client, args=(conn, addr), daemon=True).start()
    finally:
        _server_socket = None
        nuke.executeInMainThreadWithResult(_print_to_editor, ("nuke-mcp server stopped",))


# Reload-safe: importlib.reload() re-runs this module's top level in place,
# so a plain `_server_thread = None` here would sever the reference to a
# LIVE server thread/socket every time the module gets reloaded (which
# happens on every hotkey/menu press, per the dev-loop pattern above) --
# not just when Stop is actually clicked. Guard against re-init so reload
# only picks up new function/class code, never wipes live server state.
if '_server_thread' not in globals():
    _server_thread = None
if '_server_socket' not in globals():
    _server_socket = None
if '_stop_requested' not in globals():
    _stop_requested = threading.Event()


def start_server():
    global _server_thread
    if _server_thread and _server_thread.is_alive():
        print("nuke-mcp already running")
        return
    _stop_requested.clear()
    _server_thread = threading.Thread(target=_serve, daemon=True)
    _server_thread.start()


def stop_server():
    global _server_thread
    if not (_server_thread and _server_thread.is_alive()):
        print("nuke-mcp not running")
        return
    _stop_requested.set()
    if _server_socket is not None:
        try:
            _server_socket.close()
        except OSError:
            pass
    _server_thread.join(timeout=2.0)
    if _server_thread.is_alive():
        print("nuke-mcp: server thread did not stop within 2s")
    _server_thread = None
