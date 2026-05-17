"""Metadata and per-channel stats panel."""

import math
import numpy as np
import soundfile as sf
from PySide6.QtWidgets import (
    QWidget, QGridLayout, QLabel, QFrame, QVBoxLayout, QSizePolicy,
)
from PySide6.QtCore import Qt

from app.theme import CYAN, MAGENTA, GREEN, TEXT_DIM, BORDER


def _dbfs(data: np.ndarray) -> str:
    peak = np.max(np.abs(data))
    if peak == 0:
        return "-inf dBFS"
    return f"{20 * math.log10(peak):.1f} dBFS"


def _rms(data: np.ndarray) -> str:
    r = math.sqrt(np.mean(data.astype(float) ** 2))
    if r == 0:
        return "-inf dBFS"
    return f"{20 * math.log10(r):.1f} dBFS"


def _fmt_duration(seconds: float) -> str:
    m = int(seconds) // 60
    s = seconds - m * 60
    return f"{m}:{s:05.2f}"


class _StatRow(QWidget):
    def __init__(self, key: str, value: str = "—", color: str = CYAN, parent=None):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setColumnStretch(1, 1)

        self._key_lbl = QLabel(key.upper())
        self._key_lbl.setObjectName("stat_key")
        self._val_lbl = QLabel(value)
        self._val_lbl.setObjectName("stat_value")
        self._val_lbl.setStyleSheet(f"color: {color};")
        self._val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout.addWidget(self._key_lbl, 0, 0)
        layout.addWidget(self._val_lbl, 0, 1)

    def set_value(self, v: str):
        self._val_lbl.setText(v)


class InfoPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"background:{BORDER}; max-height:1px;")
        outer.addWidget(sep)

        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(8, 4, 8, 4)
        grid.setVerticalSpacing(2)
        grid.setHorizontalSpacing(16)
        outer.addWidget(grid_w)

        def row(label, color=CYAN):
            r = _StatRow(label, color=color)
            return r

        self._file    = row("file")
        self._fmt     = row("format")
        self._sr      = row("sample rate")
        self._bits    = row("bit depth")
        self._dur     = row("duration")
        self._ch      = row("channels")
        self._brate   = row("est. bitrate")
        self._l_peak  = row("L peak",  CYAN)
        self._r_peak  = row("R peak",  MAGENTA)
        self._l_rms   = row("L RMS",   CYAN)
        self._r_rms   = row("R RMS",   MAGENTA)
        self._pitch   = row("pitch",   GREEN)
        self._key     = row("key",     GREEN)

        rows_col0 = [self._file, self._fmt, self._sr, self._bits, self._dur, self._brate]
        rows_col1 = [self._ch, self._l_peak, self._r_peak, self._l_rms, self._r_rms,
                     self._pitch, self._key]

        for i, w in enumerate(rows_col0):
            grid.addWidget(w, i, 0)
        for i, w in enumerate(rows_col1):
            grid.addWidget(w, i, 1)

    def load(self, path: str, data: np.ndarray, sr: int):
        info = sf.info(path)
        n_frames = len(data)
        duration = n_frames / sr

        file_name = path.split("\\")[-1].split("/")[-1]
        self._file.set_value(file_name[:40])
        self._fmt.set_value(f"{info.format} / {info.subtype}")
        self._sr.set_value(f"{sr:,} Hz")

        # bit depth from subtype string e.g. "PCM_24" → 24
        subtype = info.subtype
        bits = "—"
        for part in subtype.split("_"):
            if part.isdigit():
                bits = f"{part}-bit"
                break
        self._bits.set_value(bits)
        self._dur.set_value(_fmt_duration(duration))
        self._ch.set_value("Stereo" if data.ndim == 2 and data.shape[1] == 2 else "Mono")

        # estimated bitrate (file size / duration)
        try:
            import os
            size_bytes = os.path.getsize(path)
            kbps = (size_bytes * 8) / (duration * 1000)
            self._brate.set_value(f"{kbps:.0f} kbps")
        except Exception:
            self._brate.set_value("—")

        if data.ndim == 1:
            left = right = data.astype(float)
        else:
            left  = data[:, 0].astype(float)
            right = data[:, 1].astype(float)

        self._l_peak.set_value(_dbfs(left))
        self._r_peak.set_value(_dbfs(right))
        self._l_rms.set_value(_rms(left))
        self._r_rms.set_value(_rms(right))

        self._pitch.set_value("detecting…")
        self._key.set_value("…")

    def load_data(self, data: np.ndarray, sr: int, label: str):
        """Populate panel from raw numpy data (no file path)."""
        duration = len(data) / sr
        self._file.set_value(label[:40])
        self._fmt.set_value("float32 (in-memory)")
        self._sr.set_value(f"{sr:,} Hz")
        self._bits.set_value("32-bit float")
        self._dur.set_value(_fmt_duration(duration))
        self._ch.set_value("Stereo" if data.ndim == 2 and data.shape[1] == 2 else "Mono")
        self._brate.set_value("—")

        if data.ndim == 1:
            left = right = data.astype(float)
        else:
            left  = data[:, 0].astype(float)
            right = data[:, 1].astype(float)

        self._l_peak.set_value(_dbfs(left))
        self._r_peak.set_value(_dbfs(right))
        self._l_rms.set_value(_rms(left))
        self._r_rms.set_value(_rms(right))
        self._pitch.set_value("detecting…")
        self._key.set_value("…")

    def set_pitch(self, hz: float | None, note: str):
        self._pitch.set_value(f"{hz:.1f} Hz" if hz else "—")
        self._key.set_value(note)

    def clear(self):
        for w in (self._file, self._fmt, self._sr, self._bits,
                  self._dur, self._ch, self._brate,
                  self._l_peak, self._r_peak, self._l_rms, self._r_rms,
                  self._pitch, self._key):
            w.set_value("—")
