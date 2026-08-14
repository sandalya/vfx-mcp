# hmcp headless worker — plan

**Status: not started.** Deferred deliberately, not abandoned — this is the
actual destination of the render work, and the GUI render shipped in
2026-08-12 exists partly to de-risk it.

Audience: an implementing agent with no memory of the planning conversation.
Read `houdini/docs/HMCP_DESIGN.md` first — its §2 safety model and §3 hard
rules apply here unchanged and are not relitigated below. Measured API facts
live in `houdini/docs/HMCP_HOUDINI_NOTES.md`.

This document is the surviving Track B of a larger render plan whose Track A
(the GUI `render_snapshot`) shipped and was harvested into the two documents
above.

---

## 1. Why this exists

The owner's stated endgame: **a render that does not freeze the UI and does
not tie up the open scene.** The shipped GUI render gets partway there and no
further — `executebackground` still blocks Houdini's main thread for 6.5–16.6s
per call (measured, see `HMCP_HOUDINI_NOTES.md`), and every iteration still
occupies the owner's live session.

A headless `hython` worker is the real fix: its own process, its own scene, no
window, nothing of the owner's to disturb.

Two things in the shipped code exist for this and must not be compromised:
`render.py` stays `hou.ui`-free outside its `camera="viewport"` branch, and
`camera="fit"` is verified working.

---

## 2. Phase A — research probe. No shipped code.

A single throwaway script (`scripts/probe_headless.py`, explicitly **not**
part of the `hmcp` package and never deployed to the runtime package
directory), run as `hython.exe probe_headless.py`. Running hython is already
routine, but **it consumes a Houdini licence seat — ask the owner before
running it during working hours** (Q3 below).

Deliverable: findings written back into this document, plus a go/no-go.

What it must answer:

1. `hou.isUIAvailable()` is False and `hou.ui` is absent — confirm which code
   paths die.
2. `import hmcp` succeeds in bare hython with **no Qt available**. This is
   what motivates moving the PySide import out of `server.py`'s module scope.
3. **`hou.undos.group("x")` as a context manager: does it raise, or no-op?**
   This single answer decides whether every write handler needs a change.
4. `hou.playbar.frameRange()` and `nodeType.helpText()` work.
5. Load an existing sandbox scene, then run each GUI-independent handler by
   calling `commands.REGISTRY[name]["handler"]` directly, in-process — no
   sockets, no bridge. Record pass/fail per command.
6. **The decisive one:** build a Karma ROP by hand and call `.render()`. Does
   it work with no GUI? How long? Is the image black without lights? Does it
   survive an RDP-disconnected session?
7. Whether a headless Karma render spawns extra processes or consumes an
   additional licence seat.

**Phase A passes when** a rendered PNG exists on disk, produced by hython with
no Houdini window open anywhere on the machine, and Claude can Read and
describe it. **If that does not happen, Track B stops here** and the honest
answer to the owner is "headless is not viable for eyes on this setup."

---

## 3. Phase B — the worker

Only if Phase A is green.

### 3.1 Transport: a blocking loop, not the pump

New `houdini/plugin/hmcp/headless.py`:

- A plain blocking socket server on the process's **only** thread:
  `accept()` → `recv()` → dispatch → `sendall()` → loop. No `QTimer`, no
  `hou.ui`, no PySide import anywhere in the module. This deletes the entire
  class of bug in `HMCP_LOCAL_TIMEOUT_TRIAGE.md` — there is no event loop to
  share and no "listening but deaf" state to diagnose.
- **Reuse, don't duplicate.** Same `commands.REGISTRY`, same
  `ALLOWED_CLIENTS`, same JSON framing, same audit helpers. Refactor
  `server.py`'s `execute_command` / `_execute_command_internal` from methods
  into module-level functions that `HmcpServer` delegates to, so both
  transports dispatch through one reviewed path. That refactor is
  behaviour-preserving and should be **its own commit**, verified by
  `check_contract.py` before `headless.py` is added.
- **Port 9879**, not 9878, so a worker and a GUI Houdini can coexist without
  a silent bind conflict.
- Audit log `hmcp_headless_audit.log` — a distinct filename, so two
  concurrent processes never interleave into one file.
- The blocking `recv` needs a socket timeout so the loop can notice a stop
  request and log a heartbeat. Keep a `ticks`-equivalent counter and a
  `status` line so "is it alive" has the same one-number answer as
  `hmcp.status()`.

### 3.2 Session model: one persistent process, one open scene

Recommended without hesitation. A stateless open/save/close per call breaks
three things that already work:

1. **`delete_node` dies permanently.** `SessionRegistry` is keyed on
   `sessionId()`, and session ids do not survive a scene reload. Stateless
   means every call is a reload, so the agent could never delete its own
   work — it fails safe, but into uselessness.
2. **The bootstrap flow inverts.** `save_scene_as` is gated to never-saved
   scenes. That fits a persistent session perfectly (fresh worker → untitled
   scene → agent bootstraps → writes unlock). Stateless means every call
   after the first opens an already-saved scene, killing the bootstrap path.
3. **The way the tools are actually used** is dozens of small sequential
   calls, each reading live cook state from the previous. Stateless means a
   full load and re-cook per call — it destroys exactly the iteration loop
   that makes the toolset worth having.

**Durability gap this creates, and its fix.** A persistent worker's scene
lives in RAM and there is no owner at a keyboard to press Ctrl+S. Add
`save_checkpoint()` — no arguments, `require_sandbox_scene()` first,
`hou.hipFile.save(file_name=SANDBOX_ROOT + "mcp_" + ts + ".hip")`. Constant
directory, timestamped filename, never overwrites, never bare
`hou.hipFile.save()`. Cheap, and useful in GUI mode too.

**Second consequence, and the owner must be told explicitly rather than left
to assume otherwise: headless loses Ctrl+Z rollback.** `hou.undos.group()`
records nothing without a GUI. The remaining barriers are the ones the safety
model actually relies on — the sandbox boundary, no delete capability, no
output-path writes, no Python parms — plus `save_checkpoint`'s
never-overwriting history.

### 3.3 Lifecycle: who starts it

`houdini/CLAUDE.md`'s "never start/stop Houdini yourself" was written about
the interactive application, where starting it costs the owner their session,
their scene and their screen. A headless worker is a different animal. Do not
decide this by analogy — it is Q2 below.

Recommendation: **day one, owner-started and owner-stopped.** A
`houdini/scripts/hmcp_worker.cmd` the owner runs, Ctrl-C to stop. Same posture
as the shelf Start button — the owner remains the one who decides a licence
seat is in use.

This is not merely policy, it is enforced by construction: the `hmcp` package
cannot spawn a process without `import subprocess`, which the doctrine
forbids. **Any autostart must live outside the package** — a `.cmd`, a
Scheduled Task, a shortcut — never inside it. That constraint should survive
whatever the owner decides.

### 3.4 Eyes

Track A's `render_snapshot`, unchanged, with `camera="fit"` forced — there is
no viewport to save from, so the handler detects the absence of `hou.ui` and
refuses `camera="viewport"` with a message that says so, not an
`AttributeError`.

Karma does **not** auto-headlight (`force_headlight` defaults false). If Phase
A confirms headless renders come back black, the handler additionally creates
a plugin-owned light in `/obj` — reuse-or-create, registered in the session
registry — when the scene contains no light objects.

### 3.5 Deployment: no third target

**Do not add `deploy_plugin.sh hmcp-headless`.** The package deployed is
byte-identical; only the entry point differs, and a third target would
duplicate the backup + scp + py_compile + contract-check blocks for no gain.

- `headless.py` is picked up automatically by the existing `hmcp` and
  `hmcp-local` targets (they glob `*.py`).
- Add the launcher (`hmcp_worker.py` + `.cmd`) and two lines to each existing
  target to copy them, plus the same py_compile check.
- Bridge: add `PORT = int(os.environ.get("HMCP_PORT", 9878))` to
  `hmcp_bridge.py` and `check_contract.py`, so the identical bridge talks to
  GUI (9878) or headless (9879) by env var — matching the existing
  `HMCP_HOST` pattern exactly. To run both at once, register a second Claude
  Code MCP entry whose `env` pins `HMCP_PORT=9879`.

### Phase B — done when

1. `import hmcp` succeeds in bare hython with no Qt on the path;
   `grep -n "PySide" houdini/plugin/hmcp/` shows the import only inside
   `_install_pump`.
2. The worker starts from the launcher, prints its port and log path, and
   `HMCP_PORT=9879 scripts/check_contract.py` reports all commands agreeing.
3. A connection from a **non-allowlisted IP** is refused and logged.
4. From Claude Code with `HMCP_PORT=9879`: `save_scene_as` bootstraps the
   worker's untitled scene into the sandbox; every other write refuses before
   that point.
5. Every GUI-independent command round-trips through the real MCP path
   (extend `scripts/mcp_client_test_hmcp.py`).
6. `viewport_snapshot` refuses headless with a message naming the reason, not
   an `AttributeError` traceback.
7. `render_snapshot` produces a readable PNG with **no Houdini window open
   anywhere on the machine** — check Task Manager, not "I didn't see one."
8. `save_checkpoint()` twice produces two files and overwrites neither.
9. The worker survives a guard refusal, a malformed JSON payload, and a
   client disconnect mid-command without dying.
10. GUI Houdini on 9878 and the worker on 9879 run simultaneously without
    either misbehaving; the two audit logs are separate files.

---

## 4. Acceptance target

Mirror of the original Phase 3 rock, with the GUI removed: **from a cold
headless worker, Claude Code builds a procedural rock unattended —
`save_scene_as` → `sphere` → `mountain` → `attribwrangle` (VEX) → `smooth`,
reading geometry and errors after each step — then renders it with
`render_snapshot()`, reads the PNG, judges it, corrects itself, re-renders,
and `save_checkpoint()`s. The owner's Houdini is never opened.**

Passes when: the graph cooks clean; `get_geometry_info` returns sensible
counts and bbox; the render looks like a rock; the checkpoint `.hip` opens
correctly in interactive Houdini afterwards; and total wall-clock is
recorded.

Only after that passes is it worth discussing whether headless becomes the
default mode.

---

## 5. Open questions for the owner

**Q1 — Does a headless `hython` worker count as "Houdini" for
`houdini/CLAUDE.md`'s never-start-it rule?** Recommendation: owner-started
day one, because it consumes a licence seat and that should stay the owner's
decision. But if a Scheduled Task or an agent-restartable worker is preferred
once it is proven, say so before the launcher is designed.

**Q2 — Licences.** How many seats are there on pc137, and does a persistent
worker holding one interfere with the interactive session? If seats are
tight, the worker should be started per-task and stopped after — which
changes the session model's cost/benefit, though probably not its conclusion.

**Q3 — Which machine hosts the trial?** pc137 (Houdini 21, the real target,
but shared with the owner's work) or local (20.5, no VPN, faster iteration,
but a different build and it has HtoA where pc137 does not). Preference:
local for Phase A's probe, pc137 for Phase B's verification.

---

## 6. Explicitly not in this plan

- **A `shutdown_worker` or autostart command inside the plugin.** New
  capability class, no demonstrated need, and structurally impossible without
  breaking the no-`subprocess` rule.
- **Retiring `viewport_snapshot`.** It stays — faster, free, needs no lights,
  and it is the ground truth the ROP camera is matched against.
- **Getting the image off pc137.** Local mode returns a path Claude can Read
  directly; remote mode returns a path on another machine. A
  `scripts/fetch_render.sh` `scp` wrapper on the *bridge* side (where the
  no-`subprocess` doctrine does not apply) is the intended fix, deliberately
  unbuilt until remote mode is actually used. Documented as a known
  limitation in `README.md`. Inline base64 is permanently rejected.
- Everything on `HMCP_DESIGN.md`'s never-list.
