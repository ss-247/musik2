"""Large floating inspection windows for waveform and spectrogram."""

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)
from PySide6.QtGui import QKeySequence, QShortcut

from app.waveform import WaveformView
from app.spectrogram import SpectrogramView
from app.theme import STYLESHEET, CYAN, TEXT_DIM, BORDER


def _tip_bar(title: str, hint: str) -> tuple[QHBoxLayout, QLabel]:
    bar = QHBoxLayout()
    bar.setContentsMargins(8, 4, 8, 4)
    lbl = QLabel(title)
    lbl.setObjectName("title")
    tip = QLabel(hint)
    tip.setObjectName("stat_key")
    bar.addWidget(lbl)
    bar.addStretch()
    bar.addWidget(tip)
    return bar, lbl


class ExpandedWaveform(QDialog):
    """Full-screen-ish waveform — selection propagates back on close."""

    selection_committed = Signal(float, float)

    def __init__(self, data: np.ndarray, sr: int, deck_name: str = "", parent=None):
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint)
        self.setWindowTitle(f"MUSIK2  ·  DECK {deck_name}  —  WAVEFORM")
        self.setModal(False)
        self.setStyleSheet(STYLESHEET)
        self.resize(1400, 480)
        self.setMinimumSize(800, 300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        bar, _ = _tip_bar(
            f"DECK  {deck_name}  —  WAVEFORM",
            "shift+drag  select   ·   scroll  zoom   ·   drag  scrub   ·   ESC  close"
        )
        layout.addLayout(bar)

        self._view = WaveformView(self)
        self._view.load(data, sr)
        layout.addWidget(self._view, stretch=1)

        QShortcut(QKeySequence(Qt.Key_Escape), self, self._commit_and_close)

    def _commit_and_close(self):
        sel = self._view.get_selection()
        if sel:
            self.selection_committed.emit(*sel)
        self.accept()

    def closeEvent(self, ev):
        sel = self._view.get_selection()
        if sel:
            self.selection_committed.emit(*sel)
        super().closeEvent(ev)


class ExpandedSpectrogram(QDialog):
    """Full-screen-ish spectrogram + FFT — scrub to update FFT slice."""

    def __init__(self, data: np.ndarray, sr: int, deck_name: str = "", parent=None):
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint)
        self.setWindowTitle(f"MUSIK2  ·  DECK {deck_name}  —  SPECTROGRAM")
        self.setModal(False)
        self.setStyleSheet(STYLESHEET)
        self.resize(1400, 560)
        self.setMinimumSize(800, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        bar, _ = _tip_bar(
            f"DECK  {deck_name}  —  SPECTROGRAM",
            "scroll  zoom   ·   ESC  close"
        )
        layout.addLayout(bar)

        self._spec = SpectrogramView(parent=self)
        self._spec.load(data, sr)
        layout.addWidget(self._spec, stretch=1)

        QShortcut(QKeySequence(Qt.Key_Escape), self, self.accept)
