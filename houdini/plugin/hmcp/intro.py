"""
intro.py — read-only commands, available always, in any scene.

Reading cannot damage anything, so nothing here calls into guards.py.
Every function is defensive (never raises for a missing/bad path if it
can return a clean error dict instead) so the agent gets a usable error
back instead of a raw traceback -- see get_node_errors's docstring for
why that specifically mattered.

No `import os` / `shutil` / `requests` / `subprocess` / `zipfile` anywhere
in this package -- see guards.py's module docstring for why.
"""

from . import commands_spec


def _basename(path):
    """os.path.basename without importing os."""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _safe(getter, default=None):
    try:
        return getter()
    except Exception:
        return default


def _safe_attr(obj, name, *args, default=None):
    """Call obj.<name>(*args) if that method exists and doesn't raise;
    otherwise return default. Covers both failure modes seen live during
    Phase 1 verification: a method that doesn't exist at all on this
    particular node/parm-template subtype (e.g. OpNode has no .geometry(),
    ButtonParmTemplate has no .defaultValue()) -- which _safe(obj.name)
    can't catch because the AttributeError fires while evaluating the
    argument, before _safe's own try/except ever runs -- and a method
    that exists but raises when called."""
    method = getattr(obj, name, None)
    if method is None:
        return default
    try:
        return method(*args)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Scene / node info
# ---------------------------------------------------------------------------


def get_scene_info(max_nodes=100, context_filter=None):
    """Current .hip file info and a sample of top-level nodes."""
    import hou

    hip_file = hou.hipFile.name()
    scene_info = {
        "name": _basename(hip_file) if hip_file else "Untitled",
        "filepath": hip_file or "",
        "node_count": len(hou.node("/").allSubChildren()),
        "nodes": [],
        "fps": hou.fps(),
        "start_frame": hou.playbar.frameRange()[0],
        "end_frame": hou.playbar.frameRange()[1],
        "max_nodes": max_nodes,
        "truncated": False,
    }

    root = hou.node("/")
    all_contexts = ["obj", "shop", "out", "ch", "vex", "stage"]
    contexts = context_filter if context_filter else all_contexts
    top_nodes = []

    for ctx_name in contexts:
        ctx_node = root.node(ctx_name)
        if not ctx_node:
            continue
        for node in ctx_node.children():
            if len(top_nodes) >= max_nodes:
                scene_info["truncated"] = True
                break
            top_nodes.append({
                "name": node.name(),
                "path": node.path(),
                "type": node.type().name(),
                "category": ctx_name,
            })
        if len(top_nodes) >= max_nodes:
            break

    scene_info["nodes"] = top_nodes
    return scene_info


def _serialize_parm(parm):
    try:
        pt = parm.parmTemplate()
        ptype = pt.type().name() if (pt and pt.type()) else "unknown"
        label = pt.label() if pt else parm.name()
        return {
            "name": parm.name(),
            "label": label,
            "value": str(parm.eval()),
            "raw_value": parm.rawValue(),
            "type": ptype,
        }
    except Exception as e:
        try:
            n = parm.name()
        except Exception:
            n = "<unknown>"
        return {"name": n, "error": f"{type(e).__name__}: {e}"}


def _parm_is_default(parm):
    try:
        pt = parm.parmTemplate()
        defaults = pt.defaultValue()
        current = parm.eval()
        if isinstance(defaults, tuple):
            idx = parm.componentIndex()
            if idx is not None and 0 <= idx < len(defaults):
                return current == defaults[idx]
            return current == defaults
        return current == defaults
    except Exception:
        return False  # if we can't tell, treat as non-default (include it)


def _serialize_node_ref(node):
    if node is None:
        return None
    try:
        t = node.type()
        return {"name": node.name(), "path": node.path(), "type": t.name() if t else "unknown"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def get_node_info(path, max_parms=None, only_non_default=False):
    """Detailed single-node info: parms, inputs, outputs, flags."""
    import hou

    node = hou.node(path)
    if not node:
        raise ValueError(f"Node not found: {path}")

    all_parms = node.parms()

    node_info = {
        "name": _safe_attr(node, "name", default="<unknown>"),
        "path": _safe_attr(node, "path", default=path),
        "type": _safe(lambda: node.type().name(), "unknown"),
        "category": _safe(lambda: node.type().category().name(), "unknown"),
        "position": _safe(lambda: [node.position()[0], node.position()[1]], None),
        "color": _safe(lambda: list(node.color().rgb()) if node.color() else None, None),
        "is_bypassed": _safe_attr(node, "isBypassed"),
        "is_displayed": _safe_attr(node, "isDisplayFlagSet"),
        "is_rendered": _safe_attr(node, "isRenderFlagSet"),
        "parm_count_total": len(all_parms),
        "parm_filter": {"max_parms": max_parms, "only_non_default": only_non_default},
        "parameters": [],
        "inputs": [],
        "outputs": [],
    }

    for parm in all_parms:
        if max_parms is not None and len(node_info["parameters"]) >= max_parms:
            break
        if only_non_default and _parm_is_default(parm):
            continue
        node_info["parameters"].append(_serialize_parm(parm))

    try:
        for i, in_node in enumerate(node.inputs()):
            ref = _serialize_node_ref(in_node)
            if ref is not None:
                ref["index"] = i
                node_info["inputs"].append(ref)
    except Exception as e:
        node_info["inputs_error"] = f"{type(e).__name__}: {e}"

    try:
        for i, out_conn in enumerate(node.outputConnections()):
            try:
                out_node = out_conn.outputNode()
                ref = _serialize_node_ref(out_node)
                if ref is None:
                    continue
                ref["index"] = i
                try:
                    ref["input_index"] = out_conn.inputIndex()
                except Exception:
                    pass
                node_info["outputs"].append(ref)
            except Exception as e:
                node_info["outputs"].append({"index": i, "error": f"{type(e).__name__}: {e}"})
    except Exception as e:
        node_info["outputs_error"] = f"{type(e).__name__}: {e}"

    return node_info


def get_node_errors(node_path):
    """Errors, warnings, and cook state for a node -- a clean error dict
    for a bad path, never a raw traceback."""
    import hou

    node = hou.node(node_path)
    if not node:
        return {"status": "error", "message": f"Node not found: {node_path}"}

    return {
        "path": node.path(),
        "errors": _safe_attr(node, "errors", default=[]),
        "warnings": _safe_attr(node, "warnings", default=[]),
        "needs_to_cook": _safe_attr(node, "needsToCook"),
        "cook_time": _safe_attr(node, "cookTime"),
    }


def get_network(parent_path):
    """Children of a network node plus their input connections, so the
    agent can read back the graph it just built."""
    import hou

    parent = hou.node(parent_path)
    if not parent:
        return {"status": "error", "message": f"Node not found: {parent_path}"}

    children = []
    for node in parent.children():
        inputs = []
        try:
            for i, in_node in enumerate(node.inputs()):
                if in_node is not None:
                    inputs.append({"index": i, "path": in_node.path()})
        except Exception:
            pass
        children.append({
            "name": node.name(),
            "path": node.path(),
            "type": node.type().name(),
            "position": _safe(lambda: [node.position()[0], node.position()[1]], None),
            "inputs": inputs,
        })

    return {"parent": parent.path(), "children": children}


def find_nodes(name_filter=None, type_filter=None, root="/", max_results=100):
    """Scene-wide (or subtree-wide) node search. `get_network` only lists
    one network's direct children at a time -- this walks the whole
    subtree under `root` in one call, filtered by a case-insensitive
    substring of the node's name and/or an exact node-type name. Stage 5a
    of HMCP_FEEDBACK_LOOP_PLAN.md, adapted from the external review's
    `find_nodes`/`list_children` (EXTERNAL_REVIEW_oculairmedia_houdini-mcp.md
    section 4.3)."""
    import hou

    root_node = hou.node(root)
    if not root_node:
        return {"status": "error", "message": f"Node not found: {root}"}

    name_needle = name_filter.lower() if name_filter else None
    matches = []
    truncated = False

    for node in root_node.allSubChildren():
        if len(matches) >= max_results:
            truncated = True
            break
        if name_needle and name_needle not in node.name().lower():
            continue
        node_type = _safe(lambda: node.type().name(), "unknown")
        if type_filter and node_type != type_filter:
            continue
        matches.append({
            "name": node.name(),
            "path": node.path(),
            "type": node_type,
            "category": _safe(lambda: node.type().category().name(), "unknown"),
        })

    return {
        "root": root_node.path(),
        "name_filter": name_filter,
        "type_filter": type_filter,
        "max_results": max_results,
        "truncated": truncated,
        "nodes": matches,
    }


# ---------------------------------------------------------------------------
# Geometry inspection -- the most important new tool
# ---------------------------------------------------------------------------


def _serialize_attribs(attribs):
    out = []
    for a in attribs:
        out.append({
            "name": _safe_attr(a, "name"),
            "data_type": _safe(lambda: a.dataType().name(), "unknown"),
            "size": _safe_attr(a, "size"),
        })
    return out


def get_geometry_info(node_path):
    """npoints/nprims/nvertices, attribute list (point/prim/vertex/detail),
    group names, bounding box, cook errors/warnings, cook time for a SOP
    node. Without this the agent builds a SOP graph blind."""
    import hou

    node = hou.node(node_path)
    if not node:
        return {"status": "error", "message": f"Node not found: {node_path}"}

    result = {
        "path": node.path(),
        "type": _safe(lambda: node.type().name(), "unknown"),
        "errors": _safe_attr(node, "errors", default=[]),
        "warnings": _safe_attr(node, "warnings", default=[]),
        "cook_time": _safe_attr(node, "cookTime"),
    }

    geo = _safe_attr(node, "geometry")
    if geo is None:
        result["geometry"] = None
        result["geometry_error"] = "Node has no evaluable geometry (not a SOP, or cook failed)."
        return result

    bbox = _safe_attr(geo, "boundingBox")
    result["geometry"] = {
        "npoints": _safe(lambda: geo.intrinsicValue("pointcount"), None),
        "nprims": _safe(lambda: geo.intrinsicValue("primitivecount"), None),
        "nvertices": _safe(lambda: geo.intrinsicValue("vertexcount"), None),
        "bounding_box": {
            "min": list(bbox.minvec()) if bbox else None,
            "max": list(bbox.maxvec()) if bbox else None,
        } if bbox else None,
        "point_attribs": _safe(lambda: _serialize_attribs(geo.pointAttribs()), []),
        "prim_attribs": _safe(lambda: _serialize_attribs(geo.primAttribs()), []),
        "vertex_attribs": _safe(lambda: _serialize_attribs(geo.vertexAttribs()), []),
        "detail_attribs": _safe(lambda: _serialize_attribs(geo.globalAttribs()), []),
        "point_groups": _safe(lambda: [g.name() for g in geo.pointGroups()], []),
        "prim_groups": _safe(lambda: [g.name() for g in geo.primGroups()], []),
    }
    return result


# ---------------------------------------------------------------------------
# Node type discovery -- how the agent looks up real parameter names
# instead of recalling them.
# ---------------------------------------------------------------------------


def _flatten_parm_templates(templates):
    """Recursively walk folders to a flat list of leaf parm templates."""
    flat = []
    for pt in templates:
        try:
            is_folder = pt.type().name() == "Folder" and hasattr(pt, "parmTemplates")
        except Exception:
            is_folder = False
        if is_folder:
            flat.extend(_flatten_parm_templates(pt.parmTemplates()))
        else:
            flat.append(pt)
    return flat


def _serialize_parm_template(pt):
    entry = {
        "name": pt.name(),
        "label": pt.label(),
        "type": _safe(lambda: pt.type().name(), "unknown"),
    }
    default = _safe_attr(pt, "defaultValue")
    if default is not None:
        entry["default"] = default if isinstance(default, (str, int, float, bool)) else list(default)
    menu_items = _safe(getattr(pt, "menuItems", lambda: None))
    if menu_items:
        entry["menu_items"] = list(menu_items)
    return entry


def get_node_type_parms(type_name, category):
    """Parameter names/labels/types/defaults/menu items for a node type --
    how the agent looks up real parameter names instead of recalling them."""
    import hou

    categories = hou.nodeTypeCategories()
    cat = categories.get(category)
    if not cat:
        return {"status": "error", "message": f"Unknown category '{category}'. Available: {sorted(categories.keys())}"}

    node_type = cat.nodeTypes().get(type_name)
    if not node_type:
        return {"status": "error", "message": f"Unknown node type '{type_name}' in category '{category}'."}

    group = _safe_attr(node_type, "parmTemplateGroup")
    if group is None:
        return {"type": type_name, "category": category, "parameters": []}

    leaves = _flatten_parm_templates(group.entries())
    return {
        "type": type_name,
        "category": category,
        "parameters": [_serialize_parm_template(pt) for pt in leaves],
    }


def list_node_types(category, name_filter=None):
    """Node type names available in a category, optionally filtered."""
    import hou

    categories = hou.nodeTypeCategories()
    cat = categories.get(category)
    if not cat:
        return {"status": "error", "message": f"Unknown category '{category}'. Available: {sorted(categories.keys())}"}

    names = sorted(cat.nodeTypes().keys())
    if name_filter:
        needle = name_filter.lower()
        names = [n for n in names if needle in n.lower()]

    truncated = len(names) > 3000
    return {"category": category, "count": len(names), "truncated": truncated, "types": names[:3000]}


def get_node_help(type_name, category, max_chars=4000):
    """Built-in help text for a node type, truncated to max_chars."""
    import hou

    categories = hou.nodeTypeCategories()
    cat = categories.get(category)
    if not cat:
        return {"status": "error", "message": f"Unknown category '{category}'. Available: {sorted(categories.keys())}"}

    node_type = cat.nodeTypes().get(type_name)
    if not node_type:
        return {"status": "error", "message": f"Unknown node type '{type_name}' in category '{category}'."}

    text = _safe_attr(node_type, "helpText", default="") or ""
    truncated = len(text) > max_chars
    return {"type": type_name, "category": category, "truncated": truncated, "help": text[:max_chars]}


def describe_commands():
    """Returns the command list as this plugin sees it -- used by
    scripts/check_contract.py to catch bridge/plugin drift."""
    return {"commands": commands_spec.COMMANDS}


# ---------------------------------------------------------------------------
# Viewport / camera -- Stage 2. Read-only here; the write commands
# (viewport_frame_node etc.) live in build.py since they mutate viewport
# state and go through guards.require_sandbox_scene() +
# guards.check_viewport_camera_free().
# ---------------------------------------------------------------------------


def viewport_state(viewport):
    """Shared read-only snapshot of a GeometryViewport's state -- used by
    get_viewport_info below and folded into every Stage 2 camera write
    handler's return payload in build.py. Every field via _safe_attr; this
    module must never raise, even against a stale viewport reference."""
    cam = _safe_attr(viewport, "defaultCamera")
    pivot = _safe(lambda: list(cam.pivot())) if cam is not None else None
    translation = _safe(lambda: list(cam.translation())) if cam is not None else None
    return {
        "name": _safe_attr(viewport, "name"),
        "type": _safe(lambda: viewport.type().name()),
        "camera_path": _safe_attr(viewport, "cameraPath"),
        "camera_locked": _safe_attr(viewport, "isCameraLockedToView"),
        "pivot": pivot,
        "translation": translation,
    }


def update_mode_state():
    """hou.updateModeSetting()'s name, plus whether it currently allows
    viewport_snapshot to succeed. Shared by get_viewport_info and every
    Stage 2 camera write handler's return payload -- per the Stage 1
    decision to surface this instead of hard-refusing camera commands on
    a precondition that only actually blocks flipbook (see
    build.py:viewport_snapshot)."""
    try:
        import hou

        mode = hou.updateModeSetting().name()
        return {"update_mode": mode, "snapshot_ready": mode != "Manual"}
    except Exception:
        return {"update_mode": None, "snapshot_ready": None}


def get_viewport_info():
    """Read-only viewport/camera state: name, type, pivot/translation,
    camera-lock status, and whether the current update_mode allows
    viewport_snapshot to succeed right now. Available in any scene --
    never raises, even headless or with no SceneViewer pane open (returns
    available: False instead of a precondition error, since intro.py
    commands carry no guard)."""
    try:
        import hou
    except Exception:
        return {"available": False, "message": "hou module unavailable."}

    if not hasattr(hou, "ui"):
        return {"available": False, "message": "No viewport -- headless hython session."}

    sv = _safe(lambda: hou.ui.paneTabOfType(hou.paneTabType.SceneViewer))
    if sv is None:
        return {"available": False, "message": "No SceneViewer pane is open."}

    viewport = _safe_attr(sv, "curViewport")
    if viewport is None:
        return {"available": False, "message": "SceneViewer pane has no current viewport."}

    info = viewport_state(viewport)
    info["available"] = True
    info.update(update_mode_state())
    return info
