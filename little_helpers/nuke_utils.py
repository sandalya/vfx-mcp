"""
little_helpers.nuke_utils

DAG viewport + render-dir helpers shared across the product HUDs. Qt-free
at module level -- PySide is imported inside dag_viewport_rect() itself.
"""

import os

import nuke


def dag_viewport_rect():
    """(center, zoom, vis_rect) for the frontmost open Node Graph panel --
    shared by callers that need to know what's on screen (e.g. the
    version-stepping "nothing selected" fallback, versions._working_read_nodes,
    below). Nuke has no built-in "is this node on screen" API, so this reconstructs the
    viewport rect from nuke.center()/nuke.zoom() (DAG pan/zoom, in world
    units) and the pixel size of the DAG's Qt widget.

    Caveat: if multiple Node Graph panels/tabs are open, this grabs the
    first "DAG_Window" Qt widget found -- not necessarily the one the user
    is looking at. Raises RuntimeError if none is found (no Node Graph
    panel open)."""
    try:
        from PySide2 import QtWidgets
    except ImportError:
        from PySide6 import QtWidgets

    center = nuke.center()
    zoom = nuke.zoom()

    app = QtWidgets.QApplication.instance()
    w_px = h_px = None
    for w in app.allWidgets():
        if w.metaObject().className() == "DAG_Window":
            geo = w.geometry()
            w_px, h_px = geo.width(), geo.height()
            break

    if w_px is None:
        raise RuntimeError("no DAG_Window widget found -- is a Node Graph panel open?")

    half_w = (w_px / zoom) / 2.0
    half_h = (h_px / zoom) / 2.0
    vis_rect = {
        "x_min": center[0] - half_w, "x_max": center[0] + half_w,
        "y_min": center[1] - half_h, "y_max": center[1] + half_h,
    }
    return center, zoom, (w_px, h_px), vis_rect


def nodes_in_view(node_class=None):
    """Nodes of node_class (or all classes) whose bounding box intersects
    the visible Node Graph viewport -- see dag_viewport_rect. Returns Node
    objects directly (not JSON-friendly dicts), for in-process callers like
    versions._working_read_nodes."""
    _center, _zoom, _widget_px, vis_rect = dag_viewport_rect()
    all_nodes = nuke.allNodes(node_class) if node_class else nuke.allNodes()

    def intersects(x0, y0, x1, y1):
        return not (x1 < vis_rect["x_min"] or x0 > vis_rect["x_max"]
                    or y1 < vis_rect["y_min"] or y0 > vis_rect["y_max"])

    result = []
    for n in all_nodes:
        try:
            sw, sh = n.screenWidth(), n.screenHeight()
        except Exception:
            sw, sh = 80, 18
        x, y = n.xpos(), n.ypos()
        if intersects(x, y, x + sw, y + sh):
            result.append(n)
    return result


def list_render_dir(path=None):
    """listdir() on path, defaulting to $FTRACK_RENDER_PATH -- the first
    step of Function 1 (node init, see docs/NUKE_COMP_LAYER_ASSEMBLY.md),
    which needs to see what render layer-branches exist on disk before it can
    build the 4-Read assembly chain for one of them. Runs Nuke-side because
    pc137's Nuke process already has working SMB access to the render share
    under the ftrack-launched domain session -- the Claude Code host does not
    (tested 2026-08-07: VPN/TCP reachable, but not domain-joined, so no creds
    for loky.plarium.local).

    Confirmed by Sashok: $FTRACK_RENDER_PATH itself contains only layer
    subfolders, no per-frame files -- so no sequence-collapsing needed here."""
    path = path or os.environ.get("FTRACK_RENDER_PATH")
    if not path:
        raise ValueError("no path given and $FTRACK_RENDER_PATH is not set")

    entries = []
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        entries.append({
            "name": name,
            "is_dir": os.path.isdir(full),
            "mtime": os.path.getmtime(full),  # lets callers sort by
            # recency -- added for the layer-branch picker HUD, which
            # wants the most recently touched layer-branch folder first
            # (a new version subfolder landing inside it bumps the
            # branch folder's own mtime on Windows/NTFS).
        })

    return {"path": path, "entries": entries}
