"""musik2 — entry point."""

import sys
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QDockWidget,
    QPushButton, QWidget, QHBoxLayout, QLabel, QStatusBar,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon

from app.theme import STYLESHEET, CYAN, BG_PANEL
from app.deck import DeckWidget
from app.file_browser import FileBrowserPanel

_DECK_LETTERS = "ABCDEFGHIJKLMNOP"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MUSIK2")
        self.resize(1280, 780)
        self.setMinimumSize(900, 600)

        pg.setConfigOptions(antialias=True, useOpenGL=False)

        # ── Status bar ─────────────────────────────────────────────────────
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("ready")

        # ── File browser dock ──────────────────────────────────────────────
        self._browser = FileBrowserPanel()
        dock = QDockWidget("FILE BROWSER", self)
        dock.setObjectName("browser_dock")
        dock.setWidget(self._browser)
        dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )
        dock.setMinimumWidth(200)
        dock.setMaximumWidth(280)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

        self._browser.file_selected.connect(self._load_into_active_deck)

        # ── Central tab area ───────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.North)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)

        # corner widget: "+ Add Deck" button
        add_btn = QPushButton("+ DECK")
        add_btn.setFixedHeight(28)
        add_btn.setToolTip("Add a new deck")
        add_btn.clicked.connect(self._add_deck)
        self._tabs.setCornerWidget(add_btn, Qt.TopRightCorner)

        self.setCentralWidget(self._tabs)
        self._decks: list[DeckWidget] = []

        # start with one deck
        self._add_deck()

    # ── Deck management ────────────────────────────────────────────────────

    def _add_deck(self) -> "DeckWidget":
        letter = _DECK_LETTERS[len(self._decks) % len(_DECK_LETTERS)]
        deck = DeckWidget(name=letter)
        deck.load_error.connect(lambda msg: self._status.showMessage(msg, 5000))
        deck.send_to_deck.connect(self._receive_from_deck)
        self._decks.append(deck)
        self._tabs.addTab(deck, f"  DECK {letter}  ")
        self._tabs.setCurrentWidget(deck)
        return deck

    def _receive_from_deck(self, data, sr: int, label: str):
        new_deck = self._add_deck()
        new_deck.load_data(data, sr, label)
        self._status.showMessage(f"sent to  DECK {new_deck.name}", 3000)

    def _active_deck(self) -> DeckWidget | None:
        w = self._tabs.currentWidget()
        if isinstance(w, DeckWidget):
            return w
        return None

    def _load_into_active_deck(self, path: str):
        deck = self._active_deck()
        if deck is None:
            self._add_deck()
            deck = self._active_deck()
        deck.load_file(path)
        fname = path.split("\\")[-1].split("/")[-1]
        self._status.showMessage(f"loaded  {fname}", 3000)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("musik2")
    app.setStyleSheet(STYLESHEET)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
