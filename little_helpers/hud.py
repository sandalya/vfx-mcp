"""
little_helpers.hud

Shared HUD widget(s) used by the product tools. Do not "improve" the Qt
code here -- it carries hard-won RDP-specific workarounds (no
WA_TranslucentBackground, setMask() silhouettes, NoFocus on every child).
"""

try:
    from PySide6 import QtWidgets, QtCore, QtGui
except ImportError:
    from PySide2 import QtWidgets, QtCore, QtGui


class _WheelPicker(QtWidgets.QWidget):
    """Vertical phone-timer-style picker: the centered row is the current
    selection, rows above/below shrink and fade with distance. Moves in
    whole-item steps only, no drag/momentum -- matches the rest of this
    file's click-and-keyboard-first interaction style (drag-based UI has
    a history of being unreliable over RDP here, see the eventFilter/
    focus comments elsewhere in this file). Confirm via the `activated`
    signal (Enter or double-click) -- scrolling alone only browses."""

    ROW_HEIGHT = 26
    VISIBLE_ROWS = 5  # odd, so there's a true center row

    activated = QtCore.Signal(str)

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self._items = list(items)
        self._index = 0
        self.setFixedHeight(self.ROW_HEIGHT * self.VISIBLE_ROWS)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

    def current_name(self):
        return self._items[self._index] if self._items else None

    def set_current(self, name):
        if name in self._items:
            self._index = self._items.index(name)
            self.update()

    def _step(self, delta):
        if not self._items:
            return
        self._index = max(0, min(len(self._items) - 1, self._index + delta))
        self.update()

    def wheelEvent(self, event):
        self._step(-1 if event.angleDelta().y() > 0 else 1)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Up:
            self._step(-1)
        elif event.key() == QtCore.Qt.Key_Down:
            self._step(1)
        elif event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if self.current_name() is not None:
                self.activated.emit(self.current_name())
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        # Tapping any visible row (not just the centered one) jumps
        # straight to it -- the shortcut real wheel pickers give you
        # instead of forcing one scroll step per row.
        try:
            y = event.position().y()  # Qt6/PySide6
        except AttributeError:
            y = event.y()  # Qt5/PySide2
        row_under_cursor = int(y // self.ROW_HEIGHT)
        self._step(row_under_cursor - self.VISIBLE_ROWS // 2)

    def mouseDoubleClickEvent(self, event):
        if self.current_name() is not None:
            self.activated.emit(self.current_name())

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        center_row = self.VISIBLE_ROWS // 2

        band = QtGui.QPainterPath()
        band.addRoundedRect(
            QtCore.QRectF(4, center_row * self.ROW_HEIGHT, self.width() - 8, self.ROW_HEIGHT), 6, 6
        )
        painter.fillPath(band, QtGui.QColor(70, 130, 220, 90))

        for row in range(self.VISIBLE_ROWS):
            item_index = self._index + (row - center_row)
            if not (0 <= item_index < len(self._items)):
                continue
            distance = abs(row - center_row)
            alpha = max(60, 230 - distance * 70)
            point_size = 11 if distance == 0 else max(8, 11 - distance * 2)
            font = QtGui.QFont("Segoe UI", point_size)
            font.setWeight(QtGui.QFont.DemiBold if distance == 0 else QtGui.QFont.Normal)
            painter.setFont(font)
            painter.setPen(QtGui.QColor(230, 230, 230, alpha))
            rect = QtCore.QRectF(0, row * self.ROW_HEIGHT, self.width(), self.ROW_HEIGHT)
            painter.drawText(rect, QtCore.Qt.AlignCenter, self._items[item_index])
        super().paintEvent(event)
