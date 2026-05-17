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
from app.loop_scanner import LoopScanWorker, LoopScanDialog
from app.expander import ExpandedWaveform, ExpandedSpectrogram
from app.theme import CYAN, AMBER, TEXT_DIM, BORDER, CYAN_DIM


class _PitchWorker(QObject):
    done = Signal(object, str)

    def __init__(self, data, sr):
        super().__init__()
        self._data, self._sr = data, sr

    def run(self):
        self.done.emit(*detect_pitch(self._data, self._sr))


class DeckWidget(QWidget):
    """One deck: load → view → expand → modify → route → bin."""

    load_error   = Signal(str)
    send_to_deck = Signal(np.ndarray, int, str, object)  # data,sr,label,target
    send_to_bin  = Signal(np.ndarray, int, str)          # data,sr,label

    def __init__(self, name: str = "A", parent=None):
        super().__init__(parent)
        self._name = name
        self._data: np.ndarray | None = None
        self._sr   = 44100
        self._path: str | None = None
        self._pitch_thread: QThread | None = None
        self._apply_thread: QThread | None = None
        self._bpm_thread:   QThread | None = None
        self.get_sibling_decks: callable = lambda: []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 0)
        layout.setSpacing(0)

        # ── header ──────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setContentsMargins(8, 2, 8, 2)
        lbl = QLabel(f"DECK  {name}")
        lbl.setObjectName("title")
        hdr.addWidget(lbl)
        hdr.addStretch()
        self._file_lbl = QLabel("no file loaded")
        self._file_lbl.setObjectName("stat_key")
        self._file_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hdr.addWidget(self._file_lbl)
        layout.addLayout(hdr)

        # ── waveform + spectrogram ───────────────────────────────────────────
        self._waveform    = WaveformView(self)
        self._spectrogram = SpectrogramView(link_to=self._waveform._left, parent=self)
        for w in (self._waveform, self._spectrogram):
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # expand buttons sit in thin strips above each view
        wave_wrap  = self._wrapped(self._waveform,    "WAVEFORM",    self._expand_wave)
        spec_wrap  = self._wrapped(self._spectrogram, "SPECTROGRAM", self._expand_spec)

        vsplit = QSplitter(Qt.Vertical)
        vsplit.setHandleWidth(5)
        vsplit.setStyleSheet("QSplitter::handle{background:#1a3a4a;border-top:1px solid #00f5ff;}")
        vsplit.addWidget(wave_wrap)
        vsplit.addWidget(spec_wrap)
        vsplit.setSizes([200, 200])
        vsplit.setCollapsible(0, False)
        vsplit.setCollapsible(1, False)
        layout.addWidget(vsplit, stretch=1)

        # ── edit bar ────────────────────────────────────────────────────────
        edit = QHBoxLayout()
        edit.setContentsMargins(8, 3, 8, 3)
        edit.setSpacing(6)

        def ebtn(text, tip, color=None):
            b = QPushButton(text)
            b.setToolTip(tip)
            if color:
                b.setStyleSheet(f"color:{color}; border-color:{color};")
            return b

        self._btn_reverse = ebtn("⟵ REVERSE", "Reverse selection or whole track", AMBER)
        self._btn_send    = ebtn("→ DECK ▾",  "Send selection to a deck",          CYAN)
        self._btn_bin     = ebtn("→ BIN",     "Add selection to Sample Bin",        "#b060ff")

        self._btn_reverse.clicked.connect(self._on_reverse)
        self._btn_send.clicked.connect(self._on_send_menu)
        self._btn_bin.clicked.connect(self._on_send_to_bin)

        for b in (self._btn_reverse, self._btn_send, self._btn_bin):
            edit.addWidget(b)
        edit.addStretch()

        edit_w = QWidget()
        edit_w.setLayout(edit)
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
        self._process.scan_loops_req.connect(self._on_scan_loops)

        self._scan_thread: QThread | None = None

    # ── Expand strip helper ───────────────────────────────────────────────────

    def _wrapped(self, widget: QWidget, label: str, expand_fn) -> QWidget:
        """Wrap a view in a QWidget with a thin header strip + ⤢ button."""
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        strip = QHBoxLayout()
        strip.setContentsMargins(6, 1, 4, 1)
        lbl = QLabel(label)
        lbl.setObjectName("stat_key")
        strip.addWidget(lbl)
        strip.addStretch()
        exp_btn = QPushButton("⤢")
        exp_btn.setFixedSize(20, 18)
        exp_btn.setToolTip(f"Open {label} in large floating window")
        exp_btn.setStyleSheet(f"color:{CYAN_DIM}; border:none; padding:0;")
        exp_btn.clicked.connect(expand_fn)
        strip.addWidget(exp_btn)

        strip_w = QWidget()
        strip_w.setLayout(strip)
        strip_w.setFixedHeight(20)
        strip_w.setStyleSheet(f"background:#0d0d18; border-bottom:1px solid {BORDER};")

        vl.addWidget(strip_w)
        vl.addWidget(widget, stretch=1)
        return w

    # ── Public API ────────────────────────────────────────────────────────────

    def load_file(self, path: str):
        try:
            data, sr = sf.read(path, dtype="float32", always_2d=True)
        except Exception as e:
            self.load_error.emit(str(e))
            return
        self._path = path
        self._load(data, sr, path.replace("\\", "/").split("/")[-1])

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

    def _bg(self, worker, attr):
        old = getattr(self, attr, None)
        if old and old.isRunning():
            old.quit(); old.wait(300)
        t = QThread(self)
        worker.moveToThread(t)
        t.started.connect(worker.run)
        t.start()
        setattr(self, attr, t)
        setattr(self, attr + "_worker", worker)
        return t

    def _run_pitch_detection(self, data, sr):
        w = _PitchWorker(data, sr)
        w.done.connect(self._info.set_pitch)
        t = self._bg(w, "_pitch_thread")
        w.done.connect(t.quit)

    def _on_apply(self, pitch: float, stretch: float):
        if self._data is None:
            return
        self._process.set_busy(True)
        w = _ApplyWorker(self._data, self._sr, pitch, stretch)
        w.done.connect(self._on_apply_done)
        t = self._bg(w, "_apply_thread")
        w.done.connect(t.quit)

    def _on_apply_done(self, data):
        self._process.set_busy(False)
        self._load(data, self._sr, self._file_lbl.text())

    def _on_detect_bpm(self):
        if self._data is None:
            return
        w = _BPMWorker(self._data, self._sr)
        w.done.connect(self._process.set_bpm)
        t = self._bg(w, "_bpm_thread")
        w.done.connect(t.quit)

    def _on_scan_loops(self):
        if self._data is None:
            return
        self._process.set_scanning(True)
        w = LoopScanWorker(self._data, self._sr)
        w.done.connect(self._on_scan_done)
        t = self._bg(w, "_scan_thread")
        w.done.connect(t.quit)

    def _on_scan_done(self, results: list):
        self._process.set_scanning(False)
        if not results:
            return
        dlg = LoopScanDialog(results, self._name, parent=self)
        # clicking a row sets the waveform selection 0 → loop_point
        dlg.set_selection.connect(self._waveform.show_selection)
        # → BIN sends data slice to the bin
        dlg.send_to_bin.connect(self._send_loop_to_bin)
        dlg.show()

    def _send_loop_to_bin(self, start_s: float, end_s: float):
        if self._data is None:
            return
        s = int(start_s * self._sr)
        e = int(end_s   * self._sr)
        chunk = self._data[s:e].copy()
        dur = (e - s) / self._sr
        m, sec = int(dur) // 60, dur % 60
        label = f"{self._name}  loop  {end_s:.2f}s  [{m}:{sec:04.1f}]"
        self.send_to_bin.emit(chunk, self._sr, label)

    # ── Expand windows ────────────────────────────────────────────────────────

    def _expand_wave(self):
        if self._data is None:
            return
        win = ExpandedWaveform(self._data, self._sr, self._name, parent=self)
        win.selection_committed.connect(self._waveform.show_selection)
        win.show()

    def _expand_spec(self):
        if self._data is None:
            return
        win = ExpandedSpectrogram(self._data, self._sr, self._name, parent=self)
        win.show()

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
            self._transport.play_selection(*sorted(sel))

    def _on_send_to_bin(self):
        if self._data is None:
            return
        data, label = self._selection_or_all()
        self.send_to_bin.emit(data, self._sr, label)

    def _on_send_menu(self):
        if self._data is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#0d0d18;color:#c8e8ff;border:1px solid #1a2a3a;}"
            "QMenu::item:selected{background:#007a80;color:#000;}"
        )
        new_act = QAction("+ NEW DECK", self)
        new_act.triggered.connect(lambda: self._send_to(None))
        menu.addAction(new_act)
        menu.addSeparator()
        for sname, sdeck in self.get_sibling_decks():
            act = QAction(f"DECK  {sname}", self)
            act.triggered.connect(lambda _=False, d=sdeck: self._send_to(d))
            menu.addAction(act)
        menu.exec(self._btn_send.mapToGlobal(self._btn_send.rect().bottomLeft()))

    def _send_to(self, target):
        data, label = self._selection_or_all()
        self.send_to_deck.emit(data, self._sr, label, target)

    def _selection_or_all(self) -> tuple[np.ndarray, str]:
        sel = self._waveform.get_selection()
        if sel:
            a, b = sorted(sel)
            s, e = int(a * self._sr), int(b * self._sr)
            return self._data[s:e].copy(), f"{self._name}  {a:.2f}s–{b:.2f}s"
        return self._data.copy(), f"copy  {self._name}"
