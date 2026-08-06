#!/usr/bin/env python
"""
nuke_overlay.py

PoC: hotkey-triggered, transparent, frameless overlay (PySide6) that sends
commands straight to the Nuke plugin over raw TCP -- same wire protocol as
raw_ping_nuke.py, no MCP/stdio layer involved. First command wired up:
"print" (see cmd_print in nuke_mcp_plugin.py), just to prove the mechanism:

    global hotkey -> overlay appears near the cursor -> click a button ->
    round-trips to Nuke on pc137 -> message lands in the Script Editor.

LIMITATION: Nuke runs on pc137, reached over RDP -- this overlay runs on
the local machine and has no way to know whether the *remote* Nuke window
currently has focus inside the RDP session. The hotkey is simply always
live while this script is running.

USAGE
    python nuke_overlay.py            # normal mode: waits for the hotkey
    python nuke_overlay.py --test-show  # show the overlay immediately (for
                                         # visual testing/screenshots, skips
                                         # the global hotkey registration)

HOTKEY: ctrl+alt+p (change HOTKEY below if it collides with something)
"""
import sys
import json
import socket
import argparse

from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QCursor, QFont, QPainter, QColor, QPainterPath
from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QLineEdit, QLabel,
)

HOST = "10.10.10.31"
PORT = 9877
HOTKEY = "ctrl+alt+p"


def send_nuke_command(cmd_type: str, payload: dict = None, timeout: float = 5.0) -> dict:
    """Raw newline-delimited JSON round-trip to the Nuke plugin. Same
    framing as nuke_mcp_bridge.NukeConnection.send_command, minimal here
    since the overlay talks to Nuke directly without going through MCP."""
    command = {"type": cmd_type, "payload": payload or {}}
    data_out = (json.dumps(command) + "\n").encode("utf-8")
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout) as s:
            s.sendall(data_out)
            s.settimeout(timeout)
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
            line, _, _ = buf.partition(b"\n")
            return json.loads(line.decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e), "origin": "overlay_client"}


class HotkeySignal(QObject):
    """keyboard's hook fires on its own thread -- bounce the trigger onto
    the Qt main thread via a queued signal instead of touching widgets
    from a non-GUI thread."""
    triggered = Signal()


class Overlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        self.setStyleSheet("""
            QLabel {
                color: rgba(230, 230, 230, 230);
                font-size: 11px;
            }
            QLineEdit {
                background-color: rgba(255, 255, 255, 20);
                color: white;
                border: 1px solid rgba(255, 255, 255, 60);
                border-radius: 6px;
                padding: 6px;
            }
            QPushButton {
                background-color: rgba(70, 130, 220, 210);
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(90, 150, 240, 230);
            }
            QPushButton:pressed {
                background-color: rgba(50, 100, 180, 230);
            }
            #status {
                color: rgba(150, 220, 150, 230);
                font-size: 10px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        title = QLabel("Nuke quick print")
        title.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        layout.addWidget(title)

        self.input = QLineEdit()
        self.input.setPlaceholderText("message...")
        self.input.returnPressed.connect(self.send_print)
        layout.addWidget(self.input)

        btn = QPushButton("Print to Script Editor")
        btn.clicked.connect(self.send_print)
        layout.addWidget(btn)

        self.status = QLabel("")
        self.status.setObjectName("status")
        layout.addWidget(self.status)

        self.resize(260, 130)

    def paintEvent(self, event):
        # Qt's stylesheet background/border-radius doesn't reliably paint
        # on a top-level frameless+translucent QWidget, so draw the panel
        # by hand instead of fighting WA_StyledBackground.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(1, 1, -1, -1), 12, 12)
        painter.fillPath(path, QColor(25, 25, 28, 215))
        painter.setPen(QColor(255, 255, 255, 40))
        painter.drawPath(path)
        super().paintEvent(event)

    def send_print(self):
        message = self.input.text().strip() or "(hello from overlay)"
        self.status.setText("sending...")
        QApplication.processEvents()
        resp = send_nuke_command("print", {"message": message})
        if resp.get("ok"):
            self.status.setText("sent ✓")
            QTimer.singleShot(600, self.hide)
        else:
            self.status.setText(f"error: {resp.get('error', 'unknown')}")

    def show_near_cursor(self):
        pos = QCursor.pos()
        self.move(pos.x() - self.width() // 2, pos.y() - self.height() - 10)
        self.input.clear()
        self.status.setText("")
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def focusOutEvent(self, event):
        self.hide()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(event)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-show", action="store_true",
                         help="show the overlay immediately, skip hotkey registration")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    overlay = Overlay()

    if args.test_show:
        overlay.show_near_cursor()
    else:
        import keyboard  # imported late: not needed/available in --test-show smoke tests
        signal = HotkeySignal()
        signal.triggered.connect(overlay.show_near_cursor)
        keyboard.add_hotkey(HOTKEY, signal.triggered.emit)
        print(f"nuke_overlay: listening for '{HOTKEY}' (Ctrl+C to quit)")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
