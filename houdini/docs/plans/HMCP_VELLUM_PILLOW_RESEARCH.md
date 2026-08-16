# Vellum inflated-pillow research — post-mortem on the 2026-08-15 session

**Status:** research, not yet re-tested in Houdini. Nothing here has been
confirmed against the live sandbox scene. Everything below is grounded in
SideFX documentation, SideFX/odforce forum threads, and a reading of
`houdini/plugin/hmcp/build.py`.

**Scope.** Re-examines the five "silent failure modes" recorded in
`docs/HMCP_HOUDINI_NOTES.md` §"Vellum SOP solver — five silent failure modes"
and proposes what the pillow setup should have been. If the leading hypothesis
below is confirmed, that notes section needs a substantial correction — see
§7.

---

## 0. Leading hypothesis: the constraint stream never reached the solver

Read the five symptoms together and they collapse into one cause.

Vellum is a **two-stream** system. SideFX: *"A Vellum configuration is made of
two geometries: the display and collision geometry is the first input and first
output, and the constraint geometry is the second input and second output. The
two should have one-to-one point correspondence."*
([Vellum Constraints SOP](https://www.sidefx.com/docs/houdini/nodes/sop/vellumconstraints.html),
[Vellum Solver SOP](https://www.sidefx.com/docs/houdini/nodes/sop/vellumsolver.html))
The Vellum Solver's **second input is the constraint geometry**, and it is a
separate wire. One wire from `vellumconstraints` to `vellumsolver` gives the
solver geometry and *no constraints at all*.

`hmcp` structurally cannot make that second wire. `build.py:147`:

```python
to_node.setInput(input_index, from_node)
```

`hou.Node.setInput` has the signature `setInput(input_index, item_to_become_input,
output_index=0)`. `connect_nodes` exposes `input_index` (`commands_spec.py:135-141`)
but **never passes `output_index`**, so every wire hmcp has ever made comes off
**output 0**. Wiring `vellumconstraints` output **1** into `vellumsolver` input
**1** — the mandatory constraint wire — is not expressible through the current
tool surface.

That single gap predicts all four of the odd symptoms:

| Symptom | Prediction if constraints never arrived |
| --- | --- |
| #1 zero gravity → literally zero motion, bit-identical bbox | correct: unconstrained free particles, no forces, nothing to project |
| #1 gravity −0.5 → "the solver moves points" | correct: free-fall, not constraint relaxation |
| #2 self-collisions on + force → spiky explosion in ~10 frames | correct: a point cloud with `pscale` and no distance constraints holding it in a sheet mutually repels into a spiky ball |
| #3 pressure targets 1.35 / 1.6 / 5.0 all bit-identical, and identical to bypassing the node | correct: a node whose only output that matters is output 1, and output 1 goes nowhere, is a no-op |
| #4 `number of points in the geometry and constraints do not match` | consistent: a 0-point (or mismatched) constraint stream against a 1538-point geometry stream is exactly that error |

The notes' own diagnostic is the tell: *"`vellumconstraints` node output
(`get_geometry_info`) reports the same `npoints`/`nprims` as its input — the
constraint edges are not visible as extra primitives at all."* That is not a
quirk to work around — that is **output 0 behaving exactly as documented**.
Output 0 *is* the unchanged display geometry. The constraints were on output 1,
which nothing in the session ever queried or wired. Likewise, the guide
geometry drawn when the display flag is on is drawn by the SOP from its own
internal constraint data and proves nothing about what the solver received.

**Cheapest falsification** (do this before anything else next session, by hand
in the GUI since hmcp can't):

1. In the network editor, look at the wires into `vellumsolver`. Two wires from
   the `vellumconstraints` node, or one?
2. Middle-click the `vellumconstraints` node's **second** output, or drop a Null
   on it and check the geometry spreadsheet: it should show primitives with a
   string attribute `type` valued `distance` / `bend` / `pressure`, plus
   `restlength`, `stiffness`, `dampingratio`
   ([Vellum attributes](https://www.sidefx.com/docs/houdini/vellum/vellumattributes.html)).
3. Wire output 1 → solver input 1 by hand, rewind to the start frame, and see
   whether #1/#2/#3 all disappear at once.

If they do, four of the five "Vellum failure modes" are one hmcp tool gap.

---

## 1. Zero net external force → zero motion

**Finding: not expected Vellum behaviour, and the fake-gravity fix is masking
something.** Vellum is a Position-Based Dynamics solver: each substep applies
external forces, then runs Constraint Iterations of constraint *projection*,
which moves points directly toward satisfying their rest state. Projection is
not gated on external acceleration; nothing in the
[Vellum Solver docs](https://www.sidefx.com/docs/houdini/nodes/sop/vellumsolver.html)
describes a wake/seed requirement, and Quasistatic mode in particular exists
precisely to *relax geometry toward a rest configuration without dynamics*:
*"Each frame the simulation takes the inputs and runs them forward the given
number of frames."* A cloth constraint with `Rest Length Scale` 0.88 on a closed
cube must shrink the mesh ~12% under pure projection, with or without gravity.
A bit-identical bounding box to the last float over 200 frames is not "the
solver needs a nudge"; it is the solver having nothing to project. Combined
with §0, the explanation is that there were no constraints. A secondary
possibility worth ruling out at the same time: the repo's own
[known `get_geometry_info` staleness](../HMCP_HOUDINI_NOTES.md) means
"bit-identical" readings can be a measurement artefact — a bbox that never
changes across a parameter sweep should always be cross-checked with
`viewport_snapshot` before being treated as a physics result.

**Correct way to get gravity-free pressure-driven inflation:** Quasistatic mode
with `Quasistatic Frames` high enough to converge (40 is reasonable), gravity
zero, cloth + pressure constraints both actually wired. No fake gravity is
needed or wanted — gravity in a quasistatic solve just biases the equilibrium
shape downward, which is the opposite of a taut inflated pillow.

## 2. Self-collision + any external force → silent explosion

**Finding: real Vellum fragility, but a 1536-prim non-intersecting cushion is
nowhere near the regime where it should happen — so this is a symptom, not the
disease.** SideFX's
[Tips and troubleshooting](https://www.sidefx.com/docs/houdini/vellum/vellumtips.html)
names the cause directly: *"unruly objects exhibiting mysterious acceleration or
spinning typically stem from self-intersections (especially with oversized
pscales) or unconverged solves leaving asymmetric energy."* The documented
levers, in order: sanity-check `pscale` (*"The default Vellum pscale is small,
but any pscale attribute in the input will trump it"* — and it must stay **below
the shortest edge length**, or every triangle's fattening spheres overlap its
neighbours at rest and the mesh self-repels on frame 1); raise **Substeps**
(2–5 is the standard first move); use the solver's Visualize tab thickness
spheres to actually look at the radius. On a subdivided unit cube, edge lengths
are ~0.06–0.12 units, so a default thickness left at anything near 0.05+ makes
every point overlap its neighbours — that alone reproduces the spiky explosion.
Add the §0 hypothesis (no distance constraints holding the sheet together at
all) and an explosion is not merely likely, it is the only possible outcome.
**Verdict: turning self-collisions off was a workaround.** The correct order is:
wire constraints → set `pscale` well under the shortest edge → substeps 2–5 →
*then* re-enable self-collisions and check. A closed pillow only needs
self-collision once it folds enough to touch itself; for a lightly inflated
cushion it can legitimately stay off, but that should be a decision, not a
crash-avoidance measure.

## 3. The pressure constraint was inert — root cause found

**Finding: two independent, definite errors, and `stretchrestscale` is not the
pressure target.** This is the clearest result of the research.

- **`stretchrestscale` (Rest Length Scale) does not affect pressure
  constraints.** The SideFX parameter description is explicit: *"The rest length
  of the distance constraints will be the original distance between the points.
  This scale can be used to increase or decrease this. Setting to `0` will try
  to collapse the points together."* It applies to **stretch constraints only**.
  There is no per-type relabelling of this parm into a volume target; the notes'
  claim that Houdini reuses `stretchrestscale` as the pressure volume scale is
  **wrong**. Setting it to 1.35/1.6/5.0 on a Pressure-type node was always going
  to be a no-op on the volume.
- **The pressure target is the `restlength` attribute on the pressure
  constraint primitive.** Pressure *"stores the original volume and builds a
  many-point constraint to maintain it, for each piece determined by the Define
  Pieces parameter. The enforcement is global, so squishing one place will
  expand another, like a balloon."* On constraint primitives, `restlength` is
  the *"initial 'distance' of the constraint. Units are variable depending on
  type"* — for `type == "pressure"` that quantity **is the volume**
  ([Vellum attributes](https://www.sidefx.com/docs/houdini/vellum/vellumattributes.html),
  [Animated pressure constraints](https://www.sidefx.com/docs/houdini/vellum/pressure.html)).
  To over-inflate you multiply it. `restlengthorig` is provided *"so you can
  animate scaling effects without extra math."* The per-point point attribute
  `pressurescale` (*"How much to scale the effect of a Pressure constraint on a
  per-point basis"*) scales the **force**, not the target, and SideFX warns it
  *"can lead to unbalanced forces if the pressurescale is near zero on only one
  side of an un-pinned balloon."*

Answering the specific sub-questions:

- **Triangulation:** not documented as a hard requirement for pressure, but the
  page notes *"most constraints function best on triangulated geometry."* Cheap
  insurance: a Divide SOP (Convex Polygons) before the constraints. Not the
  cause here.
- **`piecemode` / `pieceattrib`:** *"Pressure constraints split the object into
  disjoint pieces to compute and enforce the volume."* Default connectivity-based
  piecing is correct for a single closed cube. If `Define Pieces` were set to
  *From Attribute* pointing at a non-existent attribute, you would get one
  degenerate piece — worth a glance, but not the primary suspect.
- **`preservevol`:** unrelated. It is a stretch/volume-preservation feature of
  the stretch solve, not the pressure constraint type. Do not expect it to
  activate pressure.
- **A separate activation toggle:** no. There is no hidden "enable pressure"
  switch. The only pressure-specific controls are `Define Pieces` / `Piece
  Attrib`, a stiffness on the generated constraint, and the `restlength` /
  `pressurescale` attributes. The
  [Vellum Balloon shelf tool](https://www.sidefx.com/docs/houdini/shelf/vellumballoon.html)
  docs do advise you may need to *"increase the Stiffness parameter in the
  `pressure_constraints` node to properly inflate your object"* if the topology
  is dense — a real second-order cause of "nothing inflates", but only once the
  constraint is actually reaching the solver.
- **Outward normals:** not documented as a requirement. Volume is computed from
  the closed surface; a consistently-wound mesh is assumed. A Box→Subdivide is
  consistently wound, so this was not the cause. (A Reverse SOP would flip the
  sign of the computed volume, which would be a genuine failure — worth knowing,
  not applicable here.)
- **Chaining cloth then pressure:** **this pattern is correct and is SideFX's
  own.** The Vellum Balloon shelf tool builds exactly *"a stretchable cloth
  constraint for the outer surface"* plus *"a pressure constraint to keep the
  cloth from collapsing."* The docs state multiple Vellum Constraints nodes
  chain together to build complex materials. `constrainttype` being an exclusive
  dropdown is by design — you stack nodes, you don't tick sub-features. **But
  chaining means chaining both streams**: geometry out0→in0 *and* constraints
  out1→in1 (the SOP's input 2 is documented as *"constraint geometry"*). Chain
  only output 0 and the second node silently discards the first node's
  constraints — which, given §0, is the second independent error here.

## 4. The wedged solver cache

**Finding: almost certainly not a cache bug, and the diagnosis in the notes
inverts cause and effect.** `The number of points in the geometry and
constraints do not match` is a plain statement of the documented invariant:
input 1 and input 2 of the solver *"should have one-to-one point
correspondence."* The error is raised at `graph_color_constraints` because that
is where the solver first indexes constraint points against geometry points.
Live-rewiring a solver's geometry input between two different `vellumconstraints`
nodes while its constraint input still points at the other one produces exactly
this, deterministically — and it explains why a **brand-new solver reproduced
it** (same mismatched pair of upstream wires), why `Reset Simulation` and
`Cache Enabled` did nothing (it is a topology check, not cached state), and why
only a full rebuild "fixed" it (the rebuild changed the wiring). There is no
evidence of corrupted state living inside a `vellumconstraints` output; the
conclusion that there was rests on `get_geometry_info` readings of **output 0**,
which by design cannot show a constraint mismatch.

One documented, genuinely different cause of the same message exists and is
worth knowing: on Houdini 20.0+, `Assume Uniform Radius` under **Grain
Collision** on the solver's Advanced tab is on by default and
[reportedly triggers this error](https://www.sidefx.com/forum/topic/89366/)
in some merged/named-piece setups — turning it off clears those. Not likely
relevant to a single cloth object, but it is the one real "known gotcha" in
this family.

**Pattern to avoid regardless:** rewiring a solver's inputs one wire at a time
while it holds a warm cache. Move both wires, then rewind to the start frame.
And note the general DOP rule that bit the session in other ways too: a Vellum
Solver in **Dynamic** mode only produces a correct result if the frames are
cooked in order from the start frame. Jumping straight to frame 60 after
changing an upstream parameter can hand you stale cached state — which is a
second, fully sufficient explanation for "1.35, 1.6 and 5.0 gave bit-identical
output." (Quasistatic mode is immune to this, since each frame re-runs from the
inputs.)

## 5. `veldamping = 0` letting a rest shape degrade

**Finding: `veldamping` is a legitimate tool but it is the blunt one, and here
it is papering over non-convergence.** SideFX describes it as *"a more brute
force approach to reducing dynamic velocity. The velocity is scaled directly by
this amount, causing sudden movements to be quickly damped."* The word
"brute force" is theirs. The
[troubleshooting page](https://www.sidefx.com/docs/houdini/vellum/vellumtips.html)
lists the causes of a shape that degrades rather than settles — *"unconverged
solves leaving asymmetric energy"* — and gives the ordered fixes: **increase
Smoothing Iterations** (*"a Jacobi approach which is slower to converge but
leaves error spread out in a more attractive fashion"*), increase damping,
randomise constraint/point ordering, or use plasticity to reset the rest
configuration. It also gives the sizing rule for **Constraint Iterations**:
they *"should roughly equal your cloth's diameter"* — the longest shortest path
through edges — and *"increasing substeps allows reducing iterations
proportionally."* A subdivided unit cube has a diameter of roughly 40–50 edges,
so under-iterating is entirely plausible. Gauss-Seidel projection with too few
iterations on a closed shell leaves a residual that accumulates frame over
frame; `veldamping` bleeds the resulting velocity but never fixes the residual,
which is exactly the "looks fine at frame 30, spiky at frame 60" signature.

**The principled way to reach a genuine equilibrium:** use **Quasistatic** mode.
It has no frame-to-frame coherency by construction, so it cannot slowly diverge
— it re-relaxes from the input every frame. If the shape must be dynamic, raise
Substeps to 2–5 and Constraint Iterations toward the mesh diameter, add
Smoothing Iterations, *then* add a small `veldamping` (0.05–0.1) as polish
rather than 0.3 as structural support. 0.3 is a lot of damping; it will also
kill any secondary motion the pillow should have.

---

## 6. Recommended setup

Two variants. Build **A** first — it is the shortest path to the actual creative
intent (a taut, inflated pillow), and it is SideFX's own balloon recipe.

### A. Quasistatic inflated pillow (recommended)

```
box              primtype = Polygon Mesh, 1×1×1
  │
divide           Convex Polygons ON   (triangulate — "most constraints
  │                                    function best on triangulated geometry")
subdivide        Catmull-Clark, 2–3 iterations
  │              (bilinear preserves the sharp box corners — confirmed
  │               in-session; Catmull-Clark is correct here)
  │
vellumconstraints_cloth     constrainttype = Cloth
  │  ╲                      Stretch Stiffness  ~1e4  (low — must stretch)
  │   ╲                     Bend Stiffness     ~1e-2 (very low — soft fabric)
  │    ╲                    Rest Length Scale  0.92–0.96 (taut surface)
  │     ╲                   Damping Ratio      ~0.05
  │      ╲
  ├───────╲──> in0          out0 ──┐
  └────────╲─> in1 (constraints)   │
vellumconstraints_pressure   constrainttype = Pressure
  │  ╲                      Define Pieces = From Connectivity
  │   ╲                     Stiffness: raise if it refuses to inflate
  │    ╲                    (shelf-tool docs call this out explicitly)
  │     ╲
  ├──────╲──> in0           out0 ──┐
  └───────╲─> in1                  │
inflate_wrangle              Primitive wrangle, run over Primitives,
  │  (on the CONSTRAINT      operating on the constraint stream only:
  │   stream, not geo)
  │                            if (s@type == "pressure") {
  │                                f@restlength *= chf("inflate");   // 1.35
  │                            }
  │
vellumsolver                 IN0 ← geometry stream
     (TWO WIRES)             IN1 ← constraint stream   ← the wire that was missing
                             Simulation Type = Quasistatic
                             Quasistatic Frames = 40
                             Gravity = (0,0,0)
                             Ground = off
                             Substeps = 2
                             Constraint Iterations ≈ mesh diameter (~50)
                             Smoothing Iterations = 5–10
                             Self Collisions = off initially
                             Thickness/pscale ≪ shortest edge length
  │
null OUT
```

Why this and not what the session landed on:

- **`restlength *= 1.35` on the pressure primitive is the actual volume
  target.** `restlength` for `type == "pressure"` *is* the stored volume, so
  the multiplier is direct — no volume-vs-linear conversion needed (the
  conversion caveat in the forum threads applies to *scaling the mesh*, not to
  scaling the stored volume). Equivalent alternative: a **Vellum Constraint
  Properties SOP** on the constraint stream in *Scale* mode on Rest Length.
- **Cloth Rest Length Scale slightly under 1 plus pressure is the pillow
  idiom** — the surface wants to shrink, the volume refuses to, the result is
  taut and puffy. That is the look "shrink + gravity onto a floor" only
  approximates.
- **Quasistatic, zero gravity, no ground.** The target is a shape, not an
  animation. This removes the entire class of problems 1, 4 and 5 by
  construction: no wake-up nudge is needed, no cached-frame ordering matters,
  and it cannot slowly diverge.

### B. Dynamic pillow resting on a floor

Same constraint chain. Change on the solver: `Simulation Type = Dynamic`,
`Gravity = (0,-9.81,0)` (real gravity — pick a scene scale rather than fudging
the constant), `Ground = on`, `Substeps = 3`, Smoothing Iterations 5–10,
`veldamping = 0.05`. Cook from the start frame, and inspect a frame well past
where it should have settled (frame 100+) before believing it, per the
session's own correct lesson. Enable self-collisions only after confirming
`pscale` is well under the shortest edge length.

### Verification checks specific to pressure

- On the **solver output points**, the attributes `pressuregradient`,
  `volumepts` and `volume` are documented as *"values computed during
  constraint evaluation for Pressure constraints."* If they are absent, the
  pressure constraint is not being evaluated — this is a far stronger test than
  guide geometry or a bounding box, and it is queryable through
  `get_geometry_info`'s attribute list.
- On the **constraint stream**, confirm a primitive with `s@type == "pressure"`
  exists and that its `f@restlength` reads as a volume of roughly the right
  magnitude (~1.0 for a unit cube), and that the value changes when the
  inflate slider changes.

---

## 7. What was a workaround, not a fix

| Session "fix" | Verdict |
| --- | --- |
| Small fake gravity (−0.5) to "wake" the solver | **Workaround.** PBD constraint projection does not need seeding. It masked a solver with no constraints. Real fix: wire output 1 → input 1. |
| `doselfcollisions = off` | **Workaround.** The explosion is the documented signature of oversized `pscale` and/or unconverged/unconstrained geometry. Real fix: `pscale` below shortest edge, substeps 2–5, constraints actually connected. Off is a defensible *choice* afterwards; it was not one here. |
| Wiring `stretchrestscale` on the Pressure node | **Wrong parameter, definitively.** Rest Length Scale is documented as applying to stretch constraints only. The pressure target is `f@restlength` on the pressure constraint primitive. |
| Abandoning pressure and faking puffiness with `stretchrestscale` 0.9 + gravity | **Workaround**, and the one the user noticed — it reads as "a soft cube that sagged" because it is. |
| Rebuilding the whole chain to clear the point-count error | **Workaround.** The error is a topology-mismatch assertion, not corrupted state. The rebuild worked because it changed the wiring. |
| `veldamping = 0.3` | **Partial workaround.** Damping is a real lever but 0.3 is heavy and it treats the symptom of an unconverged solve. Fix iterations/substeps/smoothing first; use Quasistatic if the goal is a static shape. |
| Catmull-Clark instead of bilinear subdivision | **Genuine fix.** Bilinear preserves the box's sharp corners; Catmull-Clark is correct for a cushion. Keep it. |
| "Check a frame well past where it should have settled" | **Genuine methodology fix.** Keep it. |

## 8. Follow-up work this implies

1. **Verify §0 by hand in the GUI** (the falsification steps above). Everything
   else is downstream of that answer.
2. **If confirmed: `connect_nodes` needs an `output_index` parameter.**
   `build.py:147` → `to_node.setInput(input_index, from_node, output_index)`,
   plus `"output_index": "int = 0"` in `commands_spec.py`. Without it, hmcp
   cannot build *any* Vellum setup, and the same gap blocks every other
   multi-output node (Split, Vellum I/O, Fluid Source, ROP outputs).
3. **Correct `docs/HMCP_HOUDINI_NOTES.md`** §"Vellum SOP solver — five silent
   failure modes". Items 1–4 as written are wrong or misattributed, and item 3
   states a false fact about `stretchrestscale` that will mislead the next
   session. Item 5's methodological lesson and the Catmull-Clark note are
   sound and should survive.
4. **Add a general note** that `get_geometry_info` on a multi-output node only
   ever reports output 0, so "the node's output looks unchanged" is not
   evidence about its other outputs.

Once (1) is answered and (2)/(3) are filed, this document has nothing durable
left in it and should be deleted per the repo's document-lifecycle rule.

---

## Sources

- [Vellum Constraints geometry node](https://www.sidefx.com/docs/houdini/nodes/sop/vellumconstraints.html) — inputs/outputs, constraint type list, Rest Length Scale scope, Define Pieces, Pressure description
- [Vellum Solver geometry node](https://www.sidefx.com/docs/houdini/nodes/sop/vellumsolver.html) — input list and point-correspondence requirement, Dynamic vs Quasistatic, Velocity Damping, Substeps, Constraint/Smoothing Iterations, Default Thickness
- [Vellum attributes](https://www.sidefx.com/docs/houdini/vellum/vellumattributes.html) — `restlength`, `restlengthorig`, `type`, `stiffness`, `pressurescale`, `pressuregradient`/`volumepts`/`volume`, `pscale`
- [Animated pressure constraints](https://www.sidefx.com/docs/houdini/vellum/pressure.html) — pressure stores original volume; animating `restlength` and `pressurescale`
- [Vellum Balloon shelf tool](https://www.sidefx.com/docs/houdini/shelf/vellumballoon.html) — cloth + pressure is the balloon recipe; low stretch stiffness; raise pressure stiffness if it will not inflate
- [Vellum tips and troubleshooting](https://www.sidefx.com/docs/houdini/vellum/vellumtips.html) — unruly objects, oversized pscale, unconverged solves, smoothing iterations, iterations ≈ cloth diameter
- [Fixing intersecting collision geometry](https://www.sidefx.com/docs/houdini/vellum/intersect.html) — thickness/clearance, substeps 5
- [Vellum Constraint Properties SOP](https://www.sidefx.com/docs/houdini/nodes/sop/vellumconstraintproperty.html) / [DOP](https://www.sidefx.com/docs/houdini/nodes/dop/vellumconstraintproperty.html) — Set/Scale on Rest Length and Rest Length Scale
- [SideFX forum 89366](https://www.sidefx.com/forum/topic/89366/) — `Assume Uniform Radius` under Grain Collision as a known cause of the point-count-mismatch error
- [SideFX forum 89995](https://www.sidefx.com/forum/topic/89995/) — animating `restlength`; surface and pressure constraints are separate systems
- [odforce 53679](https://forums.odforce.net/topic/53679-vellum-pressure-atribute-paul-esteves-hive/) — pressure is a single many-point primitive with one `restlength`; wrangle patterns
- [cgwiki: Vellum](https://tokeru.com/cgwiki/HoudiniVellum.html) — chaining multiple constraint nodes with both outputs into the solver; point-correspondence gotchas
- Repo: `houdini/plugin/hmcp/build.py:121-149`, `houdini/commands_spec.py:135-141`

### Not found / reasoning from architecture

- No SideFX source states that Vellum requires a nonzero external force before
  constraint projection runs. §1's conclusion is reasoned from PBD architecture
  and from Quasistatic mode's documented purpose.
- The SideFX docs do not enumerate a per-type parameter block for Constraint
  Type = Pressure, so the exact internal parm names on the SOP for pressure
  stiffness are unverified; the shelf-tool page confirms a Stiffness control
  exists on the generated `pressure_constraints` node.
- No source confirms or denies a triangulation *requirement* for pressure; the
  Divide SOP above is precautionary, on the strength of the docs' general
  "most constraints function best on triangulated geometry."
