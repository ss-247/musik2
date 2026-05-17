"""Loop point scanner — find where a track can seamlessly restart."""

import numpy as np
from PySide6.QtCore import Qt, Signal, QObject, QThread
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QCheckBox, QWidget,
)

from app.theme import STYLESHEET, CYAN, GREEN, AMBER, TEXT_DIM, BORDER, BG_PANEL


# ── Algorithm ─────────────────────────────────────────────────────────────────

def _nearest_zero_crossing(mono: np.ndarray, center: int, radius: int) -> int:
    """Return the index of the zero crossing nearest to `center` within ±radius."""
    lo = max(1, center - radius)
    hi = min(len(mono) - 1, center + radius)
    chunk = mono[lo:hi]
    sign_changes = np.where(np.diff(np.sign(chunk)))[0]
    if len(sign_changes) == 0:
        return center
    offsets = sign_changes + lo
    return int(offsets[np.argmin(np.abs(offsets - center))])


def _continuity_score(mono: np.ndarray, loop_end: int, window: int) -> float:
    """
    Score how smoothly `loop_end` can jump back to 0.

    Two components:
      - value continuity: how close mono[loop_end] is to mono[0]  (≈ 0 is best)
      - spectral similarity: normalised cross-correlation of the
        50 ms regions just before loop_end and just after 0
    Combined as weighted average → [0, 1], higher = better loop point.
    """
    # value continuity (both near zero = best)
    v_end   = float(mono[min(loop_end, len(mono) - 1)])
    v_start = float(mono[0])
    val_score = max(0.0, 1.0 - abs(v_end - v_start))
    # near-zero bonus (not just close to each other but close to 0)
    zero_bonus = max(0.0, 1.0 - abs(v_end) * 4.0)

    # short-window cross-correlation
    w = min(window, loop_end)
    if w < 16:
        corr_score = 0.0
    else:
        tail  = mono[loop_end - w: loop_end].astype(np.float64)
        head  = mono[0: w].astype(np.float64)
        # normalised correlation
        denom = (np.linalg.norm(tail) * np.linalg.norm(head))
        corr_score = float(np.dot(tail, head) / denom) if denom > 1e-10 else 0.0
        corr_score = max(0.0, corr_score)   # clamp negative

    return 0.35 * val_score + 0.25 * zero_bonus + 0.40 * corr_score


def find_loop_points(
    data: np.ndarray,
    sr: int,
    n_results: int = 12,
) -> list[dict]:
    """
    Return up to `n_results` loop point candidates, sorted by score desc.

    Each dict:  { time_s, score, bar_aligned }
      time_s      – seconds from track start where loop ends / restarts
      score       – [0..1], higher = more seamless
      bar_aligned – True if this falls on a 4-beat bar boundary
    """
    import librosa

    mono = (data.mean(axis=1) if data.ndim == 2 else data).astype(np.float32)
    duration = len(mono) / sr

    # beat grid
    tempo, beat_frames = librosa.beat.beat_track(y=mono, sr=sr, trim=False)
    tempo = float(np.atleast_1d(tempo)[0])
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    # build candidates: every beat + every bar (4 beats) + every 2/8 bars
    candidates: set[float] = set()
    for i, bt in enumerate(beat_times):
        candidates.add(bt)                          # every beat
        if i % 4 == 3:  candidates.add(bt)         # bar end
        if i % 8 == 7:  candidates.add(bt)         # 2-bar phrase
        if i % 16 == 15: candidates.add(bt)        # 4-bar phrase

    # zero-crossing radius: ±8 ms
    zc_radius = int(0.008 * sr)
    # correlation window: 50 ms
    corr_window = int(0.050 * sr)

    results = []
    seen_times = []
    min_gap = 0.10   # seconds — don't report two points closer than this

    for bt in sorted(candidates):
        if bt < 0.2 or bt > duration - 0.1:
            continue
        center = int(bt * sr)
        zc = _nearest_zero_crossing(mono, center, zc_radius)
        t  = zc / sr

        # deduplicate
        if any(abs(t - s) < min_gap for s in seen_times):
            continue
        seen_times.append(t)

        score = _continuity_score(mono, zc, corr_window)
        bar_aligned = any(
            abs(bt - beat_times[i]) < 0.02
            for i in range(3, len(beat_times), 4)
        )
        results.append({"time_s": t, "score": score, "bar_aligned": bar_aligned})

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:n_results]


# ── Background worker ─────────────────────────────────────────────────────────

class LoopScanWorker(QObject):
    done = Signal(list)   # list of result dicts

    def __init__(self, data: np.ndarray, sr: int):
        super().__init__()
        self._data = data
        self._sr   = sr

    def run(self):
        results = find_loop_points(self._data, self._sr)
        self.done.emit(results)


# ── Results dialog ────────────────────────────────────────────────────────────

def _fmt(t: float) -> str:
    m = int(t) // 60
    s = t - m * 60
    return f"{m}:{s:06.3f}"


class LoopScanDialog(QDialog):
    """
    Shows detected loop points.
    Clicking a row sets the deck's waveform selection to [0 → loop_point].
    → BIN sends that slice to the Sample Bin.
    """

    # emitted when user clicks → BIN for a result
    send_to_bin = Signal(float, float)   # start_s=0, end_s=loop_point

    # emitted when user clicks a row — deck should set selection 0..t
    set_selection = Signal(float, float)

    def __init__(self, results: list[dict], deck_name: str, parent=None):
        super().__init__(parent, Qt.Window | Qt.WindowStaysOnTopHint)
        self.setWindowTitle(f"MUSIK2  ·  DECK {deck_name}  —  LOOP POINTS")
        self.setModal(False)
        self.setStyleSheet(STYLESHEET)
        self.resize(620, 440)
        self.setMinimumSize(500, 300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        hdr = QHBoxLayout()
        title = QLabel(f"DECK {deck_name}  —  LOOP POINTS")
        title.setObjectName("title")
        hdr.addWidget(title)
        hdr.addStretch()
        note = QLabel("click row → set selection  ·  → BIN to collect")
        note.setObjectName("stat_key")
        hdr.addWidget(note)
        layout.addLayout(hdr)

        # table
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Time", "Score", "Bar ✓", "", ""])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self._table.setColumnWidth(0, 90)
        self._table.setColumnWidth(1, 70)
        self._table.setColumnWidth(2, 54)
        self._table.setColumnWidth(4, 68)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(
            f"QTableWidget{{background:{BG_PANEL};gridline-color:{BORDER};}}"
            f"QHeaderView::section{{background:{BG_PANEL};color:{TEXT_DIM};"
            f"border-bottom:1px solid {BORDER};padding:2px 4px;}}"
        )
        self._table.cellClicked.connect(self._on_row_click)
        layout.addWidget(self._table)

        # send all checked to bin
        bottom = QHBoxLayout()
        self._chk_all = QCheckBox("select all")
        self._chk_all.stateChanged.connect(self._toggle_all)
        bottom.addWidget(self._chk_all)
        bottom.addStretch()
        send_all_btn = QPushButton("→ BIN  (checked)")
        send_all_btn.setStyleSheet(f"color:#b060ff; border-color:#b060ff;")
        send_all_btn.clicked.connect(self._send_checked)
        bottom.addWidget(send_all_btn)
        layout.addLayout(bottom)

        self._results = results
        self._populate(results)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _populate(self, results: list[dict]):
        self._table.setRowCount(0)
        for r in results:
            row = self._table.rowCount()
            self._table.insertRow(row)

            t_item = QTableWidgetItem(_fmt(r["time_s"]))
            t_item.setForeground(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor(CYAN))
            t_item.setData(Qt.UserRole, r["time_s"])

            pct = int(r["score"] * 100)
            s_item = QTableWidgetItem(f"{pct}%")
            color = GREEN if pct >= 70 else (AMBER if pct >= 40 else TEXT_DIM)
            s_item.setForeground(__import__("PySide6.QtGui", fromlist=["QColor"]).QColor(color))

            bar_item = QTableWidgetItem("✓" if r["bar_aligned"] else "")
            bar_item.setTextAlignment(Qt.AlignCenter)

            # checkbox cell
            chk_w = QWidget()
            chk_l = QHBoxLayout(chk_w)
            chk_l.setContentsMargins(4, 0, 4, 0)
            chk_l.setAlignment(Qt.AlignCenter)
            chk = QCheckBox()
            chk_l.addWidget(chk)

            # → BIN button
            bin_btn = QPushButton("→ BIN")
            bin_btn.setFixedHeight(22)
            bin_btn.setStyleSheet("color:#b060ff; border-color:#b060ff; font-size:10px;")
            t = r["time_s"]
            bin_btn.clicked.connect(lambda _=False, ts=t: self.send_to_bin.emit(0.0, ts))

            self._table.setItem(row, 0, t_item)
            self._table.setItem(row, 1, s_item)
            self._table.setItem(row, 2, bar_item)
            self._table.setCellWidget(row, 3, chk_w)
            self._table.setCellWidget(row, 4, bin_btn)
            self._table.setRowHeight(row, 28)

    def _on_row_click(self, row: int, col: int):
        if col == 4:   # → BIN column handled by button
            return
        t = self._table.item(row, 0).data(Qt.UserRole)
        self.set_selection.emit(0.0, float(t))

    def _toggle_all(self, state):
        checked = state == Qt.Checked.value if hasattr(Qt.Checked, "value") else bool(state)
        for row in range(self._table.rowCount()):
            chk_w = self._table.cellWidget(row, 3)
            if chk_w:
                chk = chk_w.findChild(QCheckBox)
                if chk:
                    chk.setChecked(checked)

    def _send_checked(self):
        for row in range(self._table.rowCount()):
            chk_w = self._table.cellWidget(row, 3)
            if not chk_w:
                continue
            chk = chk_w.findChild(QCheckBox)
            if chk and chk.isChecked():
                t = self._table.item(row, 0).data(Qt.UserRole)
                self.send_to_bin.emit(0.0, float(t))
