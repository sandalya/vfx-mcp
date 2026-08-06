#!/usr/bin/env python
"""
raw_ping_nuke.py

Minimal raw-socket smoke test for nuke_mcp_plugin.py -- no MCP wrapper,
no fastmcp. Sends a single {"type": "ping"} line and prints whatever comes
back. Same sequence used to debug the Houdini plugin's "actively refused"
issue: verify raw TCP works before layering the MCP bridge on top.
"""
import json
import socket
import sys

HOST = "10.10.10.31"
PORT = 9877

def main():
    print(f"Connecting to {HOST}:{PORT} ...")
    with socket.create_connection((HOST, PORT), timeout=10) as s:
        msg = json.dumps({"type": "ping"}) + "\n"
        print(f"Sending: {msg.strip()}")
        s.sendall(msg.encode("utf-8"))
        s.settimeout(10)
        data = b""
        while not data.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
        print(f"Received: {data.decode('utf-8', errors='replace').strip()}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
