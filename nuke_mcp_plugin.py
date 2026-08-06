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


DISPATCH = {
    "ping": cmd_ping,
    "get_script_info": cmd_get_script_info,
    "list_nodes": cmd_list_nodes,
    "execute_code": cmd_execute_code,
}


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
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(5)
    print(f"nuke-mcp listening on {HOST}:{PORT}")
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=_handle_client, args=(conn, addr), daemon=True).start()


_server_thread = None


def start_server():
    global _server_thread
    if _server_thread and _server_thread.is_alive():
        print("nuke-mcp already running")
        return
    _server_thread = threading.Thread(target=_serve, daemon=True)
    _server_thread.start()
