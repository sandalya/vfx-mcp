# frozen_cave — look-dev notes

Reference: `halo_ice_cave_01.png` (screenshot from the game *Halo*, ice-cave
interior). Not a lighting "halo" effect — the name is the game title.

## What the reference actually shows

- Not granular/cracked plates. Smooth, rounded ice **shelves/folds** that
  overlap each other like draped fabric or pooled wax — each lobe has a
  rounded front, and the boundary where one lobe overlaps the next reads as
  a soft seam, not a sharp crack.
- Gravity-directed structure — the big shapes read as having flowed/dripped
  and frozen, not isotropic noise.
- **Icicles** hanging from the upper cave surface: thin, tapered, organic
  (not straight geometric cones), translucent, catching highlights at the
  tip.
- Deep saturated teal/emerald in thick ice, lightening toward near-white on
  thin edges and icicle tips — thickness-driven translucency (SSS-like).
- Even the big smooth lobes have fine ripple/micro-detail, not perfectly
  smooth.

## Attempts log (geometry only, no shading yet)

1. **`/obj/ice_cave`** — original scene, tunnel-shaped, VDB technique:
   scatter spheres → `copytopoints` → `vdbfrompolygons` → `vdbsmooth` →
   `convertvdb`. Closest match so far, per direct comparison — VDB-union is
   the right *family* of technique for this organic melted-ice look. But:
   uniform blob size (no large+small mix), no icicles, fully opaque flat
   teal (no thickness-driven color/translucency), surface too smooth even
   under highlights.
2. **`/obj/ice_pattern_test`** — flat grid, Voronoi-fracture crack pattern
   (sharp plates + gaps). Built *before* the real Halo reference was shared;
   based on a misread of "sharp edges" from our own first render, not the
   actual reference. Wrong family entirely for this reference — a cracked
   ice-sheet look, not a draped-cave-wall look. Kept as a separate,
   possibly-useful pattern for a different context (e.g. a frozen lake
   surface), not for this cave.
3. **`/obj/frozen_cave_layers_test`** — flat grid, height-terracing
   (banded/terraced noise) + `tube` primitives copied to scattered points
   for icicles. Wrong on two levels: (a) height-displacement on a flat plane
   fundamentally can't produce the volumetric overlapping-fold look — it
   only ever gives a flat plateau or a rolling hill, never a draped mass;
   (b) `tube`-primitive icicles, straight-tapered and merged (not unioned)
   onto the surface, read as literal traffic cones stuck into a floor, not
   ice growing out of a wall. User feedback: "виглядає ніби нічого не
   виходить" — confirmed off-target.

## Current direction (agreed 2026-08-12, not yet built)

Pivot back to the VDB-union family (attempt 1's technique), retuned:

- Scatter blobs in **directional/clustered** groups (biased vertically, not
  isotropic) so the VDB union naturally overlaps into shelf/fold shapes,
  instead of a uniform field of merged spheres.
- Build icicles from a **slightly bent/noisy curve + polywire with a
  tapering radius ramp**, not a straight `tube` primitive — then
  **`vdbcombine` (union)** them into the same VDB as the main shelf mass, so
  they blend smoothly into the surface instead of sitting on top as a
  separate merged prop.
- Still pure geometry pass — shading (SSS/translucency, color gradient,
  frost micro-noise) stays deferred, per the standing task list from the
  first critique.

## Why this file exists

`BACKLOG.md` (repo root) only logs verified-working, done items per
`CLAUDE.md`'s work-log habit — it deliberately does not carry failed
directions or in-progress design reasoning. This file is where that context
lives instead, so a future session doesn't repeat attempts 2/3 blind.
