"""
lh_router

Dev/prod router for little_helpers. Sits between the stock hotkeys
(Shift+A / Shift+E / F10 / Ctrl+V) and whichever package is currently
active -- little_helpers (studio share, production) or little_helpers_dev
(worktree, iterated on via `deploy_plugin.sh nuke-dev`). F12 toggles which
one the hotkeys run. See nuke/docs/plans/LITTLE_HELPERS_BRANCH_WORKFLOW.md
for the design this implements.

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

LAYER_PICKER_MENU_PATH = "Little Helpers/Create Layer Branch"
VERSION_HUD_MENU_PATH = "Little Helpers/Change Layer Version"
SPLIT_LAYERS_MENU_PATH = "Little Helpers/Split Layers"
PASTE_OVERRIDE_MENU_PATH = "Edit/Paste"
TOGGLE_MENU_PATH = "Little Helpers/Dev Mode (F12)"

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
    getattr(pkg, entry_point)()


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
        """)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(12, 5, 12, 5)
        self.label = QtWidgets.QLabel("MAIN")
        layout.addWidget(self.label)
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

    def move_to_corner(self):
        screen = QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(geo.right() - self.width() - 16, geo.top() + 16)


def _update_badge(label):
    badge = getattr(nuke, "_lh_mode_badge", None)
    if badge is None:
        badge = _ModeBadge()
        nuke._lh_mode_badge = badge
        badge.move_to_corner()
        badge.show()
    badge.set_mode(label)
    badge.raise_()


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

    nuke_menu = nuke.menu("Nuke")
    if nuke_menu.findItem(PASTE_OVERRIDE_MENU_PATH):
        nuke_menu.removeItem(PASTE_OVERRIDE_MENU_PATH)
    nuke_menu.addCommand(
        PASTE_OVERRIDE_MENU_PATH,
        "import importlib, lh_router; importlib.reload(lh_router); "
        "lh_router.paste_and_maybe_repath()",
        "Ctrl+V",
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

    ensure_badge()
