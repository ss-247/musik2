"""DeckWidget — waveform · spectrogram · process · transport · info."""

import numpy as np
import soundfile as sf
from PySide6.QtCore import Qt, Signal, QThread, QObject
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy,
    QSplitter, QPushButton, QMenu,
)
from PySide6.QtGui import QAction

from app.waveform import WaveformView
from app.spectrogram import SpectrogramView, detect_pitch
from app.transport import TransportBar
from app.info_panel import InfoPanel
from app.process_panel import ProcessPanel, _ApplyWorker, _BPMWorker
from app.theme import CYAN, MAGENTA, AMBER, TEXT_DIM, CYAN_DIM


class _PitchWorker(QObject):
    done = Signal(object, str)

    def __init__(self, data, sr):
        super().__init__()
        self._data, self._sr = data, sr

    def run(self):
        self.done.emit(*detect_pitch(self._data, self._sr))


class DeckWidget(QWidget):
    """One deck: load → view → modify → route."""

    load_error   = Signal(str)
    # target: None = new deck, or a DeckWidget reference for existing
    send_to_deck = Signal(np.ndarray, int, str, object)

    def __init__(self, name: str = "A", parent=None):
        super().__init__(parent)
        self._name = name
        self._data: np.ndarray | None = None
        self._sr   = 44100
        self._path: str | None = None
        self._pitch_thread: QThread | None = None
        self._apply_thread: QThread | None = None
        self._bpm_thread:   QThread | None = None

        # injected by main window — returns list of (name, DeckWidget)
        self.get_sibling_decks: callable = lambda: []

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

        # ── waveform + spectrogram ───────────────────────────────────────────
        self._waveform     = WaveformView(self)
        self._spectrogram  = SpectrogramView(link_to=self._waveform._left, parent=self)
        for w in (self._waveform, self._spectrogram):
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        vsplit = QSplitter(Qt.Vertical)
        vsplit.setHandleWidth(5)
        vsplit.setStyleSheet("QSplitter::handle{background:#1a3a4a;border-top:1px solid #00f5ff;}")
        vsplit.addWidget(self._waveform)
        vsplit.addWidget(self._spectrogram)
        vsplit.setSizes([200, 200])
        vsplit.setCollapsible(0, False)
        vsplit.setCollapsible(1, False)
        layout.addWidget(vsplit, stretch=1)

        # ── edit bar ────────────────────────────────────────────────────────
        edit_bar = QHBoxLayout()
        edit_bar.setContentsMargins(8, 3, 8, 3)
        edit_bar.setSpacing(6)

        self._btn_reverse = QPushButton("⟵ REVERSE")
        self._btn_reverse.setToolTip("Reverse selection (or whole track)")
        self._btn_reverse.setStyleSheet(f"color:{AMBER}; border-color:{AMBER};")

        self._btn_send = QPushButton("→ DECK ▾")
        self._btn_send.setToolTip("Send selection to a deck (click for menu)")
        self._btn_send.setStyleSheet(f"color:{CYAN}; border-color:{CYAN};")

        self._btn_reverse.clicked.connect(self._on_reverse)
        self._btn_send.clicked.connect(self._on_send_menu)

        edit_bar.addWidget(self._btn_reverse)
        edit_bar.addWidget(self._btn_send)
        edit_bar.addStretch()

        edit_w = QWidget()
        edit_w.setLayout(edit_bar)
        layout.addWidget(edit_w)

        # ── process panel ────────────────────────────────────────────────────
        self._process = ProcessPanel(self)
        layout.addWidget(self._process)

        # ── transport ────────────────────────────────────────────────────────
        self._transport = TransportBar(self)
        layout.addWidget(self._transport)

        # ── info ─────────────────────────────────────────────────────────────
        self._info = InfoPanel(self)
        layout.addWidget(self._info)

        # ── wiring ───────────────────────────────────────────────────────────
        self._waveform.scrub_pos.connect(self._transport.seek)
        self._waveform.scrub_pos.connect(self._spectrogram.set_playhead)
        self._transport.playhead_tick.connect(self._waveform.set_playhead)
        self._transport.playhead_tick.connect(self._spectrogram.set_playhead)

        self._process.apply_requested.connect(self._on_apply)
        self._process.detect_bpm_req.connect(self._on_detect_bpm)
        self._process.preview_sel_req.connect(self._on_preview_sel)

    # ── Public API ────────────────────────────────────────────────────────────

    def load_file(self, path: str):
        try:
            data, sr = sf.read(path, dtype="float32", always_2d=True)
        except Exception as e:
            self.load_error.emit(str(e))
            return
        self._path = path
        fname = path.replace("\\", "/").split("/")[-1]
        self._load(data, sr, fname)

    def load_data(self, data: np.ndarray, sr: int, label: str = "selection"):
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

    # ── Load pipeline ─────────────────────────────────────────────────────────

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

    # ── Background workers ────────────────────────────────────────────────────

    def _bg(self, worker: QObject, thread_attr: str):
        """Move worker to a new QThread, start it, store reference."""
        old = getattr(self, thread_attr, None)
        if old and old.isRunning():
            old.quit(); old.wait(300)
        t = QThread(self)
        worker.moveToThread(t)
        t.started.connect(worker.run)
        t.start()
        setattr(self, thread_attr, t)
        setattr(self, thread_attr + "_worker", worker)

    def _run_pitch_detection(self, data, sr):
        w = _PitchWorker(data, sr)
        w.done.connect(self._info.set_pitch)
        w.done.connect(self.sender().__class__.quit if False else lambda *_: None)
        # simpler: connect quit directly
        self._bg(w, "_pitch_thread")
        w.done.connect(self._pitch_thread.quit)

    def _on_apply(self, pitch: float, stretch: float):
        if self._data is None:
            return
        self._process.set_busy(True)
        w = _ApplyWorker(self._data, self._sr, pitch, stretch)
        w.done.connect(self._on_apply_done)
        w.done.connect(self._apply_thread.quit if self._apply_thread else lambda _: None)
        self._bg(w, "_apply_thread")
        w.done.connect(self._apply_thread.quit)

    def _on_apply_done(self, data: np.ndarray):
        self._process.set_busy(False)
        label = self._file_lbl.text()
        self._load(data, self._sr, label)

    def _on_detect_bpm(self):
        if self._data is None:
            return
        w = _BPMWorker(self._data, self._sr)
        w.done.connect(self._process.set_bpm)
        self._bg(w, "_bpm_thread")
        w.done.connect(self._bpm_thread.quit)

    # ── Edit actions ──────────────────────────────────────────────────────────

    def _on_reverse(self):
        if self._data is None:
            return
        data = self._data.copy()
        sel  = self._waveform.get_selection()
        if sel:
            a, b = sorted(sel)
            s, e = int(a * self._sr), int(b * self._sr)
            data[s:e] = data[s:e][::-1]
        else:
            data = data[::-1]
        self._load(data, self._sr, self._file_lbl.text() + " [rev]")

    def _on_preview_sel(self):
        if self._data is None:
            return
        sel = self._waveform.get_selection()
        if sel:
            a, b = sorted(sel)
            self._transport.play_selection(a, b)

    def _on_send_menu(self):
        if self._data is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet("QMenu{background:#0d0d18;color:#c8e8ff;border:1px solid #1a2a3a;}"
                           "QMenu::item:selected{background:#007a80;color:#000;}")

        new_act = QAction("+ NEW DECK", self)
        new_act.triggered.connect(lambda: self._send_to(None))
        menu.addAction(new_act)
        menu.addSeparator()

        for sibling_name, sibling in self.get_sibling_decks():
            act = QAction(f"DECK  {sibling_name}", self)
            act.triggered.connect(lambda _=False, s=sibling: self._send_to(s))
            menu.addAction(act)

        menu.exec(self._btn_send.mapToGlobal(self._btn_send.rect().bottomLeft()))

    def _send_to(self, target):
        sel = self._waveform.get_selection()
        if sel:
            a, b = sorted(sel)
            s, e = int(a * self._sr), int(b * self._sr)
            chunk = self._data[s:e].copy()
            label = f"{self._name}  {a:.2f}s–{b:.2f}s"
        else:
            chunk = self._data.copy()
            label = f"copy  {self._name}"
        self.send_to_deck.emit(chunk, self._sr, label, target)
