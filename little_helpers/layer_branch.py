"""
little_helpers.layer_branch

Function 1 logic: builds the layer-branch node chain (4 Reads + assembly)
from a render-root layer folder. See docs/NUKE_COMP_LAYER_ASSEMBLY.md.
"""

import os
import re

import nuke

_LAYER_BRANCH_PASSES = ("lights", "beauty", "tech", "crypto")


_VERSION_DIR_RE = re.compile(r"^v(\d+)$", re.IGNORECASE)
_FRAME_FILE_RE_TMPL = r"^{pass_name}_product\.(\d+)\.([A-Za-z0-9]+)$"


def _collapse_sequence(dirpath, pass_name):
    """Scan dirpath for '<pass_name>_product.<frame>.<ext>' files and
    collapse them into one printf-style pattern + frame range. Returns
    None if no matching files exist in dirpath, otherwise a dict with
    pattern/first/last/missing (missing = sorted list of frame numbers
    absent inside [first, last])."""
    pattern = re.compile(_FRAME_FILE_RE_TMPL.format(pass_name=re.escape(pass_name)))
    frames = []
    ext = None
    pad = None
    for name in os.listdir(dirpath):
        m = pattern.match(name)
        if not m:
            continue
        frame_str, ext = m.group(1), m.group(2)
        frames.append(int(frame_str))
        pad = len(frame_str)
    if not frames:
        return None
    frames.sort()
    first, last = frames[0], frames[-1]
    missing = sorted(set(range(first, last + 1)) - set(frames))
    return {
        # "####"-style padding, not "%04d" -- confirmed working on pc137
        # (Sashok fixed a broken Read by hand this way); %04d combined
        # with the UNC path apparently doesn't resolve the same way.
        "pattern": f"{pass_name}_product.{'#' * pad}.{ext}",
        "first": first,
        "last": last,
        "missing": missing,
    }


def _available_versions(layer_dir, pass_name):
    """List every version folder directly under layer_dir that actually
    contains files for pass_name, as a list of (version_int, version_str)
    sorted ascending. Versions are resolved per-pass, independently --
    per docs/NUKE_COMP_LAYER_ASSEMBLY.md, the 4 passes of a layer-branch
    are not guaranteed to move in lock-step (e.g. beauty/lights at v007
    while tech/crypto sit at v006 in one recorded shot)."""
    candidates = []
    for name in os.listdir(layer_dir):
        full = os.path.join(layer_dir, name)
        if not os.path.isdir(full):
            continue
        m = _VERSION_DIR_RE.match(name)
        if m:
            candidates.append((int(m.group(1)), name))
    candidates.sort()

    found = []
    for num, vname in candidates:
        # Plain "/" join, not os.path.join -- this path's root is a UNC
        # network path (//loky.plarium.local/...) already on forward
        # slashes; os.path.join on Windows mixes in backslashes, which
        # broke Nuke's Read for lights/tech/crypto (confirmed 2026-08-07:
        # beauty worked once Sashok hand-fixed it to all-forward-slash).
        if _collapse_sequence(f"{layer_dir}/{vname}", pass_name):
            found.append((num, vname))
    return found


def _resolve_pass(layer_dir, pass_name):
    """Highest-numbered version (see _available_versions) for pass_name,
    collapsed into a sequence. Raises ValueError if no version folder
    under layer_dir has any files for pass_name at all."""
    versions = _available_versions(layer_dir, pass_name)
    if not versions:
        raise ValueError(f"no '{pass_name}_product' sequence found under {layer_dir} (any version)")
    _, vname = versions[-1]
    return vname, _collapse_sequence(f"{layer_dir}/{vname}", pass_name)


def _apply_read_sequence(read, pass_name, version, seq, layer_dir):
    """Set a Read node's file/frame-range knobs from a resolved (version,
    seq) pair, and flag missing frames (orange tile_color + label) instead
    of silently building a wrong range. Shared by build_layer_branch (new
    Read nodes) and versions._bump_read_version (existing ones).

    postage_stamp defaults off here -- with a full layer-branch (4 live
    Reads) plus up to 6 history Reads per branch, leaving every one of
    them generating a live thumbnail every frame change is a real
    playback-performance hit. The two call sites that build/bump the
    *live* beauty Read (the one artists actually look at) turn it back on
    afterward -- everything else (lights/tech/crypto, and every history
    Read regardless of pass) stays off."""
    read["file"].setValue(f"{layer_dir}/{version}/{seq['pattern']}")
    read["first"].setValue(seq["first"])
    read["last"].setValue(seq["last"])
    read["origfirst"].setValue(seq["first"])
    read["origlast"].setValue(seq["last"])
    read["postage_stamp"].setValue(False)

    if seq["missing"]:
        missing_preview = ", ".join(str(f) for f in seq["missing"][:8])
        if len(seq["missing"]) > 8:
            missing_preview += ", ..."
        read["label"].setValue(f"{version}  MISSING FRAMES: {missing_preview}")
        read["tile_color"].setValue(0xD08000FF)  # orange -- catches the eye
        print(
            f"_apply_read_sequence: {pass_name} ({version}) missing "
            f"{len(seq['missing'])} frame(s): {missing_preview}"
        )
    else:
        read["label"].setValue(version)
        read["tile_color"].setValue(0)  # clear any stale missing-frames flag


def build_layer_branch(layer_name):
    """Function 1 init, per docs/NUKE_COMP_LAYER_ASSEMBLY.md: 4 Read nodes
    (lights/beauty/tech/crypto) + the ShuffleCopy/Copy assembly chain + an
    empty Cryptomatte pick point + a StickyNote label, centered on the
    current Node Graph view (nuke.createNode's default placement when
    nothing is selected).

    Each pass's version + frame range is resolved independently by
    scanning disk (see _resolve_pass/_collapse_sequence above) -- highest
    version folder that actually has files for that pass wins. Read nodes
    whose sequence has gaps get flagged (label + orange tile_color) rather
    than silently built with a wrong frame range."""
    root = os.environ.get("FTRACK_RENDER_PATH")
    if not root:
        raise ValueError("$FTRACK_RENDER_PATH is not set")

    layer_dir = f"{root}/{layer_name}"

    for n in nuke.allNodes():
        n.setSelected(False)

    def make(node_class, **knobs):
        node = nuke.createNode(node_class, inpanel=False)
        for k, v in knobs.items():
            node[k].setValue(v)
        return node

    reads = {}
    for pass_name in _LAYER_BRANCH_PASSES:
        version, seq = _resolve_pass(layer_dir, pass_name)
        read = make("Read")
        _apply_read_sequence(read, pass_name, version, seq, layer_dir)
        if pass_name == "beauty":
            read["postage_stamp"].setValue(True)  # the one Read artists
            # actually look at -- everything else in the branch stays off
        reads[pass_name] = read

    # Relative (dx, dy) offsets lifted directly from the captured sh320/bg
    # v014 reference (docs/NUKE_COMP_LAYER_ASSEMBLY.md), anchored on the
    # lights Read at (0, 0) -- Nuke's DAG convention here is top-to-bottom
    # flow (sources at low y, result at high y), NOT left-to-right, so this
    # must stay vertical to actually resemble the template.
    anchor_x, anchor_y = reads["lights"].xpos(), reads["lights"].ypos()
    reads["beauty"].setXYpos(anchor_x - 129, anchor_y + 129)
    reads["tech"].setXYpos(anchor_x - 129, anchor_y + 307)
    reads["crypto"].setXYpos(anchor_x - 281, anchor_y + 467)

    shuffle_rgba = make("ShuffleCopy", red="red", green="green", blue="blue",
                         label="RGBA IN")
    shuffle_rgba.setInput(0, reads["lights"])
    shuffle_rgba.setInput(1, reads["beauty"])
    shuffle_rgba.setXYpos(anchor_x, anchor_y + 166)

    shuffle_dir = make("ShuffleCopy", **{
        "in": "direct_emission", "alpha": "alpha2", "black": "red",
        "white": "green", "red2": "blue", "out2": "direct_emission",
    }, label="DIR EMISSION")
    shuffle_dir.setInput(0, shuffle_rgba)
    shuffle_dir.setInput(1, reads["beauty"])
    shuffle_dir.setXYpos(anchor_x, anchor_y + 202)

    shuffle_indir = make("ShuffleCopy", **{
        "in": "indirect_emission", "alpha": "alpha2", "black": "red",
        "white": "green", "red2": "blue", "out2": "indirect_emission",
    }, label="INDIR EMISSION")
    shuffle_indir.setInput(0, shuffle_dir)
    shuffle_indir.setInput(1, reads["beauty"])
    shuffle_indir.setXYpos(anchor_x, anchor_y + 238)

    copy_tech = make("Copy", **{
        "from0": "Zc.X", "to0": "depth.Z",
        "from1": "Zg.X", "to1": "Zg.X",
        "from2": "mv.X", "to2": "mv.X",
        "from3": "mv.Y", "to3": "mv.Y",
        "mix": 0.48,
    })
    copy_tech.setInput(0, shuffle_indir)
    copy_tech.setInput(1, reads["tech"])
    copy_tech.setXYpos(anchor_x, anchor_y + 319)

    shuffle_pos = make("ShuffleCopy", **{
        "in": "Pg", "alpha": "alpha2", "black": "red", "white": "green",
        "red2": "blue", "out2": "Pg",
    }, label="POS IN")
    shuffle_pos.setInput(0, copy_tech)
    shuffle_pos.setInput(1, reads["tech"])
    shuffle_pos.setXYpos(anchor_x, anchor_y + 391)

    dot = make("Dot")
    dot.setInput(0, reads["crypto"])
    dot.setXYpos(anchor_x - 247, anchor_y + 603)

    # Left empty on purpose (no matteList/pickerAdd) -- a ready pick point
    # for the artist, mirroring the doc's captured init template.
    cryptomatte = make("Cryptomatte")
    cryptomatte.setInput(0, dot)
    cryptomatte.setXYpos(anchor_x - 149, anchor_y + 600)

    copy_matte = make("Copy", **{"from0": "rgba.alpha", "to0": "mask.a"})
    copy_matte.setInput(0, shuffle_pos)
    copy_matte.setInput(1, cryptomatte)
    copy_matte.setXYpos(anchor_x, anchor_y + 594)

    sticky = make(
        "StickyNote",
        label=layer_name.upper(),
        tile_color=0x353535FF,
        gl_color=0x797979FF,
        note_font_size=222,
    )
    sticky.setXYpos(anchor_x + 286, anchor_y + 210)

    return copy_matte
