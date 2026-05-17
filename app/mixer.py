"""Per-clip mixer: independent loop / volume / pan / crossfade per sample."""

import math
import numpy as np
import sounddevice as sd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QSlider, QScrollArea, QFrame, QSizePolicy,
)
from app.theme import CYAN, MAGENTA, GREEN, AMBER, TEXT_DIM, BORDER, BG_WIDGET, BG_PANEL

_LOOP_STATES = ["OFF", "×1", "×2", "×3", "∞"]
_LOOP_COLORS = {"OFF": TEXT_DIM, "×1": CYAN, "×2": CYAN, "×3": CYAN, "∞": AMBER}


# ── Audio engine ──────────────────────────────────────────────────────────────

class _Player:
    """Owns one sounddevice stream for one clip. All setters are GIL-safe."""

    def __init__(self, data: np.ndarray, sr: int):
        if data.ndim == 1:
            data = np.stack([data, data], axis=1)
        elif data.shape[1] == 1:
            data = np.concatenate([data, data], axis=1)
        self._stereo     = data.astype(np.float32)
        self._sr         = sr
        self._pos        = 0
        self._playing    = False
        self._loop_idx   = 0
        self._loop_count = 0
        self._volume     = 0.80
        self._pan        = 0.0   # -1 (L) … +1 (R)
        self._xf_group   = None  # "A", "B", or None
        self._xf_weight  = 0.5   # 0 = A full, 1 = B full
        self._stream: sd.OutputStream | None = None

    def set_volume(self, v: float):     self._volume   = v
    def set_pan(self, p: float):        self._pan      = p
    def set_loop_state(self, idx: int): self._loop_idx = idx; self._loop_count = 0
    def set_xf_group(self, g):          self._xf_group = g
    def set_xf_weight(self, w: float):  self._xf_weight = w

    def play(self):
        self._kill_stream()
        self._pos = 0
        self._loop_count = 0
        self._playing = True
        self._stream = sd.OutputStream(
            samplerate=self._sr, channels=2, dtype="float32",
            callback=self._cb, blocksize=1024,
        )
        self._stream.start()

    def pause(self):
        self._playing = False
        self._kill_stream()

    def stop(self):
        self._playing = False
        self._pos = 0
        self._kill_stream()

    def _kill_stream(self):
        if self._stream:
            try:
                self._stream.abort()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _cb(self, outdata, frames, time_info, status):
        n   = len(self._stereo)
        out = np.zeros((frames, 2), dtype=np.float32)

        if self._playing:
            written = 0
            while written < frames:
                take = min(n - self._pos, frames - written)
                out[written: written + take] = self._stereo[self._pos: self._pos + take]
                self._pos   += take
                written += take

                if self._pos >= n:
                    self._pos = 0
                    loop_state = _LOOP_STATES[self._loop_idx]
                    if loop_state == "∞":
                        pass
                    elif loop_state == "OFF":
                        self._playing = False
                        break
                    else:
                        self._loop_count += 1
                        if self._loop_count >= int(loop_state[1:]):
                            self._playing = False
                            break

        # pan: linear law — no volume at hard pan, no clipping at centre
        pan = max(-1.0, min(1.0, self._pan))
        out[:, 0] *= self._volume * max(0.0, 1.0 - pan)
        out[:, 1] *= self._volume * max(0.0, 1.0 + pan)

        # constant-power crossfade attenuation
        g = self._xf_group
        if g is not None:
            w = max(0.0, min(1.0, self._xf_weight))
            out *= math.cos(w * math.pi / 2) if g == "A" else math.sin(w * math.pi / 2)

        outdata[:] = out


# ── Channel strip ─────────────────────────────────────────────────────────────

class ChannelStrip(QWidget):
    """Vertical mixer strip for one sample clip."""

    def __init__(self, data: np.ndarray, sr: int, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("strip")
        self.setFixedWidth(90)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setStyleSheet(
            f"QWidget#strip{{background:{BG_WIDGET}; border:1px solid {BORDER}; border-radius:3px;}}"
        )
        self._player = _Player(data, sr)

        vl = QVBoxLayout(self)
        vl.setContentsMargins(4, 6, 4, 6)
        vl.setSpacing(4)
        vl.setAlignment(Qt.AlignTop)

        # clip label
        name_lbl = QLabel(label[:14])
        name_lbl.setObjectName("stat_key")
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setWordWrap(True)
        name_lbl.setToolTip(label)
        vl.addWidget(name_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{BORDER}; max-height:1px;")
        vl.addWidget(sep)

        # loop state
        self._loop_idx = 0
        self._loop_btn = QPushButton("OFF")
        self._loop_btn.setFixedHeight(22)
        self._loop_btn.setToolTip("OFF → ×1 → ×2 → ×3 → ∞ → OFF")
        self._loop_btn.setStyleSheet(f"color:{TEXT_DIM}; border-color:{TEXT_DIM};")
        self._loop_btn.clicked.connect(self._cycle_loop)
        vl.addWidget(self._loop_btn)

        # XF group A / B
        xf_row = QHBoxLayout()
        xf_row.setSpacing(2)
        self._xfa = QPushButton("A")
        self._xfb = QPushButton("B")
        for btn, col in ((self._xfa, CYAN), (self._xfb, MAGENTA)):
            btn.setFixedSize(35, 20)
            btn.setCheckable(True)
            btn.setStyleSheet(
                f"color:{col}; border-color:{col};"
                f"QPushButton:checked{{background:{col}; color:#000;}}"
            )
        self._xfa.clicked.connect(lambda: self._set_xf("A"))
        self._xfb.clicked.connect(lambda: self._set_xf("B"))
        xf_row.addWidget(self._xfa)
        xf_row.addWidget(self._xfb)
        vl.addLayout(xf_row)

        # volume (vertical)
        vol_lbl = QLabel("VOL")
        vol_lbl.setObjectName("stat_key")
        vol_lbl.setAlignment(Qt.AlignCenter)
        vl.addWidget(vol_lbl)

        self._vol_sl = QSlider(Qt.Vertical)
        self._vol_sl.setRange(0, 100)
        self._vol_sl.setValue(80)
        self._vol_sl.setFixedHeight(90)
        self._vol_sl.setToolTip("Volume")
        self._vol_sl.valueChanged.connect(lambda v: self._player.set_volume(v / 100))
        vl.addWidget(self._vol_sl, alignment=Qt.AlignHCenter)

        # pan (horizontal)
        pan_lbl = QLabel("PAN")
        pan_lbl.setObjectName("stat_key")
        pan_lbl.setAlignment(Qt.AlignCenter)
        vl.addWidget(pan_lbl)

        self._pan_sl = QSlider(Qt.Horizontal)
        self._pan_sl.setRange(-50, 50)
        self._pan_sl.setValue(0)
        self._pan_sl.setToolTip("Pan  L ←  →  R")
        self._pan_sl.valueChanged.connect(lambda v: self._player.set_pan(v / 50))
        vl.addWidget(self._pan_sl)

        # play / stop
        pb_row = QHBoxLayout()
        pb_row.setSpacing(2)
        self._play_btn = QPushButton("▶")
        self._play_btn.setFixedSize(36, 26)
        self._play_btn.setCheckable(True)
        self._play_btn.setStyleSheet(
            f"color:{GREEN}; border-color:{GREEN};"
            f"QPushButton:checked{{background:{GREEN}; color:#000;}}"
        )
        self._play_btn.clicked.connect(self._on_play)

        stop_btn = QPushButton("■")
        stop_btn.setFixedSize(36, 26)
        stop_btn.clicked.connect(self._on_stop)

        pb_row.addWidget(self._play_btn)
        pb_row.addWidget(stop_btn)
        vl.addLayout(pb_row)

        vl.addStretch()

    # ── Public ────────────────────────────────────────────────────────────────

    def set_xf_weight(self, weight: float):
        self._player.set_xf_weight(weight)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _cycle_loop(self):
        self._loop_idx = (self._loop_idx + 1) % len(_LOOP_STATES)
        state = _LOOP_STATES[self._loop_idx]
        col   = _LOOP_COLORS[state]
        self._loop_btn.setText(state)
        self._loop_btn.setStyleSheet(f"color:{col}; border-color:{col};")
        self._player.set_loop_state(self._loop_idx)

    def _set_xf(self, group: str):
        new_group = None if self._player._xf_group == group else group
        self._player.set_xf_group(new_group)
        self._xfa.setChecked(new_group == "A")
        self._xfb.setChecked(new_group == "B")

    def _on_play(self, checked: bool):
        if checked:
            self._play_btn.setText("⏸")
            self._player.play()
        else:
            self._play_btn.setText("▶")
            self._player.pause()

    def _on_stop(self):
        self._play_btn.setChecked(False)
        self._play_btn.setText("▶")
        self._player.stop()


# ── Mixer panel ───────────────────────────────────────────────────────────────

class MixerPanel(QWidget):
    """Horizontal row of per-clip channel strips + A/B crossfader."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._strips: list[ChannelStrip] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(4)

        # crossfader bar
        xf_row = QHBoxLayout()
        xf_row.setSpacing(8)

        xf_title = QLabel("MIXER")
        xf_title.setObjectName("title")
        xf_row.addWidget(xf_title)

        xf_row.addSpacing(16)
        xf_row.addWidget(QLabel("XF", objectName="stat_key"))

        a_lbl = QLabel("A")
        a_lbl.setStyleSheet(f"color:{CYAN}; font-weight:bold;")
        b_lbl = QLabel("B")
        b_lbl.setStyleSheet(f"color:{MAGENTA}; font-weight:bold;")

        self._xf_sl = QSlider(Qt.Horizontal)
        self._xf_sl.setRange(0, 100)
        self._xf_sl.setValue(50)
        self._xf_sl.setFixedWidth(240)
        self._xf_sl.setToolTip(
            "Crossfader  A ← centre (equal) → B\n"
            "Assign strips to A or B groups using the A/B buttons on each strip."
        )
        self._xf_sl.valueChanged.connect(self._on_xf)

        xf_row.addWidget(a_lbl)
        xf_row.addWidget(self._xf_sl)
        xf_row.addWidget(b_lbl)
        xf_row.addStretch()

        hint = QLabel("add clips to Sample Bin → they appear here automatically")
        hint.setObjectName("stat_key")
        xf_row.addWidget(hint)

        xf_w = QWidget()
        xf_w.setLayout(xf_row)
        xf_w.setStyleSheet(f"background:{BG_PANEL};")
        outer.addWidget(xf_w)

        # scrollable strip area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea{{border:none; background:{BG_PANEL};}}")

        self._container = QWidget()
        self._container.setStyleSheet(f"background:{BG_PANEL};")
        self._hl = QHBoxLayout(self._container)
        self._hl.setContentsMargins(4, 4, 4, 4)
        self._hl.setSpacing(6)
        self._hl.addStretch()

        scroll.setWidget(self._container)
        outer.addWidget(scroll, stretch=1)

    # ── Public API ────────────────────────────────────────────────────────────

    def add_clip(self, data: np.ndarray, sr: int, label: str):
        strip = ChannelStrip(data, sr, label, self)
        strip.set_xf_weight(self._xf_sl.value() / 100)
        self._strips.append(strip)
        self._hl.insertWidget(self._hl.count() - 1, strip)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _on_xf(self, val: int):
        w = val / 100.0
        for s in self._strips:
            s.set_xf_weight(w)
