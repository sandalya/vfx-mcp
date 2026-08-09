"""
server.py — transport plus dispatch over commands.REGISTRY.

Socket accept loop, PySide6 QTimer main-thread pump, IP allowlist, and the
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

from PySide6 import QtCore

from .commands import REGISTRY

PORT = 9878

# Same allowlist as the old plugin (port 9876) -- this machine's own VPN
# address plus loopback. Widen here (and there) together if the VPN
# address ever changes.
ALLOWED_CLIENTS = {"127.0.0.1", "10.10.11.41", "10.10.11.31"}

# Shared audit log with the old plugin (see houdini/docs/HOUDINI_MCP_REWRITE_PLAN.md
# section 5) -- a hardcoded constant, not os.path.expanduser, so this file
# never needs `import os`.
AUDIT_LOG_PATH = "C:/Users/Admin/houdini_mcp_audit.log"


def _audit(line):
    try:
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {line}\n")
    except Exception:
        pass  # audit logging must never break a command


class HmcpServer:
    def __init__(self, host="0.0.0.0", port=PORT):
        self.host = host
        self.port = port
        self.running = False
        self.socket = None
        self.client = None
        self.buffer = b""
        self.timer = None

    def start(self):
        """Begin listening; sets up a QTimer to poll for data on the main thread."""
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

            self.timer = QtCore.QTimer()
            self.timer.timeout.connect(self._process_server)
            self.timer.start(100)

            print(f"hmcp server started on {self.host}:{self.port}")
        except Exception as e:
            print(f"Failed to start hmcp server: {e}")
            self.stop()

    def stop(self):
        self.running = False
        if self.timer:
            self.timer.stop()
            self.timer = None
        if self.socket:
            self.socket.close()
        if self.client:
            self.client.close()
        self.socket = None
        self.client = None
        print("hmcp server stopped")

    def _process_server(self):
        if not self.running:
            return

        try:
            if not self.client and self.socket:
                try:
                    self.client, address = self.socket.accept()
                    if address[0] not in ALLOWED_CLIENTS:
                        _audit(f"BLOCKED_IP: {address[0]}:{address[1]}")
                        print(f"BLOCKED connection from {address}")
                        self.client.close()
                        self.client = None
                    else:
                        self.client.setblocking(False)
                        print(f"Connected to client: {address}")
                except BlockingIOError:
                    pass
                except Exception as e:
                    print(f"Error accepting connection: {e}")

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
                        print("Client disconnected")
                        self.client.close()
                        self.client = None
                        self.buffer = b""
                except BlockingIOError:
                    pass
                except Exception as e:
                    print(f"Error receiving data: {e}")
                    self.client.close()
                    self.client = None
                    self.buffer = b""

        except Exception as e:
            print(f"Server error: {e}")

    def execute_command(self, command):
        try:
            return self._execute_command_internal(command)
        except Exception as e:
            traceback.print_exc()
            return {
                "status": "error",
                "message": str(e),
                "exception_type": type(e).__name__,
                "traceback": traceback.format_exc(),
            }

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
            return {"status": "error", "message": str(e), "exception_type": type(e).__name__}

        return {"status": "success", "result": result}
