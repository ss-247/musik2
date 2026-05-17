"""Transport bar — play / pause / stop / loop-count + selection-bounds playback."""

import threading
import numpy as np
import sounddevice as sd
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel, QFrame,
)

from app.theme import CYAN, AMBER, GREEN, TEXT_DIM, BORDER, CYAN_DIM

# loop states cycle: off → ×1 → ×2 → ×3 → ∞ → off
_LOOP_STATES = [
    (False, 0,  "↺"),
    (True,  1,  "↺×1"),
    (True,  2,  "↺×2"),
    (True,  3,  "↺×3"),
    (True,  -1, "↺∞"),
]


class TransportBar(QWidget):
    playhead_tick   = Signal(float)   # seconds ~30fps during playback
    playback_ended  = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setFixedHeight(44)

        self._data: np.ndarray | None = None
        self._sr: int = 44100
        self._pos: int = 0
        self._stream: sd.OutputStream | None = None
        self._lock = threading.Lock()

        # loop state
        self._loop_idx:  int = 0          # index into _LOOP_STATES
        self._loop_on:   bool = False
        self._loop_count: int = 0         # -1 = infinite
        self._loops_done: int = 0

        # selection bounds (None = full track)
        self._bound_start: int = 0
        self._bound_end:   int = 0
        self._using_bounds: bool = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        def btn(text, tip, checkable=False, w=32):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.setFixedSize(w, 30)
            return b

        self._btn_rewind = btn("|◄", "Rewind")
        self._btn_play   = btn("►",  "Play / Pause", checkable=True)
        self._btn_stop   = btn("■",  "Stop")
        self._btn_loop   = btn("↺",  "Loop: click to cycle OFF→×1→×2→×3→∞", w=52)
        self._btn_loop.setStyleSheet(f"color:{TEXT_DIM}; border-color:{BORDER};")

        self._btn_rewind.clicked.connect(self._on_rewind)
        self._btn_play.clicked.connect(self._on_play_pause)
        self._btn_stop.clicked.connect(self._on_stop)
        self._btn_loop.clicked.connect(self._on_loop_cycle)

        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"background:{BORDER}; max-width:1px;")

        self._pos_label = QLabel("0:00.00")
        self._pos_label.setObjectName("stat_value")
        self._pos_label.setFixedWidth(70)
        self._pos_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._dur_label = QLabel("/ 0:00.00")
        self._dur_label.setObjectName("stat_key")
        self._dur_label.setFixedWidth(70)

        for w in (self._btn_rewind, self._btn_play, self._btn_stop,
                  sep, self._btn_loop, self._pos_label, self._dur_label):
            layout.addWidget(w)
        layout.addStretch()

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._on_tick)

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self, data: np.ndarray, sr: int):
        self._stop_stream()
        self._data = data
        self._sr = sr
        self._pos = 0
        self._using_bounds = False
        self._bound_start = 0
        self._bound_end = len(data)
        self._btn_play.setChecked(False)
        self._btn_play.setText("►")
        self._dur_label.setText(f"/ {self._fmt(len(data) / sr)}")
        self._pos_label.setText(self._fmt(0))

    def seek(self, seconds: float):
        with self._lock:
            if self._data is not None:
                self._pos = min(int(seconds * self._sr), len(self._data) - 1)
        self._pos_label.setText(self._fmt(seconds))

    def play_selection(self, start_s: float, end_s: float):
        """Play only the selected region (loops if loop is on)."""
        if self._data is None:
            return
        self._stop_stream()
        with self._lock:
            self._bound_start = max(0, int(start_s * self._sr))
            self._bound_end   = min(len(self._data), int(end_s * self._sr))
            self._pos = self._bound_start
            self._using_bounds = True
            self._loops_done = 0
        self._btn_play.setChecked(True)
        self._btn_play.setText("‖")
        self._start_stream()

    def stop_bounds(self):
        """Return to full-track playback mode."""
        with self._lock:
            self._using_bounds = False
            self._bound_start = 0
            self._bound_end = len(self._data) if self._data is not None else 0

    # ── Loop cycling ──────────────────────────────────────────────────────────

    def _on_loop_cycle(self):
        self._loop_idx = (self._loop_idx + 1) % len(_LOOP_STATES)
        on, count, label = _LOOP_STATES[self._loop_idx]
        self._loop_on    = on
        self._loop_count = count
        self._loops_done = 0
        self._btn_loop.setText(label)
        active = on
        self._btn_loop.setStyleSheet(
            f"color:{CYAN}; border-color:{CYAN};" if active
            else f"color:{TEXT_DIM}; border-color:{BORDER};"
        )

    # ── Playback ─────────────────────────────────────────────────────────────

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
            start = self._bound_start if self._using_bounds else 0
            self._pos = start
            self._loops_done = 0
        t = (self._bound_start / self._sr) if self._using_bounds else 0.0
        self._pos_label.setText(self._fmt(t))
        self.playhead_tick.emit(t)

    def _on_rewind(self):
        playing = self._btn_play.isChecked()
        self._on_stop()
        if playing:
            self._btn_play.setChecked(True)
            self._btn_play.setText("‖")
            self._start_stream()

    def _on_tick(self):
        with self._lock:
            pos = self._pos
        if self._data is not None:
            t = pos / self._sr
            self._pos_label.setText(self._fmt(t))
            self.playhead_tick.emit(t)

    # ── Audio callback ────────────────────────────────────────────────────────

    def _audio_callback(self, outdata: np.ndarray, frames: int, time, status):
        with self._lock:
            if self._data is None:
                outdata[:] = 0
                return

            start_f = self._bound_start if self._using_bounds else 0
            end_f   = self._bound_end   if self._using_bounds else len(self._data)
            n_ch    = outdata.shape[1]

            end = self._pos + frames
            if end <= end_f:
                chunk = self._data[self._pos:end]
                self._pos = end
            else:
                before = self._data[self._pos:end_f]
                remaining = frames - len(before)
                loop_infinite = self._loop_on and self._loop_count == -1
                loop_counted  = self._loop_on and self._loop_count > 0 and \
                                 self._loops_done < self._loop_count - 1

                if loop_infinite or loop_counted:
                    if loop_counted:
                        self._loops_done += 1
                    self._pos = start_f + remaining
                    after = self._data[start_f: start_f + remaining]
                    chunk = np.concatenate([before, after])
                else:
                    pad   = np.zeros((remaining,) + self._data.shape[1:],
                                     dtype=self._data.dtype)
                    chunk = np.concatenate([before, pad])
                    self._pos = end_f
                    self._loops_done = 0
                    QTimer.singleShot(0, self._on_playback_ended)

            # shape to output channels
            if chunk.ndim == 1:
                chunk = np.stack([chunk] * n_ch, axis=-1)
            elif chunk.shape[1] < n_ch:
                chunk = np.tile(chunk, (1, n_ch))[:, :n_ch]
            elif chunk.shape[1] > n_ch:
                chunk = chunk[:, :n_ch]

            outdata[:] = chunk.astype(np.float32)

    def _start_stream(self):
        if self._stream and self._stream.active:
            return
        try:
            self._stream = sd.OutputStream(
                samplerate=self._sr, channels=2,
                dtype="float32", callback=self._audio_callback,
            )
            self._stream.start()
            self._timer.start()
        except Exception as e:
            print(f"[transport] {e}")
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
        self._stop_stream()
        self._btn_play.setChecked(False)
        self._btn_play.setText("►")
        self.playback_ended.emit()

    @staticmethod
    def _fmt(seconds: float) -> str:
        m = int(seconds) // 60
        s = seconds - m * 60
        return f"{m}:{s:05.2f}"
