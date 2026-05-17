"""File browser panel — scans the samples/ folder for audio files."""

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton, QHBoxLayout,
)

AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".ogg", ".aiff", ".aif", ".opus", ".m4a"}
SAMPLES_DIR = Path(__file__).parent.parent / "samples"


class FileBrowserPanel(QWidget):
    file_selected = Signal(str)  # absolute path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        header = QHBoxLayout()
        lbl = QLabel("SAMPLES")
        lbl.setObjectName("stat_key")
        header.addWidget(lbl)
        header.addStretch()
        refresh_btn = QPushButton("↺")
        refresh_btn.setFixedSize(22, 22)
        refresh_btn.setToolTip("Refresh folder")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        layout.addLayout(header)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self._list)

        self.refresh()

    def refresh(self):
        self._list.clear()
        if not SAMPLES_DIR.exists():
            SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

        files = sorted(
            p for p in SAMPLES_DIR.iterdir()
            if p.suffix.lower() in AUDIO_EXTENSIONS
        )
        for f in files:
            item = QListWidgetItem(f.name)
            item.setData(Qt.UserRole, str(f))
            item.setToolTip(str(f))
            self._list.addItem(item)

        if not files:
            placeholder = QListWidgetItem("— drop files in samples/ —")
            placeholder.setFlags(Qt.NoItemFlags)
            self._list.addItem(placeholder)

    def _on_double_click(self, item: QListWidgetItem):
        path = item.data(Qt.UserRole)
        if path:
            self.file_selected.emit(path)
