#!/usr/bin/env bash
# Deploy plugin/server.py to pc137 with timestamped backup.
# Usage: ./scripts/deploy_plugin.sh
# Requires: ssh pc137 alias configured, VPN up.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_PLUGIN="$REPO_ROOT/plugin/server.py"
REMOTE_DIR='C:/Users/Admin/Documents/houdini21.0/scripts/python/houdinimcp'
REMOTE_PLUGIN="$REMOTE_DIR/server.py"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_NAME="server.py.bak_$STAMP"

if [ ! -f "$LOCAL_PLUGIN" ]; then
  echo "ERROR: local plugin not found at $LOCAL_PLUGIN" >&2
  exit 1
fi

echo "==> Reachability check"
ssh -o BatchMode=yes -o ConnectTimeout=5 pc137 'echo ok' >/dev/null || {
  echo "ERROR: cannot reach pc137. VPN up? ssh config correct?" >&2
  exit 1
}

echo "==> Backup current plugin -> $BACKUP_NAME"
ssh pc137 "powershell -Command \"Copy-Item '$REMOTE_PLUGIN' '$REMOTE_DIR/$BACKUP_NAME'\""

echo "==> SCP local plugin -> pc137"
scp "$LOCAL_PLUGIN" "pc137:$REMOTE_PLUGIN"

echo "==> Done."
echo
echo "Next steps on pc137 (RDP):"
echo "  1. Click the 'Stop MCP' shelf button (or run houdinimcp.stop_server() in Python Shell)"
echo "  2. Close the Houdini instance that was serving MCP"
echo "  3. Reopen Houdini, load sandbox scene, in Python Shell run:"
echo "       import houdinimcp"
echo "       houdinimcp.start_server(host='0.0.0.0')"
echo
echo "  Then restart Claude Desktop locally so the bridge picks up any new tools."
