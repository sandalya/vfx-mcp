# hmcp poll pump: why the server listened but never accepted

Resolved. Kept because the failure mode is silent, machine-specific, and
easy to reintroduce — anything that goes back to a bare `QTimer` for the
poll loop will break the same way with no error anywhere.

## Symptom (local mode, first end-to-end use after `727ee20`)

Every command — through the MCP bridge *and* through a raw socket script —
connected and sent fine, then got nothing back until the bridge's 10s
`bridge_timeout`. `netstat` showed the handshake completing at the OS level
(`CLOSE_WAIT` on the Houdini PID, `FIN_WAIT_2` on the client), so the
connection really was queued on Houdini's listening socket — Houdini just
never `accept()`ed it. No exception, no console output, survived full
Houdini restarts.

## Root cause

`HmcpServer.start()` drove `_process_server()` from a bare
`QtCore.QTimer`. A `QTimer` only ever fires if the thread that started it
runs a Qt event loop — and **Houdini's Python Shell pane does not run in the
main thread**, which is where `import hmcp; hmcp.start_server()` is typed.

Measured in the local Python Shell (Houdini 20.5.278, PySide2):

```
thread: Dummy-6 | main: MainThread
ticks: 0 | isActive: True
```

The timer reports itself active and never ticks once. Qt's complaint
(`QObject::startTimer: Timers can only be used with threads started with
QThread`) goes to the process's stderr, which a GUI Houdini on Windows
discards — hence total silence.

Two things made this much harder to see than it should have been:

- **`print()` from the poll callback never reaches the Python Shell pane.**
  The pane only captures stdout for the statement it is executing. "No
  console output from `_process_server`" was therefore evidence of nothing.
- **The audit log was writing nowhere.** `AUDIT_LOG_PATH` was hardcoded to
  `C:/Users/Admin/houdini_mcp_audit.log` — pc137's profile. That path does
  not exist on the local machine, and `_audit()` swallows every exception, so
  local mode ran with no trail at all.

pc137 was never affected in practice because the old plugin there is started
from the `Start MCP` shelf button, which runs on the main thread.

## Fix

`houdini/plugin/hmcp/server.py`:

- `_install_pump()` / `_remove_pump()` replace the inline timer setup.
  Primary pump is **`hou.ui.addEventLoopCallback(self._process_server)`** —
  Houdini's own main-thread idle pump, independent of which thread installs
  it. The `QTimer` path remains only as a fallback for non-graphical hython,
  where `hou.ui` does not exist.
- `self.ticks` counts every pump call, before the `running` check.
- The log path is resolved from `hou.homeHoudiniDirectory()` at first use
  (`hmcp_audit.log` under the Houdini prefs dir), so it is correct on any
  machine and any user. Server lifecycle events — start, accept, blocked IP,
  disconnect, errors — go through `_note()`, which writes to that log and
  prints best-effort.
- The blanket `except` in `_process_server()` now logs instead of printing:
  an exception escaping an event-loop callback makes Houdini drop the
  callback, which would silently deafen the server all over again.

`houdini/plugin/hmcp/__init__.py`: `status()` prints
`running / pump / ticks / client / address / log`.

## How to check liveness

In Houdini's Python Shell:

```python
import hmcp
hmcp.status()
```

Call it twice a few seconds apart. **`ticks` must climb.** If it doesn't, the
server is listening but deaf and nothing will ever be accepted — that is the
one number worth looking at. `pump=eventloop` is expected in GUI Houdini;
`pump=qtimer` in GUI Houdini means the fallback kicked in and the same
never-ticking bug is likely back.

Full round-trip check from outside Houdini: `./scripts/check_contract_local.sh`.

## Still open (unrelated)

Houdini's main window floods stderr with
`OverflowError` from `houpythonportion/qt/ViewerOverlay.py:204`
(`_moveRelativeToParent`) whenever the window straddles two monitors with
different Windows display-scaling percentages — a Qt/PySide2 mixed-DPI
coordinate bug. Confirmed *not* related to the hang above (the hang
reproduced identically with the window on one monitor and the console quiet).
Workarounds: align monitor scaling, or launch Houdini with
`QT_SCALE_FACTOR_ROUNDING_POLICY=PassThrough` / `QT_ENABLE_HIGHDPI_SCALING=0`.
