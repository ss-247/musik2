"""DeckWidget — composes waveform view, spectrogram, transport, and info panel."""

import numpy as np
import soundfile as sf
from PySide6.QtCore import Qt, Signal, QThread, QObject
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy,
    QSplitter, QPushButton,
)

from app.waveform import WaveformView
from app.spectrogram import SpectrogramView, detect_pitch
from app.transport import TransportBar
from app.info_panel import InfoPanel
from app.theme import CYAN, MAGENTA, AMBER


class _PitchWorker(QObject):
    done = Signal(object, str)  # (hz_or_None, note_str)

    def __init__(self, data, sr):
        super().__init__()
        self._data = data
        self._sr = sr

    def run(self):
        self.done.emit(*detect_pitch(self._data, self._sr))


class DeckWidget(QWidget):
    """A self-contained audio deck: load → view → play → edit → send."""

    load_error   = Signal(str)
    send_to_deck = Signal(np.ndarray, int, str)  # data, sr, label

    def __init__(self, name: str = "A", parent=None):
        super().__init__(parent)
        self._name = name
        self._data: np.ndarray | None = None
        self._sr: int = 44100
        self._path: str | None = None
        self._pitch_thread: QThread | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 0)
        layout.setSpacing(0)

        # ── header ──────────────────────────────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(8, 2, 8, 2)
        lbl = QLabel(f"DECK  {name}")
        lbl.setObjectName("title")
        header.addWidget(lbl)
        header.addStretch()
        self._file_lbl = QLabel("no file loaded")
        self._file_lbl.setObjectName("stat_key")
        self._file_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addWidget(self._file_lbl)
        layout.addLayout(header)

        # ── waveform + spectrogram splitter ──────────────────────────────────
        self._waveform = WaveformView(self)
        self._waveform.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._spectrogram = SpectrogramView(link_to=self._waveform._left, parent=self)
        self._spectrogram.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        vsplit = QSplitter(Qt.Vertical)
        vsplit.setHandleWidth(5)
        vsplit.setStyleSheet("QSplitter::handle { background: #1a3a4a; border-top: 1px solid #00f5ff; }")
        vsplit.addWidget(self._waveform)
        vsplit.addWidget(self._spectrogram)
        vsplit.setSizes([200, 200])
        vsplit.setCollapsible(0, False)
        vsplit.setCollapsible(1, False)
        layout.addWidget(vsplit, stretch=1)

        # ── edit bar (Increment 3) ───────────────────────────────────────────
        edit_bar = QHBoxLayout()
        edit_bar.setContentsMargins(8, 3, 8, 3)
        edit_bar.setSpacing(6)

        self._btn_reverse  = QPushButton("⟵ REVERSE")
        self._btn_send     = QPushButton("→ NEW DECK")
        self._btn_reverse.setToolTip("Reverse selection (or whole track if no selection)")
        self._btn_send.setToolTip("Copy selection to a new deck (whole track if no selection)")
        self._btn_reverse.setStyleSheet(f"color: {AMBER}; border-color: {AMBER};")
        self._btn_send.setStyleSheet(f"color: {CYAN}; border-color: {CYAN};")

        self._btn_reverse.clicked.connect(self._on_reverse)
        self._btn_send.clicked.connect(self._on_send_to_deck)

        edit_bar.addWidget(self._btn_reverse)
        edit_bar.addWidget(self._btn_send)
        edit_bar.addStretch()

        edit_w = QWidget()
        edit_w.setLayout(edit_bar)
        layout.addWidget(edit_w)

        # ── transport ────────────────────────────────────────────────────────
        self._transport = TransportBar(self)
        layout.addWidget(self._transport)

        # ── info panel ───────────────────────────────────────────────────────
        self._info = InfoPanel(self)
        layout.addWidget(self._info)

        # ── signal wiring ────────────────────────────────────────────────────
        self._waveform.scrub_pos.connect(self._transport.seek)
        self._waveform.scrub_pos.connect(self._spectrogram.set_playhead)
        self._transport.playhead_tick.connect(self._waveform.set_playhead)
        self._transport.playhead_tick.connect(self._spectrogram.set_playhead)

    # ── Public API ────────────────────────────────────────────────────────────

    def load_file(self, path: str):
        try:
            data, sr = sf.read(path, dtype="float32", always_2d=True)
        except Exception as e:
            self.load_error.emit(f"Cannot load {path}: {e}")
            return
        fname = path.split("\\")[-1].split("/")[-1]
        self._path = path
        self._load(data, sr, fname)

    def load_data(self, data: np.ndarray, sr: int, label: str = "selection"):
        """Load from raw numpy array (no file path)."""
        self._path = None
        self._load(data, sr, label)

    @property
    def name(self) -> str:
        return self._name

    @property
    def data(self) -> np.ndarray | None:
        return self._data

    @property
    def sr(self) -> int:
        return self._sr

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load(self, data: np.ndarray, sr: int, label: str):
        self._data = data
        self._sr   = sr
        self._file_lbl.setText(label[:50])
        self._waveform.load(data, sr)
        self._spectrogram.load(data, sr)
        self._transport.load(data, sr)
        if self._path:
            self._info.load(self._path, data, sr)
        else:
            self._info.load_data(data, sr, label)
        self._run_pitch_detection(data, sr)

    def _run_pitch_detection(self, data: np.ndarray, sr: int):
        if self._pitch_thread and self._pitch_thread.isRunning():
            self._pitch_thread.quit()
            self._pitch_thread.wait(500)
        worker = _PitchWorker(data, sr)
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.done.connect(self._info.set_pitch)
        worker.done.connect(thread.quit)
        thread.started.connect(worker.run)
        thread.start()
        self._pitch_thread = thread
        self._pitch_worker = worker

    # ── Edit actions ──────────────────────────────────────────────────────────

    def _on_reverse(self):
        if self._data is None:
            return
        sel = self._waveform.get_selection()
        data = self._data.copy()
        if sel:
            a, b = sorted(sel)
            s, e = int(a * self._sr), int(b * self._sr)
            data[s:e] = data[s:e][::-1]
        else:
            data = data[::-1]
        self._load(data, self._sr, self._file_lbl.text() + " [rev]")

    def _on_send_to_deck(self):
        if self._data is None:
            return
        sel = self._waveform.get_selection()
        if sel:
            a, b = sorted(sel)
            s, e = int(a * self._sr), int(b * self._sr)
            chunk = self._data[s:e].copy()
            label = f"{self._name}  {a:.2f}s – {b:.2f}s"
        else:
            chunk = self._data.copy()
            label = f"copy  {self._name}"
        self.send_to_deck.emit(chunk, self._sr, label)
