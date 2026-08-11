"""
hmcp — the new Houdini MCP plugin package (port 9878, read-only in Phase 1).

No auto-start on import, same rule as the old plugin: the owner opens
Houdini and calls start_server() by hand from the Python Shell. This
package must never start, stop, or otherwise touch Houdini's own
lifecycle beyond what a manual call requests.
"""

from .server import HmcpServer, _log_path

_server = None


def start_server(host="0.0.0.0", port=9878):
    global _server
    if _server is not None and _server.running:
        print("hmcp server already running.")
        return _server
    _server = HmcpServer(host=host, port=port)
    _server.start()
    return _server


def stop_server():
    global _server
    if _server is not None:
        _server.stop()
        _server = None
    else:
        print("hmcp server is not running.")


def status():
    """Print (and return) whether the poll pump is actually alive.

    `ticks` is the number that matters: call status() twice a few seconds
    apart and if it hasn't moved, the server is listening but deaf -- nothing
    is calling _process_server, so no connection will ever be accepted. That
    was the local-mode failure mode and it is otherwise invisible.
    """
    if _server is None:
        print("hmcp: no server object -- start_server() not called this session")
        return None

    info = {
        "running": _server.running,
        "pump": _server.pump,
        "ticks": _server.ticks,
        "client": _server.client is not None,
        "address": f"{_server.host}:{_server.port}",
        "log": _log_path(),
    }
    print("hmcp: " + "  ".join(f"{k}={v}" for k, v in info.items()))
    return info
