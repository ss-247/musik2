"""musik2 — entry point."""

import sys
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QDockWidget,
    QPushButton,
)
from PySide6.QtCore import Qt

from app.theme import STYLESHEET
from app.deck import DeckWidget
from app.file_browser import FileBrowserPanel

_DECK_LETTERS = "ABCDEFGHIJKLMNOP"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MUSIK2")
        self.resize(1280, 820)
        self.setMinimumSize(900, 600)

        pg.setConfigOptions(antialias=True, useOpenGL=False)

        self.statusBar().showMessage("ready")

        # ── File browser dock ──────────────────────────────────────────────
        self._browser = FileBrowserPanel()
        dock = QDockWidget("FILE BROWSER", self)
        dock.setWidget(self._browser)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        dock.setMinimumWidth(190)
        dock.setMaximumWidth(270)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self._browser.file_selected.connect(self._load_into_active_deck)

        # ── Tab area ───────────────────────────────────────────────────────
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
        deck.get_sibling_decks = self._sibling_decks_for(deck)
        self._decks.append(deck)
        self._tabs.addTab(deck, f"  DECK {letter}  ")
        self._tabs.setCurrentWidget(deck)
        # refresh sibling lists in all decks
        self._refresh_sibling_refs()
        if data is not None:
            deck.load_data(data, sr, label)
        return deck

    def _sibling_decks_for(self, owner: DeckWidget):
        """Returns a callable that lists all other decks — re-evaluated at call time."""
        def _get():
            return [(d.name, d) for d in self._decks if d is not owner]
        return _get

    def _refresh_sibling_refs(self):
        for deck in self._decks:
            deck.get_sibling_decks = self._sibling_decks_for(deck)

    def _active_deck(self) -> DeckWidget | None:
        w = self._tabs.currentWidget()
        return w if isinstance(w, DeckWidget) else None

    def _load_into_active_deck(self, path: str):
        deck = self._active_deck() or self._add_deck()
        deck.load_file(path)
        fname = path.replace("\\", "/").split("/")[-1]
        self.statusBar().showMessage(f"loaded  {fname}", 3000)

    def _on_send_to_deck(self, data, sr: int, label: str, target):
        if target is None:
            self._add_deck(data, sr, label)
            self.statusBar().showMessage(f"sent to  DECK {self._decks[-1].name}", 3000)
        else:
            target.load_data(data, sr, label)
            self._tabs.setCurrentWidget(target)
            self.statusBar().showMessage(f"sent to  DECK {target.name}", 3000)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("musik2")
    app.setStyleSheet(STYLESHEET)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
