import hou
from .server import HoudiniMCPServer

def start_server(host='127.0.0.1', port=9876):
    if not hasattr(hou.session, "houdinimcp_server") or hou.session.houdinimcp_server is None:
        hou.session.houdinimcp_server = HoudiniMCPServer(host=host, port=port)
        hou.session.houdinimcp_server.start()
    else:
        print("Houdini MCP Server is already running.")

def stop_server():
    if hasattr(hou.session, "houdinimcp_server") and hou.session.houdinimcp_server:
        hou.session.houdinimcp_server.stop()
        hou.session.houdinimcp_server = None
    else:
        print("Houdini MCP Server is not running.")

def initialize_session():
    """Set up default session toggles (does NOT auto-start server)."""
    if not hasattr(hou.session, "houdinimcp_use_assetlib"):
        hou.session.houdinimcp_use_assetlib = False

initialize_session()