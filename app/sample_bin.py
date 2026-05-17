"""Sample Bin — accumulate clips, reorder by drag-drop, build a track."""

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QAbstractItemView, QMenu,
)

from app.theme import GREEN, AMBER, TEXT_DIM, BORDER, CYAN


def _fmt(seconds: float) -> str:
    m = int(seconds) // 60
    s = seconds - m * 60
    return f"{m}:{s:04.1f}"


class SampleBinPanel(QWidget):
    # target=None → new deck; target=DeckWidget → load into that deck
    send_to_deck = Signal(np.ndarray, int, str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # header
        hdr = QHBoxLayout()
        lbl = QLabel("SAMPLE BIN")
        lbl.setObjectName("stat_key")
        hdr.addWidget(lbl)
        hdr.addStretch()
        clr = QPushButton("✕")
        clr.setFixedSize(22, 22)
        clr.setToolTip("Clear all clips")
        clr.clicked.connect(self._clear_all)
        hdr.addWidget(clr)
        layout.addLayout(hdr)

        # count label
        self._count_lbl = QLabel("0 clips")
        self._count_lbl.setObjectName("stat_key")
        layout.addWidget(self._count_lbl)

        # clip list — drag-drop to reorder
        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.InternalMove)
        self._list.setAlternatingRowColors(True)
        self._list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._ctx_menu)
        layout.addWidget(self._list)

        # build track button
        build_btn = QPushButton("▶  BUILD TRACK")
        build_btn.setToolTip(
            "Concatenate all clips (in current order) into a new deck"
        )
        build_btn.setStyleSheet(f"color:{GREEN}; border-color:{GREEN};")
        build_btn.clicked.connect(self._build_track)
        layout.addWidget(build_btn)

    # ── Public API ────────────────────────────────────────────────────────────

    def add_clip(self, data: np.ndarray, sr: int, label: str):
        dur = len(data) / sr
        item = QListWidgetItem(f"{label}   [{_fmt(dur)}]")
        item.setToolTip(f"{sr} Hz  ·  {'stereo' if data.ndim==2 else 'mono'}  ·  {_fmt(dur)}")
        # store the actual data in the item so drag-drop reorder stays consistent
        item.setData(Qt.UserRole, (data, sr, label))
        self._list.addItem(item)
        self._update_count()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _update_count(self):
        n = self._list.count()
        self._count_lbl.setText(f"{n} clip{'s' if n != 1 else ''}")

    def _clear_all(self):
        self._list.clear()
        self._update_count()

    def _ctx_menu(self, pos):
        item = self._list.itemAt(pos)
        if not item:
            return
        data, sr, label = item.data(Qt.UserRole)

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#0d0d18;color:#c8e8ff;border:1px solid #1a2a3a;}"
            "QMenu::item:selected{background:#007a80;color:#000;}"
        )
        act_send = QAction("→ NEW DECK", self)
        act_send.triggered.connect(
            lambda: self.send_to_deck.emit(data, sr, label, None)
        )
        act_del = QAction("Remove", self)
        act_del.triggered.connect(lambda: (
            self._list.takeItem(self._list.row(item)),
            self._update_count(),
        ))
        menu.addAction(act_send)
        menu.addSeparator()
        menu.addAction(act_del)
        menu.exec(self._list.mapToGlobal(pos))

    def _build_track(self):
        n = self._list.count()
        if n == 0:
            return

        clips = [self._list.item(i).data(Qt.UserRole) for i in range(n)]
        sr = clips[0][1]   # use first clip's sr as target

        arrays = []
        for data, clip_sr, _ in clips:
            if clip_sr != sr:
                from scipy import signal as sp
                if data.ndim == 1:
                    data = sp.resample_poly(data, sr, clip_sr).astype(np.float32)
                else:
                    l = sp.resample_poly(data[:, 0], sr, clip_sr).astype(np.float32)
                    r = sp.resample_poly(data[:, 1], sr, clip_sr).astype(np.float32)
                    data = np.stack([l[:min(len(l), len(r))], r[:min(len(l), len(r))]], axis=1)
            arrays.append(data)

        # unify channel count
        stereo = any(a.ndim == 2 for a in arrays)
        if stereo:
            arrays = [
                np.stack([a, a], axis=1) if a.ndim == 1 else a
                for a in arrays
            ]

        track = np.concatenate(arrays, axis=0).astype(np.float32)
        self.send_to_deck.emit(track, sr, f"built track  ({n} clips)", None)
