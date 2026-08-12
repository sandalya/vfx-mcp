# Houdini MCP — ROP Rendering and Headless Operation — Execution Plan

Status: **draft for owner review. Nothing implemented. Phases 0 and 3 are research/verification only; the first line of shipping code is Phase 1.**
Audience: an implementing agent with no memory of this planning conversation.
Supersedes two lines of `houdini/docs/HOUDINI_MCP_REWRITE_PLAN.md` — see §1. Everything else in that document (§3 decisions, §4 safety model, the guard doctrine, the sandbox boundary) applies here unchanged and is not renegotiated.

Produced by an Opus planning agent, 2026-08-12. Not yet reviewed/approved by the owner (Sashok) — treat as a draft to discuss before Phase 0 starts.

---

## 1. What this changes in the original plan, and what it does not

Two lines are overridden by the owner:

| Original | File:line | New |
|---|---|---|
| "Eyes: OpenGL viewport snapshot only. No Karma/Arnold/Mantra rendering." | `houdini/docs/HOUDINI_MCP_REWRITE_PLAN.md:59` | Karma/Mantra ROP rendering becomes a second, additive "eyes" path. `viewport_snapshot` stays as-is. |
| "Out of scope: … Karma/Arnold/Mantra rendering" | `HOUDINI_MCP_REWRITE_PLAN.md:384-386` | Karma and Mantra move in scope. **Arnold stays out** — see §7 Open Questions, evidence in §2.4. |

Not changed, and load-bearing for everything below:

- `guards.py`'s module docstring rule: no `import os`/`shutil`/`requests`/`subprocess`/`zipfile`, no filesystem delete, no `open(..., "w")` on caller-influenced paths (`houdini/plugin/hmcp/guards.py:11-18`).
- Output directories **pre-exist**; the plugin never creates directories (`HOUDINI_MCP_REWRITE_PLAN.md:78-80`, `guards.py:29`).
- The agent never passes a filesystem path to any tool (`HOUDINI_MCP_REWRITE_PLAN.md:55`).
- Output-path parms stay refused by generic `set_parm` (`guards.py:142-146`, `guards.py:197-198`). Nothing in this plan widens `check_settable_parm`.
- One declaration of commands in `houdini/commands_spec.py`; bridge, dispatcher, and `check_contract.py` all derive from it.

---

## 2. What I verified before planning (facts, not assumptions)

### 2.1 GUI-dependency of all 24 existing commands

Read handler by handler from `intro.py` / `build.py`. Hypothesis in the brief ("everything except `viewport_snapshot`") is **confirmed**, with three caveats flagged for live probing.

| # | Command | Handler | Touches `hou.ui` / SceneViewer? | Verdict |
|---|---|---|---|---|
| 1 | `get_scene_info` | `intro.py:52` | no; uses `hou.playbar.frameRange()` (`intro.py:64-65`) | headless OK — *probe `hou.playbar`* |
| 2 | `get_geometry_info` | `intro.py:267` | no | headless OK |
| 3 | `get_node_errors` | `intro.py:204` | no | headless OK |
| 4 | `get_node_type_parms` | `intro.py:346` | no (`hou.nodeTypeCategories`) | headless OK |
| 5 | `list_node_types` | `intro.py:372` | no | headless OK |
| 6 | `get_node_help` | `intro.py:390` | no; `nodeType.helpText()` | headless OK — *probe helpText* |
| 7 | `get_network` | `intro.py:222` | no | headless OK |
| 8 | `get_node_info` | `intro.py:140` | no | headless OK |
| 9 | `describe_commands` | `intro.py:408` | pure Python | headless OK |
| 10 | `create_node` | `build.py:46` | no; `hou.undos.group` at `build.py:60` | headless OK — *undo caveat* |
| 11 | `connect_nodes` | `build.py:73` | no | headless OK |
| 12 | `set_parm` | `build.py:89` | no | headless OK |
| 13 | `set_expression` | `build.py:107` | no | headless OK |
| 14 | `delete_node` | `build.py:124` | no | headless OK |
| 15 | `rename_node` | `build.py:151` | no | headless OK |
| 16 | `set_position` | `build.py:161` | no (network-editor coords are scene data) | headless OK |
| 17 | `set_color` | `build.py:171` | no | headless OK |
| 18 | `set_comment` | `build.py:181` | no | headless OK |
| 19 | `layout_children` | `build.py:191` | no (`parent.layoutChildren()` is a graph op) | headless OK |
| 20 | `set_display_flag` | `build.py:206` | no | headless OK |
| 21 | `set_render_flag` | `build.py:216` | no | headless OK |
| 22 | `set_bypass` | `build.py:226` | no | headless OK |
| 23 | `save_scene_as` | `build.py:241` | no (`hou.hipFile.save`) | headless OK |
| 24 | `viewport_snapshot` | `build.py:259` | **yes** — `hou.ui.paneTabOfType` (`build.py:269`), `hou.updateModeSetting` (`279`), `sv.flipbook` (`296`) | **GUI-only** |

**23 of 24 are GUI-independent.** Caveats to prove in Phase 3, not assume:

- `hou.undos.group()` (used by all 14 write handlers): Houdini only *records* undos in a graphical session. If the context manager raises in `hython`, every write handler breaks at line 1 of its mutation block. Even if it doesn't raise, the Phase 2 safety property "one Ctrl+Z removes the entire build" (`HOUDINI_MCP_REWRITE_PLAN.md:350`) **is lost headless**. That is a real reduction in the safety model and is addressed in §5.3.
- `hou.playbar.frameRange()` in `get_scene_info`.
- `nodeType.helpText()` in `get_node_help`.

### 2.2 Transport is GUI-bound, and the documented fallback does not actually work headless

`_install_pump` (`server.py:118-145`) prefers `hou.ui.addEventLoopCallback`; its docstring says the `QTimer` path "stays as a fallback for non-graphical hython, where hou.ui does not exist at all" (`server.py:129-130`). **That fallback is a trap.** `HMCP_LOCAL_TIMEOUT_TRIAGE.md:31-46` establishes the root cause precisely: a `QTimer` only ever fires if the thread that started it runs a **Qt event loop**. A bare `hython` process runs no Qt event loop at all, so the QTimer path in headless would reproduce the exact documented failure — port bound, OS handshake completes, `accept()` never called, total silence, no error. The fallback has never been exercised (BACKLOG 2026-08-12); it is anticipation, not a working path.

Conclusion for Track B: **do not reuse the pump.** Write a blocking accept loop. Details in §5.4.

Secondary finding: `server.py:20-25` imports PySide at module import time. That drags Qt into a headless process for no reason and couples `import hmcp` to Qt availability. Move it inside `_install_pump`.

### 2.3 The 10-second wall is real and the failure is a disconnect, not a wait

`HmcpConnection.DEFAULT_TIMEOUT = 10.0` (`hmcp_bridge.py:58`), enforced twice (socket timeout at `:93`, wall-clock check at `:97`). On expiry the bridge returns `bridge_timeout` **and calls `self.disconnect()`** (`:114`). The plugin then fails its `sendall` and drops the client (`server.py:216-220`). So an over-budget render doesn't just look slow — the result is *thrown away* even though the render completed.

Worse, the dispatcher is synchronous inside the pump: `_process_server` → `execute_command` (`server.py:205`) runs on Houdini's main thread inside the event-loop callback. A blocking `rop.render()` there freezes the entire Houdini UI and stops the server servicing anything else — including a polling `get_render_status` call. This kills the naive async design; see §4.3.

### 2.4 Environment facts I checked live on pc137 (read-only, over the existing `ssh pc137`)

- Houdini installs present: 20.0.688 → **21.0.729** (11 versions). `houdini/CLAUDE.md:10` pins 21.0.596 for py_compile; Phase 2 verification hit 21.0.729 behaviour (`build.py:275-277`).
- `Houdini 21.0.729\bin\` contains **`mantra.exe`, `vmantra.exe`, `husk.exe`, `hython.exe`** — Mantra still ships in Houdini 21 on this machine. (The `opengl` ROP is deprecated as of Houdini 22 per SideFX docs; Mantra's `ifd` ROP page is still live documentation. Neither is removed in 21.)
- `C:\Users\Admin\Documents\houdini21.0\packages\` contains **only `hpaste.json`**, and `houdini21.0\houdini.env` is stock/commented-out. **No HtoA package in the Houdini 21 environment hmcp runs in.** Production Arnold work (`houdini/docs/SCENE_ANALYSIS.md`) evidently comes in through a pipeline launcher, not this environment. This is the evidence behind "Arnold deferred."
- `C:\houdini_mcp_sandbox\` on pc137 exists with `_snapshots\` and `backup\`. There is **no `_renders\`** — consistent with the plan below, where the owner creating that directory is the opt-in switch.
- Locally (SASHOKPC): Houdini 20.5.278 only, `mantra.exe` + `husk.exe` present, and `houdini20.5/packages/htoa.json` **does** exist locally. So Arnold-in-Houdini-20.5 exists on the dev machine but not in pc137's Houdini-21 environment — another reason to keep Arnold out of the day-one surface rather than write a renderer abstraction around a renderer only one of the two targets has.

### 2.5 Houdini capability findings from research (flagged where confidence is short of certain)

- **The `/out` `karma` ROP is an HDA wrapper around Scene Import** (SideFX docs). It converts `/obj` geometry to USD internally and renders it through Karma — meaning it works for this project's `/obj`+SOP target domain *without* the agent touching `/stage`, which keeps `HOUDINI_MCP_REWRITE_PLAN.md:35` ("not `/stage`, not Solaris") intact at the user-facing level. Consequence: its parameter names are HDA parameters, **not** guessable, and the old plugin's guesses (`picture`, `resolution1`/`resolution2`, `engine` — `HoudiniMCPRender.py:572-596`) must be re-derived live via the already-existing `get_node_type_parms("karma", "Driver")`. Do not port those names on faith.
- **The `opengl` ROP cannot render headless** — it needs a GL canvas; out-of-process/no-GUI invocation fails. Confirms the brief's premise: headless "eyes" must be Karma or Mantra, there is no cheap OpenGL shortcut.
- **`rop.render()` from `hython` is the standard batch mechanism** and is widely used for Mantra and Karma. I am confident for Mantra (`ifd` → `mantra.exe`), and *reasonably* confident for the Karma ROP — but the Karma ROP's internal Scene-Import→USD→Karma path is exactly the sort of thing that can behave differently without a UI (one forum thread notes it invokes hython internally to generate USD for husk, and that consumes a license on farm nodes). **This is the single biggest unverified assumption in Track B and Phase 3 exists to settle it before any headless code is written.**
- **`hou.GeometryViewport.saveViewToCamera(camera_node[, camera_name])` exists** (HOM docs) and copies the viewport's current view transform into a camera node. The one-argument signature is deprecated in favour of the two-argument one — verify which works on 21.0.729 before relying on it. This is the key to Track A's camera problem (§4.2).
- **Lights**: Mantra falls back to a default headlight with no lights in the scene; Karma via Scene Import most likely does **not** and will produce a black or near-black frame. Unverified — Phase 0 measures it, and §4.4 designs for it.

---

## 3. Track structure

- **Track A — ROP rendering, GUI attached.** New guarded render command on the existing live server. Ships and is verified entirely on its own. Delivers real value immediately: a lit, shaded, non-OpenGL image of the agent's work, and framing that doesn't depend on where the owner left the viewport.
- **Track B — headless `hython` worker.** Reuses Track A's render handler as its only eyes. Attempted only after Track A passes, and only after Phase 3's probe answers the questions Track A cannot.

Phases 0 and 3 produce **no shipped code**. Phase 0 gates Track A; Phase 3 gates Track B.

---

## Phase 0 — research and live verification (Track A). No plugin code.

Everything here uses capability that already exists: the read-only `houdini2` MCP tools, and `hython` over `ssh pc137` (already routine — `deploy_plugin.sh:126-133` runs hython on pc137 on every deploy).

1. **Which ROP types exist.** `list_node_types(category="Driver", name_filter="karma")`, then `"ifd"`, `"opengl"`, `"arnold"`, `"husk"`. Record exactly which are present on 21.0.729. Confirm `"Driver"` is the right category string (if not, find it from the error's `Available:` list — `intro.py:354` returns it).
2. **Real parameter names.** `get_node_type_parms("karma", "Driver")` and `get_node_type_parms("ifd", "Driver")`. Extract the actual names for: output picture, resolution override, camera, engine (CPU/XPU), sample/quality controls, frame range (`trange`, `f1`, `f2`), and the pre/post-render script parms. Write the findings into this document as a table before writing any handler. **Do not reuse `HoudiniMCPRender.py:557-621`'s names without confirming each one against this output.**
3. **Output format.** Confirm Karma and Mantra can write `.png` (and `.jpg`) to the `picture`/`vm_picture` parm, not only `.exr`. This is not cosmetic: Claude Code's Read tool can display PNG/JPG and cannot display EXR, so an EXR-only renderer produces no eyes at all.
4. **A hand-run render, timed.** Ask the owner (or do it via the existing `houdini2` write tools plus one manual step in Houdini's Python Shell) to render the existing sandbox rock scene through a hand-built Karma ROP at 512×512 draft settings, and again through Mantra. Record: wall-clock seconds each; whether the image is black without lights; whether Houdini's UI froze; whether any modal dialog appeared. **These numbers decide §4.3's timeout strategy — do not proceed to Phase 1 without them.**
5. **Camera probe.** In the Python Shell: `hou.ui.paneTabOfType(hou.paneTabType.SceneViewer).curViewport().saveViewToCamera(cam)` — determine which signature 21.0.729 accepts, and confirm the resulting camera reproduces the viewport framing.
6. **Licence/idle sanity.** Confirm a `karma` ROP render does not pop a licence dialog in this environment (it will hang the socket the same way Manual update mode did — `build.py:275-285`).

**Verify Phase 0 (all must be answerable in one sentence each before Phase 1 starts):**

1. Karma ROP present on 21.0.729: yes/no. Mantra `ifd` present: yes/no.
2. The exact parm names for picture / resolution / camera / engine / trange on both, pasted from `get_node_type_parms`.
3. A 512×512 draft Karma render of the sandbox rock completes in **N** seconds; Mantra in **M** seconds.
4. PNG output confirmed working: yes/no. If no, what format is.
5. With no lights in the scene, Karma produces: black / lit / grey. Mantra produces: …
6. `saveViewToCamera` signature that works on 21.0.729.
7. No modal dialog appeared during any of the above.

---

## Phase 1 — Track A implementation: `render_snapshot`

New file `houdini/plugin/hmcp/render.py`. One new command. Deliberately one, not three.

### 1.1 `guards.py` additions (the only place output paths are ever produced)

```
RENDER_DIR = "c:/houdini_mcp_sandbox/_renders/"   # must pre-exist; plugin never creates it
RENDER_OUTPUT_PARMS = {"picture", "vm_picture"}   # settable ONLY via set_render_output()
ALLOWED_RENDERERS = {"karma", "mantra"}
RENDER_QUALITY = {"draft": (512, 512, <samples>), "preview": (960, 540, <samples>)}
```

Design decisions and their reasons:

- **A new `RENDER_DIR`, not `SNAPSHOT_DIR`.** Three reasons. (a) The pre-existence rule (`guards.py:29`, `HOUDINI_MCP_REWRITE_PLAN.md:78-80`) turns a directory into a physical kill switch: no `_renders/` on disk → every render refuses cleanly, and the owner controls that with one `mkdir`, no code change and no deploy. Reusing `SNAPSHOT_DIR` would silently arm the new capability the moment it deploys, because that directory already exists on both machines. (b) ROP renders and OpenGL flipbooks have different provenance and different sizes; mixing them makes the owner's `_snapshots/` folder unreadable. (c) It documents itself in the audit log.
- **`set_render_output(node, parm_name, path)` lives in `guards.py`, not in the handler.** It asserts `parm_name in RENDER_OUTPUT_PARMS` and `path.startswith(RENDER_DIR)` before calling `parm.set(path)`. This keeps the property that made §4 of the rewrite plan work: *every* write to an output-path parameter passes through one reviewable file. `check_settable_parm` (`guards.py:186`) is **not** touched — generic `set_parm` still refuses `picture`/`vm_picture` exactly as today, and Phase 2 verification item 4 still passes.
- **Filename** `mcp_<YYYYmmdd_HHMMSS>_<renderer>.png`, same collision-free-by-construction pattern as `build.py:287-288`. Never caller-supplied, never a caller-supplied fragment.

### 1.2 `render.py` — one handler

`render_snapshot(renderer="karma", quality="draft", camera="viewport")`

Sequence, in order:

1. `guards.require_sandbox_scene()` — first line, same as every other write handler.
2. Validate `renderer` against `ALLOWED_RENDERERS` and `quality` against `RENDER_QUALITY`. Both are closed enums; anything else raises `ValueError` (→ logged as `REFUSED`, `server.py:253-258`).
3. Preflight, in the spirit of `build.py:269-285` — fail with an actionable message rather than let Houdini open a modal dialog and hang the socket:
   - the requested ROP type exists in this Houdini (from Phase 0's findings);
   - `RENDER_DIR` is readable (open-for-read probe on the directory, or a `hou.findFile`-free existence probe — see §6.1);
   - a camera can be produced (see 1.3).
4. Build the camera (§1.3).
5. Get or create the plugin's own ROP node, at a fixed path (`/out/hmcp_render_<renderer>`), inside `hou.undos.group("MCP: render_snapshot")`. **Never accept a caller-supplied ROP path.** Rendering someone else's ROP would execute whatever is in its `prerender`/`postrender`/`precmd` parms — the exact class of parm `guards.CODE_PARMS_REFUSED` (`guards.py:158-161`) exists to refuse. On a reused node, assert those parms are empty and refuse if not.
6. Set, internally: camera, resolution from `RENDER_QUALITY`, samples, `trange = 0` **and** `f1 = f2 = hou.frame()`. Frame-range pinning is belt-and-braces on purpose — the same guarantee `viewport_snapshot` gets from `settings.frameRange((cur_frame, cur_frame))` (`build.py:295`). `trange` is never exposed as a parameter of the command.
7. `guards.set_render_output(rop, "picture" | "vm_picture", path)`.
8. `rop.render(verbose=False)`.
9. Verify the file exists by opening it for read (§6.1); return `{"path", "renderer", "resolution", "camera_path", "rop_path", "seconds"}`.

Note on the ROP node's category: `create_node` cannot make Driver nodes (`guards.ALLOWED_NODE_CATEGORIES = {"Sop", "Object"}`, `guards.py:172`) and that stays true — the ROP is created by this dedicated handler only, exactly the way `viewport_snapshot` owns its own output path. The agent gets rendering; it does not get "create arbitrary ROPs."

### 1.3 Camera — and the dependency on the sibling camera-control plan

Two modes, and the design works whichever plan lands first:

- **`camera="viewport"` (default, GUI only).** Create/reuse `/obj/hmcp_cam` (an Object-category node, registered in `guards.session_registry`) and populate it with `curViewport().saveViewToCamera(...)`. The ROP then renders *exactly what the agent already sees* in `viewport_snapshot`. This is the whole reason to prefer it: it makes the two eyes agree, needs no bbox maths, and — importantly — **the sibling orbit/frame/pan plan (`HMCP_CAMERA_CONTROL_PLAN.md`) steers this for free.** If that plan lands first, its camera moves change the viewport, and `render_snapshot` picks them up with zero integration work. Note this dependency as one-directional and optional: Track A does not need that plan, and that plan does not need Track A.
- **`camera="fit"` (works headless; the fallback when there is no viewport).** Port the bbox-fit logic from `HoudiniMCPRender.py` — `find_displayed_geometry():148`, `calculate_bounding_box():181`, `setup_camera_rig():241`, `adjust_camera_to_fit_bbox():341` — **rewritten guard-compliant**: no `import os`, no caller-supplied path, no `numpy` (replace the `np.array` bbox accumulation at `HoudiniMCPRender.py:187-227` with plain floats; `numpy` isn't forbidden but is an unnecessary dependency in a headless-capable module), and the destroy-then-recreate pattern at `HoudiniMCPRender.py:254-260` replaced with reuse-or-create so the handler never destroys a node it did not create. The maths (`:359-421`) is the valuable part and transfers directly.

A third mode, `camera_path=<existing camera>`, is deliberately **deferred** — it is safe in principle but widens the surface before there is a demonstrated need.

### 1.4 The timeout problem — recommendation and rejected alternatives

**Recommendation: synchronous render + per-command bridge timeout + hard caps. No job/poll protocol day one.**

| Option | Verdict | Why |
|---|---|---|
| **Per-command timeout in the bridge** — add `timeout` to `HmcpConnection.send_command` (`hmcp_bridge.py:81`) and a `TIMEOUTS = {"render_snapshot": 300.0}` map, defaulting to `DEFAULT_TIMEOUT` | **adopt** | ~10 lines, no protocol change, no new state, and the failure mode is unchanged (a hard disconnect the client already handles). Everything else keeps its 10s guard — the timeout is widened for one command, not globally. |
| **Hard caps on resolution/samples/frames** in the handler | **adopt** | The only mechanism that actually bounds the cost. Closed `quality` enum, single frame, resolution never caller-supplied. |
| **Async `start_render` / `get_render_status`** | **reject day one** | It does not work with this transport. The dispatcher is synchronous inside the single-threaded pump (`server.py:205`), so while `rop.render()` blocks, the poll call cannot be serviced either — the poll times out exactly like the render would have. Making it work requires *also* moving the render out of process (below), which costs the error reporting. Two new failure surfaces (job registry, orphaned jobs) for zero gain at current render times. |
| **Out-of-process background render** (press the ROP's `executebackground` button, poll for the output file) | **reject day one, keep as the designed escape hatch** | Genuinely non-blocking and keeps the GUI alive, and it needs no `subprocess` import (Houdini spawns it). But `rop.render()`'s exception — which carries the renderer's actual error text — is replaced by "the file never appeared," which is the worst possible diagnostic for an agent that must self-correct. Adopt only if Phase 0 measures renders over ~60 s. |
| **Raise `DEFAULT_TIMEOUT` globally** | **reject** | The 10s wall is a useful liveness signal for every other command (it is what surfaced the dead-pump bug — `HMCP_LOCAL_TIMEOUT_TRIAGE.md:9-12`). Don't spend it. |

Two consequences to write into the code and the docs:

- **Houdini's UI freezes for the duration of a render** in Track A, because the handler runs inside `hou.ui.addEventLoopCallback`. That is acceptable for a capped draft render measured in seconds, and unacceptable for a minute. Phase 0's timing is the go/no-go. Log start and finish through `_note()` (`server.py:66`) so the audit log shows the freeze window.
- Claude Code's own MCP tool timeout may be shorter than 300 s. Check and, if needed, set `MCP_TIMEOUT`/`MCP_TOOL_TIMEOUT` in the `houdini2` entry's `env` in `~/.claude.json` — the same place `HMCP_HOST` already lives (README.md:201-202).

### 1.5 Renderer exposure, day one

- **Karma CPU — supported, default.** It is the current renderer, present in 21, and the `/out` wrapper handles `/obj` geometry without pushing the agent into `/stage`.
- **Mantra — supported.** `mantra.exe` is present on 21.0.729 (verified), it renders `/obj` directly with no USD conversion, and it gives a default headlight — i.e. it is the reliable fallback when Karma comes back black. Cheap to support since the handler already parameterises the ROP type.
- **Karma XPU — deferred.** GPU availability under a disconnected RDP session is unknown and untestable from here; adding a second engine before the CPU path is proven doubles the Phase 0 verification matrix for no new capability. One-line addition later once the `engine` parm name is known from Phase 0.
- **Arnold — out of scope.** Evidence, not guesswork: no HtoA package in pc137's `houdini21.0/packages` and a stock `houdini.env` (§2.4). Adding it means depending on a pipeline launcher environment hmcp does not run in. Revisit only if the owner says Arnold is available in the plain-Houdini-21 environment (Open Question Q1).

### 1.6 Wiring

- `houdini/commands_spec.py`: one new entry, `kind: "write"`, params `renderer` / `quality` / `camera`, doc naming `RENDER_DIR` and its pre-existence requirement (mirror the `viewport_snapshot` entry at `commands_spec.py:213-222`).
- `houdini/plugin/hmcp/commands.py`: one line in `_HANDLERS` (`commands.py:22-48`). `_build_registry` (`:51`) fails loudly if either side is missed.
- `houdini/bridge/hmcp_bridge.py`: one `@mcp.tool()`, plus the name in `_bridge_tool_names` (`:359-368`) — the assertion at `:369` catches omission at startup.
- `.claude/settings.local.json`: allow `mcp__houdini2__render_snapshot`.
- Deploy: `./scripts/deploy_plugin.sh hmcp` picks up `render.py` automatically — `deploy_dir` copies `*.py` (`deploy_plugin.sh:99`) and the py_compile loop iterates the local dir (`:128-132`). No deploy-script change needed for Track A.

**Verify Phase 1** (negative tests first, in the style of `HOUDINI_MCP_REWRITE_PLAN.md:338-353`):

1. With `_renders/` **absent**, `render_snapshot` refuses with a clear message naming the directory, and creates nothing.
2. With a **non-sandbox** scene open, `render_snapshot` refuses (`require_sandbox_scene`).
3. `set_parm` on `picture` and on `vm_picture` still refuses — the generic path is unchanged.
4. `render_snapshot(renderer="arnold")` and `renderer="opengl"` refuse as unsupported enums; both appear as `REFUSED` in the audit log.
5. `render_snapshot()` on the sandbox rock scene returns a path under `C:/houdini_mcp_sandbox/_renders/`, the file exists, and Claude Code can Read it and describe the rock.
6. The returned image visibly matches the viewport framing (`camera="viewport"`), and `camera="fit"` returns a differently-framed but fully-contained image of the same geometry.
7. Two consecutive calls produce two different files; nothing is overwritten.
8. `/out/hmcp_render_karma`'s `prerender`/`postrender`/`precmd`/`postcmd` parms are empty after the render; setting one by hand and re-calling causes a refusal.
9. `trange` on the render ROP reads 0, and `f1 == f2 == hou.frame()`, after a render.
10. `grep -nE "os\.remove|shutil|unlink|rmtree|requests|subprocess|zipfile|import os" houdini/plugin/hmcp/` returns **zero** matches (unchanged from `HOUDINI_MCP_REWRITE_PLAN.md:351`).
11. `hython -m py_compile` passes on every file; `scripts/check_contract.py` reports 25 commands, no mismatch.
12. Measured wall-clock time is recorded in `BACKLOG.md`, and is comfortably under the 300 s bridge timeout.

---

## Phase 2 — Track A: getting the image home from pc137 (small, optional, do it if Phase 1 leaves a gap)

Local mode returns a path Claude can Read directly. **Remote mode (pc137, the default `HMCP_HOST=10.10.10.31`) returns a path on another machine.** `viewport_snapshot` has the same gap today; it has not bitten because verification has been happening in local mode (BACKLOG 2026-08-12). Options, cheapest first:

1. Do nothing; document that render/snapshot eyes require local mode, and use `scp pc137:<path>` by hand when on pc137.
2. A `scripts/fetch_render.sh` wrapper around `scp` (outside the plugin — `scp` on the *bridge* side is not constrained by the plugin's no-`subprocess` doctrine).
3. Return the image inline as base64 in the command result. Rejected for now: it puts megabytes through a socket protocol whose framing is "parse the whole buffer as one JSON object" (`server.py:203`), and inflates the audit log.

Recommendation: (2), and only after Phase 1 proves the renders are worth fetching.

---

## Phase 3 — Track B research. No code shipped; a throwaway probe only.

The purpose is to convert §2.5's "reasonably confident" into "verified," **before** anyone writes a headless server. Deliverable: findings appended to this document, plus a go/no-go.

Mechanism: a single throwaway probe script (`scripts/probe_headless.py`, explicitly **not** part of the `hmcp` package and not deployed to the runtime package directory) run as `hython.exe probe_headless.py` on pc137 over ssh and/or on the local 20.5. Running hython on pc137 is already routine (`deploy_plugin.sh:126-133`), so this needs no new permission — **but it consumes a Houdini licence seat while it runs, so ask the owner before running it during working hours** (Open Question Q3).

What the probe answers:

1. `hou.isUIAvailable()` is False; `hou.ui` raises/absent — confirming which code paths die.
2. `import hmcp` succeeds in bare hython with **no Qt** available (this is what motivates moving the PySide import out of `server.py`'s module scope, §2.2).
3. **`hou.undos.group("x")` as a context manager**: does it raise, or no-op? This single answer decides whether 14 write handlers need a code change.
4. `hou.playbar.frameRange()` and `nodeType.helpText()` work.
5. Load the existing sandbox rock `.hip`, then run each of the 23 GUI-independent handlers **by calling `commands.REGISTRY[name]["handler"]` directly, in-process** — no sockets, no bridge. Record pass/fail per command. This turns §2.1's table from a reading into a measurement.
6. **The decisive one:** build a Karma ROP and a Mantra ROP by hand and call `.render()`. Does Karma work with no GUI? How long? Is the image black without lights? Does XPU work over an RDP-disconnected session?
7. Whether a `karma` ROP render in hython spawns additional processes / consumes an extra licence (the forum thread in §2.5 suggests the Scene-Import path may).

**Verify Phase 3:**

1. A pass/fail line for each of the 23 commands, run in-process under hython.
2. `hou.undos.group` behaviour stated in one sentence, with the consequence for `build.py`.
3. A rendered PNG on disk, produced by hython with no Houdini window open, that Claude can Read and describe. **If this does not happen, Track B stops here** and the answer to the owner is "headless is not viable for eyes on this setup; Track A plus a GUI session is the way."
4. Licence-seat cost of a running hython worker, measured (does opening a second seat block the owner's interactive Houdini?).
5. Recorded render time headless vs. Phase 0's GUI number.

---

## Phase 4 — Track B implementation: the headless worker

Only if Phase 3 is green.

### 4.1 Transport: a new blocking loop, not the pump

New `houdini/plugin/hmcp/headless.py`:

- A plain blocking `socket` server on the process's **only** thread: `accept()` → `recv()` → dispatch → `sendall()` → loop. No `QTimer`, no `hou.ui`, no PySide import anywhere in the module. This deletes the entire class of bug documented in `HMCP_LOCAL_TIMEOUT_TRIAGE.md` — there is no event loop to share, no thread-affinity question, and no "listening but deaf" state to diagnose.
- Reuse, don't duplicate: the same `commands.REGISTRY`, the same `ALLOWED_CLIENTS` (`server.py:34`), the same JSON framing, the same `_audit`/`_note`. Refactor `server.py`'s `execute_command`/`_execute_command_internal` (`server.py:228-260`) from methods into module-level functions that `HmcpServer` delegates to, so both transports dispatch through one reviewed code path. That refactor is behaviour-preserving and should be its own commit, verified by the existing `check_contract.py` before `headless.py` is added.
- **Port 9879**, not 9878, so a headless worker and a GUI Houdini can coexist on one machine without a silent bind conflict.
- Audit log: `hmcp_headless_audit.log` (distinct filename), same `hou.homeHoudiniDirectory()` resolution (`server.py:46-55`), so two concurrent processes never interleave into one file.
- Blocking `recv` needs a socket timeout so the loop can notice a stop request and log a heartbeat; keep a `ticks`-equivalent counter and a `status` line so the "is it alive" question has the same one-number answer as `hmcp.status()` (`__init__.py:34-55`).

### 4.2 Session model: **one persistent process, one open scene**

Recommended without hesitation. Stateless open/save/close per call breaks three things that already exist:

1. **`delete_node` dies permanently.** `SessionRegistry` is keyed on `sessionId()`, and `guards.py:244-247` documents that session ids do not survive a scene reload. In a stateless model *every* call is a reload, so the agent could never delete its own work — it would fail safe, but into uselessness.
2. **The bootstrap flow inverts.** `save_scene_as` is gated by `require_bootstrap_scene()` — never-saved scenes only (`guards.py:117-134`). It fits a persistent session perfectly (fresh worker → untitled scene → agent bootstraps → writes unlock, exactly today's flow, unchanged). In a stateless model, every call after the first opens an already-saved scene, so the bootstrap path is dead and something new would have to be invented.
3. **The way the tools are actually used.** The Phase 3 rock (BACKLOG, 2026-08-10) and the ice-cave work were dozens of small sequential calls — `create_node` → `get_geometry_info` → `set_parm` → `get_node_errors` → correct → repeat — each one reading live cook state from the previous. Stateless means a full `.hip` load and re-cook per call; the iteration loop that makes the toolset worth having is exactly what it destroys.

Durability gap this creates, and its fix: a persistent worker's scene lives in RAM, and there is no owner at a keyboard to press Ctrl+S. Add **`save_checkpoint()`** — no arguments, `require_sandbox_scene()` first, `hou.hipFile.save(file_name=SANDBOX_ROOT + "mcp_" + ts + ".hip")`. Constant directory, timestamped filename, never overwrites, never `hou.hipFile.save()` with no argument — i.e. exactly the rule at `HOUDINI_MCP_REWRITE_PLAN.md:82-83`. Cheap, and it also has value in Track A/GUI mode.

Second consequence, and it must be written down for the owner: **headless loses Ctrl+Z rollback.** `hou.undos.group()` (`build.py:60` et al.) records nothing without a GUI. The remaining barriers are unchanged and are the ones §4 of the rewrite plan actually relies on — the sandbox boundary, the absence of delete capability, no output-path writes, no Python parms — plus `save_checkpoint`'s never-overwriting history. Say so explicitly rather than let the owner assume the undo safety net came along.

### 4.3 Lifecycle: who starts it — my recommendation and the question I'm posing back

`houdini/CLAUDE.md:6` says "Never start/stop Houdini yourself — the user does that manually." That rule was written about the interactive application: starting it costs the owner their session, their scene, and their screen. A headless worker is a different animal — no window, no user state, disposable.

I do **not** think this should be decided by analogy, so it is Open Question Q2. My recommendation:

- **Day one: owner-started, owner-stopped.** A `houdini/scripts/hmcp_worker.cmd` the owner double-clicks or runs over RDP, and Ctrl-C / closing the window to stop. Same posture as the `hmcp start` shelf button (`houdini/shelf/hmcp.shelf:22`) — the owner remains the one who decides a Houdini licence seat is in use.
- This is not merely policy, it is enforced by construction: the `hmcp` package cannot spawn a process without `import subprocess`, which the doctrine forbids (`guards.py:11-14`). **Any autostart must live outside the package** — a `.cmd`, a Scheduled Task, a shortcut — never inside it. That constraint should survive whatever the owner decides.
- If the owner wants more automation later, the right shape is a Windows Scheduled Task or a service wrapper the *owner* installs once, plus (optionally) a narrowly-scoped `shutdown_worker` command that calls `hou.exit()` and only exists in the headless transport. Deferred; it is a new capability class and there is no demonstrated need yet.

### 4.4 Eyes headless

Track A's `render_snapshot` handler, unchanged, with `camera="fit"` forced (there is no viewport to save from — the handler must detect the absence of `hou.ui` and refuse `camera="viewport"` with a message that says so, rather than throwing an AttributeError). If Phase 3 shows Karma renders black without lights, the handler additionally creates a plugin-owned light (a distant or dome light in `/obj`, reuse-or-create, registered in the session registry) when the scene contains no light objects — or defaults `renderer="mantra"` headless, which has the default headlight. Phase 3 decides which.

### 4.5 Deployment: no third target

Proposal: **do not add `deploy_plugin.sh hmcp-headless`.** The package deployed is byte-identical; only the entry point differs, and a third target would duplicate the backup + scp + py_compile + contract-check blocks (`deploy_plugin.sh:115-140`) for no gain. Instead:

- `headless.py` is picked up automatically by the existing `hmcp` and `hmcp-local` targets (`*.py` glob at `:99`/`:147`, py_compile loop at `:128`/`:158`).
- Add the launcher `houdini/scripts/hmcp_worker.py` + `hmcp_worker.cmd` and **two lines** to each existing target to copy them to a known location (alongside the package, or `C:/Users/Admin/Documents/houdini21.0/scripts/`), plus the same py_compile check.
- Bridge: add `PORT = int(os.environ.get("HMCP_PORT", 9878))` to `hmcp_bridge.py:49` and `check_contract.py:25`, so the identical bridge talks to GUI (9878) or headless (9879) by env var — matching the existing `HMCP_HOST` pattern exactly (README.md:166-206). If the owner wants both live at once, register a second Claude Code MCP entry (`houdini_headless`) whose `env` pins `HMCP_PORT=9879`; otherwise the one entry flips between them.

**Verify Phase 4:**

1. `import hmcp` succeeds in bare hython with no Qt on the path; `grep -n "PySide" houdini/plugin/hmcp/` shows the import only inside `_install_pump`.
2. Worker starts from the launcher, prints its port and log path, and `HMCP_PORT=9879 scripts/check_contract.py` reports all commands agreeing with `commands_spec.py`.
3. A connection from a **non-allowlisted IP** is refused and logged, same as the GUI server (`server.py:184-187`).
4. From Claude Code with `HMCP_PORT=9879`: `save_scene_as` bootstraps the worker's untitled scene into the sandbox; every other write refuses before that point.
5. All 23 GUI-independent commands round-trip through the real MCP path (extend `scripts/mcp_client_test_hmcp.py`, which already exercises the full path — BACKLOG 2026-08-09).
6. `viewport_snapshot` refuses headless with a message naming the reason, not an AttributeError traceback.
7. `render_snapshot` produces a readable PNG with **no Houdini window open anywhere on the machine** (check Task Manager, not just "I didn't see one").
8. `save_checkpoint()` writes a new timestamped `.hip`; calling it twice produces two files and overwrites neither.
9. The worker survives a guard refusal, a malformed JSON payload, and a client disconnect mid-command without dying.
10. GUI Houdini on 9878 and the worker on 9879 run simultaneously without either misbehaving; the two audit logs are separate files.

---

## Phase 5 — Track B acceptance target

Mirror of `HOUDINI_MCP_REWRITE_PLAN.md`'s Phase 3, with the GUI removed: **from a cold headless worker, Claude Code builds a procedural rock unattended — `save_scene_as` → `sphere` → `mountain` → `attribwrangle` (VEX) → `smooth`, reading geometry and errors after each step — then renders it with `render_snapshot()`, reads the PNG, judges it, corrects itself, re-renders, and `save_checkpoint()`s. The owner's Houdini is never opened.**

Passes when: the graph cooks clean; `get_geometry_info` returns sensible counts and bbox; the render looks like a rock; the checkpoint `.hip` opens correctly in interactive Houdini afterwards; and total wall-clock is recorded.

Only after this passes is it worth discussing whether headless becomes the default mode.

---

## Out of scope (deliberately, with reasons)

- **Arnold.** No HtoA in pc137's Houdini-21 environment (verified §2.4). Supporting it means depending on a pipeline launcher hmcp does not run under. Revisit if Q1 says otherwise.
- **Karma XPU.** One extra engine value, but doubles the verification matrix and depends on GPU availability under RDP, which cannot be settled from here. Trivial to add once the CPU path is proven and Phase 0 has the `engine` parm name.
- **Multi-frame / sequence rendering.** Deliberately impossible by construction: `trange = 0`, `f1 = f2 = hou.frame()`, no frame parameters on the command. An unbounded sequence render is precisely the "runs forever, freezes Houdini, blows every timeout" failure this plan is built to avoid.
- **Async job/poll protocol (`start_render` / `get_render_status`).** Rejected day one with reasoning in §1.4; kept as the designed escape hatch if Phase 0/3 measurements demand it.
- **Inline base64 image return.** Rejected in §2 of Phase 2; the framing (`server.py:203`) and audit log are not built for it.
- **Rendering an existing/caller-specified ROP.** A capability escalation via pre/post-render script parms; the handler owns its ROP.
- **`/stage` and Solaris as a user-facing surface.** The Karma ROP uses USD internally; that stays an implementation detail. `HOUDINI_MCP_REWRITE_PLAN.md:35` is unchanged.
- **A `shutdown_worker` / autostart command inside the plugin.** New capability class, no demonstrated need, and structurally impossible without breaking the no-`subprocess` rule.
- **Retiring `viewport_snapshot`.** It stays. It is faster, free, needs no lights, and is the ground truth the ROP camera is matched against.
- **Retiring the old plugin on 9876.** Unrelated to this work; still gated on `HOUDINI_MCP_REWRITE_PLAN.md:372`.

---

## Open questions for the owner

**Q1 — Arnold.** Is HtoA available in the plain Houdini 21.0.729 environment on pc137, or only through the studio's pipeline launcher? I found no `htoa` package in `houdini21.0/packages` and a stock `houdini.env`, so my plan defers Arnold. Correct me if it's available another way and it's worth a day-one slot.

**Q2 — Does a headless `hython` worker count as "Houdini" for `houdini/CLAUDE.md:6`?** My recommendation: owner-started and owner-stopped day one (a `.cmd` you run), because it consumes a licence seat and that should stay your decision — and note the plugin *cannot* start itself anyway without breaking the no-`subprocess` rule. But if you'd rather it be a Scheduled Task or something I can restart myself once it's proven, say so now, because it changes the launcher design.

**Q3 — Licences.** How many Houdini seats do you have on pc137, and does a persistent hython worker holding one interfere with your interactive session? If seats are tight, the worker should be started per-task and stopped after, which changes the session model's cost/benefit (though not, I think, its conclusion).

**Q4 — Which machine hosts the headless trial?** pc137 (Houdini 21, the real target, but shared with your work) or the local machine (Houdini 20.5, no VPN needed, faster iteration, but a different Houdini version and it has HtoA where pc137 doesn't)? My preference is local for Phase 3's probe, pc137 for Phase 4's verification.

**Q5 — `_renders/` directory.** Track A refuses to render until `C:/houdini_mcp_sandbox/_renders/` exists on the target machine, per the "plugin never creates directories" rule. That makes creating it your explicit arming switch. Confirm you want it that way (and create it on whichever machine, when you're ready) rather than reusing `_snapshots/`.

**Q6 — How long a freeze is acceptable?** In Track A a render blocks Houdini's UI for its duration. Phase 0 measures it. What's your ceiling — 5 s, 15 s, 60 s? Your answer decides whether the synchronous design survives or whether we go to out-of-process background rendering with worse diagnostics.

**Q7 — Reading files for existence checks.** The doctrine forbids `open(..., "w")` and `import os`; it says nothing about reading. Confirming a render actually landed needs *some* existence check, and the least-capability option is `open(path, "rb")` on a path built entirely from `RENDER_DIR` + timestamp. I plan to do that and document it as an explicit, narrow exception in `guards.py` (note `server.py:60` already opens the audit log with `"a"`). Flagging it rather than doing it quietly.

---

### Critical files for implementation

- `C:\Users\gamai\vfx-mcp\houdini\plugin\hmcp\guards.py` — `RENDER_DIR`, `RENDER_OUTPUT_PARMS`, `ALLOWED_RENDERERS`, `RENDER_QUALITY`, `set_render_output()`; the only place an output-path parm is ever written.
- `C:\Users\gamai\vfx-mcp\houdini\plugin\hmcp\build.py` — `viewport_snapshot()` (`:259-298`) is the template for the new handler's shape; the new `render.py` sits beside it and `save_checkpoint()` lands here.
- `C:\Users\gamai\vfx-mcp\houdini\plugin\hmcp\server.py` — extract `execute_command` to module level for shared dispatch, move the PySide import (`:20-25`) into `_install_pump`; `headless.py` is its sibling.
- `C:\Users\gamai\vfx-mcp\houdini\commands_spec.py` — new `render_snapshot` (and later `save_checkpoint`) entries; nothing ships until this, `commands.py`, and the bridge agree.
- `C:\Users\gamai\vfx-mcp\houdini\bridge\hmcp_bridge.py` — per-command timeout map on `send_command` (`:81-120`), `HMCP_PORT` env var (`:49`), new tool + `_bridge_tool_names` (`:359-368`).

Sources for the external Houdini facts above: [Karma render node (SideFX)](https://www.sidefx.com/docs/houdini/nodes/out/karma.html), [OpenGL render node (SideFX)](https://www.sidefx.com/docs/houdini/nodes/out/opengl.html), [Mantra render node (SideFX)](https://www.sidefx.com/docs/houdini/nodes/out/ifd.html), [hou.GeometryViewport (SideFX HOM)](https://www.sidefx.com/docs/houdini/hom/hou/GeometryViewport.html), [SideFX forum: rendering karma in batch](https://www.sidefx.com/forum/post/353660/), [SideFX forum: OpenGL ROP out-of-process](https://www.sidefx.com/forum/topic/90144/).
