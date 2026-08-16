# Houdini API notes — measured, not recalled

Facts about Houdini's Python API and this environment that were expensive to
establish and are easy to get wrong again. Everything here was confirmed live
against a running Houdini or `hython`, on the date given — none of it is
recalled from documentation, and several entries exist precisely *because*
the documentation is wrong.

Add to this file whenever a probe answers something non-obvious. Related:
`HMCP_LOCAL_TIMEOUT_TRIAGE.md` (why the poll pump is an event-loop callback),
`HMCP_DESIGN.md` (the doctrine this code obeys).

---

## Machines and builds

| | Build | Notes |
|---|---|---|
| pc137 (`10.10.10.31`) | **21.0.729** | Both 21.0.596 and 21.0.729 are installed; the process that actually runs is 21.0.729. Anything hardcoding 21.0.596 is stale |
| local | 20.5.278 | Has HtoA loaded; pc137 does not. Used for fast iteration without VPN |

Every API fact below was checked on **both** builds unless noted. No version
drift was found in any of them.

`hou.getenv("JOB")` on pc137 resolves to the Houdini install's own `bin/`
directory even with a real sandbox hip loaded — it is not usable as a
sandbox-relative root. Only `$HIP` tracks the scene, and that is redundant
with `SANDBOX_ROOT`.

---

## Viewport camera

### The rotation convention — HOM's own docs are wrong

This cost four failed implementations of `viewport_orbit` before it was
root-caused (2026-08-12, confirmed by SideFX staff on [forum topic
71472](https://www.sidefx.com/forum/topic/71472/?page=1)):

- **`GeometryViewportCamera.rotation()` is the world-to-camera rotation**,
  not camera-to-world as the docs imply.
- **`translation()` is not a world position.** It is `pivot + (eye - pivot)`
  expressed *in camera space* — which is exactly `(0, 0, distance)` whenever
  the camera is already aimed at its pivot.

The consequence is the useful part: **an orbit never touches translation at
all.** Centring is structural, not something to compute. Every failed attempt
was writing a world-space eye position into `setTranslation()`, which Houdini
then re-rotated into camera space, double-applying the orbit.

The working orbit is rotation-only, pre-multiplied by the delta's *inverse*:

```python
delta3 = hou.hmath.buildRotate(dy_degrees, dx_degrees, 0).extractRotationMatrix3()
cam.setRotation(delta3.inverted() * cam.rotation())
```

Note the type mismatch that bites first: `cam.rotation()` returns a
`hou.Matrix3`, `hou.hmath.buildRotate()` returns a `hou.Matrix4`, and
`Matrix3 * Matrix4` raises `TypeError`. Hence `.extractRotationMatrix3()`.

`viewport_dolly`'s scale-the-offset formula is correct by construction —
scaling a camera-space offset scales world distance identically regardless of
which space it is labelled as.

### Other confirmed viewport facts

- `frameBoundingBox(bbox)` **does** move the pivot to the box centre. No
  explicit `setPivot()` is needed after framing.
- The viewport type query method is **`type()`**, not `viewportType()` —
  several forum posts get this wrong. `hou.geometryViewportType` exposes
  exactly `Perspective, Top, Bottom, Front, Back, Right, Left, UV`.
- `cameraPath()` returns `""` when the viewport is not looking through a
  camera. `isCameraLockedToView()` is independent of it and **can stay `True`
  after the locked camera node is deleted** — a stale-lock state that
  `check_viewport_camera_free`'s second condition catches on its own.
- `saveViewToCamera` takes **one** argument on these builds
  (`vp.saveViewToCamera(cam_node)`). The two-argument form raises
  `TypeError` — contrary to notes claiming the 1-arg form was deprecated in
  favour of it.
- `hou.BoundingBox` has **no `transform()` method**. Transform is
  `bbox * matrix4`, which returns the axis-aligned box around the transformed
  box.
- A SOP's `geometry().boundingBox()` is **SOP-local**. To get a world bbox,
  transform it by the nearest ancestor Object's `worldTransform()`. Calling
  `sop.geometry()` forces a cook, so a heavy uncooked SOP can blow the
  bridge's 10s budget.
- `defaultCamera()` returns a **live** object: if a camera or light is locked
  to the view, changing its settings changes that *node's* parameters. This
  is the entire reason `check_viewport_camera_free` exists.
- Not probed, deliberately: whether `viewport.draw()` is required before a
  flipbook picks up a new view, and whether the "smooth view transitions"
  preference animates `frameBoundingBox`. Both are sidestepped by calling
  `viewport.draw()` unconditionally before returning — cheap, and harmless if
  unnecessary.

---

## Renderers

### Descriptor table — real parm names, byte-identical on both builds

Pulled from live `get_node_type_parms`, then independently re-derived
headlessly on the other machine. **Never guess these** — the `/out` karma ROP
is an HDA wrapper and its parm names are HDA parameters.

| | `karma` | `ifd` (Mantra) |
|---|---|---|
| Output picture | `picture` | `vm_picture` |
| Resolution | `resolution` tuple → `resolutionx` / `resolutiony` | `res_override` tuple → `res_overridex` / `res_overridey`, gated by `override_camerares` |
| Camera | `camera` | `camera` |
| Frame range | `f` tuple → `f1` / `f2` / `f3` | same |
| `trange` menu | `off, normal, on, stage` (default `off`) | `off, normal, on` (default `off`) |
| Background render | `executebackground` | `executebackground` |
| Samples | `samplesperpixel` ("Primary Samples") | — |
| No-light fallback | `force_headlight`, default **false** — Karma does *not* auto-headlight | `soho_autoheadlight`, default **true** — Mantra does |

Karma also has a separate `override_camerares` / `res_override` /
`res_fraction` group, apparently a second resolution path. Left untouched.

### Output format

Karma has **no device/format parm at all** — the format is inferred from the
`picture` parm's file extension. PNG output is confirmed working. Mantra's
`vm_device` menu lists `PNG`/`JPEG`, but see below.

### Mantra fails silently on this setup — unresolved

`ifd.render()` produces **no file and no `rop.errors()`/`warnings()`**, across
every attempt, before and after saving the scene. Narrowed but not
root-caused: the SOHO export step itself works (pointing `soho_diskfile` at a
real path produced a genuine 4.5KB `.ifd`), and `mantra.exe` exists at
`$HFS/bin/mantra.exe`. The failure is specifically in Houdini launching or
piping to the `mantra` process (`soho_pipecmd`), which reports nothing back
either way. One oddity noted in passing, relevance unconfirmed: `$HFS`
resolves to an 8.3 short path (`C:/PROGRA~1/SIDEEF~1/HOUDIN~1.278`) on the
local machine.

This is why `ALLOWED_RENDERERS` is Karma-only.

### `executebackground` — three findings that shaped the render design

1. **Houdini refuses it outright with unsaved changes.** A blocking modal —
   *"Cannot perform background render with unsaved changes"* — that **aborts
   the render** when dismissed, not a confirm-and-continue. Since the render
   handler's own ROP preflight always dirties the scene, this fires on
   essentially every call. Hence the unconditional `hou.hipFile.save()`
   immediately before pressing the button.
2. **It is not near-instant, and it does block the main thread.** Measured on
   a 512×512 draft Karma render: `pressButton()` blocked for **16.6s** on a
   session's first call and **6.5s** on the second (warm), versus **0.28s**
   for a foreground `rop.render()` of the identical scene. Confirmed by hand:
   dragging a parameter slider during a call froze for ~5s. A per-call
   overhead of roughly this shape is real and front-loaded on the first call;
   an `"Arnold shutdown"` line appearing in the console during a *Karma*
   render suggests HtoA hooks the render-session lifecycle regardless of
   renderer, which is a plausible source of it (not chased further).
3. **A silently-aborted background render leaves `rop.errors()` and
   `rop.warnings()` completely empty.** It is indistinguishable from "still
   running" by errors alone. This is the accepted diagnostic cost of
   background execution.

### `trange` is the only frame guard that holds

Pinning `f1`/`f2` to `hou.frame()` is a **structural no-op on the Karma
ROP** — the HDA keeps them synced to `$FSTART`/`$FEND` and silently reverts
any direct `.set()`, regardless of `trange`. The guard that actually works is
`trange` forced to `"off"` immediately before every button press, in the same
call. Proved by tampering `trange` to `"normal"` externally with `f1`/`f2` at
1/240 and confirming the reset fired and the render stayed single-frame. A
background render with `trange="off"` ignores `f1`/`f2` entirely.

### Two bugs in `camera="fit"`, both fixed

Worth knowing because both were invisible from the outside:

1. **FOV.** `cam.parm("aspect")` is Houdini's *pixel* aspect ratio, not the
   image aspect ratio, and a fresh `cam` node defaults to 1280×720 rather
   than the render resolution. Computing vertical FOV from `aperture/aspect`
   gave 26.25° where the math assumed 45°, placing the camera ~1.7× too
   close. Fix: pin the camera's own `res`/`win`/`winsize` to the render
   resolution first, then compute from `resy·aperture/(resx·aspect)`.
2. **The plugin's own render camera framed itself.** `/obj/hmcp_cam` carries
   its display flag on by default, so an unfiltered `isDisplayFlagSet()` scan
   included the camera as a point-sized bbox, skewing the union bbox centre
   every call. Fix: exclude `cam`/`light` object types from that scan by
   type — which also guards against a stray user camera left displayed.

The current fit math is a bounding-sphere approach —
`distance = radius / sin(min_fov/2)` where radius is half the world bbox
diagonal — which guarantees containment for any fixed viewing angle. It
replaced the old plugin's per-axis-rotation branching, and is both simpler
and strictly more general.

---

## Node-network authoring: compiled for-each expressions

Confirmed 2026-08-14 on a production scene (`x12_travel_case`), not the
`hmcp` plugin itself — kept here because there is no better-fitting
Houdini-stack notes doc for artist-facing node-graph technique.

A manual compiled for-each loop (`block_begin` / `block_end` SOPs, not the
packaged "for-each" HDA) needs `iteration`/`numiterations` read a specific
way from a parameter expression on a node **inside** the loop body:

- **Don't `detail("../some_node", "iteration")` by raw op-path** on a node
  that is itself between `block_begin` and `block_end`. Two distinct
  failure modes hit trying this:
  1. Referencing a *second, disconnected* `block_begin` (method=`metadata`,
     `blockpath=../foreach_end1`, meant for external/post-loop queries)
     creates a circular cook dependency when the querying node is itself
     upstream of that same `foreach_end1` — silently evaluates to `0`, no
     error surfaced.
  2. Referencing the loop's own driving `block_begin` (method=`input`) by
     raw path throws `Unable to evaluate expression (Bad data type for
     function or operation)` — a compiled block duplicates itself per
     iteration, and a bare path string doesn't resolve to the right
     per-iteration instance.
- **Working pattern: type the target node's path into the expression, let
  Houdini auto-convert it to a spare input, then reference it by negative
  index.** Typing `detail("../foreach_count1", "iteration", 0)` into a parm
  and confirming it makes Houdini silently create a `spare_input0` parm
  (visible via `get_node_info`, holds the literal path) and rewrite the
  expression to `detail(-1, "iteration", 0)`. The spare input wires the
  dependency into the DAG explicitly, resolving both failure modes above —
  confirmed working even referencing the metadata-method `block_begin` from
  case 1, once it's a spare input rather than a bare path.
- **Normalize sweep expressions against `numiterations`, don't bake a fixed
  per-step increment.** `angle_per_step * detail(-1,"iteration",0)` only
  hits the intended max angle for the one iteration count it was tuned
  against — changing "Iterations" on the `block_end` silently
  stretches/shrinks the whole range. Pin the endpoints instead and let
  iteration count only change the density between them:
  ```
  end_angle * detail(-1,"iteration",0) / (detail(-1,"numiterations",0)-1)
  ```
  (add `start_angle +` and use `(end-start)` if the range doesn't start at
  0). General pattern for a swept-volume/motion-envelope shape — e.g.
  sweeping a camera housing through its gimbal tilt range to carve a lid
  clearance pocket — where `numiterations` should read as "quality" of the
  merged result, independent of the physical range being swept.

---

## Boolean SOP + CAD-tessellated input: T-junction diagnosis and fix

Confirmed 2026-08-16 on a production scene (`x12_travel_case`, `boolean41`).
General artist-facing technique, kept here for the same reason as the
for-each notes above.

**Symptom:** `boolean::2.0` cooks with no errors, one `Crossed boundary
(unshared) edges in solid A` warning naming three point numbers — but the
actual output is visibly broken: flat, backfacing (inconsistent-normal)
garbage shards disconnected from the main solid. One residual non-manifold
edge is enough to corrupt the solid classification for a whole connected
shell region, not just a local dimple — don't dismiss a single warning as
cosmetic on a Boolean SOP. Confirm with `viewport_snapshot`, not just
`get_node_errors` — the warning count and the visual correctness are not the
same signal.

**What does *not* fix it, both tried and measured worse or no-op:**
- **`Fuse` cannot close a T-junction at any tolerance.** A T-junction is a
  vertex from a finer patch sitting on the *middle* of an edge from a
  coarser patch — there is no matching point to snap to. Raising `tol3d`
  from the default 0.001 up to 0.02 (20×) on this mesh left the exact same
  single warning every time. (Fuse *is* still needed first, though — on this
  mesh it correctly collapsed 845k points to 194k real coincident-point
  duplicates from independent CAD tessellation; it just can't touch the last
  T-junction.)
- **`PolyDoctor` in repair mode made this specific mesh worse, not better.**
  Defaults (`illformed`/`manyedges`/`nonconvex`/`overlapping` = repair) plus
  `intersect` = repair introduced *new* warning categories on the Boolean
  output that weren't there before (`Inconsistent incident polygon winding
  across edges`, additional `Nonmanifold edges`) — going from one warning to
  hundreds. Not a universal fix; don't reach for it by default on
  independently-tessellated CAD import.

**What worked — point-level surgery, not a blanket tool:**
1. `Group` SOP, `entity=point`, `pattern="<the exact point numbers Boolean's
   warning named>"` — selects just the defect.
2. `grouppromote`, 3 chained promotions in one node (points→prims, using
   `fromtype`/`totype`/`group`/`newname` per numbered promotion): points→prims
   (touching prims) → prims→points (dilate) → points→prims again. One ring of
   dilation is what turns the immediate defect into a hole with a *simple*
   closed boundary loop — filling the undilated hole directly can leave a
   non-simple boundary.
3. `Blast` on that ring group — deletes only the local patch (tens of prims
   out of 200k+), not a blanket repair pass.
4. `PolyFill` to cap the resulting hole — see the fillmode gotcha below.
5. Feed back into the Boolean's input. Re-check with both `get_node_errors`
   (should drop to zero) and a fresh `viewport_snapshot` (the visual garbage
   should be gone, not just the warning text).

This is a completely different failure class from the "compiled for-each"
section below — no VDB conversion needed, and precision CAD topology is
fully preserved since only the actually-broken prims are touched.

---

## Vellum SOP solver (`vellumsolver`) — five silent failure modes

Found 2026-08-15 building a pressure-inflated cloth pillow
(`/obj/ice_scale_pattern`, sandbox scene). All five cook "cleanly" in some
sense — no errors, or errors that look unrelated to the real cause — which is
what makes them expensive to find. Working end state: `box` → `subdivide`
(catmull-clark, not bilinear — bilinear keeps sharp box corners even after
many iterations) → `vellumconstraints`(cloth only, no pressure) →
`vellumsolver` → null, gravity small, `useground` on, `doselfcollisions` off,
`veldamping` > 0.

1. **Zero net external force means zero motion, even with unsatisfied
   constraints.** With `gravity` and wind both zeroed, the solver's output
   bounding box stayed bit-identical to the pre-sim rest box (`±0.5` on every
   axis, to the last float) from frame 1 through frame 200, despite the
   constraints visibly existing (guide geometry, see #3) and their rest-length
   targets being nowhere near 1.0. The constraint-projection step apparently
   never runs at all without some nonzero external acceleration to seed it.
   A small gravity (`-0.5`, well under the real-world `-9.8` default) was
   enough to "wake" the solver and let the constraints actually shape the
   mesh.
2. **Self-collision explodes on any external force, silently.** The moment
   real gravity was reintroduced with `doselfcollisions` on, the mesh
   degenerated into a spiky, self-intersecting mess within 10 frames (bbox
   ballooning from `±0.5` to roughly `±4.5`) — no cook error, it just cooks
   garbage. `doselfcollisions` off fixes it outright. Likely why a
   from-scratch build might zero gravity in the first place (mode 1) — it
   silences the explosion without curing it.
3. **The `pressure` constraint type can be completely inert while looking
   fine.** Wiring a channel into `stretchrestscale` (correct — Houdini
   reuses this same parm as the volume-scale target for `constrainttype:
   pressure`, the per-type relabeling doesn't show up via the API) and
   confirming guide geometry exists is not enough evidence it's doing
   anything. Proof it wasn't: bypassing the pressure `vellumconstraints`
   node entirely from the graph produced a **bit-identical** result to
   including it: tried targets 1.35, 1.6, and 5.0 (500% volume) and all
   three converged to the exact same floats. Root cause not found — not a
   cache issue (see #4, ruled out independently) and not a wiring issue (the
   node's own `get_node_info` showed the resolved numeric value updating
   correctly). Do not trust "guide geometry shows something" as proof a
   constraint type is contributing force; it may just be showing the
   upstream cloth constraint's own guide passing through. If a pressure/
   balloon look is needed, don't fight this — use a collision proxy instead
   (a smaller closed mesh as static collision geometry, cloth stretch-scale
   under 1.0 shrink-wraps taut against it), though see #5 for a caveat on
   that path.
4. **The solver's internal DOP cache can wedge itself permanently, on a
   per-node-instance basis, independent of the SOP-level `Cache Enabled`
   toggle.** After enough live rewiring of a `vellumsolver`'s inputs (input
   swapped between different upstream `vellumconstraints` nodes and back,
   repeatedly, while iterating), it started throwing `Error: The number of
   points in the geometry and constraints do not match` from deep inside its
   compiled subnetwork (`dopimport_geometry/.../graph_color_constraints`) —
   despite every upstream node reporting correct, matching point counts via
   `get_geometry_info`. None of the following cleared it: toggling `Cache
   Enabled` off, pressing `Reset Simulation` (including a deliberate 0→1
   edge, in case a same-value `.set()` doesn't fire the button callback),
   toggling `bypass` on the solver itself, toggling `bypass` on its upstream
   `vellumconstraints`. **A brand new `vellumsolver` node fed by the exact
   same upstream reproduced the identical error** — proving it wasn't a
   per-node cache at all but corrupted state living in the upstream
   `vellumconstraints`' output despite that node itself reporting zero
   errors and correct topology. The only fix found: rebuild the constraint
   chain from a fresh `box`/`subdivide`/`vellumconstraints` too, not just a
   fresh solver. Lesson: if a solver error mentions internal DOP subnetwork
   paths and every visible geometry check looks fine, don't trust
   `get_node_errors`/`get_geometry_info` on the upstream nodes as proof
   they're clean — rebuild the chain from further back before spending more
   time on cache-clearing tricks.
5. **Zero velocity damping lets a resting shape degrade over time instead of
   settling.** A cloth+ground sim that looked like a genuinely nice rounded
   cushion at frame 30 had collapsed into a spiky, jagged mess by frame 60 —
   same settings, just later frames, no errors either time. `veldamping`
   was `0` (the solver's own default). Setting it to `0.3` made the
   identical setup hold a stable, fully-rounded resting shape from frame 30
   through at least frame 100. A shape that looks right at one frame is not
   confirmation of a stable sim — check a frame well past where it "should"
   have settled before trusting the result.

**Diagnostic technique that found both:** `vellumconstraints` node output
(`get_geometry_info`) reports the *same* `npoints`/`nprims` as its input —
the constraint edges/volume constraint are not visible as extra primitives
in the schema query at all. To confirm constraints actually exist, set the
node's own display flag on temporarily (`set_display_flag`) and take a
`viewport_snapshot` — the guide geometry (constraint lines) only renders
when the node carries the display flag, and shows up as a dense tangle of
white lines over the base mesh when constraints are present.

---

## Undo

`hou.undos` has **no public undo-stack position or revision counter.** The
workable substitute, confirmed to increment correctly across `create` and
`destroy` each in its own `hou.undos.group()`, is a fingerprint of
`(len(hou.undos.undoLabels()), hou.undos.undoLabels()[-1])`.
`hou.undos.areEnabled()` is `True` even headless, but `hou.undos.group()`
records nothing without a GUI — so a headless worker has no Ctrl+Z safety net
at all.

---

## Infrastructure failure modes

### Orphaned listener after a plugin reload

Reloading via the `sys.modules`-purge pattern can leave a **second listening
socket bound to 9878 in the same Houdini process**: the old server object's
event-loop callback stays registered and its socket stays open, but the
Python reference to it is gone, so `stop_server()` on the new instance has
nothing to close. `netstat` shows two `LISTENING` lines under one PID. New
connections get routed nondeterministically; the dead one's backlog fills
with never-accepted connections, so the symptom escalates from intermittent
timeouts to a hard `WinError 10061` that looks exactly like a firewall block.

**No code fix exists** — a dead listener with no reachable Python reference
cannot be closed short of attaching a debugger. The only reliable fix is a
full Houdini restart. If a reload session starts timing out or getting
refused, run `netstat -ano | findstr :9878` and count the `LISTENING` lines
before suspecting the code.

### `layout_children(parent_path)` lays out the *entire* network, not just agent-created nodes

Confirmed 2026-08-16. There is no scoping to "nodes this session created" —
it repositions every child under `parent_path`. Calling it on a shared
network (e.g. `/obj/geo1` in a real production scene) silently discards
whatever manual layout the owner had. There is no undo exposed through the
bridge for this; the only recovery is the owner's own Ctrl+Z in Houdini's
interactive undo stack (works because HOM writes go through Houdini's normal
undo system), which is not guaranteed and is not an hmcp capability.

**Never call `layout_children` on a parent that holds pre-existing work.**
Reposition only the specific nodes the current session created, individually,
via `set_position`.

### `get_node_type_parms` / `get_node_help` take `type_name`, not `node_type`

Every write/inspect command that creates or targets a node instance
(`create_node`, `list_node_types`) takes `node_type`. These two
introspection-only commands take `type_name` (plus `category`) instead —
passing `node_type` to either raises a pydantic "field required" error before
the call even reaches Houdini. Worth checking parameter names against the
tool schema before assuming consistency across the bridge surface.

### `polyfill` SOP `fillmode` — real menu tokens, don't guess

Confirmed live via `get_node_type_parms` after several guessed tokens
(`polygon`, `triangle`, `poly`, `fan`, `subdivide`, `polypatch`) all failed
with `Invalid menu item`. The real values: `none, tris, trifan, quadfan,
quads, gridquads` — default is `quads`. `quads` requires each boundary loop
to have an even edge count and **silently skips** (warning, not error) any
loop that doesn't — which a T-junction-shaped hole always produces (see the
Boolean section above). `tris` (triangle fan) fills any simple closed loop
regardless of parity and is the reliable choice for an irregular
hand-selected hole.

### A non-sandbox write is not automatically a bug — check for D9 opt-in first

Write commands (`set_parm`, `create_node`, `connect_nodes`, viewport/render
tools) succeeded without refusal on `Y:/3dPrints/x12_travel_case/...`, a
path well outside `SANDBOX_ROOT`. This is not a gap in `require_sandbox_scene()`
— see `HMCP_DESIGN.md` D9: a scene outside the sandbox can be opted in with a
`hmcp = 1` scene variable, and this production scene already had it set from
earlier work. Before treating a non-sandbox write succeeding as a safety
finding, check the open scene's `hmcp` variable rather than assuming the
guard is silently broken.

### The plugin serves one client at a time

`_process_server()` only calls `accept()` when it has no current client — by
design. `hmcp_bridge.py` holds a persistent singleton connection that never
disconnects between tool calls, so for the entire life of a Claude Code
session with the `houdini2` bridge connected, that single slot is
permanently occupied. Any second socket client — `check_contract.py`
included — can never be accepted and will time out in `CLOSE_WAIT`.

This is not the orphaned-listener bug above (one PID, one listener). Work
around it by diffing the bridge's own live `describe_commands` response
against `commands_spec.COMMAND_NAMES` instead of opening a second socket.
