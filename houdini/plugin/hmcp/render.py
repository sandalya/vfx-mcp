"""
render.py -- Stage 3: non-blocking render_snapshot
(houdini/docs/HMCP_FEEDBACK_LOOP_PLAN.md).

Two commands, not one, because the render runs out-of-process (plan D3):
render_snapshot() spawns a background Karma render and returns
immediately; render_status() polls the single pending slot. Every
safety-relevant constant/check this file calls into
(guards.RENDER_DIR, guards.RENDERERS, guards.ALLOWED_RENDERERS,
guards.RENDER_QUALITY, guards.set_render_output, guards.render_dir_exists)
lives in guards.py per that file's own rule -- this module only ever
calls them, never invents a new safety check inline.

Kept hou.ui-free outside the camera="viewport" branch (plan §3e), so this
file can move into the deferred headless worker (plan §7, Track B)
unchanged.

No `import os` / `shutil` / `requests` / `subprocess` / `zipfile`
anywhere in this package -- see guards.py's module docstring for why.
"""

import math
from datetime import datetime

from . import build
from . import guards

# Single-slot pending-render state (plan §3c: "one slot, not a job
# registry" -- a second render_snapshot while one is pending is refused).
# Reset on plugin reload / Houdini restart, same as guards.session_registry.
_pending = None


def _check_renderer_available(descriptor):
    import hou

    cat = hou.nodeTypeCategories().get("Driver")
    if cat is None or descriptor["rop_type"] not in cat.nodeTypes():
        raise ValueError(
            f"Refused: ROP type {descriptor['rop_type']!r} isn't available "
            f"on this Houdini build."
        )


def _get_or_create_rop(renderer):
    """The plugin's own render ROP at /out/hmcp_render_<renderer> --
    created once, reused after. Never a caller-supplied ROP path (plan
    §3b step 6): rendering someone else's ROP executes whatever is in its
    prerender/postrender/precmd parms, the exact class
    guards.CODE_PARMS_REFUSED exists to refuse. On a reused node, every
    CODE_PARMS_REFUSED-named parm that exists on it must be empty, or
    this refuses outright rather than rendering it."""
    import hou

    descriptor = guards.RENDERERS[renderer]
    name = f"hmcp_render_{renderer}"
    rop_path = f"/out/{name}"
    out = hou.node("/out")
    rop = out.node(name)

    if rop is None:
        rop = out.createNode(descriptor["rop_type"], node_name=name)
        guards.session_registry.register_created(rop)
    else:
        if rop.type().name() != descriptor["rop_type"]:
            raise ValueError(
                f"Refused: {rop_path} exists but is not a "
                f"{descriptor['rop_type']!r} ROP -- the plugin will not "
                f"repurpose a foreign node."
            )
        for parm_name in guards.CODE_PARMS_REFUSED:
            parm = rop.parm(parm_name)
            if parm is not None and parm.rawValue():
                raise ValueError(
                    f"Refused: {rop_path}'s {parm_name!r} parm is "
                    f"non-empty -- rendering it would execute that "
                    f"script. This node wasn't left clean by this "
                    f"plugin; refusing to reuse it."
                )

    return rop, rop_path


# ---------------------------------------------------------------------------
# Camera modes -- plan §3d
# ---------------------------------------------------------------------------


def _get_or_create_render_camera():
    """The plugin's own render camera, at /obj/hmcp_cam -- created once,
    reused after (D2: this is the same shape as viewport_snapshot owning
    its own output path). Both camera='viewport' and camera='fit'
    populate this same node; whichever mode ran most recently wins."""
    import hou

    cam = hou.node("/obj/hmcp_cam")
    if cam is None:
        cam = hou.node("/obj").createNode("cam", node_name="hmcp_cam")
        guards.session_registry.register_created(cam)
    elif cam.type().name() != "cam":
        raise ValueError(
            "Refused: /obj/hmcp_cam exists but is not a camera node -- "
            "the plugin will not repurpose a foreign node."
        )
    return cam


def _build_viewport_camera():
    """camera='viewport': copy the SceneViewer's current camera onto
    /obj/hmcp_cam via the 1-argument saveViewToCamera() -- the signature
    Stage 0d confirmed live (the 2-arg form doesn't exist on this build,
    contradicting HMCP_CAMERA_CONTROL_PLAN.md's note that it's
    deprecated -- see D2). GUI-only; render_snapshot itself checks
    hou.ui before calling this (plan §3e)."""
    import hou

    sv, viewport = build._require_scene_viewport()
    guards.check_viewport_camera_free(viewport)
    cam = _get_or_create_render_camera()

    with hou.undos.group("MCP: render_snapshot viewport camera"):
        viewport.saveViewToCamera(cam)

    return cam


_NON_GEOMETRY_OBJECT_TYPES = {"cam", "light"}


def _find_displayed_geometry():
    """Every /obj-level Object node with its display flag set -- what
    camera='fit' frames. Simpler than the old plugin's subnet-walking
    version (HoudiniMCPRender.py:148): guards.ALLOWED_NODE_CATEGORIES
    also includes Vop now, but Vop nodes only ever live nested inside a
    Sop container's internal network, never as a top-level /obj child, so
    a plain top-level scan still covers everything it could itself have
    created or that a normal scene displays.

    Excludes camera/light object types: live-tested 2026-08-12, Houdini
    leaves the display flag set on a freshly-created camera object (this
    plugin never sets it), so an un-filtered scan makes camera='fit'
    frame its own /obj/hmcp_cam -- a tiny point-like bbox at the camera's
    own position that skews the union bbox toward wherever the camera
    last happened to be. Excluding by type, not by the plugin's own
    camera path, also guards against a stray user camera/light with its
    display flag left on."""
    import hou

    obj = hou.node("/obj")
    return [
        n for n in obj.children()
        if n.type().category().name() == "Object"
        and n.isDisplayFlagSet()
        and n.type().name() not in _NON_GEOMETRY_OBJECT_TYPES
    ]


def _collective_world_bbox(nodes):
    """Union of build._node_world_bbox over every node -- reuses that
    function's already Stage-0b-verified per-node bbox+transform math
    (bbox * matrix4; hou.BoundingBox has no .transform() method) instead
    of re-deriving it, the way the old plugin's calculate_bounding_box
    did with numpy (HoudiniMCPRender.py:181)."""
    import hou

    result = None
    for node in nodes:
        try:
            bbox = build._node_world_bbox(node)
        except ValueError:
            continue
        if result is None:
            result = hou.BoundingBox(
                bbox.minvec()[0], bbox.minvec()[1], bbox.minvec()[2],
                bbox.maxvec()[0], bbox.maxvec()[1], bbox.maxvec()[2],
            )
        else:
            result.enlargeToContain(bbox)
    return result


def _build_fit_camera(width, height):
    """camera='fit': point /obj/hmcp_cam at the scene's displayed
    geometry from a fixed default angle, at a distance computed from the
    bounding SPHERE of the collective world bbox (not its axis-aligned
    extents) -- radius = half the box diagonal, distance = radius /
    sin(min_fov/2). That guarantees full containment for ANY fixed
    viewing angle, which is a simpler and strictly more general
    replacement for the old plugin's per-axis-rotation special case
    (HoudiniMCPRender.py:341-421: 'has_significant_rotation' branching).
    Works headless -- never touches hou.ui.

    Rotation/eye math confirmed correct by an independent live-number
    reconstruction (2026-08-12): Houdini is row-vector (v' = v*M),
    hou.hmath.buildRotate's default order 'xyz' matches an Object node's
    default rOrd 'xyz', so buildRotate(rx, ry, 0) reproduces exactly the
    rotation Houdini applies for r=(rx, ry, 0). The actual bug found live
    was the FOV: 'aspect' is Houdini's PIXEL aspect ratio, not the image
    aspect ratio, and a freshly-created cam node defaults to 1280x720 --
    left un-pinned, its real vertical FOV (driven by resy/resx) doesn't
    match the 512x512/960x540 the ROP actually renders, placing the
    camera far too close and cropping the frame. Pinning the camera's own
    res/win/winsize to the render resolution before computing vertical_fov
    from resy*aperture/(resx*aspect) fixes this -- see
    https://www.sidefx.com/docs/houdini/ref/cameralenses.html."""
    import hou

    nodes = _find_displayed_geometry()
    if not nodes:
        raise ValueError(
            "Refused: camera='fit' found no /obj node with its display "
            "flag set -- nothing to frame."
        )
    world_bbox = _collective_world_bbox(nodes)
    if world_bbox is None or not world_bbox.isValid():
        raise ValueError(
            "Refused: camera='fit' found displayed nodes but none had "
            "evaluable geometry to frame."
        )

    center = world_bbox.center()
    radius = max(world_bbox.sizevec().length() / 2.0, 1e-4)

    cam = _get_or_create_render_camera()
    rx, ry = -20.0, 35.0  # fixed default 3/4 angle -- see docstring above

    with hou.undos.group("MCP: render_snapshot fit camera"):
        # win/winsize reset because camera='viewport' shares this same
        # node and saveViewToCamera() can leave its own screen window on
        # it (plan D2/3d) -- 'fit' must not inherit that.
        cam.parmTuple("res").set([width, height])
        cam.parmTuple("win").set([0.0, 0.0])
        cam.parmTuple("winsize").set([1.0, 1.0])

        aperture = cam.parm("aperture").eval()
        aspect = cam.parm("aspect").eval()  # pixel aspect, not image aspect
        focal = cam.parm("focal").eval()
        horizontal_fov = 2 * math.atan((aperture / 2.0) / focal)
        vertical_aperture = (height * aperture) / (width * aspect)
        vertical_fov = 2 * math.atan((vertical_aperture / 2.0) / focal)
        min_fov = min(horizontal_fov, vertical_fov)

        padding_factor = 1.1
        distance = max(5.0, (radius * padding_factor) / math.sin(min_fov / 2.0))

        rot = hou.hmath.buildRotate(rx, ry, 0).extractRotationMatrix3()
        forward_world = hou.Vector3(0, 0, -1) * rot
        eye = hou.Vector3(center) - forward_world * distance

        cam.parm("projection").set(0)  # perspective
        cam.parmTuple("r").set([rx, ry, 0])
        cam.parmTuple("t").set(list(eye))

    framed = {
        "nodes": [n.path() for n in nodes],
        "bbox_min": list(world_bbox.minvec()),
        "bbox_max": list(world_bbox.maxvec()),
    }
    return cam, framed


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def render_snapshot(renderer="karma", quality="draft", camera="viewport"):
    """Render a still frame in the background and return immediately --
    the render itself finishes out-of-process; call render_status() to
    poll it. Two commands, not one, because a non-blocking render is
    fundamentally out-of-process (plan D3): a screenshot must not freeze
    Houdini's UI. Requires a sandbox scene and a pre-existing
    guards.RENDER_DIR (the owner's own physical kill switch -- the
    plugin never creates it).

    renderer: only 'karma' (guards.ALLOWED_RENDERERS) -- mantra's render
    silently produces no output on this build (Stage 0d's still-open
    mystery), arnold isn't written (D4).
    quality: 'draft' (512x512) or 'preview' (960x540) -- guards.RENDER_QUALITY.
    camera: 'viewport' (default, GUI only) copies the SceneViewer's
    current camera onto the plugin's own /obj/hmcp_cam, so this renders
    exactly what viewport_snapshot sees and Stage 2's camera commands
    steer it for free. 'fit' works headless: frames every displayed
    /obj node from a fixed angle, guaranteed fully contained.

    If the render comes back black, the scene most likely has no lights
    -- Karma does not auto-headlight (unlike Mantra). set_parm the
    reused ROP's 'force_headlight' toggle rather than asking for a new
    command; it isn't wired in here automatically so a real lighting
    setup is never silently overridden.
    """
    guards.require_sandbox_scene()
    import hou

    if renderer not in guards.ALLOWED_RENDERERS:
        raise ValueError(
            f"Refused: unknown renderer {renderer!r}. Allowed: "
            f"{sorted(guards.ALLOWED_RENDERERS)}."
        )
    if quality not in guards.RENDER_QUALITY:
        raise ValueError(
            f"Refused: unknown quality {quality!r}. Allowed: "
            f"{sorted(guards.RENDER_QUALITY)}."
        )
    if camera not in ("viewport", "fit"):
        raise ValueError(
            f"Refused: unknown camera mode {camera!r}. Allowed: "
            f"['fit', 'viewport']."
        )

    global _pending
    if _pending is not None:
        raise ValueError(
            f"Refused: a render is already pending ({_pending['rop_path']}, "
            f"started {_pending['started_at'].isoformat()}). Call "
            f"render_status() and wait for it to finish before starting "
            f"another."
        )

    descriptor = guards.RENDERERS[renderer]
    _check_renderer_available(descriptor)

    if not guards.render_dir_exists():
        raise ValueError(
            f"Refused: {guards.RENDER_DIR} does not exist. The plugin "
            f"never creates directories -- create it by hand to arm "
            f"render_snapshot."
        )

    quality_settings = guards.RENDER_QUALITY[quality]
    framed = None

    if camera == "viewport":
        if not hasattr(hou, "ui"):
            raise ValueError(
                "Refused: camera='viewport' requires a graphical Houdini "
                "session. Use camera='fit' in headless mode."
            )
        cam_node = _build_viewport_camera()
    else:
        cam_node, framed = _build_fit_camera(
            quality_settings["width"], quality_settings["height"]
        )

    rop, rop_path = _get_or_create_rop(renderer)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"{guards.RENDER_DIR}mcp_{ts}_{renderer}.png"

    with hou.undos.group("MCP: render_snapshot"):
        rop.parm(descriptor["camera_parm"]).set(cam_node.path())
        rop.parmTuple(descriptor["resolution_parm"]).set(
            (quality_settings["width"], quality_settings["height"])
        )
        samples_parm = rop.parm(descriptor["samples_parm"])
        if samples_parm is not None:
            samples_parm.set(quality_settings["samples"])
        # This is the actual multi-frame guard: forcing trange to "off"
        # unconditionally, right before every executebackground press,
        # inside this same undo group. Karma's "f" tuple (f1/f2/f3) is
        # NOT a usable second guard here -- live-tested 2026-08-12: this
        # HDA keeps f1/f2 synced to $FSTART/$FEND and silently reverts
        # any direct .set() on them regardless of trange's state, so a
        # would-be belt-and-braces frame pin is a structural no-op on
        # this ROP type. trange="off" alone is sufficient and verified:
        # tampering trange to "normal" externally with f1/f2 still at
        # $FSTART/$FEND (1/240), then calling render_snapshot, produced
        # a normal ~14s single-frame render -- this reset fired and
        # trange read back "off" immediately after.
        rop.parm(descriptor["trange_parm"]).set(descriptor["trange_off_value"])
        guards.set_render_output(rop, descriptor["picture_parm"], filepath)

    # D3 addendum (Stage 0e): executebackground pops a blocking, abort-on-
    # OK modal on unsaved changes, and the ROP setup just above always
    # dirties the scene. Auto-save immediately before pressing it -- no
    # separate confirmation step, per that decision.
    hou.hipFile.save()

    rop.parm("executebackground").pressButton()

    _pending = {"path": filepath, "started_at": datetime.now(), "rop_path": rop_path}

    result = {
        "path": filepath,
        "renderer": renderer,
        "resolution": [quality_settings["width"], quality_settings["height"]],
        "camera_path": cam_node.path(),
        "rop_path": rop_path,
        "started": True,
    }
    if framed is not None:
        result["framed"] = framed
    return result


def render_status():
    """Poll the single pending render slot. No arguments. Never raises,
    even with nothing pending. Probes the output file with
    open(path, "rb") (guards.py module docstring rule 3) -- the only way
    to know a background render finished, since the process is
    out-of-process and rop.render()'s own return value is never seen
    (D3's stated cost). Also reads rop.errors()/warnings(), though Stage
    0e found a modal-aborted render leaves both empty -- a real
    diagnostic gap, not fixed here. Clears the pending slot once the
    render is done, so the next render_snapshot call is no longer
    refused."""
    global _pending

    if _pending is None:
        return {"pending": False, "done": None, "path": None}

    path = _pending["path"]
    try:
        open(path, "rb")
        done = True
    except FileNotFoundError:
        done = False
    except OSError:
        done = True

    import hou

    rop = hou.node(_pending["rop_path"])
    errors = list(rop.errors()) if rop is not None else []
    warnings = list(rop.warnings()) if rop is not None else []
    elapsed = (datetime.now() - _pending["started_at"]).total_seconds()

    result = {
        "pending": True,
        "done": done,
        "path": path,
        "seconds_elapsed": elapsed,
        "errors": errors,
        "warnings": warnings,
    }
    if done:
        _pending = None
    return result
