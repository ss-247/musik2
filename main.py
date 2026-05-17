"""musik2 — entry point."""

import sys
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QDockWidget, QPushButton,
)
from PySide6.QtCore import Qt

from app.theme import STYLESHEET
from app.deck import DeckWidget
from app.file_browser import FileBrowserPanel
from app.sample_bin import SampleBinPanel

_DECK_LETTERS = "ABCDEFGHIJKLMNOP"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MUSIK2")
        self.resize(1400, 860)
        self.setMinimumSize(960, 640)

        pg.setConfigOptions(antialias=True, useOpenGL=False)
        self.statusBar().showMessage("ready")

        # ── File browser (left dock) ───────────────────────────────────────
        self._browser = FileBrowserPanel()
        left_dock = QDockWidget("FILE BROWSER", self)
        left_dock.setWidget(self._browser)
        left_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        left_dock.setMinimumWidth(180)
        left_dock.setMaximumWidth(260)
        self.addDockWidget(Qt.LeftDockWidgetArea, left_dock)
        self._browser.file_selected.connect(self._load_into_active_deck)

        # ── Sample Bin (right dock) ────────────────────────────────────────
        self._bin = SampleBinPanel()
        right_dock = QDockWidget("SAMPLE BIN", self)
        right_dock.setWidget(self._bin)
        right_dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        right_dock.setMinimumWidth(200)
        right_dock.setMaximumWidth(300)
        self.addDockWidget(Qt.RightDockWidgetArea, right_dock)
        self._bin.send_to_deck.connect(self._on_send_to_deck)

        # ── Deck tabs ──────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.North)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)

        add_btn = QPushButton("+ DECK")
        add_btn.setFixedHeight(28)
        add_btn.clicked.connect(lambda: self._add_deck())
        self._tabs.setCornerWidget(add_btn, Qt.TopRightCorner)

        self.setCentralWidget(self._tabs)
        self._decks: list[DeckWidget] = []
        self._add_deck()

    # ── Deck management ────────────────────────────────────────────────────

    def _add_deck(self, data=None, sr=None, label=None) -> DeckWidget:
        letter = _DECK_LETTERS[len(self._decks) % len(_DECK_LETTERS)]
        deck = DeckWidget(name=letter)
        deck.load_error.connect(lambda msg: self.statusBar().showMessage(msg, 5000))
        deck.send_to_deck.connect(self._on_send_to_deck)
        deck.send_to_bin.connect(self._bin.add_clip)
        deck.get_sibling_decks = self._siblings_for(deck)
        self._decks.append(deck)
        self._tabs.addTab(deck, f"  DECK {letter}  ")
        self._tabs.setCurrentWidget(deck)
        self._refresh_siblings()
        if data is not None:
            deck.load_data(data, sr, label)
        return deck

    def _siblings_for(self, owner: DeckWidget):
        return lambda: [(d.name, d) for d in self._decks if d is not owner]

    def _refresh_siblings(self):
        for d in self._decks:
            d.get_sibling_decks = self._siblings_for(d)

    def _active_deck(self) -> DeckWidget | None:
        w = self._tabs.currentWidget()
        return w if isinstance(w, DeckWidget) else None

    def _load_into_active_deck(self, path: str):
        deck = self._active_deck() or self._add_deck()
        deck.load_file(path)
        self.statusBar().showMessage(path.replace("\\", "/").split("/")[-1], 3000)

    def _on_send_to_deck(self, data, sr: int, label: str, target):
        if target is None:
            deck = self._add_deck(data, sr, label)
            self.statusBar().showMessage(f"→  DECK {deck.name}", 3000)
        else:
            target.load_data(data, sr, label)
            self._tabs.setCurrentWidget(target)
            self.statusBar().showMessage(f"→  DECK {target.name}", 3000)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("musik2")
    app.setStyleSheet(STYLESHEET)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
