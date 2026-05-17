"""Dual-channel waveform view with linked zoom, scrub, and selection."""

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy

from app.theme import CYAN, MAGENTA, BG, BG_PANEL, BORDER, TEXT_DIM, CYAN_DIM


_MAX_DISPLAY_POINTS = 8000  # downsample target per channel for smooth rendering


def _downsample(data: np.ndarray, target: int) -> np.ndarray:
    """Min-max envelope downsample so peaks are preserved."""
    n = len(data)
    if n <= target:
        return data
    stride = n // target
    trimmed = data[: stride * target].reshape(target, stride)
    mins = trimmed.min(axis=1)
    maxs = trimmed.max(axis=1)
    interleaved = np.empty(target * 2, dtype=data.dtype)
    interleaved[0::2] = mins
    interleaved[1::2] = maxs
    return interleaved


class _ChannelPlot(pg.PlotWidget):
    """Single-channel waveform plot (L or R)."""

    scrub_pos = Signal(float)  # sample position (seconds)

    def __init__(self, label: str, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self._sr = 1
        self._dragging_scrub = False
        self._shift_start = None
        self._duration = 0.0

        self.setBackground(BG)
        self.setMenuEnabled(False)
        self.hideButtons()
        self.showGrid(x=True, y=False, alpha=0.15)
        self.setYRange(-1.05, 1.05, padding=0)
        self.getPlotItem().setContentsMargins(0, 0, 0, 0)
        self.getAxis("bottom").setStyle(tickFont=None, tickTextOffset=2)
        self.getAxis("left").setWidth(36)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(50)

        # channel label overlay
        self._label = pg.TextItem(label, color=color, anchor=(0, 0))
        self._label.setPos(0, 0.85)
        self._label.setZValue(10)
        self.addItem(self._label)

        # waveform curve
        self._curve = self.plot(pen=pg.mkPen(color=color, width=1))

        # playhead
        self._playhead = pg.InfiniteLine(
            pos=0,
            angle=90,
            pen=pg.mkPen(color="#ffffff", width=1, style=Qt.DashLine),
            movable=False,
        )
        self.addItem(self._playhead)

        # selection region (hidden until user shift-drags)
        self._region = pg.LinearRegionItem(
            values=(0, 0),
            brush=pg.mkBrush(QColor(0, 245, 255, 30)),
            pen=pg.mkPen(color=CYAN_DIM, width=1),
            movable=True,
        )
        self._region.setZValue(5)
        self._region.hide()
        self.addItem(self._region)

        # style axes
        for ax in ("left", "bottom"):
            self.getAxis(ax).setPen(pg.mkPen(color=BORDER))
            self.getAxis(ax).setTextPen(pg.mkPen(color=TEXT_DIM))

    # ── Public API ─────────────────────────────────────────────────────────

    def load(self, data: np.ndarray, sr: int):
        self._sr = sr
        self._duration = len(data) / sr
        t_full = np.linspace(0, self._duration, len(data))
        ds = _downsample(data, _MAX_DISPLAY_POINTS)
        t_ds = np.linspace(0, self._duration, len(ds))
        self._curve.setData(x=t_ds, y=ds)
        self.setXRange(0, self._duration, padding=0.01)
        self._label.setPos(self._duration * 0.005, 0.85)
        self._playhead.setValue(0)
        self._region.hide()

    def set_playhead(self, seconds: float):
        self._playhead.setValue(seconds)

    def get_selection(self):
        if self._region.isVisible():
            return self._region.getRegion()
        return None

    def show_selection(self, a: float, b: float):
        self._region.setRegion((min(a, b), max(a, b)))
        self._region.show()

    def hide_selection(self):
        self._region.hide()

    # ── Mouse interaction ───────────────────────────────────────────────────

    def _to_data(self, ev) -> float:
        return self.plotItem.vb.mapSceneToView(QPointF(ev.position())).x()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            if ev.modifiers() & Qt.ShiftModifier:
                x = self._to_data(ev)
                self._shift_start = x
                self._region.setRegion((x, x))
                self._region.show()
                ev.accept()   # block PyQtGraph's shift+zoom-rect
                return
            else:
                self._dragging_scrub = True
                t = max(0.0, min(self._duration, self._to_data(ev)))
                self.scrub_pos.emit(t)
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._shift_start is not None:
            x = self._to_data(ev)
            self._region.setRegion((min(self._shift_start, x), max(self._shift_start, x)))
            ev.accept()
            return
        if self._dragging_scrub:
            t = max(0.0, min(self._duration, self._to_data(ev)))
            self.scrub_pos.emit(t)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._shift_start is not None:
            # finalise selection — don't let PyQtGraph reset the view
            self._shift_start = None
            self._dragging_scrub = False
            ev.accept()
            return
        self._dragging_scrub = False
        super().mouseReleaseEvent(ev)

    def wheelEvent(self, ev):
        # delegate to parent WaveformView for linked zoom
        ev.ignore()


class WaveformView(QWidget):
    """Dual-channel (L+R) waveform display with linked zoom and scrub."""

    scrub_pos = Signal(float)      # seconds
    selection_changed = Signal(float, float)  # start, end seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self._duration = 0.0
        self._zoom_factor = 1.0
        self._view_start = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._left  = _ChannelPlot("L", CYAN,    self)
        self._right = _ChannelPlot("R", MAGENTA,  self)

        # link X axes so zoom/pan is always in sync
        self._right.setXLink(self._left)

        for ch in (self._left, self._right):
            ch.scrub_pos.connect(self._on_scrub)
            layout.addWidget(ch)

        self._left._region.sigRegionChanged.connect(self._sync_region_lr)
        self._right._region.sigRegionChanged.connect(self._sync_region_rl)
        self._left._region.sigRegionChangeFinished.connect(self._emit_selection)
        self._right._region.sigRegionChangeFinished.connect(self._emit_selection)

        self.setAcceptDrops(True)

    # ── Public API ──────────────────────────────────────────────────────────

    def load(self, data: np.ndarray, sr: int):
        """data shape: (N,) mono or (N, 2) stereo."""
        self._duration = len(data) / sr
        self._view_start = 0.0
        self._zoom_factor = 1.0

        if data.ndim == 1:
            left = right = data
        else:
            left  = data[:, 0]
            right = data[:, 1]

        self._left.load(left, sr)
        self._right.load(right, sr)

    def set_playhead(self, seconds: float):
        self._left.set_playhead(seconds)
        self._right.set_playhead(seconds)

    def get_selection(self):
        return self._left.get_selection()

    # ── Internal ────────────────────────────────────────────────────────────

    def _on_scrub(self, t: float):
        self.set_playhead(t)
        self.scrub_pos.emit(t)

    def _sync_region_lr(self):
        r = self._left._region.getRegion()
        self._right._region.blockSignals(True)
        self._right.show_selection(*r)
        self._right._region.blockSignals(False)

    def _sync_region_rl(self):
        r = self._right._region.getRegion()
        self._left._region.blockSignals(True)
        self._left.show_selection(*r)
        self._left._region.blockSignals(False)

    def _emit_selection(self):
        r = self._left.get_selection()
        if r:
            self.selection_changed.emit(*r)

    # ── Wheel zoom (linked) ──────────────────────────────────────────────────

    def wheelEvent(self, ev):
        if self._duration == 0:
            return
        delta = ev.angleDelta().y()
        factor = 0.85 if delta > 0 else 1.0 / 0.85

        vb = self._left.plotItem.vb
        cur_range = vb.viewRange()[0]
        center = (cur_range[0] + cur_range[1]) / 2.0
        half = (cur_range[1] - cur_range[0]) / 2.0 * factor
        new_lo = max(0.0, center - half)
        new_hi = min(self._duration, center + half)
        self._left.setXRange(new_lo, new_hi, padding=0)
        ev.accept()
