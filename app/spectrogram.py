"""Dual-channel spectrogram view + FFT strip + pitch detection."""

import numpy as np
from scipy import signal as sp_signal
from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSplitter, QSizePolicy
import pyqtgraph as pg

from app.theme import CYAN, MAGENTA, BG, BORDER, TEXT_DIM, CYAN_DIM

# ── Tron colormap: near-black → dark-teal → bright-cyan ──────────────────────
_TRON_CMAP = pg.ColorMap(
    pos=np.array([0.0, 0.35, 0.70, 1.0]),
    color=np.array([
        [10,  10,  15,  255],   # silence
        [0,   30,  50,  255],   # low energy
        [0,  160, 180,  255],   # mid energy
        [0,  245, 255,  255],   # loud
    ], dtype=np.uint8),
)
_MAGENTA_CMAP = pg.ColorMap(
    pos=np.array([0.0, 0.35, 0.70, 1.0]),
    color=np.array([
        [10,   5,  15,  255],
        [40,   0,  50,  255],
        [180,  0, 180,  255],
        [255,  0, 255,  255],
    ], dtype=np.uint8),
)

_DB_MIN = -80.0
_DB_MAX =   0.0


def compute_stft(mono: np.ndarray, sr: int, n_fft: int = 2048, hop: int = 512):
    """Returns (freqs Hz, times s, Sdb) where Sdb shape=(freq_bins, time_bins)."""
    freqs, times, Zxx = sp_signal.stft(
        mono, fs=sr, nperseg=n_fft, noverlap=n_fft - hop, boundary=None
    )
    Sdb = 20.0 * np.log10(np.maximum(np.abs(Zxx), 1e-10))
    return freqs, times, Sdb


def fft_slice(mono: np.ndarray, sr: int, t: float, window: int = 4096):
    """FFT magnitude spectrum at time t. Returns (freqs Hz, amplitudes dB)."""
    idx = int(t * sr)
    half = window // 2
    start = max(0, idx - half)
    chunk = mono[start: start + window].copy()
    if len(chunk) < window:
        chunk = np.pad(chunk, (0, window - len(chunk)))
    chunk *= np.hanning(window)
    mag = np.abs(np.fft.rfft(chunk)) / window
    db  = 20.0 * np.log10(np.maximum(mag, 1e-10))
    freqs = np.fft.rfftfreq(window, d=1.0 / sr)
    return freqs, db


def detect_pitch(data: np.ndarray, sr: int):
    """Return (median_hz, note_str) for the dominant pitch. Uses librosa.yin."""
    try:
        import librosa
        mono = data.mean(axis=1).astype(np.float32) if data.ndim == 2 else data.astype(np.float32)
        # downsample to 22050 for speed on long files
        if sr != 22050:
            mono = sp_signal.resample_poly(mono, 22050, sr).astype(np.float32)
        sr_a = 22050
        f0 = librosa.yin(mono, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"),
                         sr=sr_a)
        valid = f0[(f0 > 50) & (f0 < 5000)]
        if len(valid) == 0:
            return None, "—"
        median_hz = float(np.median(valid))
        note = librosa.hz_to_note(median_hz)
        return median_hz, note
    except Exception:
        return None, "—"


# ── single channel spectrogram plot ──────────────────────────────────────────

def _make_spec_plot(label: str, link_to=None) -> tuple:
    """Returns (PlotWidget, ImageItem)."""
    pw = pg.PlotWidget()
    pw.setBackground(BG)
    pw.setMenuEnabled(False)
    pw.hideButtons()
    pw.setLabel("left", label, color=TEXT_DIM, size="9pt")
    pw.showGrid(x=False, y=False)
    pw.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    pw.setMinimumHeight(40)

    for ax in ("left", "bottom"):
        pw.getAxis(ax).setPen(pg.mkPen(color=BORDER))
        pw.getAxis(ax).setTextPen(pg.mkPen(color=TEXT_DIM))
    pw.getAxis("bottom").setStyle(showValues=False)

    img = pg.ImageItem()
    img.setZValue(-1)
    pw.addItem(img)

    playhead = pg.InfiniteLine(pos=0, angle=90,
                               pen=pg.mkPen(color="#ffffff", width=1, style=Qt.DashLine))
    pw.addItem(playhead)

    if link_to is not None:
        pw.setXLink(link_to)

    return pw, img, playhead


class SpectrogramView(QWidget):
    """Dual-channel (L cyan / R magenta) spectrogram + FFT strip."""

    def __init__(self, link_to=None, parent=None):
        super().__init__(parent)
        self._link_to = link_to    # a pg.PlotWidget to sync X with
        self._sr = 1
        self._l_mono: np.ndarray | None = None
        self._r_mono: np.ndarray | None = None
        self._duration = 0.0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        # ── spectrogram plots ────────────────────────────────────────────────
        spec_split = QSplitter(Qt.Vertical)
        spec_split.setHandleWidth(2)

        self._l_plot, self._l_img, self._l_head = _make_spec_plot("L  freq", link_to)
        self._r_plot, self._r_img, self._r_head = _make_spec_plot("R  freq", link_to)

        # link R to L so they stay in sync even without external link
        self._r_plot.setXLink(self._l_plot)

        spec_split.addWidget(self._l_plot)
        spec_split.addWidget(self._r_plot)
        spec_split.setSizes([100, 100])
        outer.addWidget(spec_split, stretch=3)

        # ── FFT strip ────────────────────────────────────────────────────────
        self._fft_plot = pg.PlotWidget()
        self._fft_plot.setBackground(BG)
        self._fft_plot.setMenuEnabled(False)
        self._fft_plot.hideButtons()
        self._fft_plot.setLabel("left", "dB", color=TEXT_DIM, size="9pt")
        self._fft_plot.setLabel("bottom", "Hz", color=TEXT_DIM, size="9pt")
        self._fft_plot.setYRange(_DB_MIN, _DB_MAX, padding=0)
        self._fft_plot.setMinimumHeight(55)
        self._fft_plot.showGrid(x=True, y=True, alpha=0.15)
        for ax in ("left", "bottom"):
            self._fft_plot.getAxis(ax).setPen(pg.mkPen(color=BORDER))
            self._fft_plot.getAxis(ax).setTextPen(pg.mkPen(color=TEXT_DIM))

        self._fft_l = self._fft_plot.plot(pen=pg.mkPen(color=CYAN, width=1))
        self._fft_r = self._fft_plot.plot(pen=pg.mkPen(color=MAGENTA, width=1))
        outer.addWidget(self._fft_plot, stretch=0)

    # ── Public API ────────────────────────────────────────────────────────────

    def load(self, data: np.ndarray, sr: int):
        self._sr = sr
        self._duration = len(data) / sr

        if data.ndim == 1:
            self._l_mono = self._r_mono = data.astype(np.float32)
        else:
            self._l_mono = data[:, 0].astype(np.float32)
            self._r_mono = data[:, 1].astype(np.float32)

        self._render_spectrogram(self._l_plot, self._l_img, self._l_mono, _TRON_CMAP)
        self._render_spectrogram(self._r_plot, self._r_img, self._r_mono, _MAGENTA_CMAP)

        for head in (self._l_head, self._r_head):
            head.setValue(0)

        # initial FFT at t=0
        self._update_fft(0.0)

    def set_playhead(self, t: float):
        self._l_head.setValue(t)
        self._r_head.setValue(t)
        self._update_fft(t)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _render_spectrogram(self, plot: pg.PlotWidget, img: pg.ImageItem,
                             mono: np.ndarray, cmap: pg.ColorMap):
        freqs, times, Sdb = compute_stft(mono, self._sr)

        # clip to useful freq range (cap at 16 kHz)
        max_freq = min(freqs[-1], 16000)
        mask = freqs <= max_freq
        freqs = freqs[mask]
        Sdb   = Sdb[mask, :]

        # normalise to [0, 1] for colormap
        Sdb_norm = np.clip((Sdb - _DB_MIN) / (_DB_MAX - _DB_MIN), 0.0, 1.0)

        # ImageItem expects (x=time, y=freq) → transpose
        img.setImage(Sdb_norm.T, autoLevels=False, levels=(0.0, 1.0))
        img.setColorMap(cmap)
        img.setRect(QRectF(0.0, 0.0, self._duration, float(max_freq)))

        plot.setXRange(0, self._duration, padding=0.01)
        plot.setYRange(0, max_freq, padding=0)

    def _update_fft(self, t: float):
        if self._l_mono is None:
            return
        fl, dl = fft_slice(self._l_mono, self._sr, t)
        fr, dr = fft_slice(self._r_mono, self._sr, t)
        # limit display to 16 kHz
        mask = fl <= 16000
        self._fft_l.setData(x=fl[mask], y=dl[mask])
        self._fft_r.setData(x=fr[mask], y=dr[mask])
        self._fft_plot.setXRange(0, min(self._sr / 2, 16000), padding=0)
