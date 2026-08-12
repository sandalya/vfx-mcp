"""
build.py -- Phase 2 write commands (houdini/docs/HOUDINI_MCP_REWRITE_PLAN.md).

Every handler calls guards.require_sandbox_scene() before doing anything
(save_scene_as is the one documented exception, gated by
guards.require_bootstrap_scene() instead -- see guards.py), then wraps its
actual mutation in hou.undos.group() so a single Ctrl+Z in Houdini removes
it completely.

create_node deliberately has no `parameters` dict -- that was the old
plugin's bypass (plugin/server.py:290-294 sets arbitrary parms at creation
time without going through any whitelist). Here, set_parm is the only way
to set a value and it always runs guards.check_settable_parm, so the
bypass has no path back in.

No `import os` / `shutil` / `requests` / `subprocess` / `zipfile` anywhere
in this package -- see guards.py's module docstring for why.
"""

from datetime import datetime

from . import guards


def _require_node(node_path):
    import hou

    node = hou.node(node_path)
    if not node:
        raise ValueError(f"Node not found: {node_path}")
    return node


def _require_parm(node, parm_name):
    parm = node.parm(parm_name)
    if not parm:
        raise ValueError(f"Parameter not found: '{parm_name}' on {node.path()}")
    return parm


def _require_scene_viewport():
    """Return (scene_viewer, viewport) for the current SceneViewer pane.

    Shared preflight for viewport_snapshot and every Stage 2 viewport_*
    command. Raises ValueError, not RuntimeError -- server.py's guard-
    refusal catch only handles (PermissionError, ValueError); a
    RuntimeError falls through to the generic handler and comes back as a
    full traceback with no REFUSED audit line. Handles hou.ui being
    absent entirely (headless hython) as well as no pane / no current
    viewport, so headless callers get a clean message instead of an
    AttributeError.
    """
    import hou

    if not hasattr(hou, "ui"):
        raise ValueError(
            "Precondition: no viewport is available -- this command "
            "requires a graphical Houdini session, not headless hython."
        )

    sv = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if sv is None:
        err = ValueError(
            "Precondition: no SceneViewer pane is open in Houdini. Open "
            "Scene View (Windows -> Scene View) first."
        )
        err.hint = "Open Windows -> Scene View in Houdini, then retry."
        raise err

    viewport = sv.curViewport()
    if viewport is None:
        raise ValueError("Precondition: the SceneViewer pane has no current viewport.")

    return sv, viewport


# ---------------------------------------------------------------------------
# Node graph editing
# ---------------------------------------------------------------------------


def create_node(parent_path, node_type, name=None):
    """Create a node under parent_path. Category is derived from the
    parent (parent.childTypeCategory()), not caller-supplied, and checked
    against guards.ALLOWED_NODE_CATEGORIES (Sop/Object only, Phase 1/2
    target domain). Registers the new node so delete_node can remove it
    later this session."""
    guards.require_sandbox_scene()
    import hou

    parent = _require_node(parent_path)
    category = parent.childTypeCategory()
    category_name = category.name() if category else None
    guards.check_creatable_node_type(node_type, category_name)

    with hou.undos.group(f"MCP: create_node {node_type}"):
        node = parent.createNode(node_type, node_name=name)
        guards.session_registry.register_created(node)

    return {
        "name": node.name(),
        "path": node.path(),
        "type": node.type().name(),
        "category": category_name,
        "position": list(node.position()),
    }


def connect_nodes(from_path, to_path, input_index=0):
    """Wire from_path's output into to_path's input_index-th input -- the
    capability the old plugin advertised (connect_nodes) but never
    actually implemented (see the rewrite plan's problem table)."""
    guards.require_sandbox_scene()
    import hou

    from_node = _require_node(from_path)
    to_node = _require_node(to_path)

    from_cat = from_node.type().category().name()
    to_cat = to_node.type().category().name()
    if from_cat != to_cat:
        err = ValueError(
            f"Refused: cannot connect {from_node.path()} ({from_cat}) into "
            f"{to_node.path()} ({to_cat}) -- their network categories don't "
            f"match."
        )
        err.hint = (
            f"Connect nodes within the same category ({from_cat} outputs "
            f"only wire into {from_cat} inputs). Wiring across categories "
            f"(e.g. Sop -> Dop) isn't valid in Houdini's network model."
        )
        raise err

    with hou.undos.group("MCP: connect_nodes"):
        to_node.setInput(input_index, from_node)

    return {"from": from_node.path(), "to": to_node.path(), "input_index": input_index}


def set_parm(node_path, parm_name, value):
    """Set a single parameter value. Runs the same guard checks as
    create_node (output-path / code / file-type name checks in
    guards.check_settable_parm) -- the only gate on what can be written,
    since create_node itself never takes parameter values."""
    guards.require_sandbox_scene()
    import hou

    node = _require_node(node_path)
    parm = _require_parm(node, parm_name)
    guards.check_settable_parm(parm)

    with hou.undos.group(f"MCP: set_parm {parm_name}"):
        parm.set(value)

    return {"path": node.path(), "parm": parm_name, "value": str(parm.eval())}


def set_expression(node_path, parm_name, expression):
    """Set an HScript expression on a parameter. Never Python -- see
    guards.check_expression_language."""
    guards.require_sandbox_scene()
    import hou

    node = _require_node(node_path)
    parm = _require_parm(node, parm_name)
    guards.check_settable_parm(parm)
    guards.check_expression_language(hou.exprLanguage.Hscript)

    with hou.undos.group(f"MCP: set_expression {parm_name}"):
        parm.setExpression(expression, language=hou.exprLanguage.Hscript)

    return {"path": node.path(), "parm": parm_name, "expression": expression}


def delete_node(node_path):
    """Destroy a node -- only if the agent created it earlier this session
    (guards.session_registry). See SessionRegistry's docstring for why
    that's keyed on sessionId() and not path."""
    guards.require_sandbox_scene()
    import hou

    node = _require_node(node_path)
    if not guards.session_registry.can_delete(node):
        raise PermissionError(
            f"Refused: {node_path} was not created by this agent in the "
            f"current session -- delete rights are scoped to the agent's "
            f"own work (see guards.SessionRegistry)."
        )

    with hou.undos.group("MCP: delete_node"):
        guards.session_registry.forget(node)
        node.destroy()

    return {"deleted": node_path}


# ---------------------------------------------------------------------------
# Cosmetic
# ---------------------------------------------------------------------------


def rename_node(node_path, new_name):
    guards.require_sandbox_scene()
    import hou

    node = _require_node(node_path)
    with hou.undos.group("MCP: rename_node"):
        node.setName(new_name)
    return {"path": node.path(), "name": node.name()}


def set_position(node_path, x, y):
    guards.require_sandbox_scene()
    import hou

    node = _require_node(node_path)
    with hou.undos.group("MCP: set_position"):
        node.setPosition([x, y])
    return {"path": node.path(), "position": list(node.position())}


def set_color(node_path, r, g, b):
    guards.require_sandbox_scene()
    import hou

    node = _require_node(node_path)
    with hou.undos.group("MCP: set_color"):
        node.setColor(hou.Color(r, g, b))
    return {"path": node.path(), "color": [r, g, b]}


def set_comment(node_path, comment):
    guards.require_sandbox_scene()
    import hou

    node = _require_node(node_path)
    with hou.undos.group("MCP: set_comment"):
        node.setComment(comment)
    return {"path": node.path(), "comment": comment}


def layout_children(parent_path):
    guards.require_sandbox_scene()
    import hou

    parent = _require_node(parent_path)
    with hou.undos.group("MCP: layout_children"):
        parent.layoutChildren()
    return {"parent": parent.path()}


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


def set_display_flag(node_path, on):
    guards.require_sandbox_scene()
    import hou

    node = _require_node(node_path)
    with hou.undos.group("MCP: set_display_flag"):
        node.setDisplayFlag(bool(on))
    return {"path": node.path(), "display_flag": node.isDisplayFlagSet()}


def set_render_flag(node_path, on):
    guards.require_sandbox_scene()
    import hou

    node = _require_node(node_path)
    with hou.undos.group("MCP: set_render_flag"):
        node.setRenderFlag(bool(on))
    return {"path": node.path(), "render_flag": node.isRenderFlagSet()}


def set_bypass(node_path, on):
    guards.require_sandbox_scene()
    import hou

    node = _require_node(node_path)
    with hou.undos.group("MCP: set_bypass"):
        node.bypass(bool(on))
    return {"path": node.path(), "bypassed": node.isBypassed()}


# ---------------------------------------------------------------------------
# Scene bootstrap / eyes
# ---------------------------------------------------------------------------


def save_scene_as():
    """The one write command that runs on a scene NOT yet in the sandbox --
    and only a never-saved one (guards.require_bootstrap_scene). No
    arguments: the plugin generates both directory (guards.SANDBOX_ROOT)
    and filename (timestamped, so it can never collide with an existing
    file)."""
    guards.require_bootstrap_scene()
    import hou

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"{guards.SANDBOX_ROOT}mcp_{ts}.hip"

    with hou.undos.group("MCP: save_scene_as"):
        hou.hipFile.save(file_name=path)

    return {"path": path}


def viewport_snapshot():
    """OpenGL viewport snapshot only -- no Karma/Arnold/Mantra rendering,
    out of scope per the rewrite plan section 3. No arguments: captures
    whatever the SceneViewer's current viewport/renderer is already
    showing and writes to a generated, collision-free path under
    guards.SNAPSHOT_DIR (must pre-exist -- the plugin never creates
    directories)."""
    guards.require_sandbox_scene()
    import hou

    sv, viewport = _require_scene_viewport()

    # hou.updateMode() is deprecated and, as of 21.0.729, not even callable
    # (hou.updateMode is purely the enum class -- calling it raises
    # AttributeError: No constructor defined, hit live during Phase 2
    # verification). hou.updateModeSetting() is the current query API.
    # Deliberately kept local to this handler, not folded into
    # _require_scene_viewport -- it exists because *flipbook* pops a modal
    # dialog; a camera move does not render and cannot trip it, so the
    # Stage 2 viewport_* commands must not inherit this check.
    if hou.updateModeSetting() == hou.updateMode.Manual:
        err = ValueError(
            "Precondition: Houdini is in Manual update mode -- viewport "
            "capture would trigger a fatal OpenGL dialog and hang the "
            "connection. Switch to Auto Update first."
        )
        err.hint = "Call hou.setUpdateMode(hou.updateMode.AutoUpdate) in Houdini, then retry."
        raise err

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"{guards.SNAPSHOT_DIR}mcp_{ts}.jpg"

    with hou.undos.group("MCP: viewport_snapshot"):
        cur_frame = int(hou.frame())
        settings = sv.flipbookSettings().stash()
        settings.output(filepath)
        settings.frameRange((cur_frame, cur_frame))
        sv.flipbook(viewport, settings)

    return {"path": filepath}
