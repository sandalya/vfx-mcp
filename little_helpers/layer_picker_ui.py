"""
little_helpers.layer_picker_ui

Function 1 HUD (Shift+A): lists the render root's layer subfolders and
builds a layer branch on pick. See docs/NUKE_COMP_LAYER_ASSEMBLY.md.

---- Layer-branch picker (Shift+A) ---------------------------------------
Lists the render root's layer subfolders (same data list_render_dir
returns); picking one drops the "Function 1 init" node chain documented
in docs/NUKE_COMP_LAYER_ASSEMBLY.md -- 4 Read nodes + the ShuffleCopy/
Copy assembly + an empty Cryptomatte pick point + a StickyNote label.
Each Read's version + frame range is resolved by scanning disk per-pass
(see layer_branch._resolve_pass/_collapse_sequence).

Picker is a phone-timer-style vertical spinner (hud._WheelPicker), per
Sashok's ask for something better than one-button-per-folder once the
render root grew past a handful of branches -- scroll or Up/Down to the
value you want, confirm with the Build button, Enter, or a double-click.
Names are sorted by folder mtime, freshest first, with the freshest one
pre-selected on open -- per Sashok's ask, since picking up whatever
branch was just re-rendered is the common case. (An earlier revision also
had a plain QListWidget view with a toggle to switch between the two;
removed once the wheel alone proved to be everything Sashok wanted -- see
BACKLOG.md if it needs resurrecting.)
"""

import random

try:
    from PySide6 import QtWidgets, QtCore, QtGui
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui

from .hud import _WheelPicker
from .layer_branch import build_layer_branch
from .nuke_utils import list_render_dir

_layer_picker_hud = None  # rebuilt fresh every open -- the folder list can
                          # change between opens, so caching would go
                          # stale.

# Sashok's ask: Build button reads a random one of these instead of the
# same static label every time -- purely cosmetic, re-rolled on every HUD
# open (see _LayerPickerHUD.__init__).
_BUILD_BTN_LABELS = (
    "ЄБАШ",
    "АНУКА",
    "МЕНІ ПОВЕЗЕ",
    "БУДЬ ДОБРІШЕ",
    "ОТАКО",
    "ГАТІ",
    "А ТАК МОЖНА БУЛО?",
    "ГОЦ",
    "БАЦ",
)


class _LayerPickerHUD(QtWidgets.QWidget):
    def __init__(self, layer_names):
        super().__init__()
        self.layer_names = layer_names  # already sorted freshest-first
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)

        self.setStyleSheet("""
            QLabel { color: rgba(230, 230, 230, 230); font-size: 11px; }
            QCheckBox { color: rgba(230, 230, 230, 230); font-size: 11px; }
            QPushButton {
                background-color: rgba(70, 130, 220, 210);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px;
                font-weight: 600;
                text-align: left;
            }
            QPushButton:hover { background-color: rgba(90, 150, 240, 230); }
            QPushButton:pressed { background-color: rgba(50, 100, 180, 230); }
            #status { color: rgba(220, 150, 150, 230); font-size: 10px; }
        """)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        self.wheel = _WheelPicker(self.layer_names)
        self.wheel.activated.connect(self._pick)
        layout.addWidget(self.wheel)

        self.split_checkbox = QtWidgets.QCheckBox("Split layers")
        self.split_checkbox.setChecked(False)
        self.split_checkbox.setFocusPolicy(QtCore.Qt.NoFocus)
        self.split_checkbox.setToolTip(
            "Після збірки рідів буде викликаний скріпт для розбиття композу по лайтгрупам"
        )
        layout.addWidget(self.split_checkbox)

        self.build_btn = QtWidgets.QPushButton(random.choice(_BUILD_BTN_LABELS))
        self.build_btn.setFocusPolicy(QtCore.Qt.NoFocus)
        self.build_btn.clicked.connect(lambda: self._pick(self._current_selection()))
        layout.addWidget(self.build_btn)

        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("status")
        layout.addWidget(self.status)

        self.setFixedWidth(240)
        self.adjustSize()

    def _current_selection(self):
        return self.wheel.current_name()

    def _pick(self, layer_name):
        if not layer_name:
            return
        try:
            last_node = build_layer_branch(layer_name)
        except Exception as exc:
            self.status.setText(str(exc))
            print(f"build_layer_branch({layer_name!r}) failed: {exc}")
            return
        if self.split_checkbox.isChecked():
            try:
                from . import run_split_layers
                run_split_layers(last_node)
            except Exception as exc:
                self.status.setText(str(exc))
                print(f"run_split_layers({last_node.name()!r}) failed: {exc}")
        self.hide()

    def resizeEvent(self, event):
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(self.rect()), 12, 12)
        self.setMask(QtGui.QRegion(path.toFillPolygon().toPolygon()))
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        path = QtGui.QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)
        painter.fillPath(path, QtGui.QColor(25, 25, 28, 255))
        painter.setPen(QtGui.QColor(255, 255, 255, 40))
        painter.drawPath(path)
        super().paintEvent(event)

    def show_near_cursor(self):
        pos = QtGui.QCursor.pos()
        self.move(pos.x() - self.width() // 2, pos.y() - self.height() - 10)
        self.show()
        self.raise_()
        self.activateWindow()
        # focusOutEvent alone isn't reliable for a Qt.Tool widget over RDP
        # -- clicking the DAG doesn't always transfer focus away cleanly,
        # so it stayed open (same issue found on _VersionHUD, fixed the
        # same way there). App-wide mouse filter instead: any press
        # outside our own rect closes us, regardless of focus semantics.
        QtWidgets.QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.MouseButtonPress:
            try:
                global_pos = event.globalPosition().toPoint()  # Qt6/PySide6
            except AttributeError:
                global_pos = event.globalPos()  # Qt5/PySide2
            if not self.geometry().contains(global_pos):
                self.hide()
        return super().eventFilter(obj, event)

    def focusOutEvent(self, event):
        self.hide()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        # Up/Down/Enter handled here, not on self.wheel directly --
        # everything in this HUD is NoFocus specifically so keyboard
        # focus stays on `self` (a focused child stealing focus fires our
        # own focusOutEvent -> hide() before a click/keypress on it can be
        # processed). Same reasoning applies to giving the wheel widget
        # real focus, so arrow-key stepping is dispatched from here instead.
        if event.key() == QtCore.Qt.Key_Escape:
            self.hide()
        elif event.key() == QtCore.Qt.Key_Up:
            self.wheel._step(-1)
        elif event.key() == QtCore.Qt.Key_Down:
            self.wheel._step(1)
        elif event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self._pick(self._current_selection())
        else:
            super().keyPressEvent(event)


def show_layer_picker():
    """Triggered by the Nuke-side hotkey (see little_helpers.register_menu).
    Always builds a fresh HUD -- see the comment on _layer_picker_hud above
    for why."""
    global _layer_picker_hud
    try:
        result = list_render_dir()
    except Exception as exc:
        print(f"show_layer_picker: list_render_dir failed: {exc}")
        return
    dirs = [e for e in result["entries"] if e["is_dir"]]
    dirs.sort(key=lambda e: e["mtime"], reverse=True)  # freshest first
    layer_names = [e["name"] for e in dirs]
    _layer_picker_hud = _LayerPickerHUD(layer_names)
    _layer_picker_hud.show_near_cursor()
