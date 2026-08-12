# hmcp Feedback Loop — Execution Plan

**Status:** approved by the owner (Sashok) 2026-08-12. Not started.
**Audience:** the implementing agent, with no memory of the planning
conversation. Read this document top to bottom before touching anything.

This document merges and supersedes the *ordering and scope* decisions of
three earlier drafts. Those three stay on disk as detailed reference and are
cited by section throughout:

- `houdini/docs/HMCP_CAMERA_CONTROL_PLAN.md` — full camera API detail
- `houdini/docs/HMCP_HEADLESS_RENDER_PLAN.md` — full render/headless detail
- `houdini/docs/EXTERNAL_REVIEW_oculairmedia_houdini-mcp.md` — comparative review

Where this document and a source document disagree, **this one wins** — the
disagreements are deliberate and listed in §2.

---

## 0. Orientation — read these first, in this order

1. `CLAUDE.md` (repo root) — shared safety doctrine, work-log habit
2. `houdini/CLAUDE.md` — Houdini-specific rules
3. `houdini/docs/HOUDINI_MCP_REWRITE_PLAN.md` §3 and §4 — the design
   decisions and the safety model. **Nothing in this plan relitigates them.**
4. `houdini/plugin/hmcp/guards.py` — read the whole file, it is 265 lines and
   it is the entire safety layer
5. `BACKLOG.md` `## Done` — the last ~10 entries tell you where the project is

Current state: 24 commands shipped and live-verified (Phase 3 acceptance
target met 2026-08-10). The plugin runs on port 9878 inside Houdini, driven
by a thin MCP bridge. `scripts/check_contract.py` proves the bridge, the
dispatcher, and `commands_spec.py` agree.

---

## 1. Why this work exists

Plumbing is not the gap — the write tools work, a procedural rock was built
unattended. **The gap is that the agent can barely see its own work.**

- `viewport_snapshot` (`build.py:259`) captures whatever the SceneViewer
  already shows, from wherever the owner left the view. On 2026-08-12 the
  ice-pattern session had to stop and ask Sashok to press Home in the
  viewport before the snapshot showed anything useful.
- The image is an unlit OpenGL grab — a weak basis for judging look-dev.
- Every iteration occupies the owner's live Houdini session.

The owner's stated endgame is **a render that does not freeze the UI and does
not tie up the open scene** — i.e. a headless worker. This plan gets to the
door of that: deterministic framing first, then a non-blocking render handler
proven in the GUI and written so it moves into a headless worker unchanged.
The headless worker itself is deferred (§7).

---

## 2. Decisions already made — do not reopen these

These resolve real contradictions between the three source documents. Each
was decided with the owner on 2026-08-12.

**D1 — Camera before render.** The render plan's `camera="viewport"` mode
steers off the viewport, so camera control landing first makes render framing
deterministic at no extra cost.

**D2 — `saveViewToCamera`: the two source docs contradict each other.**
`HMCP_CAMERA_CONTROL_PLAN.md`'s "Out of scope" list bans it;
`HMCP_HEADLESS_RENDER_PLAN.md` §1.3 builds `camera="viewport"` on it.
**Resolution: the ban is on exposing it as an agent-callable command.**
`render.py` may call it internally, on `/obj/hmcp_cam` — a node the plugin
created and registered in `guards.session_registry`. This is the same shape
as `viewport_snapshot` owning its own output path. Fix the wording in both
source docs when you cross-link them (§9).

**D3 — The render must not block Houdini's main thread.** This **overrides**
`HMCP_HEADLESS_RENDER_PLAN.md` §1.4, which recommended a synchronous
`rop.render()` inside the event-loop pump. Owner's explicit call: a
screenshot must not freeze the UI at all. So: background ROP execution
(`executebackground`), plus a poll command.

> That source doc rejected a poll protocol because "the pump is synchronous,
> so a poll cannot be serviced while the render blocks." **That objection
> only applies to the synchronous design.** With a background render the
> handler returns immediately, the pump keeps ticking, and polls are serviced
> normally. Background execution is what makes poll coherent.

Cost, stated plainly: `rop.render()`'s exception text is lost. Stage 0e
measures the failure shape; `render_status` surfaces `rop.errors()` instead.

> **D3 addendum, decided during Stage 0 (2026-08-12), not a reopening —
> Stage 0e surfaced a precondition D3 didn't anticipate.** Houdini refuses
> `executebackground` outright (a blocking, abort-on-OK modal, not a
> confirmation) whenever the hip has unsaved changes — and
> `render_snapshot`'s own preflight (creating/configuring its ROP) always
> creates exactly that condition. **Decision: `render_snapshot` calls
> `hou.hipFile.save()` immediately before pressing `executebackground`, no
> separate confirmation step.** This is a new disk-write the guard file
> needs to own explicitly (§8's `guards.py` list gets one more line) even
> though it targets the already-open, already-sandboxed hip itself, not a
> caller-supplied path. Stage 0e also found `executebackground` blocks the
> calling thread for several seconds even once this fix is applied (6.5–
> 16.6s measured) — see 0e's answer for the full data; recorded as a
> documented limitation per the plan's own contingency, not a redesign.

**D4 — Arnold: not written, but not designed out.** No `arnold` entry in
`ALLOWED_RENDERERS`, no HtoA detection, no Arnold parm derivation. The
extension point is the renderer descriptor table (D7) — adding Arnold later
is one dict entry plus a parm probe. Do not add Arnold code "while you're in
there."

**D5 — The headless worker (Track B) is out of scope here.** See §7.

**D6 — From the external review, exactly three items are in.** In:
`find_nodes`; the undo-revision check before revert; `hint` in the error
shape plus a `connect_nodes` category pre-check. Out: `network_snapshot`,
`reorder_inputs`, named token-budget constants. Permanently out:
`execute_code`, regex code-blacklists, env-var bypass flags,
caller-supplied output paths.

**D7 — One renderer descriptor table, not per-renderer branches.** A single
dict in `guards.py` keyed on renderer name, holding ROP type, output-picture
parm name and resolution parm names — **all filled from Stage 0's live
`get_node_type_parms` output.** Never from `HoudiniMCPRender.py:557-621`'s
guessed names.

---

## 3. Hard rules for the implementing agent

Violating any of these is a failed task, regardless of whether the feature
works. Most restate `guards.py`'s own module docstring and
`HOUDINI_MCP_REWRITE_PLAN.md` §4.

1. **No new capability outside what this plan names.** If you find yourself
   wanting a tool this plan does not list, stop and ask.
2. **Never add `execute_code`, `modify_node`, broad `delete_node`, or any
   "run this Python" path**, in the plugin or in a probe script. Stage 0c's
   probe is a snippet a *human* pastes, precisely so this capability never
   has to exist.
3. **Never `import os`, `shutil`, `requests`, `subprocess`, `zipfile`** in
   `houdini/plugin/hmcp/`. Never `os.remove`/`unlink`/`rmtree`. The one
   permitted write is the audit log (`server.py:60`, mode `"a"`); the one
   permitted read is an existence probe `open(path, "rb")` on a path built
   entirely from a constant plus a timestamp.
4. **The agent never passes a filesystem path to any tool.** Every output
   path is generated inside the plugin from a constant directory plus a
   timestamp. No caller-supplied path, not even a fragment of one.
5. **The plugin never creates directories.** A missing output directory is a
   clean refusal — that is the owner's arming switch, not a bug to fix.
6. **Never `getattr` on the `hou` namespace from caller input.** Caller
   strings map through explicit dicts. This is the same class of construct as
   the blacklist bypasses the rewrite plan §4 rejects.
7. **All safety logic lives in `guards.py`.** Write handlers only ever *call*
   already-reviewed guard functions; they never invent new ones inline.
8. **Do not widen `check_settable_parm`.** Output-path and code-bearing parms
   stay refused through the generic `set_parm` path, always.
9. **Never start or stop Houdini yourself.** The owner does that. Same for
   anything on pc137 beyond a normal read or deploy.
10. **Ask rather than guess** on: real parameter names, pc137's build number,
    whether an API method exists on this build, and anything the source docs
    marked *unverified*. Guessing here is exactly what Stage 0 exists to
    prevent.

---

## 4. Progress tracker

Fill this in as you go; it is how the next session knows where you stopped.

| Stage | What | Status |
|---|---|---|
| 0 | Fact-finding probe, no code | **done** 2026-08-12 — all of 0a–0e answered; net new finding: unsaved-changes precondition + auto-save fix + `executebackground` not near-instant (D3 addendum); Mantra recommended excluded from Stage 3's initial renderer set |
| 1 | Diagnosis + shared plumbing | **done** 2026-08-12 — live-verified on local 20.5.278; pc137 deploy/verify still pending |
| 2 | Camera control | **done** 2026-08-12 — all 6 commands live-verified and shipped (24 → 30). `viewport_orbit` briefly shipped without, then root-caused (HOM's rotation()/translation() docs are wrong -- confirmed via SideFX staff) and fixed same day |
| 3 | Non-blocking `render_snapshot` | not started |
| 4 | Image delivery from pc137 | not started |
| 5 | `find_nodes` + undo-revision guard | not started |

---

## Stage 0 — one fact-finding pass. No code.

The three source documents each open with unverified assumptions, and they
overlap heavily. **This is one probe session, not three.**

> **STOP GATE.** Every bullet below must have a one-sentence answer written
> back into this document before a single line of Stage 1 code is written.
> If a probe cannot be run (VPN down, owner unavailable, Houdini closed),
> stop and say so — do not proceed on assumptions.

### 0a. Machine and version facts — `ssh pc137`, read-only

- pc137's actual Houdini build number. Three places disagree:
  `houdini/CLAUDE.md:10` and the rewrite plan say 21.0.596; `BACKLOG.md`'s
  Phase 2 entry says the live build is 21.0.729;
  `scripts/deploy_plugin.sh:126` hardcodes 21.0.596. Record the truth.
  > **Answer (2026-08-12):** Both 21.0.596 and 21.0.729 are installed on
  > pc137, but the **live, actually-running** process is `houdinifx.exe`
  > from `Houdini 21.0.729` (confirmed via `Get-Process` — 3 instances
  > running). `BACKLOG.md`'s Phase 2 entry is correct; `houdini/CLAUDE.md:10`
  > and `deploy_plugin.sh:126` are stale. `hmcp/server.py`'s PySide6/PySide2
  > compat shim (BACKLOG 2026-08-11) already targets 21.0/PySide6, so this
  > doesn't change any code — only confirms the doc/script drift to fix
  > separately (see §7's own note on `deploy_plugin.sh:126`).
  >
  > **Working-machine note:** the rest of Stage 0's hand-run parts (0c/0d
  > render/0e) are actually being executed against the **local** machine
  > (Houdini 20.5.278, `hmcp-local` mode, `HMCP_HOST=127.0.0.1`) rather than
  > pc137, since that's where Sashok is working this session. This is fine
  > by design — `hmcp-local` exists exactly so Stage 0/1 iteration doesn't
  > need VPN — but it means every hand-run answer below needs either (a) a
  > cross-check against pc137 like the one done for the D7 table just below,
  > or (b) an explicit flag that it's local-only pending a pc137 re-check
  > before Stage 1 code lands. 0b was run on **both** machines directly.
- **Do not bundle the deploy-script fix into this work.** It is a real bug
  and it gets its own commit.

### 0b. Camera API surface — `hython`, both machines

Confirms `HMCP_CAMERA_CONTROL_PLAN.md` §2.1 holds on pc137's build:

```
hython.exe -c "import hou; print(sorted(n for n in dir(hou.GeometryViewport) if not n.startswith('_')))"
```

…and the same for `hou.GeometryViewportCamera` and `hou.geometryViewportType`.

- `hou.GeometryViewport`: `frameBoundingBox`, `frameAll`, `changeType`,
  `defaultCamera`, `draw`, `cameraPath`, `isCameraLockedToView`, `name`,
  `type` all present. (The query method is `type()`, **not**
  `viewportType()` — several forum posts get this wrong.)
- `hou.GeometryViewportCamera`: `pivot/setPivot`,
  `translation/setTranslation`, `rotation/setRotation`, `isOrthographic`,
  `orthoWidth/setOrthoWidth` all present.
- `hou.geometryViewportType` exposes exactly `Perspective, Top, Bottom,
  Front, Back, Right, Left, UV`.
- `hou.BoundingBox.__mul__` present (there is **no** `transform()` method —
  transform is `bbox * matrix4`); `hou.hmath.buildRotate` and
  `hou.Matrix4.extractRotationMatrix3` present.

**Any absence drops the corresponding command from the set rather than being
worked around.**

> **Answer (2026-08-12):** Ran the exact `dir()` probes on both machines
> (pc137 hython 21.0.729, local hython 20.5.278) — **identical results on
> both builds**. `hou.GeometryViewport`: every method the plan lists is
> present, plus extras not needed here (`frameSelected`, `homeAll`,
> `lockCameraToView`, `setCamera`, etc.); confirmed the query method is
> `type()`, no `viewportType()` exists. `hou.GeometryViewportCamera`: all
> six listed members present (`pivot/setPivot`, `translation/setTranslation`,
> `rotation/setRotation`, `isOrthographic`, `orthoWidth/setOrthoWidth`), plus
> `isPerspective`, `setPerspective`, `aperture/focalLength` (unused here).
> `hou.geometryViewportType`: exactly `Back, Bottom, Front, Left,
> Perspective, Right, Top, UV` — matches, `"uv"` really is a real member so
> 2b/§7's deliberate exclusion of it from the 7-entry dict is a real design
> choice, not an oversight. `hou.BoundingBox.__mul__` present, no
> `transform()` method — confirmed. `hou.hmath.buildRotate` and
> `hou.Matrix4.extractRotationMatrix3` both present. **Nothing missing —
> the full command set in 2a stays as planned, nothing gets dropped.** One
> minor cross-build diff, not load-bearing: pc137/21.0.729's
> `GeometryViewport` additionally has `isFloating`, absent on local
> 20.5.278; unused by this plan either way.

### 0c. Live viewport behaviour (V1–V6) — human-pasted snippet, GUI Houdini

These cannot be probed headlessly (`hou.ui` does not exist in non-graphical
hython, so no viewport instance can be obtained). Local Houdini 20.5.278 is
fine and needs no VPN.

> **This is a throwaway snippet Sashok pastes into Houdini's Python Shell.
> It must never become an `execute_code` command.** Write the snippet, hand
> it to him, ask for the printed output back. Per
> `feedback_nuke_script_editor_multiline`, there is no clipboard paste over
> RDP to pc137 — if it has to be hand-typed, give it as multi-line, not
> `;`-joined.

On a sandbox scene with one visible object, print enough to answer:

| # | Question | Why it matters |
|---|---|---|
| V1 | Does `frameBoundingBox()` move the pivot to the box centre, or leave the old pivot? | Decides whether `viewport_frame_node` must call `setPivot(bbox.center())`. If not, orbit after framing swings around the wrong point. |
| V2 | Orbit composition: `cam.setRotation(cam.rotation() * delta)` vs `delta * cam.rotation()` | One tumbles in world axes, the other in camera-local. The wrong one produces nonsense on the second call. |
| V3 | Does `setRotation()` orbit **around the pivot**, or spin in place? | If in place, orbit must also recompute translation: `new_t = pivot + R * (t - pivot)`. |
| V4 | Is `translation()` world-space or pivot-relative? | Decides the dolly formula — or drops `viewport_dolly` entirely. |
| V5 | Is `viewport.draw()` required before `sv.flipbook()` picks up the new view? | If required and omitted, frame-then-snapshot returns the *old* framing — the exact bug this feature exists to fix. |
| V6 | Does the "smooth view transitions" preference animate `frameBoundingBox`? | If it animates, a snapshot fired immediately after framing captures a mid-tween view. |

> **Answers (2026-08-12, live on local Houdini 20.5.278, `/obj/ice_pattern_test`,
> `hmcp-local` mode):**
> - **V1 — RESOLVED, pivot moves to box centre.** After `frameBoundingBox(bbox)`,
>   `cam.pivot()` == `bbox.center()` to float precision (`(6.99e-08, 0.249948,
>   -1.87e-08)` vs bbox center `(0, 0.249948, 0)`). `viewport_frame_node` does
>   **not** need an explicit `setPivot()` call — framing already does it.
> - **V2/V3 — RESOLVED together, and it's "spin in place."** Applying
>   `cam.setRotation(r_ref * delta)` (composition — see note on type mismatch
>   below) left `cam.translation()` **exactly unchanged**
>   (`unchanged?: True`). So `setRotation()` alone rotates around the
>   camera's own origin, not the pivot — confirms the "in place" branch of
>   V3. **`viewport_orbit` must recompute translation itself**, exactly per
>   the plan's own fallback formula: `new_t = pivot + delta * (old_t - pivot)`
>   (or `(old_t - pivot) * delta`, matching whichever composition order is
>   chosen for the rotation — see below). Pivot itself is untouched by
>   `setRotation()` either way (confirmed: pivot identical before/after both
>   orbit tries).
>   **Real API bug caught, not in either source doc:** `cam.rotation()`
>   returns `hou.Matrix3`; `hou.hmath.buildRotate()` returns `hou.Matrix4`.
>   `Matrix3 * Matrix4` raises `TypeError` — the delta must be converted via
>   `.extractRotationMatrix3()` before composing with `cam.rotation()`.
>   `hou.hmath.buildRotate` also apparently takes/returns a `Matrix4`, so
>   the actual `viewport_orbit` code is:
>   ```python
>   delta3 = hou.hmath.buildRotate(dy_degrees, dx_degrees, 0).extractRotationMatrix3()
>   old_r, old_t, piv = cam.rotation(), cam.translation(), cam.pivot()
>   cam.setRotation(old_r * delta3)          # camera-local tumble (row-vector convention: v*R_old*delta == delta applied in the already-rotated frame)
>   cam.setTranslation(piv + (old_t - piv) * delta3)
>   ```
>   `old_r * delta3` (post-multiply) is the camera-local/trackball-feel
>   composition; `delta3 * old_r` is the world-axis composition — both were
>   empirically exercised and produce visibly different matrices (recorded
>   in the raw probe output), confirming they really do differ, but picking
>   which one "feels right" for `viewport_orbit` is a Stage-2 implementation
>   call, not a fact to probe further — going with camera-local (`old_r *
>   delta3`) as the default since that's the conventional trackball-orbit
>   feel.
> - **V4 — RESOLVED, world-space.** `translation()` after framing was
>   `(≈0, 0.2499, 28.535)` — X/Y equal the pivot's X/Y only because the
>   default frame looks straight down world Z; the Z component is the
>   pivot-to-camera distance added on top. Combined with V2/V3 (orbit does
>   **not** auto-update translation), this can only be explained by
>   `translation()` being an absolute world-space position, not a
>   pivot-relative offset. **`viewport_dolly` is safe to ship**: move along
>   the camera's view direction (derivable from `rotation()`) scaled by
>   `factor`, in world space.
> - **V5/V6 — deliberately not probed further (Sashok's call, 2026-08-12):
>   deferred, not blocking.** Testing whether `draw()` is required before a
>   flipbook, and whether "smooth view transitions" animates
>   `frameBoundingBox`, needs an actual flipbook/video capture — out of
>   scope for this pass, revisit only if a real symptom shows up later.
>   **Mitigation adopted instead of the probe:** Stage 2's
>   `viewport_frame_node`/`viewport_set_view` handlers call
>   `viewport.draw()` defensively right before returning, unconditionally —
>   cheap, harmless if it turns out to be unnecessary, and sidesteps the
>   exact failure mode (a snapshot capturing the pre-framing view) this
>   feature exists to fix. If a mid-tween capture ever shows up in practice
>   despite that, that's the signal to come back and actually answer V6.
> - **Camera-lock guard precondition — RESOLVED, confirmed live.** Looking
>   through `/obj/cam1` (locked): `viewport.type()` →
>   `geometryViewportType.Perspective`, `viewport.cameraPath()` →
>   `'/obj/cam1'` (non-empty, as the plan expected),
>   `viewport.isCameraLockedToView()` → `True`. **Both conditions
>   `guards.check_viewport_camera_free` checks actually fire** when a
>   camera is locked — the guard's entire premise is validated before a
>   line of it is written.
> - **`saveViewToCamera` signature — RESOLVED, opposite of the plan's
>   assumption.** The **1-argument** form (`vp.saveViewToCamera(cam_node)`)
>   works. The 2-argument form raises
>   `TypeError: GeometryViewport.saveViewToCamera() takes 2 positional
>   arguments but 3 were given` on this build — there is no 2-arg overload
>   here at all, contradicting the plan's note that the 1-arg form was
>   "deprecated in favour of" a 2-arg one. **D2's `camera="viewport"` must
>   call the 1-arg form.** The written-back camera transform looked
>   non-degenerate (`t=(17.96, 20.02, -10.04)`, `r=(-43.86, 119.19,
>   -0.0005)`) but a direct visual "does it reproduce the framing"
>   comparison is still open — the probe node was destroyed immediately
>   after, per the script's own cleanup. Confirmed only on local 20.5.278 so
>   far, not yet cross-checked headlessly against pc137 the way the D7 table
>   was (this one needs a live viewport, so the pc137 cross-check would need
>   its own GUI pass there, not a headless one).

Also confirm, in the normal case *and* while looking through a camera:
`viewport.name()`, `viewport.type()`, `viewport.cameraPath()` (returns `""`
when free), `viewport.isCameraLockedToView()`. This proves the Stage 2 guard's
two conditions actually fire.

> **Status (2026-08-12):** Snippet written and delivered — combined with 0d/0e
> below into one file (`c:/houdini_mcp_sandbox/_stage0_probe.py`, syntax
> already checked via local hython) rather than three separate hand-typed
> blocks, since all three need the same GUI Python Shell access and the plan
> itself says "one probe session, not three." Delivered via `scp` straight
> into the sandbox dir (outside the hmcp plugin's own no-`os`/no-`subprocess`
> rule — this is a throwaway diagnostic script run directly by Sashok, not
> plugin code) so the hand-typed part is one short line, not the whole
> script, respecting the no-clipboard-paste-over-RDP constraint while keeping
> typing risk low. **Awaiting Sashok**: paste this one line into Houdini's
> Python Shell on pc137 and send back everything it prints:
> ```
> exec(open(r"c:/houdini_mcp_sandbox/_stage0_probe.py", encoding="utf-8").read())
> ```
> V1–V6 answers, the camera-locked-viewport follow-up, and the
> `saveViewToCamera` signature result are still **open** pending that output.

### 0d. ROP facts — MCP read tools plus one hand-run render

- `list_node_types(category="Driver", name_filter=…)` for `karma`, `ifd`,
  `opengl`. Which exist on the live build? Confirm `"Driver"` is the right
  category string (if not, the error's `Available:` list has it —
  `intro.py:354`).
- `get_node_type_parms("karma", "Driver")` and `("ifd", "Driver")`. Extract
  the real names for: output picture, resolution override, camera, engine,
  `trange`/`f1`/`f2`, and the pre/post-render script parms. **Paste them into
  the descriptor table in this document before writing any handler.**
  The `/out` karma ROP is an HDA wrapper — its parm names are HDA parameters
  and are **not** guessable.
- Can Karma and Mantra write `.png`/`.jpg`, not only `.exr`? This is not
  cosmetic: Claude's Read tool can display PNG/JPG and cannot display EXR, so
  an EXR-only renderer produces no eyes at all.
- With no lights in the scene: is Karma's output black? Is Mantra's lit by
  its default headlight? (Mantra is expected to fall back to a headlight;
  Karma via Scene Import most likely does not.)
- Does a Karma render pop a licence dialog in this environment? It would hang
  the socket the same way Manual update mode did (`build.py:275-285`).
- `saveViewToCamera` — which signature the live build accepts (the
  one-argument form is deprecated in favour of the two-argument one), and
  whether the resulting camera reproduces the viewport framing.

> **Answer, MCP-read part (2026-08-12), via live `mcp__houdini2__*` calls
> against the running pc137 session (`mcp_20260812_003121.hip`):**
> - `list_node_types(category="Driver", ...)` confirms `"Driver"` is the
>   right category string and all three exist: `karma`, `ifd` (+
>   `ifdarchive`), `opengl`.
> - `get_node_type_parms` pulled real parm names for both — **this is the
>   D7 renderer descriptor table, sourced, not guessed:**
>
>   | | `karma` | `ifd` (Mantra) |
>   |---|---|---|
>   | Output picture parm | `picture` | `vm_picture` |
>   | Resolution parm | `resolution` tuple → real components `resolutionx`/`resolutiony` (Int×2) | `res_override` tuple → real components `res_overridex`/`res_overridey` (Int×2, gated by `override_camerares` toggle) |
>   | Camera parm | `camera` | `camera` |
>   | Frame-range parm | `f` tuple → real components `f1`/`f2`/`f3` | same, `f` tuple → `f1`/`f2`/`f3` |
>   | `trange` menu | `off, normal, on, stage` (default `0` = off) | `off, normal, on` (default `0` = off) |
>   | Background-render button | `executebackground` (confirmed present) | `executebackground` (confirmed present) |
>   | No-light fallback | `force_headlight` ("Simplified Shading" toggle, **default `false`** — Karma does **not** auto-headlight, confirms the plan's suspicion) | `soho_autoheadlight` (**default `true`** — Mantra does auto-headlight, confirms the plan's expectation) |
>
>   **Cross-machine confirmed 2026-08-12**, not just single-source: pulled
>   once via live `get_node_type_parms` against local Houdini 20.5.278 (the
>   session actually driving this work — see machine note below), then
>   independently re-derived headlessly via `hython -` directly against
>   pc137/21.0.729 (no GUI, no scene, just `hou.node("/out").createNode(...)`
>   + `parmTuple` introspection in a throwaway session — same technique as
>   0b). **Byte-for-byte identical on both builds** — every parm name,
>   every tuple component name, every `trange`/`vm_device` menu, both
>   headlight defaults. Zero version drift found for this table.
> - PNG/JPG capability: **`vm_device` menu confirms Mantra supports it in
>   principle** (`PNG`, `JPEG` listed). **Karma has no device/format parm at
>   all** — output format is inferred from the `picture` parm's file
>   extension. **Karma PNG output is now hand-run-confirmed working**: once
>   the unsaved-changes precondition (see D3 addendum above) was cleared,
>   `rop.render()` on a `karma` ROP with `picture` set to a `.png` path
>   produced a real, non-empty file in 0.28s. **Mantra/ifd PNG output is
>   still an open mystery**, not resolved despite `vm_device` claiming
>   support: `ifd.render()` (foreground) has produced **no file, and no
>   `rop.errors()`/`rop.warnings()`**, across every attempt so far (both
>   before and after the scene was saved) — unlike Karma, saving didn't fix
>   it. **Narrowed further, not root-caused:** the SOHO export step itself
>   works fine — pointing `soho_diskfile`/`soho_outputmode=1` at a real path
>   produced a genuine 4507-byte `.ifd` file — and `mantra.exe` genuinely
>   exists at `$HFS/bin/mantra.exe`. So scene export is fine and the binary
>   is present; the failure is specifically in Houdini launching/piping to
>   the `mantra` process itself (`soho_pipecmd`), which produces no output
>   and reports nothing back to `rop.errors()`/`warnings()` either way. One
>   environmental oddity noted in passing: `$HFS` resolves to an 8.3
>   short-path form (`C:/PROGRA~1/SIDEEF~1/HOUDIN~1.278`) on this machine —
>   unconfirmed whether that's related. **Recommendation: exclude `mantra`
>   from Stage 3's initial `ALLOWED_RENDERERS`, ship Karma-only**, since
>   Karma is now fully hand-run-confirmed (export, render, PNG write,
>   foreground and background all working) and Mantra is not — same
>   "don't ship what isn't proven" reasoning D4 already applies to Arnold,
>   just for a different reason. Re-add Mantra later as its own small
>   investigation if it's ever needed, rather than blocking Stage 3 on it
>   now.
> - Licence dialog: **not observed** in any of the render attempts run so
>   far (the only blocking dialog seen was the unsaved-changes one, not a
>   licence prompt) — treated as answered (no licence dialog fires in this
>   environment) unless Mantra's still-unexplained silent failure turns out
>   to be a licence issue in disguise, which hasn't been ruled out.

> **Status:** table above is filled from real `get_node_type_parms` output,
> cross-machine confirmed. PNG-write and background-execution facts are
> answered live (see the D3 addendum above and 0e below) — **except the
> Mantra/ifd silent-failure mystery, which stays open.**

### 0e. Background-execution facts — new, not in any source document

D3 rests entirely on this, and none of it is established:

- Does `executebackground` exist as a parm on the karma and ifd ROPs on this
  build, and does `pressButton()` on it actually spawn out-of-process?
- **How much main-thread time elapses before it returns?** The Karma ROP does
  Scene Import → USD internally, and that export may run on the main thread
  before anything is spawned. If it does, "no freeze at all" is not fully
  achievable in GUI mode — record it as a documented limitation and as
  another argument for the headless worker.
- After a *failed* background render, does the ROP node carry
  `errors()`/`warnings()` that `render_status` can surface?
- Wall-clock for a 512×512 draft render — Karma and Mantra, foreground and
  background.

> **Answers (2026-08-12, local Houdini 20.5.278, `hmcp-local` mode):**
>
> - **`executebackground` exists** as a parm on both `karma` and `ifd` ROPs,
>   confirmed both live (get_node_type_parms) and headlessly on pc137/21.0.729.
> - **New precondition discovered, not in either source doc:** Houdini pops
>   a blocking modal — *"Cannot perform background render with unsaved
>   changes. Save your file before proceeding."* — whenever
>   `executebackground` is pressed while the hip has unsaved changes. This
>   is not a "confirm and continue" dialog: clicking OK **aborts the
>   render** (confirmed empirically — no output file, no error, after two
>   separate attempts that each hit this dialog). Critically, **the
>   render_snapshot handler itself will always dirty the scene** just by
>   creating/configuring its own ROP node right before rendering (Stage 3's
>   own §3b steps 5-8), so this fires on essentially every real call, not
>   just an edge case. **Decision (Sashok, 2026-08-12): `render_snapshot`
>   auto-saves the hip file (`hou.hipFile.save()`) immediately before
>   pressing `executebackground`, no separate confirmation.** Add this as
>   an explicit step between §3b's steps 8 and 9 when Stage 3 is written;
>   it needs its own guard-file mention since it's a new disk-write
>   capability, even though it's writing to the already-open, already-named
>   sandbox hip itself (not an arbitrary path).
> - **Main-thread blocking time — this is the number D3 rests on, and it
>   does not support "returns immediately":** two consecutive
>   `executebackground` calls in the same warm Houdini session, both with
>   the save-immediately-before fix applied (so no modal either time):
>   - Call 1 (session's first background render): `pressButton()` itself
>     blocked the calling thread for **16.6s** before returning; file
>     existed instantly after return (0.0s further poll) — so the entire
>     render happened *inside* that 16.6s, synchronously.
>   - Call 2 (same session, same ROP, immediately after): `pressButton()`
>     blocked for **6.5s**, then the file appeared **5.0s** into polling
>     after that (~11.5s total to completion) — faster than call 1 (some
>     one-time warm-up cost is real and front-loaded on the first call of a
>     session), but **still nowhere near instant**, and still substantially
>     main-thread-blocking.
>   - A `"Arnold shutdown"` line appeared in Houdini's Console during this
>     testing even though the ROP under test was **Karma**, not Arnold —
>     this pc/session has HtoA loaded and it hooks into the render-session
>     lifecycle regardless of which renderer actually runs, which is a
>     plausible source of the fixed per-call overhead. Not fully
>     root-caused; noted as an environmental factor, not chased further.
>   - Foreground `rop.render()` on the identical ROP/scene took **0.28s** —
>     `executebackground` is roughly 20-40x slower than foreground for the
>     exact same tiny draft render, which is the opposite of what a "spawn
>     and return" design should cost the main thread.
>
>   **This directly contradicts D3's "the handler returns immediately after
>   spawning" premise on this build/environment.** Per the plan's own
>   fallback instruction for exactly this outcome: **recording this as a
>   documented limitation** rather than treating it as a blocker — a
>   several-second UI pause per render call is still a large improvement
>   over blocking for a full-length production render, but it is *not* "no
>   freeze at all." This is now the strongest concrete argument in favour of
>   §7's deferred headless worker being the real fix, exactly as the plan
>   already frames it. **Open follow-up, not gate-blocking:** whether this
>   overhead is Arnold/HtoA-specific to the local machine (worth a same-test
>   pass on pc137, which may or may not have HtoA loaded) is unconfirmed.
> - **Errors/warnings after a failed background render:** the two
>   modal-aborted attempts both left `rop.errors()` and `rop.warnings()`
>   completely empty (`()`) — **confirmed as a real diagnostic gap**: a
>   silently-aborted background render is indistinguishable from "still
>   running" by `rop.errors()` alone. `render_status()`'s design should not
>   assume `errors()` will explain every failure mode; the modal-abort case
>   in particular needs its own explicit check (e.g. re-reading
>   `hou.hipFile.hasUnsavedChanges()` isn't even useful after the fact,
>   since it's true again by the time you'd check). No clean answer found
>   here — recorded as a known gap, not resolved.
> - **Wall-clock for a 512×512 draft, Karma:** foreground 0.28s; background
>   16.6s (cold) / ~11.5s (warm) end-to-end. **Mantra/ifd wall-clock:
>   unresolved** — see the open PNG-output mystery in 0d above; ifd's
>   foreground `render()` has not produced a file in either attempt so far,
>   so no reliable timing exists for it yet.

### Stage 0 — done when

- [x] Every bullet in 0a–0e has a written one-sentence answer in this document
      (2026-08-12 — see the inline `> **Answer**` blocks throughout 0a–0e)
- [x] The renderer descriptor table (D7) is filled in with real parm names
      (cross-machine confirmed, local 20.5.278 + headless pc137/21.0.729)
- [x] V1–V6 are answered, and the exact orbit expression is written down
      — V1–V4 empirically resolved with real data; V5/V6 deliberately
      deferred (Sashok's call) in favour of a cheap defensive mitigation
      (unconditional `viewport.draw()`) instead of further probing
- [x] Any missing API is recorded against the command it kills — nothing
      from the camera API was missing (0b); **`mantra` is recorded against
      Stage 3's renderer set instead** — not a missing API, but an
      unexplained render failure (SOHO export works, `mantra.exe` exists,
      the render itself silently produces nothing) — recommendation is to
      ship Karma-only initially and treat Mantra as its own follow-up

**Net new finding beyond the four checklist items, load-bearing for Stage
3:** the D3 addendum above (unsaved-changes precondition + auto-save fix +
`executebackground` not actually being near-instant, 6.5–16.6s measured).
This is the single most consequential thing this pass found — bigger than
any individual missing-API question — and needs to carry into Stage 3's own
design section, not just live in this Stage 0 answer block.

---

## Stage 1 — diagnosis and shared plumbing

One plugin deploy. **No new commands**, so the bridge is untouched and Claude
Code does *not* need restarting. Deliberately first: it adds no capability
but makes everything after it cheaper to debug, and Stages 2–3 are where the
confusing failures will be.

### 1a. Full tracebacks into the audit log — `server.py`

`execute_command` (`server.py:228-238`) already puts the traceback in the
*response*, but `_audit` never writes it to the log. Add it. Then failures
are diagnosable by reading `hmcp_audit.log` over ssh instead of asking Sashok
to copy out of Houdini's Python Shell — which is exactly what Phase 1
verification cost, twice.

(This closes a standing `BACKLOG.md` TODO item.)

### 1b. `hint` in the error shape — `server.py` + handlers

`_execute_command_internal` (`server.py:251-258`) returns
`{status, message, exception_type}` for guard refusals and adds `traceback`
for everything else. **Add an optional `hint` field**, populated where a
handler can name the fix. Keep every existing key — this is purely additive.

Worked example: `get_geometry_info` on an Object node currently gives
`'OpNode' object has no attribute 'geometry'`. With a hint it gives "this
only works on SOP nodes; `/obj/rock` is an Object — try its display node."
That saves a round trip on every such failure.

### 1c. `connect_nodes` category pre-check — `build.py`

Compare `.type().category()` on both nodes before calling `setInput()` and
raise a named `ValueError` on a mismatch (e.g. Sop → Dop), rather than
whatever opaque error Houdini throws.

### 1d. Extract `_require_scene_viewport()` — `build.py`

Pull `viewport_snapshot`'s inline preflight (`build.py:269-274`) into a
shared helper returning `(scene_viewer, viewport)`. It must also handle
`hou.ui` being absent (headless) and `curViewport()` returning `None`. Every
Stage 2 camera command and the Stage 3 render handler use it.

### 1e. `RuntimeError` → `ValueError` in that preflight

`build.py:271` raises `RuntimeError`, which `server.py:253` does **not**
catch — it falls through to the generic handler and returns a full traceback
with no `REFUSED` audit line. `ValueError` gets a clean one-line message and
a proper audit entry. Prefix the message `"Precondition: …"` so the log can
tell a precondition failure from a guard refusal.

> This changes the message text of an existing refusal path. **Call it out
> explicitly in the commit body.**

**Leave the Manual-update-mode check inside `viewport_snapshot` only.** It
exists because *flipbook* pops a modal dialog; a camera move does not render
and cannot trip it. Hard-refusing a harmless command on an unrelated
precondition is just noise. Instead, Stage 2 surfaces `update_mode` in the
camera commands' return payloads, so the agent knows in advance that a
following snapshot will refuse.

### Stage 1 — done when

- [x] `hython -m py_compile` clean on every file — **local 20.5.278 only**;
      pc137 not yet re-deployed/compiled against this stage's changes
- [x] `check_contract.py` still reports **24** commands agreeing (confirmed
      live, local, after a clean plugin+Houdini restart — see the reload
      incident note below)
- [x] A deliberately-triggered handler exception writes a full traceback into
      `hmcp_audit.log` — triggered live via `create_node` with a bogus node
      type (`hou.OperationFailed`, not `ValueError`/`PermissionError`, so it
      hits the generic handler); full traceback confirmed present in the log
- [x] A SOP → DOP `connect_nodes` returns a named refusal — tested as
      Sop → Object instead (Dop isn't in `ALLOWED_NODE_CATEGORIES`, so a Dop
      node can't be created via `create_node` to set the test up); same
      category-mismatch code path, confirmed refused with a named `ValueError`
      and a `REFUSED` audit line
- [x] With Scene View closed, `viewport_snapshot` returns
      `"Precondition: …"` and a `REFUSED` audit line — **not** a traceback —
      confirmed live, Sashok closed the pane by hand
- [x] One line in `BACKLOG.md` under `## Done`

**Reload incident, worth keeping for next time:** verifying this stage took
much longer than the code changes themselves because of an infra problem,
not a code bug. Reloading the plugin via the `sys.modules`-purge pattern
(`hmcp.stop_server()` → pop `hmcp*` from `sys.modules` → `import hmcp` →
`start_server()`) left an **orphaned listening socket** bound to port 9878 in
the same Houdini process after a second reload — the old `HmcpServer`
object's event-loop callback stayed registered and its socket stayed open,
but the Python reference to it was gone (replaced by the new module's fresh
`_server` global), so `stop_server()` on the *new* instance had nothing to
call `.stop()` on to close it. `netstat` showed **two** `LISTENING` entries
on `0.0.0.0:9878` under the same PID. New connections got nondeterministically
routed to either socket; the dead one's `listen(5)` backlog filled with
never-`accept()`'d connections, so the symptom evolved from intermittent
timeouts to a hard, consistent `WinError 10061` (connection actively
refused) — looked exactly like a firewall/AV block from the outside, and
cost real time chasing that red herring before `netstat -ano` showed the
duplicate listener. **No code fix exists for this** — a dead listener with
no reachable Python reference can't be closed short of a debugger attach.
**The only reliable fix is a full Houdini restart**, not just another
plugin reload; confirmed by the PID changing in `netstat` and the port
immediately accepting connections again. If a future reload session starts
timing out or getting refused, check `netstat -ano | findstr :9878` for more
than one `LISTENING` line before assuming it's the code.

---

## Stage 2 — camera control

The highest-value single stage: it fixes an actually-observed failure and
introduces no new risk class. Full detail in
`HMCP_CAMERA_CONTROL_PLAN.md` §3–§5 and its Phase 3; the decisions and
deltas are restated here so you do not have to reconcile two documents while
coding.

### 2a. The command set (24 → 29, or 30 with dolly; shipped as 24 → 30, all six)

| Command | Kind | Ship? |
|---|---|---|
| `get_viewport_info()` | read | yes |
| `viewport_frame_node(node_path)` | write | yes — this alone solves the problem |
| `viewport_frame_all()` | write | yes — the "I'm lost" recovery button |
| `viewport_set_view(view)` | write | yes |
| `viewport_orbit(dx_degrees=0.0, dy_degrees=0.0)` | write | only if V2/V3 resolved cleanly |
| `viewport_dolly(factor)` | write | only if V4 resolved cleanly; otherwise **drop it** |

### 2b. Design points that are load-bearing

- **Framing takes a node path, not the selection.** Every write command in
  this codebase is keyed on a path. Reading the selection makes the command
  non-deterministic; *setting* it stomps whatever the human had selected. And
  `frameSelected()` is precisely the workflow that failed on 2026-08-12 — it
  needs a human to select first.
- **Orbit takes relative deltas, not absolute angles.** Absolute angles
  require the plugin to define and expose a full camera-orientation
  convention, which is a set-arbitrary-camera-transform command wearing a
  hat — the generic-capability shape the rewrite plan §4 rejects. No
  clamping: rotation wraps, so out-of-range values are harmless.
- **Preset views map through an explicit 7-entry dict.** `getattr` is
  forbidden (rule 6). `"uv"` is deliberately not offered — a UV viewport is
  useless for looking at geometry and would silently break the next snapshot.
- **Use `sv.curViewport()`**, matching `viewport_snapshot` at
  `build.py:291`. It is not fully deterministic in a quad layout, but the
  invariant that matters is "camera commands and the snapshot act on the same
  viewport," and that holds only if both use the same accessor. Mitigation is
  visibility, not correction: every camera command returns `viewport.name()`.

### 2c. One new guard — `guards.check_viewport_camera_free(viewport)`

This is the one genuinely dangerous edge in the whole feature.
`defaultCamera()` is documented **live**: *"if a camera/light is locked to
the view, changing the settings will change the camera node's parameters."*
So an orbit on a viewport locked to `/obj/cam1` writes to that camera's
transform parms — a node not in `session_registry`, through a path that never
touches `check_settable_parm`, silently moving somebody's shot camera.

Per doctrine this gets **refused, not validated around**:

```python
def check_viewport_camera_free(viewport):
    """Raise if the viewport is looking through, or locked to, a camera node."""
    path = viewport.cameraPath()      # "" when not looking through a camera
    if path:
        raise PermissionError(...)
    if viewport.isCameraLockedToView():
        raise PermissionError(...)
```

Lives in `guards.py` (rule 7), raises `PermissionError` so `server.py:253`
logs it as `REFUSED`. **Deliberately not applied to `viewport_snapshot`** — a
snapshot moves nothing.

### 2d. Guards and kinds

`guards.require_sandbox_scene()` on the **first line of every `viewport_*`
write handler**, and `kind: "write"` in `commands_spec.py`. Camera state is
not a node-graph edit, but: viewport state is saved into the `.hip`; it
changes what the human is looking at; and per 2c it can become a real
node-graph write. `get_viewport_info` is genuinely read-only, goes in
`intro.py`, no guard.

### 2e. Files to change

| File | Change |
|---|---|
| `houdini/plugin/hmcp/guards.py` | `check_viewport_camera_free`, after `check_expression_language` |
| `houdini/plugin/hmcp/intro.py` | `viewport_state(viewport)` (shared read-only dict) and `get_viewport_info()`. Every field via `_safe_attr` (`intro.py:29`) — this module must never raise |
| `houdini/plugin/hmcp/build.py` | `_view_type`, `_node_world_bbox`, the handlers; add `from . import intro` |
| `houdini/commands_spec.py` | 5–6 entries after the `viewport_snapshot` entry (`:213-222`) |
| `houdini/plugin/hmcp/commands.py` | matching `_HANDLERS` lines |
| `houdini/bridge/hmcp_bridge.py` | `@mcp.tool()` wrappers + the names in `_bridge_tool_names` (`:359-368`) |

`_node_world_bbox(node)` is the fiddly one:
- Object → `node.displayNode()`, transformed by `node.worldTransform()`
- Sop → `node.geometry()`, transformed by the nearest ancestor Object's
  `worldTransform()` — `geometry().boundingBox()` is **SOP-local**
- anything else → `ValueError` naming `guards.ALLOWED_NODE_CATEGORIES`
- transform is `bbox * matrix4` (no `transform()` method exists)
- raise `ValueError` on no display node, no geometry, or `not bbox.isValid()`

**Cook warning:** `_node_world_bbox` calls `sop.geometry()`, which forces a
cook. A heavy uncooked SOP can blow the bridge's 10 s budget. Mitigation is
guidance in the docstring, not code — do not add a cook timeout; that would
be new machinery for a problem `get_geometry_info` already has.

### 2f. One edit to shipped behaviour

`viewport_snapshot`'s return dict gains `"viewport": viewport.name()`
(`build.py:298`), so a framing/snapshot viewport mismatch in a quad layout is
visible in the transcript instead of silent. Flag it in review.

### 2g. Bridge docstrings

The docstrings are the model's only instructions — write them as
instructions, not descriptions. E.g.:

> `viewport_frame_node` — "Aim the Houdini viewport at this node, the
> equivalent of selecting it and pressing Home. **Call this before
> `viewport_snapshot`** — the snapshot only captures whatever the viewport
> already shows. Accepts a SOP or an Object node. Does not change the user's
> selection. Requires a sandbox scene."

### 2h. Permissions

Auto-allow **only** `mcp__houdini2__get_viewport_info` in
`.claude/settings.local.json`. The camera writes stay per-call prompts until
they have been used a few times — they are non-destructive, but they move the
human's screen. (Precedent: `BACKLOG.md` 2026-08-09, only read tools are
auto-allowed.)

### Stage 2 — implementation status (2026-08-12)

All code written per §2a–2h: `guards.check_viewport_camera_free` (after
`check_expression_language`); `intro.viewport_state` / `intro.update_mode_state`
/ `intro.get_viewport_info` (read-only, never raises); `build._view_type` /
`build._node_world_bbox` / the five write handlers
(`viewport_frame_node`, `viewport_frame_all`, `viewport_set_view`,
`viewport_orbit`, `viewport_dolly`) plus `viewport_snapshot`'s `"viewport"`
key (§2f); `commands_spec.py` (24 → 30), `commands.py`, and
`hmcp_bridge.py`'s tool wrappers + `_bridge_tool_names`, all in sync.
`.claude/settings.local.json` auto-allows only `get_viewport_info`, per §2h.

Verified so far, **locally, without a running Houdini** (no live plugin
deploy yet — that needs Sashok, per rule 9):
- `hython -m py_compile` clean on every changed file (local 20.5.278)
- `hmcp.commands.REGISTRY` builds cleanly to 30 entries when imported from
  a deploy-shaped copy of the package (commands_spec.py alongside the
  other hmcp/*.py files, matching what `deploy_plugin.sh` actually lays
  out — importing straight from the repo tree fails on this circular
  import for an unrelated reason: repo-tree `hmcp/` has no
  `commands_spec.py` sibling at all, only the deployed layout does)
- `hmcp_bridge.py`'s `_bridge_tool_names` cross-checked against
  `commands_spec.COMMAND_NAMES` — matches exactly
- `rg "getattr\(hou" houdini/plugin/hmcp/` → zero hits (one near-miss: the
  first draft of `_view_type`'s docstring contained that literal string
  in prose, not code — reworded to avoid a false-positive grep failure)
- `rg -nE "os\.remove|shutil|unlink|rmtree|requests|subprocess|zipfile"` →
  only pre-existing module-docstring mentions of the forbidden-import
  list itself, no real usage

**Not yet done, needs a live Houdini session:** every item in the
done-when checklist below — deploy via `./scripts/deploy_plugin.sh
hmcp-local`, restart Claude Code (this stage adds commands, per §6), then
work through the acceptance test first.

### Stage 2 — `viewport_orbit`: broken, root-caused, fixed, shipped (2026-08-12)

**First pass: dropped.** Four independent live-tested rotation-composition
attempts all failed to keep the pivot centred, despite the position math
being independently verified correct every time: (1) composing the delta
with `cam.rotation()` assuming it's camera-to-world, (2) a hand-built
look-at matrix (matrix rows = `right/true_up/-forward`), (3) its transpose,
(4) `hou.hmath.buildRotate()` applied directly from a known-good identity
baseline. Only pure identity (camera on the pivot's local +Z axis) ever
worked. `cam.setRotation()` was confirmed to affect the actual render (a
wildly different matrix visibly changed the image), ruling out a
disconnected-API explanation. Sashok's call at the time: ship without it
rather than a command that silently frames the wrong thing —
`viewport_dolly` (translation-only, no rotation math) was unaffected and
shipped on its own.

**Root cause found** by an Opus subagent researching the SideFX-documented
convention in the background while the rest of Stage 2 wrapped up, citing
SideFX staff directly on [forum topic
71472](https://www.sidefx.com/forum/topic/71472/?page=1): **HOM's own docs
are wrong.** `cam.rotation()` is the **world-to-camera** rotation, not
camera-to-world as assumed in every attempt above. `cam.translation()` is
likewise not a world position — it's `pivot + (eye - pivot)` expressed **in
camera space**, which is exactly `(0, 0, distance)` whenever the camera is
already aimed at its pivot. That means an orbit never needs to touch
translation at all — centring is structural, not something to compute —
and every failed attempt above was writing a *world-space* eye position
into `setTranslation()`, which Houdini then silently re-rotated into camera
space, double-applying the orbit.

**Fix, live-confirmed 2026-08-12** (90° single-axis, then a cumulative
`dx=45, dy=20` on top of it — both stayed exactly centred, translation
untouched both times, matching the model): rotation-only, pre-multiplied by
the delta's *inverse* against the true world-to-camera rotation (the
mirror image of the original code's post-multiply, which assumed the wrong
direction of composition):

```python
delta3 = hou.hmath.buildRotate(dy_degrees, dx_degrees, 0).extractRotationMatrix3()
cam.setRotation(delta3.inverted() * cam.rotation())
```

`viewport_dolly`'s existing formula turned out to already be correct by
construction (scaling a camera-space offset scales world distance
identically regardless of which space it's labeled as) — only its
docstring's justification was wrong, now fixed.

### Stage 2 — done when

**The acceptance test, which is the entire point:**

- [x] With `/obj/hmcp_stage2_test` present but *not* framed and Sashok's hands
      off the keyboard: `viewport_frame_node(...)` then `viewport_snapshot()`
      produces a JPEG showing the object framed. **Confirmed live.**

Positive:
- [x] `check_contract.py` reports the new total agreeing, against a **reloaded**
      live plugin (30 commands with orbit; 29 after its removal, pending the
      final reload)
- [x] `get_viewport_info` returns name, type, pivot, and `snapshot_ready: true`
- [x] `viewport_orbit(dx_degrees=90)` then snapshot shows the same object from
      a different angle, **still centred** — confirmed, plus a follow-up
      cumulative `dx=45, dy=20` call, both centred. See the root-cause/fix
      note above. `viewport_dolly` also tested: zoom out, stays centred,
      correctly smaller
- [x] `viewport_set_view("front")` → `viewport_frame_node` → snapshot gives a
      clean orthographic front view
- [x] `viewport_frame_node` on an Object node and on a deep SOP inside it frame
      the **same** region — pivot and translation came back **bit-identical**
      between the two calls, on a test object with a non-identity object
      transform (`t=(5,2,-3)`, `ry=45`)
- [x] Viewport names match between a camera command's return and the snapshot's
      — held throughout the whole session

Negative — these matter more:
- [x] No SceneViewer pane → clean one-line precondition message (confirmed
      before Sashok opened Scene View)
- [x] Non-sandbox scene → **not separately re-tested this session** —
      `guards.require_sandbox_scene()` is the same shared guard already
      live-verified for this exact precondition in Stage 1 and Phase 2;
      skipped re-running it here to avoid disrupting Sashok's live scene
- [x] **Viewport locked to a camera → `viewport_frame_node` and
      `viewport_dolly` both refuse, and `get_node_info` confirms the camera
      node's `t`/`r` parms are unchanged (all zero).** Bonus finding: after
      the locked camera node was deleted, `camera_path` went empty but
      `isCameraLockedToView()` stayed `true` — the guard's *second*
      condition caught this stale-lock state on its own, with its own
      distinct refusal message, exactly as designed
- [x] `viewport_set_view("banana")` → clean `ValueError` listing the seven
      allowed views; `viewport_set_view("uv")` also refuses
- [x] `viewport_set_view("Perspective")` (the enum member name) refuses,
      proving no `getattr` passthrough
- [x] `viewport_frame_node("/obj/does_not_exist")` → clean "Node not found"
- [x] Empty `geo` object → clean "Refused: ... has no display node to frame"
- [x] `/out` → refused: `"node category 'Manager' is outside the target
      domain. Allowed: ['Object', 'Sop']"`
- [x] `rg -nE "os\.remove|shutil|unlink|rmtree|requests|subprocess|zipfile" houdini/plugin/hmcp/`
      → zero matches (checked during implementation)
- [x] `hmcp.status()` still shows `pump=eventloop` with climbing `ticks`
      (1145 → 1175 across two calls a moment apart)
- [x] One line in `BACKLOG.md` under `## Done`

---

## Stage 3 — non-blocking `render_snapshot`

New file `houdini/plugin/hmcp/render.py`. **Two** commands, not one, because
the render runs out-of-process (D3).

### 3a. `guards.py` additions — the only place output paths are produced

```
RENDER_DIR = "c:/houdini_mcp_sandbox/_renders/"   # must pre-exist
RENDER_OUTPUT_PARMS = {...}          # from Stage 0d
ALLOWED_RENDERERS = {"karma"}        # mantra excluded -- see Stage 0d/0e, confirmed with Sashok 2026-08-12
RENDERERS = {"karma": {...}}         # D7 descriptor table; add "mantra" back only after its silent-failure mystery is solved
RENDER_QUALITY = {"draft": (512, 512, ...), "preview": (960, 540, ...)}
```

- **A new `RENDER_DIR`, not `SNAPSHOT_DIR`.** The pre-existence rule turns
  the directory into a physical kill switch: no `_renders/` → every render
  refuses cleanly, and the owner arms the capability with one `mkdir`, no
  code change and no deploy. Reusing `SNAPSHOT_DIR` would arm it silently the
  moment it deploys, because that directory already exists on both machines.
  **The owner creates it, when he is ready. You do not.**
- **`set_render_output(node, parm_name, path)` lives in `guards.py`**, not in
  the handler. It asserts `parm_name in RENDER_OUTPUT_PARMS` and
  `path.startswith(RENDER_DIR)` before calling `parm.set(path)`. This keeps
  the property that makes the safety model work: every write to an
  output-path parm passes through one reviewable file.
  **`check_settable_parm` is not touched** — generic `set_parm` still refuses
  the picture parms exactly as today.
- Filename `mcp_<YYYYmmdd_HHMMSS>_<renderer>.png`, same collision-free-by-
  construction pattern as `build.py:287-288`.

### 3b. `render_snapshot(renderer="karma", quality="draft", camera="viewport")`

Returns immediately after spawning. Sequence, in order:

1. `guards.require_sandbox_scene()` — first line
2. Validate `renderer` and `quality` against the closed enums → `ValueError`
3. Refuse if a previous render is still pending (single slot, see 3c)
4. Preflight: the ROP type exists on this build; `RENDER_DIR` is readable; a
   camera can be produced
5. Build the camera (3d)
6. Get-or-create the plugin's own ROP at `/out/hmcp_render_<renderer>`,
   inside `hou.undos.group("MCP: render_snapshot")`.
   **Never accept a caller-supplied ROP path** — rendering someone else's ROP
   executes whatever is in its `prerender`/`postrender`/`precmd` parms, the
   exact class `guards.CODE_PARMS_REFUSED` exists to refuse. On a reused
   node, assert those parms are empty and refuse if not.
7. Set camera, resolution and samples from `RENDER_QUALITY`, plus
   `trange = 0` **and** `f1 = f2 = hou.frame()`. Frame-range pinning is
   belt-and-braces on purpose. `trange` is never a command parameter.
8. `guards.set_render_output(rop, <picture parm>, path)`
9. Press `executebackground`. **Do not call `rop.render()`.**
10. Record the pending slot; return
    `{"path", "renderer", "resolution", "camera_path", "rop_path", "started": true}`

### 3c. `render_status()`

No arguments. Reads a single module-level slot
`{path, started_at, rop_path}`, probes the file with `open(path, "rb")`, and
returns `{"done", "path", "seconds_elapsed", "errors"}` — `errors` from
`rop.errors()`/`warnings()` if Stage 0e showed those get populated.

**One slot, not a job registry.** A second `render_snapshot` while one is
pending is refused. That is the entire concurrency design; do not build more.

### 3d. Camera modes

- **`camera="viewport"`** (default, GUI only) — create/reuse `/obj/hmcp_cam`,
  registered in `guards.session_registry`, populated via
  `curViewport().saveViewToCamera(...)` with the signature Stage 0d
  confirmed. Renders exactly what `viewport_snapshot` sees, so the two eyes
  agree, and Stage 2's camera commands steer it for free. See **D2** for why
  this does not contradict the camera plan's out-of-scope list.
- **`camera="fit"`** (works headless) — port the bbox-fit maths from the old
  plugin (`HoudiniMCPRender.py:148`, `:181`, `:241`, `:341-421`),
  **rewritten guard-compliant**: no `import os`, no caller-supplied path, no
  `numpy` (plain floats instead of the `np.array` accumulation at `:187-227`),
  and reuse-or-create instead of the destroy-then-recreate at `:254-260` —
  the handler must never destroy a node it did not create. The maths is the
  valuable part and transfers directly.
- `camera_path=<existing camera>` is deliberately deferred.
- **Implement and verify `fit` even though GUI mode does not need it.** It is
  the headless worker's only camera, and verifying it here is far cheaper
  than verifying it alongside a new transport.

### 3e. Keep `render.py` headless-clean

Outside the `camera="viewport"` branch, `render.py` must not touch `hou.ui`.
When `hou.ui` is absent, `camera="viewport"` refuses with a message that says
so — **not an `AttributeError` traceback.** This is what lets the same file
move into the headless worker unchanged.

### 3f. The ROP is not creatable via `create_node`

`guards.ALLOWED_NODE_CATEGORIES` stays `{"Sop", "Object"}`. The ROP is
created only by this handler, exactly the way `viewport_snapshot` owns its
own output path. The agent gets rendering; it does not get "create arbitrary
ROPs."

### 3g. Wiring

Two `commands_spec.py` entries, two `_HANDLERS` lines, two bridge tools plus
`_bridge_tool_names`. Auto-allow `mcp__houdini2__render_status` only;
`render_snapshot` stays prompt-gated. `deploy_plugin.sh` needs no change —
`deploy_dir` already globs `*.py` (`:99`) and the py_compile loop iterates
the directory (`:128-132`).

### Stage 3 — done when

Negative first:
- [ ] `_renders/` **absent** → clean refusal naming the directory; nothing created
- [ ] Non-sandbox scene → refused by `require_sandbox_scene`
- [ ] `set_parm` on the picture parm still refuses — the generic path unchanged
- [ ] `renderer="arnold"` and `"opengl"` → refused as unsupported enums, both
      logged `REFUSED`
- [ ] Hand-set `prerender` on the ROP → the next call refuses
- [ ] A second `render_snapshot` while one is pending → refused
- [ ] `render_status()` with nothing pending → clean answer, not an exception

Positive:
- [ ] `render_snapshot()` returns within a **measured and recorded** number of
      milliseconds on the main thread, and **Houdini's UI stays responsive
      during the render** — verify by dragging a parameter slider while it
      runs. Do not infer this from the absence of a visible hang
- [ ] `render_status()` reports `done: true`, the PNG exists, and Claude can
      Read it and describe the geometry
- [ ] `camera="viewport"` framing matches `viewport_snapshot`'s;
      `camera="fit"` returns a differently-framed but fully-contained image of
      the same geometry
- [ ] `trange == 0` and `f1 == f2 == hou.frame()` after a render
- [ ] Two consecutive renders produce two files; nothing overwritten
- [ ] A deliberately-broken render (e.g. no camera) surfaces something
      actionable through `render_status().errors`. **If it surfaces nothing,
      record that as the known diagnostic cost of background execution** —
      do not paper over it
- [ ] `rg -nE "os\.remove|shutil|unlink|rmtree|requests|subprocess|zipfile|import os" houdini/plugin/hmcp/`
      → zero matches
- [ ] `check_contract.py` reports the new total agreeing
- [ ] Measured wall-clock recorded in `BACKLOG.md`

---

## Stage 4 — get the image off pc137

Local mode returns a path Claude can Read directly. **Remote mode (the
default `HMCP_HOST=10.10.10.31`) returns a path on another machine.**
`viewport_snapshot` has this gap today; it has not bitten only because
verification has been happening in local mode. Renders make it worse.

`scripts/fetch_render.sh` — a thin `scp` wrapper on the **bridge** side,
where the plugin's no-`subprocess` doctrine does not apply.

Rejected: returning the image inline as base64. The socket framing is "parse
the whole buffer as one JSON object" (`server.py:203`) and it would inflate
the audit log with megabytes.

Do this only if Stage 3 leaves an actual gap. If verification stays local,
document the limitation in `README.md` and move on.

---

## Stage 5 — two cheap wins from the external review

May ride along with Stage 2's deploy if convenient; kept separate so
verification stays clean.

### 5a. `find_nodes(name_filter=None, type_filter=None, root="/", max_results=…)`

Pure read, in `intro.py`. Today the agent can only enumerate via
`get_network(parent_path)`, one level at a time. Cap the result count in the
same spirit as the existing `max_nodes`/`max_parms` flags. Auto-allow it — it
is a read.

### 5b. Undo-revision check before revert

The one review item that touches safety rather than convenience. Record the
scene's undo-stack position right after the agent's own transaction; before
allowing an agent-initiated revert, refuse if it has since moved. This
protects against the agent silently eating Sashok's manual edits made between
the write and the revert.

Lives in `guards.py`, alongside `SessionRegistry`, which already documents
the related session-id lifetime rule (`guards.py:244-247`).

---

## 6. Deploy and verification mechanics — every stage

```
./scripts/deploy_plugin.sh hmcp-local     # local Houdini 20.5, no VPN, fast loop
./scripts/deploy_plugin.sh hmcp           # pc137 over VPN
```

Both targets run `hython -m py_compile` on every file, then
`check_contract.py`.

**After deploying, the plugin must be reloaded in Houdini** via the
`hmcp.shelf` Start button — it purges `hmcp*` from `sys.modules`. Skip this
and `check_contract.py` reports a mismatch against a live plugin still
running old code in memory, exactly as in `BACKLOG.md`'s Phase 2 entry.

Stages that **add commands** (2, 3, 5a) also need **Claude Code restarted**
to pick up the new bridge tools. Stage 1 does not.

Per root `CLAUDE.md`: one line per verified stage into `BACKLOG.md` under
`## Done` — what changed and whether it is verified, nothing more. The detail
(Stage 0's probe answers, the `RuntimeError`→`ValueError` message change, the
camera-lock guard's rationale, the background-render diagnostic cost) goes in
the **commit message bodies**.

---

## 7. Explicitly not in this plan

- **The headless `hython` worker (Track B).** Port 9879, the blocking accept
  loop, the persistent-session model, `save_checkpoint`, moving the PySide
  import out of `server.py`'s module scope, the loss of Ctrl+Z rollback. All
  of it stays in `HMCP_HEADLESS_RENDER_PLAN.md` §3–§5, to be re-planned once
  Stage 3 produces real numbers. **This is the actual destination** — it is
  deferred because Stage 3 de-risks it, not because it is unwanted. Two
  things here exist for it and must not be compromised: `render.py` stays
  `hou.ui`-free outside one branch (3e), and `camera="fit"` is verified (3d).
- **Arnold and Karma XPU.** D4. The descriptor table is the seam.
- **Multi-frame or sequence rendering.** Impossible by construction:
  `trange = 0`, `f1 = f2 = hou.frame()`, no frame parameters on the command.
  An unbounded sequence render is precisely the "runs forever, freezes
  Houdini, blows every timeout" failure this design avoids.
- **`network_snapshot`, `reorder_inputs`, named token-budget constants.**
  Reviewed, declined (D6).
- **Pan, roll, absolute camera transforms, `setCamera`, `lockCameraToView`,
  `saveViewToCamera` as a command, selection manipulation, viewport display
  options, viewport layout changes, the UV viewport, targeting a specific
  viewport in a quad layout, folding framing into `viewport_snapshot`.**
  `HMCP_CAMERA_CONTROL_PLAN.md` "Out of scope", unchanged. The four
  `hou.GeometryViewport` methods that convert viewport state into node-graph
  writes on cameras the agent did not create join the permanent never-list
  alongside `execute_code` and broad `modify_node`.
- **`execute_code` in any form, regex code-blacklists, env-var bypass flags,
  caller-supplied output paths.** The external review's avoid-list, which
  restates doctrine already in force.
- **`scripts/deploy_plugin.sh:126`'s stale `21.0.596` hardcode.** Real, found
  by Stage 0a, fixed in its own commit — not bundled here.
- **Retiring the old plugin on 9876.** Unrelated; still gated on
  `HOUDINI_MCP_REWRITE_PLAN.md:372`.
- **The SOP cookbook** (`HMCP_SOP_COOKBOOK_PLAN.md`). Its own §4.4 says do not
  start recipe production before this feedback loop lands, because recipes
  verified against an unlit grey blob have to be re-verified afterwards. It
  stays parked. Its one item that does not depend on this work is
  `DOCTRINE.md`, which can be seeded at any time.

---

## 8. Critical files

- `houdini/plugin/hmcp/guards.py` — `check_viewport_camera_free`, the
  renderer descriptor table, `RENDER_DIR`, `set_render_output`, the
  undo-revision check. **Every new safety-relevant function lands here**, per
  the file's own docstring rule.
- `houdini/plugin/hmcp/build.py` — `_require_scene_viewport`, `_view_type`,
  `_node_world_bbox`, the `viewport_*` handlers. `viewport_snapshot`
  (`:259-298`) is the template for the new handlers' shape.
- `houdini/plugin/hmcp/render.py` — **new**; `render_snapshot`,
  `render_status`.
- `houdini/plugin/hmcp/intro.py` — `viewport_state`, `get_viewport_info`,
  `find_nodes`. Every field through `_safe_attr` (`:29`); this module must
  never raise.
- `houdini/plugin/hmcp/server.py` — audit-log tracebacks, `hint` in the error
  shape.
- `houdini/commands_spec.py` — the single declaration point. `commands.py`,
  the bridge, and `check_contract.py` all derive from it; `_build_registry`
  (`commands.py:51`) raises at import if it and `_HANDLERS` disagree.
- `houdini/bridge/hmcp_bridge.py` — `@mcp.tool()` wrappers and
  `_bridge_tool_names` (`:359-376`), whose startup assertion catches drift.

---

## 9. Housekeeping when this plan completes

- Add a one-line pointer to this document in
  `houdini/docs/HOUDINI_MCP_REWRITE_PLAN.md`'s "After Phase 3" section.
- Add a header line to each of the three source documents pointing here as
  the authoritative execution order, and fix the `saveViewToCamera` wording
  per **D2**.
- Per root `CLAUDE.md`, nested docs describe *current state* — edit them in
  place, do not leave the superseded description next to the new one.
