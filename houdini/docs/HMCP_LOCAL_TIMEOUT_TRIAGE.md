# hmcp local-mode: server never responds (bridge_timeout)

## Setup

- Repo: `C:\Users\gamai\vfx-mcp`, machine SASHOKPC (this same machine runs both
  Claude Code and the local Houdini instance).
- Local connection mode added same day in commit `727ee20` ("hmcp: add local
  (no-VPN) connection mode alongside pc137/VPN") — **this is the first
  real end-to-end use of local mode**; it was never previously verified
  working.
- `HMCP_HOST=127.0.0.1` is set in `C:\Users\gamai\.claude.json` under
  `projects."C:/Users/gamai/vfx-mcp".mcpServers.houdini2.env` (confirmed
  present).
- Plugin: `houdini/plugin/hmcp/server.py` — `HmcpServer` binds
  `0.0.0.0:9878`, non-blocking listen socket, a `QtCore.QTimer` (100ms
  interval) drives `_process_server()`, which does one `accept()` (or
  `recv()` on an existing client) per tick. PySide2 on this machine
  (Houdini 20.5.278); PySide6 on pc137 (Houdini 21.0.596), where the same
  code (old plugin, port 9876) is reportedly proven/working.
- Bridge: `houdini/bridge/hmcp_bridge.py` — stdio MCP server, opens a plain
  TCP socket to `HMCP_HOST:9878`, `sendall()`s a JSON command, polls
  `recv()` with a 10s total timeout (`HmcpConnection.send_command`,
  line ~89-115). On timeout it disconnects and returns
  `{"origin": "bridge_timeout", ...}`.
- Manually started in Houdini's Python Shell each time via
  `import hmcp; hmcp.start_server()` (`houdini/plugin/hmcp/__init__.py`:
  `start_server()`/`stop_server()`, module-global `_server`).

## Symptom

Every single command (via the MCP tool `mcp__houdini2__get_scene_info`,
**and** via a raw Python socket script that bypasses the MCP bridge
entirely) behaves identically:

1. `socket.connect(("127.0.0.1", 9878))` succeeds instantly (<1ms).
2. `sendall(json command)` succeeds.
3. `recv()` **never returns anything** — times out after 10s (bridge) / 45s
   (raw test script), every time, no exceptions, no partial data.

Raw reproduction (bypasses bridge/MCP entirely, same result):

```python
import socket, json, time
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(45)
s.connect(("127.0.0.1", 9878))
s.sendall(json.dumps({"type": "get_scene_info", "params": {"max_nodes": 5}}).encode())
data = s.recv(8192)   # <-- always times out, no data, no error
```

### Server-side evidence (the key clue)

`netstat -ano | grep 9878` after every failed attempt shows the TCP
handshake **did** complete at the OS level:

```
TCP    0.0.0.0:9878        0.0.0.0:0            LISTENING    <houdini_pid>
TCP    127.0.0.1:9878      127.0.0.1:<ephemeral> CLOSE_WAIT  <houdini_pid>
TCP    127.0.0.1:<ephemeral> 127.0.0.1:9878      FIN_WAIT_2  <bridge_pid>
```

`CLOSE_WAIT` on the Houdini side only appears after a connection was fully
established and the peer (bridge, on its own timeout) sent FIN — i.e. the
kernel-level accept queue (`listen(5)` backlog) genuinely completed the
handshake.

**But Houdini's own console never prints anything from
`_process_server()`'s accept branch** — not `"Connected to client: ..."`,
not `"BLOCKED connection from ..."`, not `"Error accepting connection: ..."`
(server.py lines ~104-118). All three of those are the only possible
outcomes of the `self.socket.accept()` call once a connection is actually
queued — none of them fire. This means the QTimer-driven poll loop
appears to never actually execute `self.socket.accept()` successfully
while a connection is pending, even though the OS confirms one is queued.

## What's been ruled out

- **Bridge/MCP-layer bug** — ruled out; raw socket script bypassing the
  bridge entirely reproduces the identical symptom.
- **Wrong/stale Houdini instance** — there were briefly 4 `houdinifx.exe`
  processes running; user closed all but the one holding port 9878 (verified
  via `netstat`/`tasklist` PID match). No change.
- **Stale `HmcpServer` Python object** — `hmcp.stop_server()` +
  `hmcp.start_server()` (fresh socket, fresh `QTimer`) run multiple times.
  No change.
- **Whole-process corruption** — user fully closed and reopened Houdini
  (new PID), reran `import hmcp; hmcp.start_server()` from a clean Python
  Shell. No change.
- **IP allowlist mismatch** (`ALLOWED_CLIENTS = {"127.0.0.1", "10.10.11.41",
  "10.10.11.31"}` in server.py) — connecting from 127.0.0.1 to 127.0.0.1
  should trivially match, and this would print `"BLOCKED connection
  from ..."` if it were the issue — that print never appears either, so
  the code isn't even reaching that check.
- **Multi-monitor DPI `OverflowError` storm** — a *real*, separate bug was
  found and is worth fixing on its own (see below), but it is **not** the
  cause of this hang: user dragged the Houdini window fully onto one
  monitor, confirmed the error spam stopped completely (quiet console),
  then did a fresh `stop_server()`/`start_server()` with the console
  silent throughout — `bridge_timeout` still happens, identically, with
  still zero accept-related console output.

## Real (separate) bug found along the way

Houdini's main window intermittently floods the console with:

```
File ".../houpythonportion/qt/ViewerOverlay.py", line 204, in _moveRelativeToParent
    self._new_parent_origin.setX(x+delta_x)
OverflowError
```
(`libshiboken: Overflow: Value -21474848xx exceeds limits of type [signed] "int"`)

Triggered continuously (not from deliberate dragging) while the Houdini
window straddles two monitors with different Windows display-scaling
percentages — classic Qt/PySide2 mixed-DPI coordinate math bug in the
native viewport window-container tracking code. Confirmed fixed (spam
stops) by moving the Houdini window fully onto one monitor. Worth a
permanent fix later (align monitor scaling, or launch Houdini with
`QT_SCALE_FACTOR_ROUNDING_POLICY=PassThrough` / `QT_ENABLE_HIGHDPI_SCALING=0`)
but is a red herring for the hmcp hang itself.

## Open question / suggested next diagnostic (not yet done)

Never actually isolated whether the `QTimer` is failing to *tick at all*,
vs. ticking but `_process_server()` silently failing before any print
executes. Proposed test (started to set up, conversation moved on before
finishing it):

1. Start a raw socket connection with a long timeout (so it sits pending)
   against `127.0.0.1:9878`.
2. While it's pending, from Houdini's Python Shell run:
   ```python
   hmcp._server.timer.isActive()   # does the QTimer even think it's running?
   hmcp._server.running            # sanity check
   hmcp._server._process_server()  # manually force one tick
   ```
3. If the manual call to `_process_server()` makes `"Connected to
   client: ..."` print and the pending socket actually receives a
   response — the bug is specifically that the `QTimer` isn't
   auto-ticking in this Houdini/PySide2 session (scheduling problem).
4. If the manual call *also* hangs/fails silently — the bug is inside
   `_process_server()`/`execute_command()` itself, not the timer.

Also untested: whether `self.socket.setblocking(False)` +
`self.socket.accept()` behaves as expected on this specific
Windows/Python/PySide2 build — worth trying `self.socket.settimeout(0)`
explicitly instead of relying on `setblocking(False)`'s interaction with
a `QTimer`-polled loop, in case there's a subtle non-blocking-socket
semantics issue specific to this environment.

## Files involved

- `houdini/plugin/hmcp/server.py` — the poll loop (`_process_server`,
  lines ~99-146) and `start()` (lines ~60-84).
- `houdini/plugin/hmcp/__init__.py` — `start_server()` / `stop_server()`.
- `houdini/bridge/hmcp_bridge.py` — `HmcpConnection.send_command` (lines
  ~81-120), the 10s timeout and `bridge_timeout` origin.
- `README.md` (repo root), section "hmcp connection modes: pc137/VPN vs.
  local Houdini" — the mode-switching instructions this session followed.
