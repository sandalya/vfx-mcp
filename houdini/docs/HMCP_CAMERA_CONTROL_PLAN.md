# Houdini MCP — Viewport Camera Control

Status: **planned, not started.** Additive extension to the shipped hmcp bridge (port 9878, Phase 3 complete per `BACKLOG.md`).
Audience: an implementing agent with no memory of this planning conversation. Read `houdini/docs/HOUDINI_MCP_REWRITE_PLAN.md` §3 and §4 first; nothing here relitigates them.

Produced by an Opus planning agent, 2026-08-12. Not yet reviewed/approved by the owner (Sashok) — treat as a draft to discuss before Phase 0 starts.

**Executed.** `houdini/docs/HMCP_FEEDBACK_LOOP_PLAN.md` is the authoritative
execution order — it resolved this doc's contradictions with
`HMCP_HEADLESS_RENDER_PLAN.md` (its §2 "Decisions already made"), then
implemented and live-verified all six commands in its Stage 2 (2026-08-12).
Read that document first; this one remains for the API-surface research
(§2) and the design rationale it was written to capture.

---

## 1. Why this exists

`viewport_snapshot()` (`houdini/plugin/hmcp/build.py:259-298`) captures whatever the SceneViewer is *already* showing. It has no ability to aim. On 2026-08-12 the ice-pattern session (`BACKLOG.md`, `/obj/ice_pattern_test`) built a five-node SOP graph and then had to ask Sashok to press Home in the viewport before the snapshot showed anything useful. `describe_commands` confirms 24 commands, none of which touch the camera.

The gap is one narrow capability: **aim the viewport at a node the agent names, then look at it from a chosen angle.** Everything else in this document exists to keep that capability from widening.

---

## 2. API surface — what is confirmed and what is not

### 2.1 Confirmed live via `hython` on this machine (Houdini 20.5.278, read-only `dir()`/`__doc__` probe)

`hou.GeometryViewport` has, verbatim:

```
camera, cameraPath, changeType, defaultCamera, draw, frameAll, frameBoundingBox,
frameGrid, frameNonTemplated, frameSelected, home, homeAll, homeBoundingBox,
homeSelected, isCameraLockedToView, lockCameraToView, name, resolutionInPixels,
saveViewToCamera, setCamera, setDefaultCamera, settings, size, type, useDefaultCamera,
viewPivot, viewTransform
```

Docstrings, verbatim:

- `frameBoundingBox(self, bbox)` — "Moves the view to show an arbitrary area in the scene. bbox: A hou.BoundingBox representing the volume of space to focus on."
- `changeType(self, hou.geometryViewportType)` — "Set the viewport type. This method first attempts to restore a stashed view for the new viewport type, but failing that, will home the viewport."
- `defaultCamera(self) -> hou.GeometryViewportCamera` — "The returned object is **live** in that changing its settings will immediately change the view. If a camera/light is locked to the view, changing the settings will change the camera node's parameters" (truncated in the docstring; the full sentence is on the SideFX docs page).
- `draw(self)` — "Request that the viewport redraw. Multiple draw() calls within the same script will be merged into a single call."
- `type(self)` — query the viewport type. Note: **the query method is `type()`, not `viewportType()`** — several forum posts get this wrong.
- `name(self) -> str` — "persp1, top1, etc."
- `cameraPath(self) -> str` — "Return the path to the camera that the viewport is looking through. If the viewport isn't looking through a camera, **return an empty string**."
- `isCameraLockedToView(self) -> bool` — "Query to see if the camera is locked to the view. This returns the state of the camera lock only; this can be enabled without viewing through a camera."

`hou.GeometryViewportCamera`: `pivot`/`setPivot`, `translation`/`setTranslation`, `rotation`/`setRotation`, `isOrthographic`/`isPerspective`/`setPerspective`, `orthoWidth`/`setOrthoWidth`, `aperture`, `focalLength`, `clipPlanes`, `stash`. `translation(self) -> 3-tuple of float` — "Query the translation (position) of the viewport camera." `pivot(self) -> 3-tuple of float`.

`hou.geometryViewportType`: `Perspective, Top, Bottom, Front, Back, Right, Left, UV`.

`hou.SceneViewer`: `curViewport`, `selectedViewport`, `viewports`, `findViewport`, `viewportLayout`, `setViewportLayout`, `resetViewportCamera`, `flipbook`, `flipbookSettings`.

`hou.BoundingBox`: `center, minvec, maxvec, sizevec, isValid, contains, enlargeToContain`, and `__mul__` **exists** — there is no `transform()` method; transform is `bbox * matrix4` (returns the axis-aligned box around the transformed box).

`hou.hmath`: `buildRotate(rx, ry, rz, order="xyz") -> hou.Matrix4`, `buildRotateAboutAxis`, `buildRotateLookAt`, `buildRotateZToAxis`. `hou.Matrix4.extractRotationMatrix3` exists. `hou.ObjNode.worldTransform`, `hou.ObjNode.displayNode`, `hou.SopNode.geometry` all exist.

### 2.2 NOT confirmed — needs verification via hython/GUI on pc137 before implementation

These cannot be probed headlessly because `hou.ui` does not exist in non-graphical hython, so no viewport instance can be obtained. Each is a Phase 1 probe item:

| # | Unknown | Why it matters |
|---|---|---|
| V1 | Does `frameBoundingBox()` also move the camera **pivot** to the box centre, or leave the old pivot? | Decides whether `viewport_frame_node` must call `setPivot(bbox.center())` explicitly. If it doesn't, orbit after framing swings around the wrong point. |
| V2 | Composition order for orbit: `cam.setRotation(cam.rotation() * delta)` vs `delta * cam.rotation()`. | One tumbles in world axes, the other in camera-local axes; the wrong one produces nonsense on the second call. |
| V3 | Does `setRotation()` alone orbit **around the pivot**, or spin the camera in place at its own position? | If in place, orbit must also recompute translation: `new_t = pivot + R * (t - pivot)`. |
| V4 | Is `translation()` a world-space position or an offset relative to the pivot? | Decides the dolly formula (`p + (t-p)*factor` vs `t * factor`). |
| V5 | Is `viewport.draw()` required before `sv.flipbook()` picks up the new view, or does flipbook force its own redraw? | If required and omitted, `viewport_frame_node` + `viewport_snapshot` returns the *old* framing — the exact bug this feature exists to fix. |
| V6 | Does the "smooth view transitions" viewport preference animate `frameBoundingBox`? | If it animates, a snapshot fired immediately after framing captures a mid-tween view. |
| V7 | Same `dir()` probe on pc137's Houdini 21.0.x — confirm the surface in 2.1 is identical. | Low risk (this API has been stable since H16), but the plan's own doctrine is to check version-specific details rather than recall them (rewrite plan line 205-209 did exactly this for `isNewFile()`). |
| V8 | pc137's actual Houdini build number. | `houdini/CLAUDE.md:10` and the rewrite plan say 21.0.596; `BACKLOG.md`'s Phase 2 entry says the live build is 21.0.729, and that mismatch is what hid the `hou.updateMode()` breakage. `deploy_plugin.sh:126` hardcodes 21.0.596. |

---

## 3. Command design

### 3.1 The set

| Tier | Command | Kind | Ship? |
|---|---|---|---|
| 1 | `get_viewport_info()` | read | yes |
| 1 | `viewport_frame_node(node_path)` | write | yes — this alone solves the actual problem |
| 1 | `viewport_frame_all()` | write | yes — 3 lines, zero risk, the "I'm lost" recovery button |
| 1 | `viewport_set_view(view)` | write | yes |
| 2 | `viewport_orbit(dx_degrees, dy_degrees)` | write | yes, if V2/V3 resolve cleanly |
| 3 | `viewport_dolly(factor)` | write | only if V4 resolves cleanly; otherwise drop |
| — | pan, roll, absolute camera transform | — | **no** — see §7 |

Names are prefixed `viewport_` to group with the existing `viewport_snapshot` (`commands_spec.py:213`), which is the only naming precedent in this area.

### 3.2 Frame takes a node path, not a selection

`frameSelected()` and `homeSelected()` both exist and both were rejected:

1. **Every write command in this codebase is keyed on a path.** `commands_spec.py` has `node_path`/`parent_path` on all 15 write entries. A selection-based command would be the only one whose result depends on invisible state.
2. **Selection is the human's UI state.** Reading it makes the command non-deterministic; *setting* it (`node.setSelected(True, clear_all_selected=True)`) would stomp whatever Sashok had selected — a side effect entirely outside "the agent's own work," which is the boundary `guards.SessionRegistry` draws for deletion.
3. `frameSelected()` is precisely the workflow that failed on 2026-08-12: it needs a human to select first.

Implementation is `viewport.frameBoundingBox(bbox)` with the bbox computed from the node.

### 3.3 Orbit takes relative deltas, not absolute angles

Absolute angles would require the plugin to define and expose a full camera orientation convention (up axis, zero azimuth, elevation clamping) — which, once exposed, is a set-arbitrary-camera-transform command wearing a hat. That is the "flexible/generic capability" shape the rewrite plan §4 rejects, and it lands squarely on the same slippery slope as `modify_node` in the old plugin.

Relative deltas match how the capability is actually used ("show me the other side," "tip it down a bit"), compose naturally, and need no convention beyond "dx is horizontal, dy is vertical." No clamping is proposed: rotation wraps, so out-of-range values are harmless, and adding a clamp would be runtime validation of something that isn't dangerous.

### 3.4 Preset views map through a fixed dict — never `getattr`

```python
"persp" -> hou.geometryViewportType.Perspective
"top" | "bottom" | "front" | "back" | "left" | "right" -> matching members
```

`getattr(hou.geometryViewportType, caller_string)` would work and is one line shorter. It is forbidden here: it turns a caller string into attribute lookup on the `hou` namespace, which is the same class of construct as the blacklist bypasses named in the rewrite plan §4 (`__import__`, `getattr`, `hou.hscript()`). An explicit 7-entry dict is the whitelist. `"uv"` is deliberately not offered — a UV viewport is useless for looking at geometry and would silently break the next snapshot.

### 3.5 Which viewport

Use `sv.curViewport()`, matching `viewport_snapshot` at `build.py:291`. Documented as "the one containing the mouse cursor," so in a quad-view layout it is not fully deterministic. `selectedViewport()` is more stable but switching only `viewport_frame_node` to it would let the framing and the snapshot land on *different* viewports — the worst outcome. The invariant that matters is "camera commands and the snapshot act on the same viewport," and that holds only if both use the same accessor.

Mitigation: every camera command returns `viewport.name()` (`"persp1"`, `"top1"`, …), and `viewport_snapshot`'s return dict gains the same field so a mismatch is visible in the transcript. That is a one-line additive change to an existing handler — call it out in review, it is the only edit to shipped behaviour.

---

## 4. Guard integration

### 4.1 `require_sandbox_scene()` — yes, on every camera command

Camera state is not a node-graph edit, so the instinct is to classify it `kind: "read"`. Three reasons that is wrong:

1. **Viewport/desktop state is saved into the `.hip`.** Moving the view in a production scene leaves a modified scene that Sashok's next Ctrl+S would persist — the same class of surprise `require_bootstrap_scene()` exists to prevent (`guards.py:117-134`).
2. **It changes what the human is looking at.** Yanking the view out from under someone working in a production scene is disruptive even when it damages nothing.
3. **It can become a real node-graph write** — see 4.2.

So: `guards.require_sandbox_scene()` on the first line of every `viewport_*` handler, exactly like the other 14 write handlers, and `kind: "write"` in `commands_spec.py`. `get_viewport_info` is genuinely read-only (it queries and returns; it moves nothing) and goes in `intro.py` with no guard, per that file's docstring at `intro.py:1-12`.

### 4.2 One new guard is needed: `check_viewport_camera_free(viewport)`

`defaultCamera()` is documented as returning a **live** object, and: *"If a camera/light is locked to the view, changing the settings will change the camera node's parameters."*

That means an orbit call, on a viewport locked to `/obj/cam1`, writes to that camera node's transform parms. That node is not in `guards.session_registry`, the write bypasses `guards.check_settable_parm` entirely, and on a shared scene it silently moves somebody's shot camera. This is the one genuinely dangerous edge in the whole feature, and per doctrine it gets refused rather than validated-around:

```python
def check_viewport_camera_free(viewport):
    """Raise if the viewport is looking through, or locked to, a camera node.

    hou.GeometryViewport.defaultCamera() is documented live: 'if a camera/light
    is locked to the view, changing the settings will change the camera node's
    parameters'. A camera move would then become a write to a real node's
    transform parms -- a node not in session_registry, through a path that never
    touches check_settable_parm. Refuse instead of special-casing it."""
    path = viewport.cameraPath()      # "" when not looking through a camera
    if path:
        raise PermissionError(...)
    if viewport.isCameraLockedToView():
        raise PermissionError(...)
```

Lives in `guards.py`, not `build.py`, per that file's stated purpose (`guards.py:16-19`: write handlers should only ever *call* already-reviewed guard functions). `PermissionError` so `server.py:253-258` logs it as `REFUSED` rather than as a crash. Deliberately **not** applied to `viewport_snapshot` — a snapshot moves nothing.

### 4.3 No other new guards

No new parameter whitelist (no parms are touched), no new node-category rule beyond reusing `guards.ALLOWED_NODE_CATEGORIES` (`guards.py:172`) for "what can be framed," no filesystem contact at all — the standing `grep` for `os.remove|shutil|unlink|rmtree|requests|subprocess|zipfile` stays at zero hits.

---

## 5. Preconditions — extract the SceneViewer check, keep the Manual-mode check where it is

`viewport_snapshot` currently does two preflight checks inline:

- `build.py:269-274` — SceneViewer pane exists.
- `build.py:276-285` — `hou.updateModeSetting() != hou.updateMode.Manual`, because flipbook in Manual mode "would trigger a fatal OpenGL dialog and hang the connection."

**Split them.**

- **Extract the SceneViewer check** into `build._require_scene_viewport() -> (scene_viewer, viewport)`, shared by `viewport_snapshot` and all camera commands. Also handles `hou.ui` missing (headless) and `curViewport()` returning `None`.
- **Leave the Manual-mode check inside `viewport_snapshot` only.** It exists because *flipbook* pops a modal dialog; a camera move does not render and cannot trip it. Hard-refusing a harmless command on an unrelated precondition would just be noise. Instead, surface `update_mode` in every camera command's return payload and in `get_viewport_info`, so the agent knows in advance that a following snapshot will refuse.

**Change the exception class while extracting.** `build.py:271` raises `RuntimeError`, which `server.py:251-258` does *not* catch — it falls to the generic handler at `server.py:229-238` and returns a full traceback, unlogged as a refusal. `ValueError` gets a clean one-line message plus a `REFUSED` audit line. Recommend `ValueError` with the message prefixed `"Precondition: ..."` so the audit log can still tell a precondition failure from a guard refusal. This changes the message text of an existing refusal path — flag it explicitly in the commit body.

### Timeout and threading

Every handler runs inside the `hou.ui.addEventLoopCallback` poll on Houdini's main thread (`server.py:118-146`; see `HMCP_LOCAL_TIMEOUT_TRIAGE.md` for why it must stay there). `frameBoundingBox`, `changeType`, `setRotation`, `draw` are all immediate main-thread calls, far inside the bridge's `DEFAULT_TIMEOUT = 10.0` (`hmcp_bridge.py:58`).

The one real risk: `viewport_frame_node` calls `sop.geometry()`, which **forces a cook**. A heavy uncooked SOP can blow the 10s budget and leave the socket in the timeout state described in the triage doc. Mitigation is guidance, not code: the agent's existing habit is to call `get_geometry_info` (same cook, same ceiling) before framing. State this in the tool docstring; do not add a cook timeout, which would be new machinery for a problem `get_geometry_info` already has.

---

## Phase 0 — headless API confirmation on both machines

No code, no deploy. Read-only introspection only.

1. On pc137, confirm the real Houdini build directory (V8) — `deploy_plugin.sh:126` hardcodes `21.0.596`, `BACKLOG.md` reports the live build as `21.0.729`.
2. Run the same probe used to produce §2.1, on pc137's hython:
   ```
   hython.exe -c "import hou; print(sorted(n for n in dir(hou.GeometryViewport) if not n.startswith('_')))"
   ```
   plus the same for `hou.GeometryViewportCamera`, `hou.geometryViewportType`, and `hasattr(hou.BoundingBox, '__mul__')`.

**Verify Phase 0:**

1. `frameBoundingBox`, `frameAll`, `changeType`, `defaultCamera`, `draw`, `cameraPath`, `isCameraLockedToView`, `name`, `type` all present on `hou.GeometryViewport` in pc137's build.
2. `pivot/setPivot`, `translation/setTranslation`, `rotation/setRotation`, `isOrthographic`, `orthoWidth/setOrthoWidth` all present on `hou.GeometryViewportCamera`.
3. `hou.geometryViewportType` exposes exactly `Perspective, Top, Bottom, Front, Back, Left, Right, UV`.
4. `hou.BoundingBox.__mul__` present; `hou.hmath.buildRotate` and `hou.Matrix4.extractRotationMatrix3` present.
5. Any absence is recorded against the corresponding command, which is then dropped from the set rather than worked around.
6. pc137's actual build number recorded; if it is not 21.0.596, note that `deploy_plugin.sh:126` is stale (separate fix, do not bundle).

---

## Phase 1 — live viewport probe in a GUI Houdini

Resolves V1-V6. Requires a real viewport, so it must be pasted by Sashok into Houdini's Python Shell (local 20.5.278 is fine and needs no VPN). **This probe is a throwaway snippet typed by a human. It must not become an `execute_code` command** — rewrite plan §3 and root `CLAUDE.md` both forbid reintroducing that, and the probe's whole point is to be run once and discarded.

The probe should, on a sandbox scene with one visible object, print:

1. `cam.pivot()` before and after `viewport.frameBoundingBox(bbox)` → answers **V1**.
2. `cam.pivot()`, `cam.translation()`, and `cam.rotation()` before and after `cam.setRotation(cam.rotation() * delta)` for a 30° yaw, then the same for `delta * cam.rotation()` → answers **V2** and **V3** (if translation is unchanged and the object leaves frame, rotation alone spins in place and translation must be recomputed).
3. `cam.translation()` alongside `cam.pivot()` and the known world position of the object → answers **V4**.
4. `frameBoundingBox` then immediately `sv.flipbook(...)` with and without an intervening `viewport.draw()`; compare the two JPEGs → answers **V5** and **V6**.
5. `viewport.name()`, `viewport.type()`, `viewport.cameraPath()`, `viewport.isCameraLockedToView()` in the normal case and while looking through a camera → confirms the §4.2 guard's two conditions actually fire.

**Verify Phase 1:**

1. V1 answered; decision recorded on whether `viewport_frame_node` calls `setPivot(bbox.center())` explicitly.
2. V2 and V3 answered; the exact orbit expression written down, including whether translation is recomputed.
3. V4 answered; the dolly formula written down, or `viewport_dolly` dropped.
4. V5 answered; `viewport.draw()` either required (and therefore called in every camera handler) or confirmed unnecessary (and called anyway — it is documented as merged/idempotent).
5. V6 answered; if framing is animated by the smooth-transition preference, record it as a documented limitation ("take the snapshot as a second call, not in the same batch") rather than adding a sleep — a sleep inside the poll callback would block Houdini's main thread, the exact hazard `HMCP_LOCAL_TIMEOUT_TRIAGE.md` is about.
6. `cameraPath()` returns `""` in the free case and a real path while looking through a camera, on this build.

---

## Phase 2 — freeze the command set

Decision gate with Sashok, no code. Confirm:

1. Tier 1 ships (`get_viewport_info`, `viewport_frame_node`, `viewport_frame_all`, `viewport_set_view`).
2. `viewport_orbit` ships or is deferred, based on Phase 1's V2/V3 result.
3. `viewport_dolly` ships or is dropped, based on V4.
4. Whether the new tools go into `.claude/settings.local.json`'s allow list. Precedent (`BACKLOG.md`, 2026-08-09 Phase 2 entry) is that only the 9 read tools are auto-allowed and all write tools stay per-call prompts. Recommendation: auto-allow `mcp__houdini2__get_viewport_info` only; leave the camera commands prompt-gated until they have been used a few times. They are non-destructive, but they do move the human's screen.

**Verify Phase 2:** final command list, parameter names, and return-dict shapes written into this document before any file is touched.

---

## Phase 3 — implementation, deploy, verify

The code-writing phase. Six new commands across five files (the usual four, plus `guards.py`).

### 3a. `houdini/plugin/hmcp/guards.py`

Add one function, after `check_expression_language` (~line 224), before the SessionRegistry section:

```python
def check_viewport_camera_free(viewport):
    """Raise if the viewport is looking through, or locked to, a camera node."""
```

Body and rationale as in §4.2. Raises `PermissionError`. No new constants, no new imports.

### 3b. `houdini/plugin/hmcp/intro.py`

Two additions:

```python
def viewport_state(viewport):
    """Read-only snapshot of a hou.GeometryViewport's camera, as a plain dict.
    Shared with build.py's viewport_* handlers so their return payloads and
    get_viewport_info's cannot drift apart."""
    # -> {"viewport": name(), "type": type().name(),
    #     "pivot": [x,y,z], "translation": [x,y,z],
    #     "rotation": [[...],[...],[...]],
    #     "is_perspective": bool, "ortho_width": float,
    #     "camera_path": cameraPath(),         # "" when free
    #     "camera_locked": isCameraLockedToView(),
    #     "resolution": list(resolutionInPixels())}
    # Every field via _safe_attr (intro.py:29) -- this must never raise.

def get_viewport_info():
    """Current SceneViewer/viewport state plus Houdini's update mode.
    Defensive per this module's contract: returns
    {"scene_viewer": False, "message": ...} rather than raising when no
    SceneViewer pane is open."""
    # also returns "update_mode": str(hou.updateModeSetting()),
    #              "snapshot_ready": bool  (SceneViewer present and not Manual)
```

`build.py` will import this (`from . import intro`) — a new but acyclic edge; `intro.py` imports only `commands_spec`.

### 3c. `houdini/plugin/hmcp/build.py`

Add `from . import intro` at the top alongside `from . import guards` (line 22).

Three helpers, in the "Scene bootstrap / eyes" section above `viewport_snapshot`:

```python
def _require_scene_viewport():
    """Shared preflight for every viewport command: a SceneViewer pane must
    exist and have a current viewport. Raises ValueError (not RuntimeError) so
    server.py:253 returns a clean message and writes a REFUSED audit line
    instead of a traceback. Returns (scene_viewer, viewport)."""

def _view_type(view):
    """Map a caller string to a hou.geometryViewportType member through an
    explicit 7-entry dict. Never getattr on the hou namespace from caller
    input -- see the rewrite plan section 4 on bypassable text checks.
    'uv' is deliberately absent."""

def _node_world_bbox(node):
    """World-space hou.BoundingBox for a SOP or Object node.
      Object -> node.displayNode(), transformed by node.worldTransform()
      Sop    -> node.geometry(), transformed by the nearest ancestor Object's
                worldTransform() (geometry().boundingBox() is SOP-local)
      other  -> ValueError naming guards.ALLOWED_NODE_CATEGORIES
    Transform is `bbox * matrix4` -- hou.BoundingBox has no transform() method.
    Raises ValueError on no display node, no geometry, or not bbox.isValid()."""
```

Then the handlers. Each: `guards.require_sandbox_scene()` first line; `_require_scene_viewport()`; `guards.check_viewport_camera_free(viewport)`; mutation inside `with hou.undos.group("MCP: <op>"):` (view changes are not on Houdini's undo stack, so this is for uniformity with the other 14 handlers, not for rollback — say so in a comment); `viewport.draw()`; return `dict(intro.viewport_state(viewport), **extras)`.

```python
def viewport_frame_node(node_path):
    # frameBoundingBox(_node_world_bbox(node)); setPivot(bbox.center()) per V1
    # extras: {"path": ..., "bbox": {"min": [...], "max": [...],
    #          "center": [...], "size": [...]}, "update_mode": ...}

def viewport_frame_all():
    # viewport.frameAll()

def viewport_set_view(view):
    # viewport.changeType(_view_type(view))
    # extras: {"view": view}
    # NOTE in the docstring: changeType restores a stashed view for that type
    # or homes -- whatever was framed before is probably no longer framed.
    # Follow with viewport_frame_node.

def viewport_orbit(dx_degrees=0.0, dy_degrees=0.0):
    # delta = hou.hmath.buildRotate(dy, dx, 0.0).extractRotationMatrix3()
    # composition order and whether translation is recomputed: PHASE 1 / V2,V3
    # extras: {"dx_degrees": ..., "dy_degrees": ...}

def viewport_dolly(factor):          # only if V4 resolved
    # factor must be > 0 -- ValueError otherwise (input sanity, not a guard)
    # orthographic viewport -> setOrthoWidth(orthoWidth() * factor)
    # perspective          -> setTranslation per V4's answer
```

One edit to existing code: add `"viewport": viewport.name()` to `viewport_snapshot`'s return dict (`build.py:298`), per §3.5.

### 3d. `houdini/commands_spec.py`

Append six entries after the `viewport_snapshot` entry (`commands_spec.py:213-222`). `get_viewport_info` gets `"kind": "read"`; the five `viewport_*` commands get `"kind": "write"`. Params:

```python
"get_viewport_info":    {}
"viewport_frame_node":  {"node_path": "str"}
"viewport_frame_all":   {}
"viewport_set_view":    {"view": "str  # persp|top|bottom|front|back|left|right"}
"viewport_orbit":       {"dx_degrees": "float = 0.0", "dy_degrees": "float = 0.0"}
"viewport_dolly":       {"factor": "float"}
```

`COMMAND_NAMES` (line 225) is derived, no edit. Total goes 24 → 30 (29 without dolly).

Remember this file is deployed *into* the package as `hmcp/commands_spec.py` (`deploy_plugin.sh:123-124`), and `describe_commands` serves it — so the doc strings here are what `check_contract.py` and the agent both see.

### 3e. `houdini/plugin/hmcp/commands.py`

Six entries in `_HANDLERS` (`commands.py:22-48`):

```python
    "get_viewport_info": intro.get_viewport_info,
    "viewport_frame_node": build.viewport_frame_node,
    "viewport_frame_all": build.viewport_frame_all,
    "viewport_set_view": build.viewport_set_view,
    "viewport_orbit": build.viewport_orbit,
    "viewport_dolly": build.viewport_dolly,
```

`_build_registry()` (`commands.py:51-72`) raises at import if these disagree with `commands_spec` — no other change.

### 3f. `houdini/bridge/hmcp_bridge.py`

Six `@mcp.tool()` wrappers following the `_call(...)` pattern (`hmcp_bridge.py:153-166`), plus the six names added to `_bridge_tool_names` (`hmcp_bridge.py:359-368`) or the bridge refuses to start.

The docstrings are the model's only instructions, so write them as instructions:

- `viewport_frame_node` — "Aim the Houdini viewport at this node, the equivalent of selecting it and pressing Home. **Call this before viewport_snapshot** — the snapshot only captures whatever the viewport already shows. Accepts a SOP or an Object node. Does not change the user's selection. Requires a sandbox scene."
- `viewport_set_view` — "Switch to a standard view: persp, top, bottom, front, back, left, right. This re-homes the viewport, so follow it with viewport_frame_node to get your object back in frame."
- `viewport_orbit` — "Orbit the viewport camera around its current pivot by relative degrees (dx horizontal, dy vertical). Frame a node first so the pivot is on your subject. Typical values 15-90."
- `get_viewport_info` — "Current viewport name/type, camera pivot and orientation, and whether a snapshot will work right now (Manual update mode blocks it). Read-only, works in any scene."

### 3g. Deploy

```
./scripts/deploy_plugin.sh hmcp-local      # local Houdini 20.5, no VPN, fast loop
./scripts/deploy_plugin.sh hmcp            # pc137 over VPN
```

Both targets already run `hython -m py_compile` on every file (`deploy_plugin.sh:127-133`, `156-161`) and then `check_contract.py`. After deploying, the plugin must be **reloaded in Houdini** via the `hmcp.shelf` Start button (it purges `hmcp*` from `sys.modules`) — otherwise `check_contract.py` reports the exact mismatch seen in the Phase 2 entry of `BACKLOG.md`: the live plugin still running old code in memory. Claude Code must also be restarted to pick up the six new bridge tools.

### Verify Phase 3

Positive:

1. `hython -m py_compile` passes on all six package files plus `commands_spec.py`, on both machines (already automated by the deploy script).
2. The bridge starts without raising — its drift assertion (`hmcp_bridge.py:369-376`) proves the tool set matches `commands_spec`.
3. `scripts/check_contract.py` reports **30 commands agreeing** (29 without dolly), against a reloaded live plugin. Locally: `./scripts/check_contract_local.sh`.
4. `get_viewport_info` returns the current viewport's name, type, pivot, and `snapshot_ready: true` on a sandbox scene with Scene View open.
5. **The acceptance test — reproduce and fix the 2026-08-12 failure.** With `/obj/ice_pattern_test` present but *not* framed and the human's hands off the keyboard: `viewport_frame_node("/obj/ice_pattern_test")` then `viewport_snapshot()`. The JPEG shows the object framed. This is the whole point of the feature; if this passes and nothing else does, ship it.
6. `viewport_orbit(dx_degrees=90)` then `viewport_snapshot()` shows the same object from a visibly different angle, still centred (this is the practical test of V1/V3 — if the object drifts off-frame, the pivot handling is wrong).
7. `viewport_set_view("front")` then `viewport_frame_node(...)` then `viewport_snapshot()` gives a clean orthographic front view.
8. `viewport_frame_all()` on a lost view brings the whole scene back.
9. `viewport_frame_node` on an Object node and on a deep SOP inside it frame the *same* region — proving the SOP-local-to-world transform in `_node_world_bbox` is right. A node with a non-identity object transform must be part of this test, or the bug hides.
10. `viewport` names match between the camera command's return and `viewport_snapshot`'s (§3.5).

Negative — these matter more:

11. **No SceneViewer pane open** (close Scene View): every `viewport_*` command and `viewport_snapshot` return a clean one-line "Precondition: no SceneViewer pane is open…" message, **not a traceback**, and each appears as a `REFUSED` line in `hmcp_audit.log` under the Houdini prefs dir.
12. **Non-sandbox scene open**: all five `viewport_*` commands refuse via `require_sandbox_scene`; `get_viewport_info` still succeeds (it is a read).
13. **Viewport locked to / looking through a camera node**: `viewport_orbit` and `viewport_frame_node` refuse via `check_viewport_camera_free`. Then confirm with `get_node_info` that the camera node's `t`/`r` parms are **unchanged** — this is the whole reason the guard exists.
14. `viewport_set_view("banana")` returns a clean `ValueError` listing the seven allowed views. `viewport_set_view("uv")` also refuses.
15. `viewport_set_view("Perspective")` (the enum member name rather than the short key) refuses — proving there is no `getattr` passthrough. Back it with `rg "getattr\(hou" houdini/plugin/hmcp/` returning zero hits.
16. `viewport_frame_node("/obj/does_not_exist")` → clean "Node not found" from the existing `_require_node` (`build.py:25-31`).
17. `viewport_frame_node` on an empty `geo` object (no display node, or a display SOP producing zero points) → clean "nothing to frame", not a degenerate zero-size box that sends the camera to the origin.
18. `viewport_frame_node` on a `/out` or `/stage` node → refused, naming `guards.ALLOWED_NODE_CATEGORIES`.
19. `viewport_dolly(0)` and `viewport_dolly(-1)` → clean refusal.
20. `rg -nE "os\.remove|shutil|unlink|rmtree|requests|subprocess|zipfile" houdini/plugin/hmcp/` returns **zero** matches (the standing check from the rewrite plan's Phase 2 verify item 8).
21. `hmcp.status()` still shows `pump=eventloop` and a climbing `ticks` after the whole run — the one number that proves the poll loop survived (`HMCP_LOCAL_TIMEOUT_TRIAGE.md`).

Then:

22. Update `houdini/docs/HOUDINI_MCP_REWRITE_PLAN.md`'s "After Phase 3" section with a one-line pointer to this document (root `CLAUDE.md`: nested docs describe *current state*, edited in place).
23. Append one line to `BACKLOG.md` under `## Done`, per root `CLAUDE.md`. Detail — the V1-V6 probe answers, the `RuntimeError`→`ValueError` change, the camera-lock guard's rationale — goes in the commit message body, not the backlog.

---

## Out of scope

- **Pan.** After `viewport_frame_node` the subject is already centred, so pan buys composition only. It needs a screen-space→world basis derived from the rotation matrix and a scale tied to `resolutionInPixels()` / `orthoWidth()` — more API surface and more unverified behaviour than the payoff justifies — and it makes it easy to push the subject off-screen and burn a round trip re-framing. Revisit only if a real use case appears after Tier 1/2 are live.
- **Roll, and any absolute camera transform** (`lookAt(x,y,z)`, `set_camera_transform(...)`, exposing `setViewTransform`). This is the generic escape hatch §3.3 rejects. `viewport_frame_node` + `viewport_orbit` + `viewport_set_view` cover the actual need without it.
- **`saveViewToCamera`, `setCamera`, `lockCameraToView`, `exportViewToCameraContinuously`.** All four exist on `hou.GeometryViewport` and all four convert viewport state into node-graph writes on camera nodes the agent did not create. **The ban is on exposing any of these as an agent-callable command** — never add them to `commands_spec.py`; add the four to the "never write this capability" list alongside `execute_code` and broad `modify_node` for the command surface itself. This does not ban internal plugin use on a node the plugin itself created and registered: `HMCP_FEEDBACK_LOOP_PLAN.md` D2 resolves the apparent contradiction with `HMCP_HEADLESS_RENDER_PLAN.md` §1.3 exactly this way — `render_snapshot` calls `saveViewToCamera` internally on its own `/obj/hmcp_cam`, shipped in that plan's Stage 3.
- **Selection manipulation** (`node.setSelected`, `frameSelected`, `homeSelected`) — §3.2.
- **Viewport display options** (`viewport.settings()`: shading mode, wireframe, background, HDR) and **viewport layout changes** (`setViewportLayout`). Plausible future additions on the same pattern; each would need its own narrow command and its own justification. Not needed to see the work.
- **`hou.geometryViewportType.UV`** — §3.4.
- **Targeting a specific viewport in a quad layout** (`sv.viewports()`, `sv.findViewport(name)`). Deferred; the mismatch is made *visible* via the returned viewport name rather than *fixed*, which is enough until it demonstrably bites.
- **Folding framing into `viewport_snapshot`** as `viewport_snapshot(frame_node=...)`. Saves one round trip but overloads the one command whose entire safety story is "no arguments — the plugin generates the path" (`commands_spec.py:214-222`). The agent already batches parallel tool calls (`BACKLOG.md`, 2026-08-10 Phase 3 entry), so the round trip is nearly free.
- **Headless / offscreen rendering, Karma/Mantra, render cameras, turntables, flipbook ranges.** Separate architecture, being planned in parallel — see `HMCP_HEADLESS_RENDER_PLAN.md`. Rewrite plan §3 keeps "eyes = OpenGL viewport snapshot only" for *this* plan's scope.
- **An `execute_code`-style probe command** to answer V1-V6 from the agent side. Phase 1's probe is a human-pasted throwaway snippet precisely so this capability never has to exist.

---

### Critical Files for Implementation

- `C:\Users\gamai\vfx-mcp\houdini\plugin\hmcp\build.py`
- `C:\Users\gamai\vfx-mcp\houdini\plugin\hmcp\guards.py`
- `C:\Users\gamai\vfx-mcp\houdini\commands_spec.py`
- `C:\Users\gamai\vfx-mcp\houdini\bridge\hmcp_bridge.py`
- `C:\Users\gamai\vfx-mcp\houdini\plugin\hmcp\intro.py`

(also touched, mechanically: `C:\Users\gamai\vfx-mcp\houdini\plugin\hmcp\commands.py` — six `_HANDLERS` lines)

Sources: [hou.GeometryViewport](https://www.sidefx.com/docs/houdini/hom/hou/GeometryViewport.html), [hou.GeometryViewportCamera](https://www.sidefx.com/docs/houdini/hom/hou/GeometryViewportCamera.html), [hou.SceneViewer](https://www.sidefx.com/docs/houdini/hom/hou/SceneViewer.html), [hou.BoundingBox](https://www.sidefx.com/docs/houdini/hom/hou/BoundingBox.html), [hou.geometryViewportType](https://www.sidefx.com/docs/houdini/hom/hou/geometryViewportType.html), [SideFX forum: setting viewport type in Python](https://www.sidefx.com/forum/topic/89521/)
