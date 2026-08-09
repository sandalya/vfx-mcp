"""
hmcp — the new Houdini MCP plugin package (port 9878, read-only in Phase 1).

No auto-start on import, same rule as the old plugin: the owner opens
Houdini and calls start_server() by hand from the Python Shell. This
package must never start, stop, or otherwise touch Houdini's own
lifecycle beyond what a manual call requests.
"""

from .server import HmcpServer

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
