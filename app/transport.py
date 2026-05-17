"""Transport bar — play / pause / stop / loop with sounddevice playback."""

import threading
import numpy as np
import sounddevice as sd
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel, QFrame, QSizePolicy,
)

from app.theme import CYAN, AMBER, GREEN, TEXT_DIM, BORDER, BG_PANEL


class TransportBar(QWidget):
    """Playback controls for a single deck."""

    playhead_tick = Signal(float)   # seconds — emitted ~30 fps during playback
    playback_ended = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setFixedHeight(44)

        self._data: np.ndarray | None = None
        self._sr: int = 44100
        self._pos: int = 0        # current frame index
        self._loop: bool = False
        self._stream: sd.OutputStream | None = None
        self._lock = threading.Lock()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"background:{BORDER}; max-width:1px;")

        def btn(text, tooltip, checkable=False):
            b = QPushButton(text)
            b.setToolTip(tooltip)
            b.setCheckable(checkable)
            b.setFixedSize(32, 30)
            return b

        self._btn_rewind = btn("|◄", "Rewind to start")
        self._btn_play   = btn("►",  "Play / Pause", checkable=True)
        self._btn_stop   = btn("■",  "Stop")
        self._btn_loop   = btn("↺",  "Toggle loop", checkable=True)

        self._btn_rewind.clicked.connect(self._on_rewind)
        self._btn_play.clicked.connect(self._on_play_pause)
        self._btn_stop.clicked.connect(self._on_stop)
        self._btn_loop.toggled.connect(self._on_loop)

        self._pos_label = QLabel("0:00.00")
        self._pos_label.setObjectName("stat_value")
        self._pos_label.setFixedWidth(70)
        self._pos_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._dur_label = QLabel("/ 0:00.00")
        self._dur_label.setObjectName("stat_key")
        self._dur_label.setFixedWidth(70)

        for w in (self._btn_rewind, self._btn_play, self._btn_stop, sep,
                  self._btn_loop, self._pos_label, self._dur_label):
            layout.addWidget(w)
        layout.addStretch()

        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30 fps
        self._timer.timeout.connect(self._on_tick)

    # ── Public API ───────────────────────────────────────────────────────────

    def load(self, data: np.ndarray, sr: int):
        self._stop_stream()
        self._data = data
        self._sr = sr
        self._pos = 0
        self._btn_play.setChecked(False)
        self._btn_play.setText("►")
        dur = self._fmt(len(data) / sr)
        self._dur_label.setText(f"/ {dur}")
        self._pos_label.setText(self._fmt(0))

    def seek(self, seconds: float):
        with self._lock:
            if self._data is not None:
                self._pos = min(int(seconds * self._sr), len(self._data) - 1)
        self._pos_label.setText(self._fmt(seconds))

    # ── Slots ────────────────────────────────────────────────────────────────

    def _on_play_pause(self):
        if self._data is None:
            self._btn_play.setChecked(False)
            return
        if self._btn_play.isChecked():
            self._btn_play.setText("‖")
            self._start_stream()
        else:
            self._btn_play.setText("►")
            self._pause_stream()

    def _on_stop(self):
        self._stop_stream()
        self._btn_play.setChecked(False)
        self._btn_play.setText("►")
        with self._lock:
            self._pos = 0
        self._pos_label.setText(self._fmt(0))
        self.playhead_tick.emit(0)

    def _on_rewind(self):
        playing = self._btn_play.isChecked()
        self._on_stop()
        if playing:
            self._btn_play.setChecked(True)
            self._btn_play.setText("‖")
            self._start_stream()

    def _on_loop(self, checked: bool):
        self._loop = checked

    def _on_tick(self):
        with self._lock:
            pos = self._pos
        if self._data is not None and self._sr > 0:
            t = pos / self._sr
            self._pos_label.setText(self._fmt(t))
            self.playhead_tick.emit(t)

    # ── Stream management ────────────────────────────────────────────────────

    def _audio_callback(self, outdata: np.ndarray, frames: int, time, status):
        with self._lock:
            if self._data is None:
                outdata[:] = 0
                return

            n_ch = outdata.shape[1] if outdata.ndim > 1 else 1
            end = self._pos + frames
            chunk = self._data[self._pos:end]

            if len(chunk) < frames:
                if self._loop:
                    needed = frames - len(chunk)
                    chunk = np.concatenate([chunk, self._data[:needed]])
                    self._pos = needed
                else:
                    pad = np.zeros((frames - len(chunk),) + self._data.shape[1:],
                                   dtype=self._data.dtype)
                    chunk = np.concatenate([chunk, pad])
                    self._pos = len(self._data)
                    # signal end on main thread
                    QTimer.singleShot(0, self._on_playback_ended)
            else:
                self._pos = end

            # match channel count
            if chunk.ndim == 1:
                chunk = np.stack([chunk] * n_ch, axis=-1)
            elif chunk.shape[1] < n_ch:
                chunk = np.tile(chunk, (1, n_ch))[:, :n_ch]
            elif chunk.shape[1] > n_ch:
                chunk = chunk[:, :n_ch]

            outdata[:] = chunk.astype(np.float32)

    def _start_stream(self):
        if self._stream is not None and self._stream.active:
            return
        try:
            self._stream = sd.OutputStream(
                samplerate=self._sr,
                channels=2,
                dtype="float32",
                callback=self._audio_callback,
            )
            self._stream.start()
            self._timer.start()
        except Exception as e:
            print(f"[transport] audio stream error: {e}")
            self._btn_play.setChecked(False)
            self._btn_play.setText("►")

    def _pause_stream(self):
        if self._stream and self._stream.active:
            self._stream.stop()
        self._timer.stop()

    def _stop_stream(self):
        self._timer.stop()
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _on_playback_ended(self):
        if not self._loop:
            self._stop_stream()
            self._btn_play.setChecked(False)
            self._btn_play.setText("►")
            self.playback_ended.emit()

    @staticmethod
    def _fmt(seconds: float) -> str:
        m = int(seconds) // 60
        s = seconds - m * 60
        return f"{m}:{s:05.2f}"
