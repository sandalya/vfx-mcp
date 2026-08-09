#!/usr/bin/env python
"""
check_contract.py

Connects to the running hmcp plugin (port 9878), calls the read-only
`describe_commands` command, and diffs the live plugin's command list
against houdini/commands_spec.py -- the single source of truth also used
by the bridge (houdini/bridge/hmcp_bridge.py) and the plugin's own
dispatcher (houdini/plugin/hmcp/commands.py).

This exists to catch drift from *outside* both processes: the bridge and
plugin each assert against commands_spec.py at their own import time, but
only this script proves the three actually agree once the deployed code
is live on pc137. Run after every hmcp deploy (called from
scripts/deploy_plugin.sh).

Exit code 0 = match, 1 = mismatch or plugin unreachable.
"""
import json
import os
import socket
import sys

HOST = "10.10.10.31"
PORT = 9878
TIMEOUT = 10

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(repo_root, "houdini"))
import commands_spec


def describe_commands():
    with socket.create_connection((HOST, PORT), timeout=TIMEOUT) as s:
        s.sendall(json.dumps({"type": "describe_commands", "params": {}}).encode("utf-8"))
        s.settimeout(TIMEOUT)
        buffer = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                raise ConnectionAbortedError("Connection closed before a full response arrived.")
            buffer += chunk
            try:
                return json.loads(buffer.decode("utf-8"))
            except json.JSONDecodeError:
                continue


def main():
    print(f"Connecting to hmcp at {HOST}:{PORT} ...")
    try:
        response = describe_commands()
    except Exception as e:
        print(f"FAILED to reach hmcp plugin: {type(e).__name__}: {e}", file=sys.stderr)
        print("(Is Houdini running with a sandbox scene open and hmcp.start_server() called?)")
        return 1

    if response.get("status") != "success":
        print(f"FAILED: plugin returned an error: {response}", file=sys.stderr)
        return 1

    live_commands = {c["name"] for c in response["result"]["commands"]}
    spec_commands = commands_spec.COMMAND_NAMES

    missing_on_plugin = spec_commands - live_commands
    extra_on_plugin = live_commands - spec_commands

    if not missing_on_plugin and not extra_on_plugin:
        print(f"OK: plugin and commands_spec.py agree on {len(spec_commands)} commands.")
        return 0

    if missing_on_plugin:
        print(f"MISMATCH: declared in commands_spec.py but not live on the plugin: {sorted(missing_on_plugin)}", file=sys.stderr)
    if extra_on_plugin:
        print(f"MISMATCH: live on the plugin but not declared in commands_spec.py: {sorted(extra_on_plugin)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
