"""
lh_router

Dev/prod router for little_helpers. Sits between the stock hotkeys
(Shift+A / Shift+E / F10 / Alt+V) and whichever package is currently
active -- little_helpers (studio share, production) or little_helpers_dev
(worktree, iterated on via `deploy_plugin.sh nuke-dev`). F12 toggles which
one the hotkeys run; Shift+F12 does the same toggle and also starts/stops
the MCP server to match, for "enter/leave a dev session" in one press. See
nuke/docs/plans/LITTLE_HELPERS_BRANCH_WORKFLOW.md for the design this
implements.

Deployed by the existing `nuke` target (infra), never `nuke-dev`. Never
imports little_helpers_dev at module level -- only on demand, when dev mode
is actually active, so a missing/broken dev copy can't break production
dispatch.
"""

import importlib

import nuke

try:
    from PySide6 import QtWidgets, QtCore, QtGui
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui

LAYER_PICKER_MENU_PATH = "Little Helpers/Create Render Branch"
VERSION_HUD_MENU_PATH = "Little Helpers/Change Render Version"
SPLIT_LAYERS_MENU_PATH = "Little Helpers/Split Layers"
REPATH_PASTE_MENU_PATH = "Little Helpers/Repath Paste"  # Alt+V, standalone -- never touches native Edit/Paste (Ctrl+V)
TOGGLE_MENU_PATH = "Little Helpers/Dev Mode (F12)"
TOGGLE_WITH_MCP_MENU_PATH = "Little Helpers/Dev Mode + MCP (Shift+F12)"

PROD_PACKAGE = "little_helpers"
DEV_PACKAGE = "little_helpers_dev"


# ---- mode flag ------------------------------------------------------------
# Stored on the `nuke` module object, not as a module-level variable here or
# in little_helpers -- both little_helpers.reload_all() and this router's
# own menu commands (below) call importlib.reload() on themselves on every
# press, which re-executes top-level assignments and would silently reset a
# plain global to its default on the very next keypress. `nuke` is Nuke's
# own extension module; nothing ever reloads it.

def _dev_mode():
    return getattr(nuke, "_lh_dev_mode", False)


def _active_package_name():
    return DEV_PACKAGE if _dev_mode() else PROD_PACKAGE


def _dispatch(entry_point):
    name = _active_package_name()
    pkg = importlib.import_module(name)
    pkg.reload_all()
    label = "DEV" if name == DEV_PACKAGE else "MAIN"
    print(f"[{label}] {name} active -- {pkg.__file__}")
    fn = getattr(pkg, entry_point, None)
    if fn is None:
        # The two packages are allowed to drift -- little_helpers_dev is
        # iterated on ahead of what the TD has pulled into production, on
        # purpose. Without this check, pressing a hotkey for a feature
        # that only exists in dev while in MAIN mode threw a raw
        # AttributeError straight at the artist (confirmed live
        # 2026-09-12: MAIN + Alt+V, paste_and_maybe_repath not yet in
        # that studio-share checkout). A clear print is the whole fix --
        # this isn't a bug to route around, MAIN genuinely can't run a
        # command it doesn't have yet.
        print(f"[{label}] {name} has no '{entry_point}' -- this feature "
              f"isn't in that checkout yet (F12 for DEV if it should be).")
        return
    fn()


def show_layer_picker():
    _dispatch("show_layer_picker")


def show_version_hud():
    _dispatch("show_version_hud")


def show_split_layers():
    _dispatch("show_split_layers")


def paste_and_maybe_repath():
    _dispatch("paste_and_maybe_repath")


def toggle_dev_mode():
    """F12. Flips the flag, prints the new mode, updates the badge."""
    nuke._lh_dev_mode = not _dev_mode()
    name = _active_package_name()
    label = "DEV" if name == DEV_PACKAGE else "MAIN"
    print(f"[{label}] dev mode {'ON' if _dev_mode() else 'OFF'} -- "
          f"hotkeys now run {name}")
    _update_badge(label)


def toggle_dev_mode_and_mcp():
    """Shift+F12. Same flip as plain F12, plus starts/stops the MCP server
    to match -- one press for "entering/leaving a dev session", since
    Sashok wants MCP running whenever he's in DEV. Independent of plain
    F12, which never touches MCP -- the two hotkeys are deliberately
    separate, not a shared code path with a flag, so a plain-F12 press can
    never have an MCP side effect by accident.

    Reaches into nuke_mcp_plugin's module-level `_server_thread` directly
    (same pattern that module's own _McpHud class uses internally) --
    there is no public is-it-running accessor, and adding one for a single
    two-line caller isn't worth a new API surface."""
    import nuke_mcp_plugin
    importlib.reload(nuke_mcp_plugin)

    nuke._lh_dev_mode = not _dev_mode()
    name = _active_package_name()
    label = "DEV" if name == DEV_PACKAGE else "MAIN"

    was_running = (
        nuke_mcp_plugin._server_thread is not None
        and nuke_mcp_plugin._server_thread.is_alive()
    )
    if nuke._lh_dev_mode:
        nuke_mcp_plugin.start_server()
        mcp_status = "MCP already running" if was_running else "MCP started"
    else:
        nuke_mcp_plugin.stop_server()
        mcp_status = "MCP stopped" if was_running else "MCP was not running"

    print(f"[{label}] dev mode {'ON' if _dev_mode() else 'OFF'} + "
          f"{mcp_status} -- hotkeys now run {name}")
    badge = _update_badge(label)
    badge.flash_status(mcp_status)


# ---- floating mode badge ---------------------------------------------------
# Reuses the RDP-hardened idiom from nuke_mcp_plugin._PrintHUD /
# little_helpers/hud.py: frameless + WindowStaysOnTopHint + Tool, rounded
# silhouette via setMask(), never WA_TranslucentBackground (eats mouse
# clicks over RDP to pc137 -- see those modules' comments for the root
# cause). The instance lives on `nuke`, same reasoning as the mode flag --
# nuke_mcp_plugin's _hud/_mcp_hud both get orphaned by their module's own
# reload() wiping the module-level reference to an already-shown widget;
# keeping the reference off this (self-reloading) module avoids the same
# failure here. Unverified on pc137: whether a top-level widget created this
# early (menu.py load time, before any node graph is open) comes up
# correctly, or needs its creation deferred.

class _ModeBadge(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.setStyleSheet("""
            QLabel { color: white; font-weight: 700; font-size: 11px; }
            #status { color: rgba(255, 255, 255, 210); font-weight: 400; font-size: 9px; }
        """)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 5, 12, 5)
        layout.setSpacing(2)
        self.label = QtWidgets.QLabel("MAIN")
        layout.addWidget(self.label)
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("status")
        self.status.hide()
        layout.addWidget(self.status)
        self.resize(76, 26)

    def resizeEvent(self, event):
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(self.rect()), 10, 10)
        self.setMask(QtGui.QRegion(path.toFillPolygon().toPolygon()))
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        path = QtGui.QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)
        is_dev = self.label.text() == "DEV"
        color = QtGui.QColor(190, 90, 30, 235) if is_dev else QtGui.QColor(55, 130, 60, 235)
        painter.fillPath(path, color)
        painter.setPen(QtGui.QColor(255, 255, 255, 60))
        painter.drawPath(path)
        super().paintEvent(event)

    def set_mode(self, label):
        self.label.setText(label)
        self.update()

    def flash_status(self, text, ms=1400):
        """Temporary second line, same corner as the persistent MAIN/DEV
        text -- mirrors nuke_mcp_plugin._McpHud's flash-and-hide status
        label, just anchored at the mode badge instead of near the
        cursor."""
        self.status.setText(text)
        self.status.show()
        self.adjustSize()
        self.move_to_corner()
        QtCore.QTimer.singleShot(ms, self._clear_status)

    def _clear_status(self):
        self.status.hide()
        self.adjustSize()
        self.move_to_corner()

    def move_to_corner(self):
        screen = QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(geo.right() - self.width() - 16, geo.top() + 16)


def _update_badge(label):
    badge = getattr(nuke, "_lh_mode_badge", None)
    # `isinstance` here checks against the *current* _ModeBadge class
    # object -- if this module has been reload()'d since `badge` was built,
    # `badge`'s actual class is a now-orphaned earlier version (reload
    # rebinds the name in this module's namespace but never re-classes
    # existing instances), missing whatever methods a later edit added.
    # Same gotcha as nuke_mcp_plugin's _hud/_mcp_hud, just hitting a widget
    # this design deliberately keeps alive across reloads instead of one
    # that gets rebuilt every press -- so it needs its own staleness check
    # instead of just always rebuilding.
    if badge is not None and not isinstance(badge, _ModeBadge):
        try:
            badge.close()
        except Exception:
            pass
        badge = None
    if badge is None:
        badge = _ModeBadge()
        nuke._lh_mode_badge = badge
        badge.move_to_corner()
        badge.show()
    badge.set_mode(label)
    badge.raise_()
    return badge


def ensure_badge():
    """Called from register_menu() so the badge exists and shows the right
    mode from Nuke startup, not only after the first F12 press."""
    _update_badge("DEV" if _dev_mode() else "MAIN")


# ---- menu registration ------------------------------------------------------

def register_menu():
    """Idempotent, same findItem/removeItem/addCommand idiom as
    little_helpers.register_menu(). Calling this *after* the stock
    registration overwrites the same four paths with router commands that
    dispatch through the active-mode flag -- no duplicate entries, and
    deleting the `lh_router` import from menu.py reverts to stock
    little_helpers behaviour (always production) on the next launch."""
    menu = nuke.menu("Nodes")

    if menu.findItem(LAYER_PICKER_MENU_PATH):
        menu.removeItem(LAYER_PICKER_MENU_PATH)
    menu.addCommand(
        LAYER_PICKER_MENU_PATH,
        "import importlib, lh_router; importlib.reload(lh_router); "
        "lh_router.show_layer_picker()",
        "shift+a",
    )

    if menu.findItem(VERSION_HUD_MENU_PATH):
        menu.removeItem(VERSION_HUD_MENU_PATH)
    menu.addCommand(
        VERSION_HUD_MENU_PATH,
        "import importlib, lh_router; importlib.reload(lh_router); "
        "lh_router.show_version_hud()",
        "shift+e",
    )

    if menu.findItem(SPLIT_LAYERS_MENU_PATH):
        menu.removeItem(SPLIT_LAYERS_MENU_PATH)
    menu.addCommand(
        SPLIT_LAYERS_MENU_PATH,
        "import importlib, lh_router; importlib.reload(lh_router); "
        "lh_router.show_split_layers()",
        "F10",
    )

    if menu.findItem(REPATH_PASTE_MENU_PATH):
        menu.removeItem(REPATH_PASTE_MENU_PATH)
    menu.addCommand(
        REPATH_PASTE_MENU_PATH,
        "import importlib, lh_router; importlib.reload(lh_router); "
        "lh_router.paste_and_maybe_repath()",
        "Alt+V",
    )

    # Placeholder hotkey -- NOT collision-checked yet (see Step 2 of the
    # plan doc). Verify against every top-level Nuke menu, not just
    # "Nodes", before relying on this in a live session.
    if menu.findItem(TOGGLE_MENU_PATH):
        menu.removeItem(TOGGLE_MENU_PATH)
    menu.addCommand(
        TOGGLE_MENU_PATH,
        "import importlib, lh_router; importlib.reload(lh_router); "
        "lh_router.toggle_dev_mode()",
        "F12",
    )

    # Also not yet collision-checked (see the F12 comment above) -- a
    # second, separate binding by design (not Shift stacked onto the same
    # command), so plain F12 keeps working even if this one turns out to
    # collide and needs remapping.
    if menu.findItem(TOGGLE_WITH_MCP_MENU_PATH):
        menu.removeItem(TOGGLE_WITH_MCP_MENU_PATH)
    menu.addCommand(
        TOGGLE_WITH_MCP_MENU_PATH,
        "import importlib, lh_router; importlib.reload(lh_router); "
        "lh_router.toggle_dev_mode_and_mcp()",
        "Shift+F12",
    )

    ensure_badge()
