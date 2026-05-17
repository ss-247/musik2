"""Tron-inspired dark palette and global stylesheet."""

# Palette
BG        = "#0a0a0f"
BG_PANEL  = "#0d0d18"
BG_WIDGET = "#111120"
CYAN      = "#00f5ff"
CYAN_DIM  = "#007a80"
MAGENTA   = "#ff00ff"
MAGENTA_DIM = "#800080"
GREEN     = "#39ff14"
AMBER     = "#ffb000"
TEXT      = "#c8e8ff"
TEXT_DIM  = "#4a6070"
BORDER    = "#1a2a3a"
BORDER_BRIGHT = "#00f5ff"

FONT_FAMILY = "Consolas, 'Courier New', monospace"
FONT_SIZE   = "11px"

STYLESHEET = f"""
/* ── Global ── */
* {{
    background-color: {BG};
    color: {TEXT};
    font-family: {FONT_FAMILY};
    font-size: {FONT_SIZE};
    border: none;
    outline: none;
}}

QMainWindow, QDialog {{
    background-color: {BG};
}}

/* ── Panels / frames ── */
QFrame, QWidget#panel {{
    background-color: {BG_PANEL};
}}

QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 2px;
    margin-top: 6px;
    padding-top: 6px;
    color: {CYAN_DIM};
    font-size: 10px;
    letter-spacing: 1px;
    text-transform: uppercase;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
}}

/* ── DockWidget ── */
QDockWidget {{
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
    color: {CYAN};
    font-size: 10px;
    letter-spacing: 2px;
    text-transform: uppercase;
}}
QDockWidget::title {{
    background-color: {BG_PANEL};
    padding: 4px 8px;
    border-bottom: 1px solid {BORDER};
}}

/* ── Tabs ── */
QTabBar::tab {{
    background: {BG_PANEL};
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
    border-bottom: none;
    padding: 5px 16px;
    min-width: 80px;
    letter-spacing: 1px;
}}
QTabBar::tab:selected {{
    background: {BG_WIDGET};
    color: {CYAN};
    border-color: {CYAN_DIM};
    border-bottom: 2px solid {CYAN};
}}
QTabBar::tab:hover {{
    color: {TEXT};
    border-color: {CYAN_DIM};
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background: {BG_WIDGET};
}}

/* ── Buttons ── */
QPushButton {{
    background-color: {BG_WIDGET};
    color: {CYAN};
    border: 1px solid {CYAN_DIM};
    border-radius: 2px;
    padding: 4px 12px;
    letter-spacing: 1px;
    min-width: 32px;
    min-height: 24px;
}}
QPushButton:hover {{
    background-color: #1a2a3a;
    border-color: {CYAN};
    color: #ffffff;
}}
QPushButton:pressed {{
    background-color: {CYAN_DIM};
    color: {BG};
}}
QPushButton:checked {{
    background-color: {CYAN_DIM};
    color: {BG};
    border-color: {CYAN};
}}
QPushButton:disabled {{
    color: {TEXT_DIM};
    border-color: {BORDER};
}}

/* ── List ── */
QListWidget {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    color: {TEXT};
    alternate-background-color: {BG_WIDGET};
}}
QListWidget::item {{
    padding: 3px 6px;
    border-bottom: 1px solid {BORDER};
}}
QListWidget::item:selected {{
    background-color: {CYAN_DIM};
    color: {BG};
}}
QListWidget::item:hover {{
    background-color: #1a2a3a;
    color: {CYAN};
}}

/* ── Scrollbar ── */
QScrollBar:vertical {{
    background: {BG_PANEL};
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {CYAN_DIM};
    min-height: 24px;
    border-radius: 4px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {BG_PANEL};
    height: 8px;
}}
QScrollBar::handle:horizontal {{
    background: {CYAN_DIM};
    min-width: 24px;
    border-radius: 4px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Slider ── */
QSlider::groove:horizontal {{
    background: {BG_WIDGET};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {CYAN};
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}}
QSlider::sub-page:horizontal {{
    background: {CYAN_DIM};
    border-radius: 2px;
}}

/* ── Labels ── */
QLabel#stat_value {{
    color: {CYAN};
    font-size: 12px;
}}
QLabel#stat_key {{
    color: {TEXT_DIM};
    font-size: 10px;
    letter-spacing: 1px;
}}
QLabel#title {{
    color: {CYAN};
    font-size: 14px;
    letter-spacing: 3px;
}}

/* ── Splitter ── */
QSplitter::handle {{
    background: {BORDER};
    width: 2px;
    height: 2px;
}}

/* ── Status bar ── */
QStatusBar {{
    background: {BG_PANEL};
    color: {TEXT_DIM};
    border-top: 1px solid {BORDER};
    font-size: 10px;
}}
"""
