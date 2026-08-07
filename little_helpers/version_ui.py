"""
little_helpers.version_ui

Function 2 HUD (Shift+E): Latest/+/- buttons plus a History checkbox and a
status panel, over whatever _versions._working_read_nodes() resolves to.
"""

try:
    from PySide6 import QtWidgets, QtCore, QtGui
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui

from .layer_branch import _available_versions
from .versions import (
    _HISTORY_ENABLED,
    _is_live_read,
    _parse_read_file,
    _read_status,
    _set_history_enabled,
    _working_read_nodes,
    bump_selected_reads,
)

_version_hud = None  # rebuilt fresh every open, same reasoning as
                     # layer_picker_ui._layer_picker_hud above.


class _VersionHUD(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)

        self.setStyleSheet("""
            QLabel { color: rgba(230, 230, 230, 230); font-size: 11px; }
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
            #info { color: rgba(180, 180, 180, 200); font-size: 10px; }
            QCheckBox { color: rgba(230, 230, 230, 230); font-size: 11px; }
            #version { font-size: 18px; font-weight: 700; }
        """)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Change version")
        title.setFont(QtGui.QFont("Segoe UI", 9, QtGui.QFont.DemiBold))
        header.addWidget(title)
        header.addStretch()
        # Big, plain-sight readout of the selected Read(s)' current version
        # dir (e.g. "v014") -- per Sashok's ask, so the HUD itself answers
        # "which version am I on" without reading node names off the DAG.
        self.version_label = QtWidgets.QLabel("")
        self.version_label.setObjectName("version")
        header.addWidget(self.version_label)
        layout.addLayout(header)

        for label, direction in (
            ("Latest version", "latest"),
            ("Version +", "up"),
            ("Version -", "down"),
        ):
            btn = QtWidgets.QPushButton(label)
            btn.setFocusPolicy(QtCore.Qt.NoFocus)
            btn.clicked.connect(lambda checked=False, d=direction: self._on_bump_clicked(d))
            layout.addWidget(btn)

        # History checkbox -- checked keeps the row of old-version Read
        # nodes next to the live one (see versions._HISTORY_COUNTS) in
        # sync; unchecked removes whatever history Reads already exist for
        # the current working set and stops new ones from being created on
        # future bumps. Reflects the reload-safe versions._HISTORY_ENABLED
        # global so it stays correct across HUD re-opens, not just this
        # instance.
        self.history_cb = QtWidgets.QCheckBox("History")
        self.history_cb.setFocusPolicy(QtCore.Qt.NoFocus)
        self.history_cb.setToolTip("Тримати ріди попередніх версій")
        self.history_cb.setChecked(_HISTORY_ENABLED)
        self.history_cb.toggled.connect(self._on_history_toggled)
        layout.addWidget(self.history_cb)

        # Status panel -- outdated-version / missing-frames / shot-range-
        # incomplete flags for the current selection (see versions._read_status).
        # Was reserved empty per Sashok's original "just leave room for
        # it" ask; now wired.
        self.info = QtWidgets.QLabel("")
        self.info.setObjectName("info")
        self.info.setMinimumHeight(28)
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        self.setFixedWidth(220)  # keep the HUD's width; height grows to
        # fit however many selected Reads have something to report
        self._refresh_info()  # show current-selection status immediately on open

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
        # focusOutEvent alone isn't reliable here: this is a Qt.Tool
        # widget, and clicking the DAG (part of the same main-window focus
        # chain) doesn't reliably fire a focus-out on us the way a normal
        # top-level window losing activation would -- this HUD stayed open
        # after clicking away, confirmed by Sashok. An app-wide mouse
        # event filter, closing on any press outside our own rect, works
        # regardless of Nuke's/RDP's focus quirks (RDP hit-testing on
        # frameless/translucent Qt windows has a history of exactly this
        # kind of quirk -- every button in this HUD sets NoFocus for the
        # same reason).
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
        if event.key() == QtCore.Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)

    def _on_bump_clicked(self, direction):
        bump_selected_reads(direction)
        self._refresh_info()

    def _on_history_toggled(self, checked):
        _set_history_enabled(checked)
        self._refresh_info()

    def _refresh_info(self):
        """Recompute + display status for the current Nuke selection (same
        selectedNodes()->Read filter bump_selected_reads uses). Runs on
        HUD open and again after every button click, so this never shows
        a stale snapshot from before the last bump. Full per-node detail
        always goes to the Script Editor too -- same convention
        bump_selected_reads already uses -- this label stays compact
        since the HUD is only 220px wide."""
        # Same working-set + "live only" logic as bump_selected_reads --
        # falls back to nodes-in-view when nothing's selected, and a
        # selected/visible history Read (no downstream connections) isn't
        # something this HUD manages, so it shouldn't show up as "needs
        # attention" either.
        reads = [n for n in _working_read_nodes() if _is_live_read(n)]
        version_text, version_outdated = self._current_version_text(reads)
        self.version_label.setText(version_text)
        self.version_label.setStyleSheet(
            "color: #9A9A9A;" if version_outdated else "color: #57C25E;"
        )
        if not reads:
            self.info.setStyleSheet("")  # neutral -- falls back to the #info QSS
            self.info.setText("No live Read selected")
            self._resize_to_content()
            return

        # Short tags only in the label -- full detail (latest version,
        # exact missing-frame count, exact range) still goes to the
        # Script Editor, same split bump_selected_reads already uses.
        # Keeps the HUD itself scannable at a glance instead of a wall of
        # text.
        lines = []
        for read in reads:
            status = _read_status(read)
            if status is None:
                continue
            tags = []
            if status["outdated"]:
                tags.append("outdated")
            if status["missing"]:
                tags.append("gaps")
            if status["incomplete"]:
                tags.append("short range")
            if tags:
                lines.append(f"{read.name()}: {', '.join(tags)}")
                r0, r1 = status["root_range"]
                print(f"_VersionHUD: {read.name()} ({status['pass_name']}, "
                      f"{status['current_version']}) -- outdated={status['outdated']} "
                      f"(latest {status['latest_version']}), missing={status['missing']}, "
                      f"range={status['seq']['first']}-{status['seq']['last']} vs shot {r0}-{r1}")

        if not lines:
            self.info.setStyleSheet("color: #57C25E;")  # green -- all clear
            self.info.setText("OK")
        else:
            self.info.setStyleSheet("color: #E2554A;")  # red -- needs attention
            shown = lines[:4]
            more = "\n..." if len(lines) > 4 else ""
            self.info.setText("\n".join(shown) + more)
        self._resize_to_content()

    def _current_version_text(self, reads):
        """Version dir (e.g. "v014") of the selected live Read(s), for the
        header readout, plus whether any of them is behind the latest
        version available on disk for its own pass. Empty selection ->
        blank/not-outdated. Selection spanning more than one version (the
        4 layer-branch passes routinely aren't lock-step, per
        docs/NUKE_COMP_LAYER_ASSEMBLY.md) -> "mixed" rather than picking
        one arbitrarily. Unlike versions._read_status's "outdated" flag
        (beauty only, by design -- see its docstring), this checks every
        pass against its own latest: the header number should read gray
        whenever *what's on screen* isn't the newest of that same pass,
        regardless of which pass it is."""
        versions = set()
        outdated = False
        for read in reads:
            parsed = _parse_read_file(read["file"].value())
            if parsed is None:
                continue
            layer_dir, current_version, pass_name = parsed
            versions.add(current_version)
            avail = _available_versions(layer_dir, pass_name)
            if avail and avail[-1][1] != current_version:
                outdated = True
        if not versions:
            return "", False
        if len(versions) == 1:
            return next(iter(versions)), outdated
        return "mixed", outdated

    def _resize_to_content(self):
        self.info.adjustSize()
        self.adjustSize()


def show_version_hud():
    """Triggered by the Nuke-side hotkey (see little_helpers.register_menu).
    Stays open after a button click (unlike show_layer_picker) so +/- can
    be pressed repeatedly to step through versions -- closes on Esc or a
    click anywhere outside the HUD itself (see eventFilter above)."""
    global _version_hud
    _version_hud = _VersionHUD()
    _version_hud.show_near_cursor()
