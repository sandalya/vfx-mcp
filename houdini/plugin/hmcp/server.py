"""
server.py — transport plus dispatch over commands.REGISTRY.

Socket accept loop, PySide QTimer main-thread pump, IP allowlist, and the
audit-log writer are ported deliberately from the old plugin
(houdini/plugin/server.py) -- that networking code is proven, this
rewrite only changes what commands exist and how they're dispatched.

Not ported: import_opus_url and any download/unzip helper, the
asset-library handlers, modify_node, execute_code, set_material,
quad-view / specific-camera renders. See guards.py's module docstring for
why (no import os/shutil/requests/subprocess/zipfile anywhere here).
"""

import json
import socket
import traceback
from datetime import datetime

try:
    from PySide6 import QtCore
except ImportError:
    # Houdini 20.5 (local machine) ships PySide2; 21.0 (pc137) ships PySide6.
    # QTimer's API is identical across both -- no behavior difference below.
    from PySide2 import QtCore

from .commands import REGISTRY

PORT = 9878

# Same allowlist as the old plugin (port 9876) -- this machine's own VPN
# address plus loopback. Widen here (and there) together if the VPN
# address ever changes.
ALLOWED_CLIENTS = {"127.0.0.1", "10.10.11.41", "10.10.11.31"}

# Audit + diagnostic log (see houdini/docs/HOUDINI_MCP_REWRITE_PLAN.md
# section 5). Resolved from Houdini's own prefs dir rather than hardcoded:
# the old constant was "C:/Users/Admin/houdini_mcp_audit.log" -- pc137's
# profile, which doesn't exist on the local machine, so every local write
# failed into _audit's swallow-everything except and local mode ran with no
# trail at all. hou.homeHoudiniDirectory() keeps this file free of
# `import os` and is correct on both machines.
_LOG_PATH = None


def _log_path():
    global _LOG_PATH
    if _LOG_PATH is None:
        try:
            import hou

            _LOG_PATH = hou.homeHoudiniDirectory() + "/hmcp_audit.log"
        except Exception:
            _LOG_PATH = "hmcp_audit.log"  # cwd; last resort, never raises
    return _LOG_PATH


def _audit(line):
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {line}\n")
    except Exception:
        pass  # audit logging must never break a command


def _add_hint(response, exc):
    """Copy an optional `.hint` attribute a handler attached to its raised
    exception into the response dict. Purely additive -- every existing
    key stays; `hint` is absent entirely when a handler didn't set one,
    rather than present as null, so old clients see no shape change."""
    hint = getattr(exc, "hint", None)
    if hint:
        response["hint"] = hint


def _note(line):
    """A server-lifecycle line: to the log always, to stdout best-effort.

    The log file is the one that counts. print() from inside the poll
    callback never reaches Houdini's Python Shell pane -- the pane only
    captures stdout for the statement it is executing -- which is why the
    original silent-accept bug looked like "no console output at all".
    """
    _audit(line)
    print(f"hmcp: {line}")


class HmcpServer:
    def __init__(self, host="0.0.0.0", port=PORT):
        self.host = host
        self.port = port
        self.running = False
        self.socket = None
        self.client = None
        self.buffer = b""
        self.timer = None
        self.pump = None
        self.ticks = 0
        self._pump_cb = None

    def start(self):
        """Begin listening; installs a main-thread pump to poll for data."""
        self.running = True
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.socket.bind((self.host, self.port))
            # Backlog 5, not 1: a single stuck/slow-to-accept connection
            # (the QTimer only accepts one per 100ms tick) would otherwise
            # fill the queue and get every subsequent connection attempt
            # refused at the OS level -- observed live during Phase 1
            # verification when several diagnostic connections landed close
            # together.
            self.socket.listen(5)
            self.socket.setblocking(False)

            self._install_pump()

            _note(
                f"started on {self.host}:{self.port} "
                f"pump={self.pump} log={_log_path()}"
            )
        except Exception as e:
            _note(f"failed to start: {e}")
            self.stop()

    def _install_pump(self):
        """Drive _process_server from Houdini's main thread.

        hou.ui.addEventLoopCallback is primary because it is independent of
        the thread that calls it. A bare QTimer is not: it only ever fires if
        the thread that started it runs a Qt event loop, and the Python Shell
        pane -- where start_server() is typed -- does not. That is exactly why
        local mode bound the port, let the OS complete the handshake, and then
        never accept()ed anything, silently, forever. See
        houdini/docs/HMCP_LOCAL_TIMEOUT_TRIAGE.md.

        The QTimer path stays as a fallback for non-graphical hython, where
        hou.ui does not exist at all.
        """
        self._pump_cb = self._process_server  # one stable object to remove later
        try:
            import hou

            hou.ui.addEventLoopCallback(self._pump_cb)
            self.pump = "eventloop"
            return
        except Exception as e:
            _note(f"addEventLoopCallback unavailable ({e}); falling back to QTimer")

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._pump_cb)
        self.timer.start(100)
        self.pump = "qtimer"

    def _remove_pump(self):
        if self.pump == "eventloop" and self._pump_cb is not None:
            try:
                import hou

                hou.ui.removeEventLoopCallback(self._pump_cb)
            except Exception as e:
                _note(f"removeEventLoopCallback failed: {e}")
        if self.timer:
            self.timer.stop()
            self.timer = None
        self.pump = None
        self._pump_cb = None

    def stop(self):
        self.running = False
        self._remove_pump()
        if self.socket:
            self.socket.close()
        if self.client:
            self.client.close()
        self.socket = None
        self.client = None
        _note("stopped")

    def _process_server(self):
        # Counted before the running check so status() can tell "the pump is
        # alive but the server is off" apart from "the pump never fires".
        self.ticks += 1

        if not self.running:
            return

        try:
            if not self.client and self.socket:
                try:
                    self.client, address = self.socket.accept()
                    if address[0] not in ALLOWED_CLIENTS:
                        _audit(f"BLOCKED_IP: {address[0]}:{address[1]}")
                        _note(f"BLOCKED connection from {address}")
                        self.client.close()
                        self.client = None
                    else:
                        self.client.setblocking(False)
                        _note(f"client connected: {address}")
                except BlockingIOError:
                    pass
                except Exception as e:
                    _note(f"error accepting connection: {e}")

            if self.client:
                try:
                    data = self.client.recv(8192)
                    if data:
                        self.buffer += data
                        try:
                            command = json.loads(self.buffer.decode("utf-8"))
                            self.buffer = b""
                            response = self.execute_command(command)
                            self.client.sendall(json.dumps(response).encode("utf-8"))
                        except json.JSONDecodeError:
                            pass  # incomplete data; keep appending
                    else:
                        _note("client disconnected")
                        self.client.close()
                        self.client = None
                        self.buffer = b""
                except BlockingIOError:
                    pass
                except Exception as e:
                    _note(f"error receiving data: {e}")
                    self.client.close()
                    self.client = None
                    self.buffer = b""

        except Exception as e:
            # Must never propagate: an exception out of an event-loop callback
            # makes Houdini pop a dialog and drop the callback -- i.e. the
            # server would go deaf again, the very failure this file just fixed.
            _note(f"server error: {e} | {traceback.format_exc(limit=3)}")

    def execute_command(self, command):
        try:
            return self._execute_command_internal(command)
        except Exception as e:
            tb = traceback.format_exc()
            # Previously only reached the response, never the log -- a
            # failure was diagnosable only by asking Sashok to copy it out
            # of Houdini's Python Shell. Now it's in hmcp_audit.log too.
            _audit(f"ERROR {command.get('type')}: {e}\n{tb}")
            traceback.print_exc()
            response = {
                "status": "error",
                "message": str(e),
                "exception_type": type(e).__name__,
                "traceback": tb,
            }
            _add_hint(response, e)
            return response

    def _execute_command_internal(self, command):
        cmd_type = command.get("type")
        params = command.get("params", {})

        _audit(f"{cmd_type} {json.dumps(params, default=str)[:500]}")

        entry = REGISTRY.get(cmd_type)
        if not entry:
            _audit(f"REFUSED unknown_command: {cmd_type}")
            return {"status": "error", "message": f"Unknown command type: {cmd_type}"}

        try:
            result = entry["handler"](**params)
        except (PermissionError, ValueError) as e:
            # Guard refusals -- expected, not a bug. Logged distinctly from
            # unhandled exceptions so the audit log can tell "the agent
            # tried something disallowed" apart from "something broke".
            _audit(f"REFUSED {cmd_type}: {e}")
            response = {"status": "error", "message": str(e), "exception_type": type(e).__name__}
            _add_hint(response, e)
            return response

        return {"status": "success", "result": result}
