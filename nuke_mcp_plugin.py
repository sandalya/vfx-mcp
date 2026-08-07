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
import socket
import threading
import datetime
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


def cmd_get_nodes_in_view(payload):
    """
    Which nodes currently fall inside the visible area of the Node Graph
    panel -- unlike cmd_list_nodes, which returns every node regardless of
    pan/zoom. Nuke has no built-in "is this node on screen" API, so this
    reconstructs the viewport rect from nuke.center()/nuke.zoom() (DAG
    pan/zoom, in world units) and the pixel size of the DAG's Qt widget,
    then checks each node's bounding box against that rect.

    Caveat: if multiple Node Graph panels/tabs are open, this grabs the
    first "DAG_Window" Qt widget found -- not necessarily the one the user
    is looking at.
    """
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


DISPATCH = {
    "ping": cmd_ping,
    "print": cmd_print,
    "get_script_info": cmd_get_script_info,
    "list_nodes": cmd_list_nodes,
    "get_nodes_in_view": cmd_get_nodes_in_view,
    "get_selected_nodes": cmd_get_selected_nodes,
    "get_env": cmd_get_env,
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
        "ctrl+shift+a",
    )

    if menu.findItem(MCP_MENU_PATH):
        menu.removeItem(MCP_MENU_PATH)
    menu.addCommand(
        MCP_MENU_PATH,
        "import importlib, nuke_mcp_plugin; importlib.reload(nuke_mcp_plugin); "
        "nuke_mcp_plugin.toggle_mcp_hud()",
        "ctrl+shift+t",
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
