# hmcp — design, doctrine and decision log

**Read this before touching anything under `houdini/plugin/hmcp/`.**

This is a *current-state* document, not a plan. It says what the package is,
which rules its code must obey, and which decisions are settled and must not
be relitigated. When behaviour changes, this file is edited in place.

Companion documents:

- `HMCP_HOUDINI_NOTES.md` — measured HOM API facts and failure modes that
  were expensive to learn and are easy to get wrong again
- `HMCP_LOCAL_TIMEOUT_TRIAGE.md` — why the poll pump is an event-loop
  callback and not a `QTimer`
- `plans/` — work not yet built. A non-empty `plans/` means open work.

---

## 1. What hmcp is

A Houdini plugin package (`houdini/plugin/hmcp/`) that runs inside the
owner's Houdini process, listening on a raw socket on **port 9878**, driven
by a thin MCP bridge (`houdini/bridge/hmcp_bridge.py`) that Claude Code talks
to as the `houdini2` MCP server.

**35 commands** — 12 read, 23 write. `houdini/commands_spec.py` is the single
declaration point; the bridge, the plugin dispatcher and
`scripts/check_contract.py` all derive from it, so the bridge/plugin drift
that broke the old plugin's `connect_nodes` cannot recur silently.

The old plugin (`houdini/plugin/server.py`, port 9876, Claude Desktop) still
runs alongside, untouched. Retiring it is a separate, still-open decision.

### Target domain

**SOP/VOP-level procedural geometry and VEX.** Not lighting, not `/stage`,
not Solaris. Generic SOP/VEX knowledge is stable across versions and well
represented in model weights, and the result is visually self-verifying in a
viewport. The studio's lighting stack is custom `pl_*` HDAs no model has
seen, so lighting work would depend entirely on copying an existing scene.

---

## 2. The safety model, stated plainly

The plugin runs inside the owner's Houdini process under the owner's account,
on a machine with studio shares mounted. At OS level it can reach everything
the owner can reach. There is no sandbox, no jail, no privilege boundary.
**The only barrier is which functions exist in the code.**

Therefore the design rule is: **do not write the dangerous capability at all,
rather than write it and guard it.**

Concretely, in this package:

- No `import os`, `shutil`, `requests`, `subprocess`, `zipfile`. No
  `os.remove` / `unlink` / `rmtree`.
- Exactly three permitted file operations, each narrow and each documented at
  its call site: the audit log (`server.py`, mode `"a"`); an existence probe
  `open(path, "rb")` on a path built from a constant plus a timestamp; and
  `hou.hipFile.save()` on the already-open, already-sandboxed hip immediately
  before a background render (see D8).
- Path handling uses plain string operations and `hou.hipFile.path()`. Output
  directories must **pre-exist** — the plugin never creates directories. A
  missing directory is a clean refusal, and that is the owner's arming
  switch, not a bug to fix.
- Generated filenames are `mcp_<YYYYmmdd_HHMMSS>[_<renderer>].<ext>` under a
  constant directory, so overwriting an existing file is impossible by
  construction.
- Scene saving is `hou.hipFile.saveAs(<constant dir> + "mcp_<ts>.hip")`.

A blacklist over Python source text (rejecting `import os` etc.) is **not**
acceptable as a control — it is trivially bypassed via `__import__`,
`getattr`, `hou.hscript()`. That is why Python-bearing parameters are refused
outright instead of scanned.

---

## 3. Hard rules for anyone editing this package

Violating any of these is a failed change, regardless of whether the feature
works.

1. **No new capability without an explicit decision.** If you want a tool
   this document does not list, stop and ask.
2. **Never add `execute_code`, `modify_node`, broad `delete_node`, or any
   "run this Python" path** — in the plugin or in a probe script. Diagnostic
   snippets are pasted by a *human* into Houdini's Python Shell precisely so
   this capability never has to exist.
3. **Never `import os` / `shutil` / `requests` / `subprocess` / `zipfile`**
   here. See §2 for the three permitted file operations.
4. **The agent never passes a filesystem path to any tool.** Every output
   path is generated inside the plugin from a constant plus a timestamp. Not
   even a fragment of a caller-supplied path.
5. **The plugin never creates directories.**
6. **Never `getattr` on the `hou` namespace from caller input.** Caller
   strings map through explicit dicts — that is the whitelist. `getattr` is
   the same class of construct as the blacklist bypasses §2 rejects.
7. **All safety logic lives in `guards.py`.** Write handlers only ever *call*
   already-reviewed guard functions; they never invent new ones inline.
8. **Do not widen `check_settable_parm`.** Output-path and code-bearing parms
   stay refused through the generic `set_parm` path, always. Where a write to
   an output-path parm is genuinely needed, it goes through its own narrow
   guard function (`set_render_output`), not through the generic path.
9. **Never start or stop Houdini yourself.** The owner does that. Same for
   anything on pc137 beyond a normal read or deploy.
10. **Ask rather than guess** on real parameter names, build numbers, and
    whether an API method exists on a given build. Check it live with
    `hython` or `get_node_type_parms` and record the answer in
    `HMCP_HOUDINI_NOTES.md`.

---

## 4. Guard inventory — what `guards.py` holds and why

| Guard | Protects against |
|---|---|
| `require_sandbox_scene()` | Any write while the open hip is outside `SANDBOX_ROOT` (or an opt-in scene, §5 D9) |
| `require_bootstrap_scene()` | `save_scene_as` repointing a *named* production scene at the sandbox — allowed only from a never-saved scene, so the owner's next Ctrl+S can't land somewhere unexpected |
| `OUTPUT_PATH_PARMS` / `INPUT_PATH_PARMS` | Writes to render/geometry output paths. Input paths are an **allowlist** (`file`, `filepath`), never a heuristic — `file` means different things on different node types |
| `CODE_PARMS_ALLOWED` / `CODE_PARMS_REFUSED` | VEX (`snippet`, `vexpression`) is allowed; Python, callbacks, and ROP pre/post scripts are refused — ROP script parms execute shell/HScript and are as dangerous as Python |
| `NODE_TYPES_REFUSED`, `ALLOWED_NODE_CATEGORIES` | Creating `python`/`unix`/`shell` SOPs, or nodes outside `{Sop, Object, Vop}` |
| `check_expression_language()` | Expressions are only ever `hou.exprLanguage.Hscript`, never Python |
| `check_viewport_camera_free()` | A camera move writing to a real camera node's transform parms. `defaultCamera()` is documented **live**: if a camera is locked to the view, changing its settings changes the camera *node*. That write would bypass `check_settable_parm` entirely and silently move somebody's shot camera |
| `SessionRegistry` | Deleting nodes the agent did not create. Keyed on `node.sessionId()`, not path — a path breaks on rename, and Houdini reuses names, so a stale path entry could authorise deleting somebody else's node. Session ids do not survive a scene reload, so after a reload the agent simply loses delete rights over its earlier work — fails in the safe direction |
| `UndoWatermark` | `delete_node` silently eating the owner's manual edits. One session-level fingerprint of `hou.undos.undoLabels()`, re-stamped centrally in `server.py`'s dispatch after every successful write, checked only by `delete_node`. Fails closed when unreadable |
| `set_render_output()` | The only place an output-path parm is ever written: asserts the parm name is a known picture parm and the path starts with `RENDER_DIR` |
| `render_dir_exists()` | Rendering before the owner has armed it by creating `_renders/` |

---

## 5. Decision log

Settled decisions, with the reason and what breaks if reverted. Do not
relitigate these; add a new dated entry if one genuinely changes.

**D1 — Who builds (2026-08-09).** Claude Code gets its own MCP server on its
own port, alongside the untouched old plugin. *Reverting* means the two
plugins share a port or the old one is removed before the new one is proven.

**D2 — Reading is unrestricted, always, in any scene.** Reading cannot damage
anything. Writes are the only thing the sandbox boundary gates.

**D3 — Write boundary is the open hip's path (2026-08-09).** Writes work only
when the open `.hip` lives under `SANDBOX_ROOT`, with one exception:
`save_scene_as` from a never-saved scene, to bootstrap into the sandbox.
*Reverting* to a flag or an env var would hand the agent control of its own
safety gate — the exact anti-pattern §2 rejects.

**D4 — Deletion is limited to the agent's own nodes**, by `sessionId()`. No
filesystem deletion capability exists anywhere in the package.

**D5 — Camera control before rendering (2026-08-12).** Framing had to be
deterministic before a render could be pointed anywhere useful.
`viewport_frame_node` takes a **node path, not the selection**: every write
command here is keyed on a path, reading the selection makes the command
non-deterministic, and *setting* it stomps the human's UI state. Orbit takes
**relative deltas, not absolute angles** — absolute angles require exposing a
full camera-orientation convention, which is a set-arbitrary-camera-transform
command wearing a hat.

**D6 — `saveViewToCamera` is callable internally, never exposed (2026-08-12).**
`render.py` may call it on `/obj/hmcp_cam`, a node the plugin created and
registered — the same shape as `viewport_snapshot` owning its own output
path. It is not, and does not become, an agent-callable command.

**D7 — One renderer descriptor table, not per-renderer branches
(2026-08-12).** A single dict in `guards.py` keyed on renderer name holding
ROP type, picture parm and resolution parm names, **filled from live
`get_node_type_parms` output, never from guessed names**. This is the seam
where Arnold or Karma XPU would be added later — one dict entry plus a parm
probe. Do not add renderer code "while you're in there".

**D8 — `render_snapshot` auto-saves the hip before pressing
`executebackground` (2026-08-12).** Houdini refuses a background render
outright — a blocking, abort-on-OK modal — whenever the hip has unsaved
changes, and the handler's own ROP preflight always creates exactly that
condition. So the save is unconditional and has no separate confirmation
step. It is a real disk write and is listed in §2 for that reason, even
though it targets the already-open, already-sandboxed hip.

**D9 — Opt-in sandbox for project scenes (2026-08-11).** A scene outside
`SANDBOX_ROOT` can be opted in with a scene variable (`hmcp = 1`), so real
project scenes can be worked on deliberately rather than by copying them into
the sandbox. See README for the mechanics.

**D10 — `Vop` added to `ALLOWED_NODE_CATEGORIES` (2026-08-13).** Was
`{Sop, Object}`; opened at the owner's request to build VOP networks
alongside VEX wrangles.

**D11 — Karma only (2026-08-12).** `ALLOWED_RENDERERS = {"karma"}`. Mantra is
excluded not by policy but because it fails silently on this setup — see
`HMCP_HOUDINI_NOTES.md`. Re-add it only after that is root-caused.

**D12 — Background render, single slot, poll for status (2026-08-12).** One
pending render at a time; a second `render_snapshot` while one is pending is
refused. That is the entire concurrency design — do not build a job registry.
The known cost, measured and accepted: `executebackground` still blocks
Houdini's main thread for several seconds (6.5–16.6s measured) and a
silently-aborted render leaves `rop.errors()` empty. Both are documented
limitations, and both are the argument for the deferred headless worker.

---

## 6. Permanently out — the never-list

These are not "not yet". They are refused by doctrine, and a future session
proposing them should be pointed here.

- **`execute_code` in any form**, and any "run this Python" path.
- **Regex or keyword blacklists over code text as a safety control** — see
  §2. Allowlists everywhere, never blacklists.
- **Bypass flags gated by an env var or a tool argument.** An env var is not
  a permission boundary the caller doesn't control.
- **Caller-supplied output paths** on any tool.
- **Broad `modify_node`, broad `delete_node`.**
- **Multi-frame / sequence rendering.** Impossible by construction: `trange`
  is forced to `"off"` immediately before every render, and no frame
  parameter exists on the command. An unbounded sequence render is precisely
  the "runs forever, freezes Houdini, blows every timeout" failure the design
  avoids.
- **Pan, roll, absolute camera transforms, `setCamera`, `lockCameraToView`,
  `saveViewToCamera` as a command, selection manipulation, viewport layout
  changes, the UV viewport.** The `hou.GeometryViewport` methods that convert
  viewport state into node-graph writes on cameras the agent did not create
  join this list alongside `execute_code`.
- **Inline base64 image returns.** The socket framing parses the whole buffer
  as one JSON object, and it would inflate the audit log with megabytes.
- **Rendering a caller-supplied ROP.** It would execute whatever is in that
  node's `prerender`/`postrender`/`precmd` parms. The handler owns its ROP,
  and refuses to reuse one whose script parms are non-empty.

### Reviewed and declined (2026-08-12)

From a comparative review of `github.com/oculairmedia/houdini-mcp`:
`network_snapshot` (a NetworkEditor screenshot), `reorder_inputs`, and named
token-budget constants. All three were judged real but not worth their
surface at the time. Adopted from the same review: `find_nodes`, the
undo-revision watermark, `hint` in the error shape, and the `connect_nodes`
category pre-check. That review also stands as the clearest available
counter-example to our own doctrine — its `execute_code` passes full
`__builtins__` into `exec` and gates it with exactly the string-scanning
approach §2 rejects.

---

## 7. Deferred, with a home

- **The headless `hython` worker** — port 9879, blocking accept loop,
  persistent session, `save_checkpoint`, loss of Ctrl+Z rollback. This is the
  actual destination; it is deferred because the GUI render de-risked it, not
  because it is unwanted. `plans/HMCP_HEADLESS_WORKER_PLAN.md`. Two things in
  the shipped code exist for it and must not be compromised: `render.py`
  stays `hou.ui`-free outside the `camera="viewport"` branch, and
  `camera="fit"` is verified working.
- **The SOP cookbook** — `plans/HMCP_SOP_COOKBOOK_PLAN.md`.
- **Arnold and Karma XPU** — D7's descriptor table is the seam.
- **Retiring the old plugin on 9876** — gated on the new one being proven in
  daily use.
- **A dedicated security review** of the grown write surface — `BACKLOG.md`
  `## TODO`.

---

## 8. Critical files

| File | Role |
|---|---|
| `houdini/commands_spec.py` | Single declaration of command names/params. `commands.py`, the bridge and `check_contract.py` all derive from it; `_build_registry` raises at import if it and `_HANDLERS` disagree |
| `houdini/plugin/hmcp/guards.py` | The entire safety layer, in one reviewable file. Every new safety-relevant function lands here |
| `houdini/plugin/hmcp/intro.py` | Read commands. Every field goes through `_safe_attr` — this module must never raise |
| `houdini/plugin/hmcp/build.py` | Write commands. `viewport_snapshot` is the template for a handler's shape |
| `houdini/plugin/hmcp/render.py` | `render_snapshot` / `render_status`. Stays `hou.ui`-free outside one branch |
| `houdini/plugin/hmcp/server.py` | Transport, dispatch, audit log, the central undo-watermark re-stamp |
| `houdini/bridge/hmcp_bridge.py` | MCP tool wrappers; `_bridge_tool_names`' startup assertion catches drift |

Bridge docstrings are the model's only instructions — write them as
instructions, not descriptions ("Call this before `viewport_snapshot`"), not
just a description of what the function does.

---

## 9. Deploy and verification mechanics

```
./scripts/deploy_plugin.sh hmcp-local     # local Houdini, no VPN, fast loop
./scripts/deploy_plugin.sh hmcp           # pc137 over VPN
```

Both run `hython -m py_compile` on every file, then `check_contract.py`.

- **After deploying, reload the plugin in Houdini** via the `hmcp.shelf`
  Start button — it purges `hmcp*` from `sys.modules`. Skip it and
  `check_contract.py` reports a mismatch against a live plugin still running
  old code in memory.
- **Changes that add commands also need Claude Code restarted** to pick up
  the new bridge tools.
- `check_contract.py` **cannot run while a Claude Code session's `houdini2`
  bridge is connected** — the plugin serves one client at a time by design
  and the bridge holds a persistent connection. Diff the bridge's own live
  `describe_commands` response against `commands_spec.COMMAND_NAMES`
  instead.
- Per root `CLAUDE.md`: one line per verified change into `BACKLOG.md` under
  `## Done`. The detail goes in the commit message body.

---

## 10. Superseded documents

These were execution plans. They are fully closed, and were harvested into
this file, `HMCP_HOUDINI_NOTES.md` and `README.md`, then deleted — retrievable
from git whenever the full reasoning is actually wanted:

```
git log --diff-filter=D --oneline -- houdini/docs/
git show <sha>^:houdini/docs/HMCP_FEEDBACK_LOOP_PLAN.md
```

- `HOUDINI_MCP_REWRITE_PLAN.md` — the original rewrite, Phases 0–3, closed
  2026-08-10. Its §3/§4 doctrine is §2 and §3 above.
- `HMCP_FEEDBACK_LOOP_PLAN.md` — camera control, non-blocking render,
  `find_nodes`, the undo watermark. Stages 0–5, all closed 2026-08-12. Its
  decisions D1–D7 are folded into §5 above.
- `HMCP_CAMERA_CONTROL_PLAN.md` — camera API research, executed via the
  above. Its verified API surface is in `HMCP_HOUDINI_NOTES.md`.
- `HMCP_HEADLESS_RENDER_PLAN.md` — Track A executed; Track B survives as
  `plans/HMCP_HEADLESS_WORKER_PLAN.md`.
- `EXTERNAL_REVIEW_oculairmedia_houdini-mcp.md` — triaged; its adopt/decline
  outcome is in §6.

`BACKLOG.md`'s `## Done` entries from 2026-08-09 to 2026-08-12 cite these
filenames. That is accurate history — the files existed then.
