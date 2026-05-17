"""Sample modification panel: pitch shift, time stretch, BPM detection."""

import numpy as np
from PySide6.QtCore import Qt, Signal, QObject, QThread
from PySide6.QtWidgets import (
    QWidget, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QFrame,
)

from app.theme import CYAN, MAGENTA, GREEN, AMBER, TEXT_DIM, BORDER, BG_WIDGET


class _ApplyWorker(QObject):
    done = Signal(np.ndarray)

    def __init__(self, data: np.ndarray, sr: int, pitch: float, stretch: float):
        super().__init__()
        self._data = data
        self._sr   = sr
        self._pitch   = pitch
        self._stretch = stretch

    def run(self):
        import librosa
        sr   = self._sr
        data = self._data

        def proc(ch: np.ndarray) -> np.ndarray:
            y = ch.astype(np.float32)
            if self._pitch != 0.0:
                y = librosa.effects.pitch_shift(y, sr=sr, n_steps=self._pitch)
            if self._stretch != 1.0:
                y = librosa.effects.time_stretch(y, rate=self._stretch)
            return y

        if data.ndim == 1:
            result = proc(data)
        else:
            l = proc(data[:, 0])
            r = proc(data[:, 1])
            n = min(len(l), len(r))
            result = np.stack([l[:n], r[:n]], axis=1)

        self.done.emit(result.astype(np.float32))


class _BPMWorker(QObject):
    done = Signal(float)

    def __init__(self, data: np.ndarray, sr: int):
        super().__init__()
        self._data = data
        self._sr   = sr

    def run(self):
        import librosa
        mono = self._data.mean(axis=1) if self._data.ndim == 2 else self._data
        tempo, _ = librosa.beat.beat_track(y=mono.astype(np.float32), sr=self._sr)
        bpm = float(np.atleast_1d(tempo)[0])
        self.done.emit(bpm)


class ProcessPanel(QWidget):
    """Pitch shift / time stretch / BPM — emits signals, deck does the work."""

    apply_requested   = Signal(float, float)   # pitch_steps, stretch_rate
    detect_bpm_req    = Signal()
    preview_sel_req   = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")

        sep = QFrame(self)
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{BORDER}; max-height:1px;")

        grid = QWidget(self)
        g = QGridLayout(grid)
        g.setContentsMargins(8, 4, 8, 4)
        g.setSpacing(5)
        g.setColumnStretch(1, 1)

        from PySide6.QtWidgets import QVBoxLayout
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(sep)
        outer.addWidget(grid)

        def key(text):
            l = QLabel(text)
            l.setObjectName("stat_key")
            return l

        def val(text, color=CYAN):
            l = QLabel(text)
            l.setObjectName("stat_value")
            l.setStyleSheet(f"color:{color};")
            l.setFixedWidth(58)
            l.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return l

        # ── Pitch ──────────────────────────────────────────────────────────
        g.addWidget(key("PITCH"), 0, 0)
        self._pitch_sl = QSlider(Qt.Horizontal)
        self._pitch_sl.setRange(-24, 24)   # half-semitones → /2 = semitones
        self._pitch_sl.setValue(0)
        self._pitch_sl.setTickPosition(QSlider.TicksBelow)
        self._pitch_sl.setTickInterval(4)
        g.addWidget(self._pitch_sl, 0, 1)
        self._pitch_lbl = val("0.0 st")
        g.addWidget(self._pitch_lbl, 0, 2)

        # ── Stretch ────────────────────────────────────────────────────────
        g.addWidget(key("STRETCH"), 1, 0)
        self._stretch_sl = QSlider(Qt.Horizontal)
        self._stretch_sl.setRange(25, 400)  # /100 = 0.25× – 4.00×
        self._stretch_sl.setValue(100)
        self._stretch_sl.setTickPosition(QSlider.TicksBelow)
        self._stretch_sl.setTickInterval(25)
        g.addWidget(self._stretch_sl, 1, 1)
        self._stretch_lbl = val("1.00×")
        g.addWidget(self._stretch_lbl, 1, 2)

        # ── BPM ───────────────────────────────────────────────────────────
        g.addWidget(key("BPM"), 2, 0)
        self._bpm_lbl = val("—", GREEN)
        self._bpm_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        g.addWidget(self._bpm_lbl, 2, 1)
        self._detect_btn = QPushButton("DETECT")
        self._detect_btn.setFixedSize(70, 24)
        g.addWidget(self._detect_btn, 2, 2)

        # ── Button row ─────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)

        self._preview_btn = QPushButton("▶ SEL")
        self._preview_btn.setToolTip("Preview selection (uses current loop setting)")
        self._preview_btn.setStyleSheet(f"color:{CYAN}; border-color:{CYAN_DIM};")

        self._apply_btn = QPushButton("APPLY")
        self._apply_btn.setToolTip("Apply pitch/stretch to track data (destructive)")
        self._apply_btn.setStyleSheet(f"color:{GREEN}; border-color:{GREEN};")

        self._reset_btn = QPushButton("RESET")
        self._reset_btn.setToolTip("Reset pitch and stretch to default")

        btn_row.addWidget(self._preview_btn)
        btn_row.addWidget(self._apply_btn)
        btn_row.addWidget(self._reset_btn)
        btn_row.addStretch()

        btn_w = QWidget()
        btn_w.setLayout(btn_row)
        g.addWidget(btn_w, 3, 0, 1, 3)

        # ── Connections ────────────────────────────────────────────────────
        self._pitch_sl.valueChanged.connect(
            lambda v: self._pitch_lbl.setText(f"{v/2:+.1f} st"))
        self._stretch_sl.valueChanged.connect(
            lambda v: self._stretch_lbl.setText(f"{v/100:.2f}×"))
        self._apply_btn.clicked.connect(self._on_apply)
        self._reset_btn.clicked.connect(self._on_reset)
        self._detect_btn.clicked.connect(self.detect_bpm_req)
        self._preview_btn.clicked.connect(self.preview_sel_req)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_bpm(self, bpm: float):
        self._bpm_lbl.setText(f"{bpm:.1f}")

    def set_busy(self, busy: bool):
        label = "APPLYING…" if busy else "APPLY"
        self._apply_btn.setText(label)
        self._apply_btn.setEnabled(not busy)

    @property
    def pitch_steps(self) -> float:
        return self._pitch_sl.value() / 2.0

    @property
    def stretch_rate(self) -> float:
        return self._stretch_sl.value() / 100.0

    # ── Internal ──────────────────────────────────────────────────────────────

    def _on_apply(self):
        self.apply_requested.emit(self.pitch_steps, self.stretch_rate)

    def _on_reset(self):
        self._pitch_sl.setValue(0)
        self._stretch_sl.setValue(100)


# keep theme import tidy
from app.theme import CYAN_DIM  # noqa: E402
