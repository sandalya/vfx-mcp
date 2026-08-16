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

## Vellum SOP solver (`vellumsolver`) — the missing constraint wire

Found 2026-08-15 building a pressure-inflated cloth pillow
(`/obj/ice_scale_pattern`, sandbox scene); root-caused and fixed 2026-08-16.
`vellumsolver` is a **three-input SOP**: input 0 geometry, input 1
**constraints** (from a `vellumconstraints` node's *second* output), input 2
collision objects. `connect_nodes` had no `output_index` parameter, so it
could only ever wire a node's output 0 — the constraint stream had no way to
reach input 1 at all. Everything below that looked like five unrelated
solver quirks was this one gap:

- zero motion under zero gravity — no constraints to project, so nothing
  moved regardless of external force
- self-collisions exploding — an unconstrained point cloud with `pscale`
  mutually repels; nothing was holding the sheet together
- the `pressure` constraint type looking totally inert — its stream never
  reached the solver, so no target value could have mattered
- a `vellumsolver` throwing `number of points in the geometry and
  constraints do not match` after rewiring — a straightforward
  topology-mismatch assertion (input 1 and input 2 must have point
  correspondence), not corrupted DOP cache state
- a resting shape degrading between frame 30 and frame 60 — unconverged
  projection accumulating residual energy with no real constraint to
  converge toward

Fixed 2026-08-16: `connect_nodes(from_path, to_path, input_index,
output_index)` — `build.py`/`commands_spec.py`/`hmcp_bridge.py` all now
carry `output_index` (default 0, so old calls are unaffected). Confirmed
live: wiring a `vellumconstraints` chain's output 1 through to the solver's
input 1 turned a cube into a taut, symmetric, rounded pressure-inflated
pillow on the first cook — see `viewport_snapshot` from that session.

**Two more things that were genuinely wrong, independent of the wire gap:**

- **`stretchrestscale` (Rest Length Scale) does not affect Pressure
  constraints — it only scales Distance/stretch constraints.** The pressure
  volume target is the `restlength` **primitive** attribute on the
  constraint primitive where `s@type == "pressure"` (that attribute *is* the
  stored volume for that type; multiply it directly, e.g. in a Primitive
  Wrangle running over the constraint stream:
  `if (s@type == "pressure") f@restlength *= chf(...);`).
- **Chaining two `vellumconstraints` nodes (e.g. cloth → pressure) requires
  wiring *both* outputs to *both* inputs of the next node** (out0→in0,
  out1→in1). A single wire (out0→in0 only) silently drops the first node's
  constraints — the second node's constraint output then only contains its
  own type, not the merged set.

**Verification that actually proves a constraint type is being evaluated:**
on the **solver's own output**, check for `pressuregradient`, `volumepts`,
`volume` point attributes (Pressure) — SideFX documents these as populated
"during constraint evaluation." Their absence is definitive proof that
constraint type never reached the solver; their presence is definitive proof
it did. Guide-geometry visibility and bounding-box-unchanged readings are
**not** reliable evidence either way — the guide draws from the SOP's own
internal constraint data regardless of what actually reached input 1, and
`get_geometry_info` on a multi-output node (any `vellumconstraints`,
`switch`, `split`, ...) only ever reports **output 0** — it cannot show
what's on output 1 or later. To inspect a second output directly, wire it
(now possible via `output_index`) to a `null` and query that.

Full research trail (SideFX doc citations, falsification steps, the
recommended quasistatic + pressure recipe): `git show
725a6c4:houdini/docs/plans/HMCP_VELLUM_PILLOW_RESEARCH.md` — the plan doc
itself is deleted post-harvest per the repo's document lifecycle rule.

**Once the wire was fixed, the cube inflated into a perfect sphere, not a
cushion — two more root causes, both silent:**

- **`vellumconstraints`' Stretch Stiffness defaults to `1.0 × 10^0` — far too
  soft to resist a pressure target, regardless of `stretchrestscale`.** The
  Vellum stiffness UI is a mantissa (`stretchstiffness`, default `1.0`) times
  a menu-selected power of ten (`stretchstiffnessexp`, default token `"0"`,
  i.e. ×1). At that default the cloth has almost no resistance to stretching,
  so any pressure inflation just blows the mesh out to whatever shape
  minimizes surface energy for the target volume — a sphere — no matter how
  taut `stretchrestscale` claims to make it. Raising `stretchstiffnessexp` to
  `"4"` (×10⁴, still "low" by Vellum's own standards per the shelf-tool docs)
  fixed it. `bendstiffnessexp` is the same mantissa/exponent-menu pattern.
- **A coarse control cage under a high subdivision depth rounds the *rest
  shape itself* into a near-sphere before the solver ever runs.** The box
  started at 2 divisions/axis (a 3×3 point grid per face) into `subdivide`
  at depth 4 (Catmull-Clark). A closed manifold box has no boundary loops, so
  none of `vtxboundary`'s corner-pinning options apply — CC subdivision on a
  cage that coarse converges almost all the way to its analytic limit
  surface, which for a low-poly cube is close to a sphere, well before depth
  4. The un-solved, un-pressurized geometry was already round. Fix: raise
  the source resolution (6 divisions/axis) and drop subdivide depth to 2 —
  enough points survive between corners that a couple of CC passes only
  rounds the edges, leaving recognizable flat-ish faces (the actual "pillow"
  silhouette). Check the **pre-solve** geometry's shape, not just its bbox,
  before blaming the solver for an overly round result — the rest shape can
  already be wrong.

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
