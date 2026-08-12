# Houdini MCP — SOP Cookbook — Plan

Status: proposal, nothing built.
Audience: the repo owner, and any agent picking this up cold.
Scope of this pass: **SOPs only.** Geometry creation/editing (primitives, points,
attributes, groups, VEX wrangles), noise via both VOP nodes and VEX functions,
and a lighter secondary look at Vellum (SOP-context Configure/Solve/constraints).
No DOPs, no Solaris, no lighting.

Sibling docs, read them before implementing anything here:
`HOUDINI_MCP_REWRITE_PLAN.md` (doctrine, safety model, phases),
`HMCP_CAMERA_CONTROL_PLAN.md`, `HMCP_HEADLESS_RENDER_PLAN.md`.

---

## 0. What problem this actually solves

The obvious framing — "the agent doesn't know enough Houdini, so feed it a
library of setups" — is not what the evidence in this repo says.

| Evidence | What it rules out |
|---|---|
| Phase 3 passed (BACKLOG, 2026-08-10): `/obj/rock` built unattended, `sphere → mountain::2.0 → attribwrangle → smooth::2.0`, cooked clean, self-corrected | Plumbing is not the gap. The write tools work. |
| `get_node_type_parms` / `get_node_help` return the *installed* 21.0.729 parameter names and help text on demand | Node-name and parameter recall is not the gap. It is solved by a tool call, and solved better than any document could, because it cannot drift from the installed build. |
| `houdini/references/frozen_cave/NOTES.md`, attempts 2 and 3: both cooked clean, both were the wrong *family* of technique for the reference. Attempt 3's own diagnosis — "height-displacement on a flat plane fundamentally can't produce the volumetric overlapping-fold look" | **This is the gap.** Technique-family selection against a visual target. |
| Same file, attempt 1: "Closest match so far, per direct comparison" | And this is the second gap. That judgment is unfalsifiable — there is no criterion behind it, so it cannot be trusted, re-checked, or improved on. |
| `viewport_snapshot` is an unlit OpenGL grab of `curViewport()` from wherever the owner left the view (`build.py:291`) | And the third: the feedback signal itself is weak. |

So the cookbook's job is **not** node syntax. It is:

1. Which family of technique produces which class of look, and — more valuable —
   which families are *structurally incapable* of which looks.
2. Checkable success criteria, so "closest match so far" becomes a measurement.
3. A place for negative results to survive past the session that produced them.

Everything in §1–§3 is designed against those three, and §4 argues about how much
of it is worth building at all.

---

## 1. Learning resources

Rules of use before the list:

- **Tier 0 beats everything.** In-process introspection is version-exact and free.
  A web page is a hypothesis about your Houdini; `get_node_type_parms` is a fact.
- **Pin the docs version.** `https://www.sidefx.com/docs/houdini/…` now serves
  **22.0** — Houdini 22 shipped in July 2026 (22.0.368). pc137 runs **21.0.729**;
  the local machine runs **20.5.278**. The versioned URL scheme works and is
  verified live: `https://www.sidefx.com/docs/houdini21.0/nodes/sop/attribnoise.html`
  loads with "Houdini 21.0" in the breadcrumb. **Always use the `houdini21.0`
  form.** An unpinned link is how a recipe ends up citing a parameter that does
  not exist on the target build.
- **Cite where a recipe came from, with an access date.** Front matter has a
  `source:` block for exactly this (§3.2).
- **A tutorial is a source of *technique families*, not of parameter values.**
  Copy the idea and the node chain; re-derive the numbers against your own
  geometry scale, and record the numbers you actually measured.

### 1.1 Tier 0 — inside the running Houdini (free, version-exact, zero drift)

| Source | How | Use it for |
|---|---|---|
| `get_node_help(type_name, category)` | MCP, already shipped | The authoritative description of a node on *this* build |
| `get_node_type_parms(type_name, category)` | MCP, already shipped | Real parm names, types, defaults, menu items |
| `list_node_types(category, name_filter)` | MCP, already shipped | "Does 21.0 have a `attribnoise`? What's it actually called?" |
| `get_network` + `get_node_info(only_non_default=True)` | MCP, already shipped | **Reading an existing scene's graph** — reads are unrestricted in any scene, so any reference `.hip` the owner opens becomes machine-readable ground truth |
| Bundled example assets | On disk, no download | See below |

**The bundled examples are the underrated one.** Verified on the local install:
`C:/Program Files/Side Effects Software/Houdini 20.5.278/houdini/help/examples/nodes/`
contains **233 SOP example directories and 128 example `.hda` files** (plus 20
DOP, 2 VOP). Including `vellumsolver` (with `VellumFluidPhases*`), `vellumdrape`,
`vellumrestblend`, `attribwrangle`, `attribtransfer`, `attribfromvolume`,
`cloudbillowynoise` and so on. These are SideFX-authored, ship with every
install, exist on pc137 too, and are exactly the scope of this pass. They are
`.hda` (not `.hip`), so they are opened/walked rather than merged — which is fine
for extraction. See §4.2; this is the corpus that makes bulk recipe generation
cheap.

### 1.2 Tier 1 — official SideFX (free)

| Resource | URL (pin to 21.0) | Notes |
|---|---|---|
| Node reference | `sidefx.com/docs/houdini21.0/nodes/sop/` | The per-node pages; each has an "Examples" section matching the bundled `.hda`s |
| VEX function index | `sidefx.com/docs/houdini21.0/vex/functions/` | `noise`, `snoise`, `onoise`, `pnoise`, `xnoise`, `anoise`, `wnoise` (Worley/cellular), `flownoise`, `curlnoise`, `curlnoise2d`, `curlxnoise`, `turbulence` — the whole SOP-noise surface in one index |
| Vellum overview | `sidefx.com/docs/houdini21.0/vellum/` | Confirms the SOP-context story: Vellum Solver SOP wraps the DOP solver; `vellumconfigure*` presets are Vellum Constraints with parameters pre-set — i.e. this scope is legitimately SOP work |
| Attribute Noise 2.0 SOP | `…/nodes/sop/attribnoise.html` | The modern one-stop noise SOP; the first thing to check before hand-rolling a wrangle |
| Content Library | `sidefx.com/contentlibrary/` | Free `.hip`/`.hda` downloads, login required. Project Skylark (stylized buildings/clouds, `.hip`, H20.5) is here |
| SideFX Labs examples | `github.com/sideeffects/SideFXLabsExamples` | Free, git-cloneable, no login |
| SideFX forums | `sidefx.com/forum/` | The most active official channel; SideFX devs answer. Best place for "which node does X in 21" |
| HIVE talks | YouTube, SideFX channel | Free, version-tagged (H22 HIVE talks exist as of mid-2026) |

### 1.3 Tier 2 — community reference (free)

| Resource | URL | Currency | Use for |
|---|---|---|---|
| **CGWiki — Matt Estela** | `tokeru.com/cgwiki/` | Live; core pages date from the H16–19 era, concepts current, some node names dated (pre-`::2.0`) | The single best free source for *technique families* and VEX idioms. `HoudiniVellum.html` is directly in scope |
| **Joy of Vex — Matt Estela** | `tokeru.com/cgwiki/JoyOfVex01.html` … | Same | A 20-day structured VEX course, free. The best-matched single resource to the "VEX wrangles + noise" half of this scope |
| od\|force forums | `forums.odforce.net` | Still up and still posted to, but well past its peak traffic | Treat as a searchable archive, not a place to ask |
| John Kunz, "Using noise in VEX" | `mrkunz.com/blog/03-04-2017_Using-noise-in-VEX.html` | 2017, and that is fine — the noise functions have not changed | The clearest breakdown of noise *parameters* (frequency/amplitude/roughness/octaves) anywhere |
| Awesome-Houdini / houdini-resources | `github.com/wyhinton/AwesomeHoudini`, `github.com/agmmnn/houdini-resources` | Link indexes, quality unvetted | Discovery only |
| qLib | `qlab.github.io/qLib/` | Open-source HDA library | Readable reference *implementations* of SOP techniques. Do **not** install onto pc137 — read, don't deploy |
| Unofficial Houdini Discord; Nine Between Discord | — | Active | For the owner, not for the agent: no stable URLs, nothing citable, nothing archivable. Deliberately excluded from recipe `source:` fields |

### 1.4 Tier 3 — educators

| Resource | Cost | Currency (verified Aug 2026) | Verdict for this scope |
|---|---|---|---|
| **Entagma** — `entagma.com` | Free bi-weekly tutorials + Patreon **$29+** tier | **Current.** Front page as of 2026/08: "Heightfields on 3D Objects (Modding Houdini 22)" (free), "Big Setups Ep.00: FLIP based Foam" (Patreon), "New in Houdini 22: Training Gaussian Splats" (free), "Vellum 201 – Ep.06: Mastering Drag and Damping" (Patreon) | **First pick.** Procedural-geometry and noise idioms are the house style, and there is an active Vellum series. SideFX even mirrors a curated set at `sidefx.com/learn/collections/entagma/` |
| Rohan Dalvi — `rohandalvi.net` | Paid (Gumroad) + a large free set | Active | Procedural modeling; good "whole asset" builds |
| Voxyde (Razvan Ciobanu) | Free courses + paid Pro tier | Active | Cinematic FX; more DOP-weighted than this pass |
| **Applied Houdini** (Steven Knipping) — `appliedhoudini.com` | Paid | **Dated.** Latest release traced to Dec 2022, H17/18-era | Excellent, but it is a *dynamics* series — mostly out of scope for a SOP-only pass, and version-dated. **Deprioritize for this pass**, revisit when DOPs enter scope |
| Henry Dean | Free (SideFX channel) | Current (H22 HIVE talk, ~Jul 2026) | **Correction to the framing of this task:** Henry Dean is SideFX staff working on **KineFX / character rigging** — he is not the CGWiki author (that is Matt Estela) and his material is not about SOP noise. Relevant only if character/rig work ever enters scope |

### 1.5 Which of these a *recipe* may cite

Ranked, and this ordering is a rule, not a preference:

1. Tier 0 introspection (always re-checked at build time anyway)
2. Tier 1 official docs, `houdini21.0`-pinned
3. Tier 1 free `.hip`/`.hda` (Content Library, Labs examples, bundled examples)
4. Tier 2 free web pages with a stable URL + access date
5. Tier 3 paid material — **derived description only**, never verbatim content
   (see Open Question Q1)

---

## 2. The replicate-and-verify loop

The loop's one non-negotiable design rule: **write the expectation before
building, not after.** Every failure in `frozen_cave/NOTES.md` was diagnosed
after the fact, in prose, against a standard that was invented once the result
was already on screen. Predict first and the comparison becomes falsifiable.

### 2.1 The loop

```
0. TARGET     pick a reference; write intent + named visual features (§2.5)
1. CONTRACT   write the expectation block BEFORE any MCP write call
2. BUILD      create_node / connect_nodes / set_parm, one step at a time
3. PROBE      get_geometry_info + get_node_errors after every step
4. MEASURE    T0..T4 against the contract (numbers, not opinions)
5. ABLATE     seed / amplitude / frequency perturbation tests (§2.4)
6. LOOK       viewport_snapshot (later: render_snapshot) vs the feature list
7. VERDICT    verified | partial | rejected-wrong-family | blocked
8. RECORD     write the recipe file, pass or fail — failures especially
```

### 2.2 The contract, written at step 1

A plain block, filled in before building:

```yaml
expect:
  chain: [sphere, mountain::2.0, attribwrangle, smooth::2.0]
  npoints: 1000..1500          # order of magnitude, not exact
  attributes_created: [N, dist]
  groups_created: []
  bbox_change_vs_input: 0.05..0.30   # fractional; NOT 0, NOT 3.0
  cook: clean
```

Ranges, not exact values, everywhere except attribute names and cook state. An
exact-value contract is either luck or a copied number; a range encodes what you
actually believe.

### 2.3 Verification tiers

**T0 — Cook health (binary, gate).** `get_node_errors` on every node in the
chain: zero errors *and* zero warnings. Nothing downstream counts until this
passes. Cheap, already shipped, and it catches the largest class of failure.

**T1 — Topology (binary).** `get_network(parent)` reproduces the intended chain
and wiring, including input indices. Catches the silent classic: a node created
but never connected, so the display flag is showing an earlier stage and the
whole judgment is about the wrong geometry.

**T2 — Attribute contract (binary).** `get_geometry_info` lists every attribute
with name / class / type / size. Assert each expected attribute exists at the
right class and type. Catches "the wrangle ran on points but wrote a detail
attribute", "`N` is missing so the shading reads flat", "`pscale` is a vector
where a float was intended".

**T3 — Numeric envelopes (bounded).** From the same call: `npoints`, `nprims`,
`nvertices`, bbox. Compare against the contract's ranges. The two failures this
is built to catch, both of which cook perfectly clean:

- **Silent no-op**: bbox identical to the input's bbox → the noise amplitude is
  zero, or the wrangle wrote to a variable nothing reads, or `@P` was never
  touched. The graph "works" and does nothing.
- **Blow-up**: bbox 10–100× the input → frequency/amplitude in the wrong unit
  for the geometry's scale. Very common when copying numbers from a tutorial
  built at a different world scale.

Anchor example from the verified rock (BACKLOG 2026-08-10): a 1122-point
polymesh sphere with bbox exactly ±0.5. After `mountain::2.0` + the VEX pass,
a plausible envelope is bbox 1.05–1.4 across each axis and npoints unchanged
(displacement moves points, it does not create them). If npoints changed,
something in the chain is not what you think it is.

**T4 — Ablation (the strongest cheap signal, and the one nobody writes).**
Three perturbations, each measured with `get_geometry_info` only — no eyes
needed, no human needed:

| Perturbation | Assertion | Catches |
|---|---|---|
| Change the noise **seed** / offset | bbox and/or point positions must change | Noise present in the graph but not actually driving the output — the single most common false-positive in procedural work |
| Set **amplitude to 0** | bbox returns to the input's bbox within epsilon | The displacement is coming from somewhere else than you think |
| **Double the frequency** | bbox stays roughly the same, surface variation increases | Frequency wired to the wrong input, or the noise is effectively constant |

Recording "ablation: pass" in a recipe is worth more than a screenshot. It is
the difference between "it looked right once" and "the mechanism is live."

*Implementation note:* T4 needs a scalar readout of surface variation, and
`get_geometry_info` returns bbox but not, say, point-position variance. Two
honest options: (a) accept bbox as the proxy for T4 day one — it is enough for
the seed and amplitude tests, which are the two that matter; (b) build the
variation measure as a *recipe* — a `measure` branch in the graph (e.g.
`attribwrangle` computing a deviation attribute → `attribpromote` to a detail
maximum) read back through the existing attribute list. Option (b) needs no new
MCP capability at all and is itself a cookbook entry. **Prefer (b); do not add
a new command for this.**

**T5 — Visual (judged, and the judgment is structured).** Before looking at the
snapshot, write 3–5 **named visual features** the reference has. This section
already exists, informally and excellently, in `frozen_cave/NOTES.md` under
"What the reference actually shows" — rounded overlapping lobes, gravity-directed
structure, tapered organic icicles, thickness-driven translucency, fine
micro-ripple on large forms. Promote that from an ad-hoc paragraph to a required,
*pre-committed* field.

Then score each feature `present` / `absent` / `wrong-family`, and pass T5 only
if every feature is `present`. "Closest match so far" is not a verdict.

`wrong-family` is a distinct outcome and deserves its own field
(`family_limitation`) because it is the highest-value thing the cookbook can
store: *a structural reason a technique can never produce a feature*, e.g.
"height displacement on a plane cannot produce overlapping folds, at any
parameter setting, because a heightfield is a function of (x,z)." That sentence
saves a whole session. `frozen_cave` attempt 3 paid for it once already.

**T5's dependency, stated plainly:** with today's tooling, T5 is an unlit OpenGL
grab from whatever viewport happens to be under the cursor. That is a poor basis
for a permanent record. See §4.1 — this is why the cookbook should not start
before the camera and render work lands.

### 2.4 Vellum-specific criteria — and a real gap

Vellum verification is not the same shape, because the interesting output is at
frame N, not frame 1:

- T0–T2 apply unchanged (constraint geometry is geometry: check for the
  constraint prims and the `Constraint` attributes on the second output).
- T3 gets Vellum-specific envelopes: point count preserved through the solve;
  bbox at rest-frame vs settled-frame differs (a cloth that never moved is the
  Vellum equivalent of the silent no-op); no NaN — detectable as an absurd bbox.
- The ablation equivalent is *stiffness*: raising stiffness must reduce settled
  displacement. Same principle, same measurement.

**The gap:** `houdini/commands_spec.py` has 24 commands and **none of them
advance the playbar**. There is no `set_frame` / `cook_frame`. A Vellum setup
built through the MCP today can be *constructed* and *inspected at the current
frame*, but the agent cannot step the sim and cannot see it settle. So:

> **Vellum is verifiable only for construction, not for behaviour, until a frame
> command exists or the headless worker lands.** Recipes in `family: vellum` are
> capped at `status: partial` until then, and must say so.

Whether to add a narrow `set_frame(frame)` write command is Open Question Q5. It
is a small, low-risk addition (no paths, no code, no filesystem) but it is new
capability, so it is the owner's call, not mine.

### 2.5 Verdict vocabulary (controlled — these five strings, no others)

| Verdict | Means |
|---|---|
| `verified` | T0–T4 pass, T5 all named features present, and a cold replay reproduced it (§2.6) |
| `partial` | T0–T4 pass, T5 incomplete — the missing feature is named in the file |
| `rejected` | The technique family cannot produce the target. `family_limitation` is mandatory |
| `blocked` | Needs capability the MCP does not have. The missing capability is named |
| `draft` | Written but not yet run end-to-end. Never cite a `draft` as precedent |

### 2.6 The cold-replay rule

A recipe is `verified` only after a **fresh session, reading only the recipe
file**, rebuilds it and hits the same T0–T4 numbers. If a recipe needs
conversation context to be rebuildable, it is not a recipe; it is a note.

Cadence: replay a random sample of 3 recipes after any Houdini version change,
any plugin deploy that touches `build.py`, and otherwise quarterly. A cookbook
nobody re-runs rots silently, which is worse than not having one.

---

## 3. Storage and retrieval

### 3.1 Layout

```
houdini/
  cookbook/
    README.md            # how to use this; verdict vocabulary; the 5 canonical queries
    DOCTRINE.md          # the short, high-density rules file (§4.2 — read this first)
    INDEX.md             # GENERATED. Do not hand-edit
    taxonomy.yaml        # controlled vocabularies: families, tags, difficulty, verdicts
    recipes/
      sop-geometry/      # primitives, topology, copy/instance, booleans, VDB
      sop-attributes/    # attribcreate/promote/transfer/wrangle-as-attribute-work
      sop-groups/        # group creation, group expressions, group-driven ops
      vex-noise/         # noise() / curlnoise() / wnoise() in wrangles
      vop-noise/         # Noise VOP, Mountain, Turbulent Noise, Unified Noise
      vellum/            # SOP-context Vellum (capped at `partial`, see §2.4)
    snapshots/
      sop-noise-0007.jpg
  references/            # UNCHANGED ROLE — per-subject look-dev logs
    frozen_cave/
      NOTES.md
      halo_ice_cave_01.png
```

`references/` and `cookbook/` are different artifacts with one direction of
flow — see §3.6.

### 3.2 One file per recipe: YAML front matter + Markdown body

Front matter is machine-queryable with plain `rg`; the body is for a human. This
matches how the repo already writes documents and needs no new tooling to read.

```yaml
---
id: vex-noise-0007
title: Two-frequency directional displacement on a sphere
status: verified                  # verified | partial | rejected | blocked | draft
verified_on: 2026-08-10
verified_by: claude-code
houdini: "21.0.729"
machine: pc137
context: SOP
family: displacement-noise        # from taxonomy.yaml
node_types: [sphere, mountain::2.0, attribwrangle, smooth::2.0]
vex_functions: [noise, fit, normalize]
attributes_read: [P, N]
attributes_created: [dist]
groups_created: []
techniques: [two-frequency, directional-bias, relax-pass]
difficulty: 2                     # 1..5
prerequisites: [sop-geometry-0001]
supersedes: []
superseded_by: null
source:
  kind: derived                   # derived | replicated | reference-hda | reference-hip
  name: "SideFX bundled example: nodes/sop/mountain"
  url: "https://www.sidefx.com/docs/houdini21.0/nodes/sop/mountain.html"
  accessed: 2026-08-12
cost:
  nodes: 4
  mcp_write_calls: 18
  wall_clock_min: 12
verification:
  cook_clean: true
  npoints: 1122
  nprims: 1120
  bbox: [1.31, 1.24, 1.28]
  ablation_seed: pass
  ablation_amplitude_zero: pass
  ablation_frequency_double: pass
  cold_replay: 2026-08-11
visual_features:                  # pre-committed at step 0, scored at step 6
  - {feature: "large rounded masses, not spikes", score: present}
  - {feature: "fine ripple riding on the large forms", score: present}
  - {feature: "no visible sphere seam / pole pinching", score: present}
family_limitation: null           # mandatory prose when status == rejected
snapshot: ../snapshots/vex-noise-0007.jpg
---
```

### 3.3 Body template (fixed section order — makes recipes diffable and skimmable)

```markdown
## Intent
One sentence: what look or behaviour this produces.

## When to use / when NOT to use
The family boundary. What this cannot do, at any parameter setting.
This section is the reason the file exists. Do not leave it thin.

## Chain
| # | Node type | Name | Parent | Input 0 | Why this node |

## Parameters
| Node | Parm | Value | What it controls / why this value |
Only non-default parms. Copied verbatim from get_node_info(only_non_default=True).

## VEX
Fenced block. This is DATA: the string that goes into a `snippet` parm via
set_parm. Nothing reads this file and executes it. See §3.7.

## Verification record
What was measured, in prose where the numbers need nuance.

## Failure modes seen
What went wrong first, and which check caught it. Never omit this section
because "nothing went wrong" — write "first pass clean" instead, that is
itself information.

## Variations
Which two or three parameters actually change the result, and in which
direction. Everything else is noise.
```

### 3.4 Retrieval — how this stays out of the context window

The failure mode of any cookbook is that it grows past the point where an agent
will read it, and then it is dead weight that still costs maintenance. Three
countermeasures:

1. **`INDEX.md` is the only file read unconditionally.** Generated by
   `scripts/cookbook_index.py` (parses front matter, emits one table plus two
   reverse indexes: *node type → recipe ids*, *family → recipe ids*). Committed,
   so it is a normal file read, not a tool call. Target size: under 120 lines at
   30 recipes.
2. **A hard budget: INDEX.md, then at most 3 full recipe files per task.** If a
   task seems to need more, the doctrine file (§4.2) is missing a rule.
3. **Recipe files capped at ~150 lines.** Longer means it is two recipes.

The five canonical queries, documented in `cookbook/README.md` so future sessions
do not each invent their own:

```
rg -l 'family: displacement-noise'        houdini/cookbook/recipes
rg -l 'mountain::2\.0'                    houdini/cookbook/recipes
rg -l 'status: rejected'                  houdini/cookbook/recipes   # read these first
rg -l 'vex_functions:.*curlnoise'         houdini/cookbook/recipes
rg -n '^  - \{feature:'                   houdini/cookbook/recipes   # what looks are covered
```

`status: rejected` first is deliberate. Knowing which family is a dead end is
faster than reading three positives.

### 3.5 Lint — `scripts/check_cookbook.py`

Run it wherever `scripts/check_contract.py` runs. Checks, all cheap:

1. Front matter parses; all required keys present.
2. `family`, `techniques`, `status`, `difficulty` values exist in `taxonomy.yaml`.
3. `status: verified` ⇒ complete `verification` block **and** a `cold_replay` date.
4. `status: rejected` ⇒ non-null `family_limitation`.
5. `snapshot` path exists on disk.
6. `prerequisites` / `supersedes` ids resolve to real files.
7. **No Python.** Reject any fenced block tagged `python`, and any occurrence of
   `import `, `hou.`, `exec(`, `eval(` outside an explicitly quoted error
   message. See §3.7.
8. `INDEX.md` is up to date (regenerate and diff; fail if it differs).

### 3.6 Relation to `frozen_cave/NOTES.md` — what to keep, what to change

The precedent is good and should not be replaced. It should be *split by role*.

**Keep, unchanged:**

- **Its reason for existing.** The closing section — `BACKLOG.md` carries only
  verified-done one-liners, so failed directions and in-progress reasoning need
  somewhere else to live — is correct and stays true. `references/` keeps that job.
- **Reference-first framing.** "What the reference actually shows" is the single
  best thing in that file. It becomes a *required* section, pre-committed before
  building (§2.5's `visual_features`).
- **Failures recorded with reasons.** Attempts 2 and 3 with their diagnoses are
  worth more than attempt 1.
- **Prose.** Do not force look-dev narrative into YAML. Chronological narrative
  is the right shape for a project log.
- **The owner's verbatim judgment** ("виглядає ніби нічого не виходить"). A
  human's reaction is data and should not be paraphrased into blandness.

**Change:**

| Problem today | Change |
|---|---|
| Per-asset and untagged, so nothing is reusable across assets | Two artifacts, one direction of flow: `references/<subject>/NOTES.md` stays the chronological project log; anything reusable is **promoted** into `cookbook/recipes/` as a tagged entry, and the NOTES entry links to it by id. Never duplicate the content — the log points at the recipe |
| Judgments are unfalsifiable ("closest match so far, per direct comparison") | Verdict vocabulary (§2.5) plus measured T0–T4. A comparison with no criterion behind it does not go in a recipe |
| Its most valuable content — attempts 2 and 3 — is invisible to any future task that isn't about ice | Those two become `status: rejected` recipes with `family_limitation` filled in. "A heightfield is a function of (x,z), therefore it cannot produce overlapping folds" is a general rule that happened to be discovered on an ice cave |
| No structure means no query | Front matter + INDEX.md |
| No minimum header | Add a light one to NOTES files too: `subject`, `reference_image`, `status`, `related_recipes`. Four lines. Do not YAML-ify the body |

Concretely, on approval of this plan, `frozen_cave` yields three cookbook entries
almost for free: one `rejected` (flat-grid height terracing for volumetric
folds), one `rejected` (Voronoi fracture for draped organic ice — *and* a
`partial` note that it is right for a different target, a frozen lake surface),
and one `partial` (VDB-union of scattered blobs for merged organic masses —
right family, look not yet landed).

### 3.7 Hard rule: recipes are data, never runnable code

- No file under `houdini/cookbook/` is ever executed by anything.
- VEX appears as a **parameter value**, in the same sense as a float on a
  `mountain` node. The doctrine already allows `snippet` / `vexpression` as
  settable parms (`guards.CODE_PARMS_ALLOWED`); a recipe storing that string is
  storing a parameter value, not a program.
- Python never appears at all — not as an example, not in a comment, not as a
  "here's how you'd script it". Lint rule 7 enforces this mechanically so it
  cannot erode by habit.
- No recipe stores a filesystem path, a URL that is fetched at build time, or a
  ROP/output parameter. If a recipe needs an input file, it names the *kind* of
  file and the owner supplies it.

This is not ceremony. `execute_code` staying dead is only durable if nothing in
the repo ever grows into a thing that wants to be executed.

---

## 4. The alternative approach, and the recommendation

### 4.1 Diagnosis first

If the goal is "an MCP agent that produces genuinely good, complex, visually
convincing Houdini setups", then rank the actual obstacles:

| # | Obstacle | Does a cookbook fix it? |
|---|---|---|
| 1 | **The agent can barely see.** Unlit OpenGL, arbitrary camera, no lit render, no deterministic framing | **No.** And this dominates everything else: a recipe verified against a bad signal is a recipe you cannot trust |
| 2 | **Technique-family selection** against a visual target | **Partly** — this is the cookbook's real target |
| 3 | **Iteration cost.** Dozens of round-trips, each occupying the owner's GUI | **No.** Worse, a cookbook *increases* total iteration if it drives more replication work |
| 4 | Node/parm recall | Already solved by Tier 0 introspection |
| 5 | Nothing measures whether the agent is improving | **No** |

Obstacles 1 and 3 are already scoped in `HMCP_CAMERA_CONTROL_PLAN.md`
(`viewport_frame_node` → deterministic framing) and
`HMCP_HEADLESS_RENDER_PLAN.md` (Track A `render_snapshot` → a lit PNG the agent
can actually read; Track B headless worker → unattended iteration that never
touches the owner's session). Neither has shipped.

**Therefore: the highest-leverage work is not the cookbook, and it is already
written down.**

### 4.2 The alternative — "mine, don't write"

Four parts, in cost order.

**A1 — Ship the feedback loop first (already planned, zero new design).**
Camera control, then Track A `render_snapshot`, then Track B headless. Do not
start recipe production before Track A. The reason is not sequencing tidiness:
every recipe verified against an unlit grey blob in an arbitrary viewport will
have to be re-verified afterwards, so starting early *creates* rework.

**A2 — Extract recipes from `.hip`/`.hda` files instead of hand-writing them.**
The repo already contains the seed: `scripts/dump_scene.py` walks a scene and
emits every node's non-default parameters as JSON, offline, under hython. Extend
it into `scripts/hip_to_recipe.py` — read-only, hython, no MCP, no GUI — which
opens a file, walks one SOP network, and emits the §3.2 front matter plus the
chain and parameter tables directly.

The corpus is already on disk and free: **128 example `.hda`s across 233 SOP
example directories** in every Houdini install (§1.1), plus SideFX Labs examples
from GitHub and Content Library downloads. That turns a ~30–60-minute hand-built
recipe into a ~10-second extraction, and what comes out is **ground truth from
SideFX's own authors**, not the agent's replication attempt.

What extraction cannot produce, and therefore what stays hand-written: the
*intent*, the *when-NOT-to-use* boundary, the visual features, and the negative
results. That is fine — those are the parts worth a human-scale effort, and they
are precisely the parts a tutorial does not give you either.

Licensing caution: commit **derived structural descriptions** and citations.
Do not commit third-party `.hip`/`.hda` files, and do not commit verbatim
material from paid courses. Bundled SideFX examples and Labs examples are the
safe end; Patreon/Gumroad material is not. Keep any local originals under
`houdini/references/_local/` and gitignore it. Open Question Q1.

**A3 — `DOCTRINE.md`: ~40 rules, and the highest value per byte in this whole
plan.** Judgment is the gap (§0), and judgment compresses. Examples, in the form
they should be written — each one a rule with the reason attached:

- Never height-displace a plane when the target has overlapping folds; a
  heightfield is a function of (x,z) and cannot self-overlap. (frozen_cave #3)
- VDB union of scattered blobs is the family for merged organic melted masses.
  (frozen_cave #1)
- Prove the noise is live before judging the look: change the seed, confirm the
  bbox moves. (§2.3 T4)
- Check an attribute exists (`get_geometry_info`) before wrangling against it;
  a missing attribute reads as 0 and produces a clean cook with no effect.
- Scale noise frequency to the geometry's bbox, never to a number copied from a
  tutorial built at a different world scale.
- Copy-to-points beats merge whenever the pieces must read as one surface —
  merge leaves visible intersections that look like props stuck on.

40 of those, at ~2 lines each, is one screen. It costs almost nothing to
maintain, it is read every session because it is short enough to be read every
session, and it targets the actual failure mode. **If only one thing in this
document gets built, build this.**

**A4 — A small golden-task eval set (6–8 tasks), not a large library.** Each is
a target with a T0–T4 contract that can be re-run whenever tooling changes.
`HOUDINI_MCP_REWRITE_PLAN.md` deferred "recipes / eval harness … until there is
something worth recording". After the Phase 3 rock and the ice-cave attempts,
there now is. Without this, there is no way to answer "did the cookbook help?" —
and that question will be asked.

### 4.3 Cost vs payoff

| Approach | Build cost | Per-entry cost | Maintenance / decay | Payoff |
|---|---|---|---|---|
| Hand-written cookbook, large (100+) | Low to start | **30–60 min each** | High — decays on every Houdini version bump; value only if actually retrieved | Moderate, and only for looks that were anticipated |
| **A1 feedback loop** | Already designed; days of implementation | — | Low | **Highest.** Unlocks every other item. Nothing else is trustworthy without it |
| **A2 hip mining** | ~1 day for `hip_to_recipe.py` | **~minutes each, in bulk** | Low; re-run the extractor on a new version | High. Ground truth, at volume, free corpus |
| **A3 DOCTRINE.md** | Hours | ~2 lines per rule | Very low | **Highest per byte.** Targets judgment, which is the gap |
| **A4 golden tasks** | ~1 day for 6–8 | — | Low | High — the only thing that measures progress |

### 4.4 Recommendation: a combination, strictly sequenced

1. **Do not start the cookbook yet.** Ship `viewport_frame_node` and Track A
   `render_snapshot` first (sibling plans, already approved-shaped).
2. **Start `DOCTRINE.md` immediately anyway** — it does not depend on the
   feedback loop, and the frozen_cave lessons are perishable. Seed it today from
   `frozen_cave/NOTES.md` plus the Phase 3 rock session.
3. **Then build the §3 storage schema**, and seed it with **A2 mining** of the
   bundled SOP examples. Bulk and cheap.
4. **Then hand-write only what mining cannot produce**: negative results,
   owner-judged look-dev families, Vellum setups tuned by feel.
5. **Then 6–8 golden tasks (A4)**, once ~20 recipes exist.
6. **Target ~30 recipes, not 200.** Re-check after three months which recipes
   were ever actually read; delete the ones that were not. A cookbook that is
   never queried is a maintenance liability wearing a knowledge-base costume.

### 4.5 What not to build

- A database, an embedding index, or any retrieval service. `rg` over 30 files
  with front matter is faster to build, faster to run, and reviewable in git.
- A recipe "runner" that replays a recipe automatically. That is
  `execute_code` with extra steps; the agent issues the MCP calls itself, one at
  a time, reading geometry between them — which is the loop that works.
- Scraping tutorial sites. Licensing risk, no ground truth, and the bundled
  examples are better material anyway.
- Recipes for anything Tier 0 already answers (parameter lists, node
  descriptions). A recipe that duplicates `get_node_help` is drift waiting to
  happen.

---

## 5. Open questions for the owner

**Q1 — Paid-course material.** May structural descriptions derived from paid
sources (Entagma Patreon, Gumroad courses) be committed to this repo with a
citation, or should the repo carry derived recipes only with originals kept
local and gitignored? My default without an answer: **derived only, originals
local, always cited.** Related: do you currently have active Entagma Patreon /
Gumroad access worth mining?

**Q2 — `frozen_cave` migration.** Retro-tag the existing NOTES and promote its
three attempts into cookbook entries, or leave it untouched and apply the new
template only to new subjects? My default: **promote the three attempts** (they
are the best negative results available) and leave the narrative file otherwise
as it stands.

**Q3 — Which machine verifies recipes?** pc137 (21.0.729, the real target, but
it competes with your session) or local (20.5.278, free to hammer, but a
different build). Recipes record a `houdini:` version; splitting the corpus
across two versions halves its value. My default: **pc137 for `verified`, local
for `draft`.** This interacts with Q4 of the headless-render plan.

**Q4 — Snapshot images in git.** Are JPEGs in `houdini/cookbook/snapshots/`
acceptable (repo size), and who moves them off pc137? There is no pull path
today — the render plan's Phase 2 flags the same gap. If the answer is no, T5
evidence becomes a text description only, which is a real loss.

**Q5 — A `set_frame(frame)` write command for Vellum.** Without it, Vellum
recipes are capped at `status: partial` — construction verifiable, behaviour not
(§2.4). It is small and carries no path/code/filesystem risk, but it is new
capability, so it is your call. Alternative: defer all Vellum until the headless
worker exists. My default if you don't answer: **defer Vellum**, and note the
cap in every Vellum recipe.

**Q6 — Audience.** Is the cookbook for the agent only, or do you expect to read
it? It changes the prose/data balance materially — an agent-only corpus can be
much terser. My default: **both**, hence Markdown bodies rather than pure YAML.

**Q7 — Ordering.** §4.4 says ship camera + `render_snapshot` before producing
recipes. That defers visible cookbook progress by however long those take. If
you would rather have recipes sooner and accept re-verification later, say so —
it is a legitimate trade, just not the one I would make.

---

## Critical files

Read before implementing:

- `houdini/docs/HOUDINI_MCP_REWRITE_PLAN.md` — doctrine, safety model, §4 in particular
- `houdini/docs/HMCP_CAMERA_CONTROL_PLAN.md` — deterministic framing, a T5 prerequisite
- `houdini/docs/HMCP_HEADLESS_RENDER_PLAN.md` — lit renders and unattended iteration
- `houdini/commands_spec.py` — the 24 commands that exist; note the absence of frame control
- `houdini/references/frozen_cave/NOTES.md` — the precedent §3.6 builds on
- `scripts/dump_scene.py` — the seed of `hip_to_recipe.py` (§4.2 A2)

New files this plan would create (none of them yet exist):

- `houdini/cookbook/README.md`, `DOCTRINE.md`, `INDEX.md`, `taxonomy.yaml`
- `houdini/cookbook/recipes/**`, `houdini/cookbook/snapshots/**`
- `scripts/cookbook_index.py`, `scripts/check_cookbook.py`, `scripts/hip_to_recipe.py`
