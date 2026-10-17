from __future__ import annotations

"""Centralized Qt palette, speaker lane colors, and dark editor stylesheet."""

from PySide6.QtGui import QColor

TRACK_COLORS = [
    QColor("#36c5d8"),
    QColor("#a78bfa"),
    QColor("#f6b94a"),
]

APP_STYLESHEET = """
QMainWindow, QWidget {
    background: #15171b;
    color: #e7e9ee;
    font-size: 13px;
}
QFrame#toolbar, QFrame#panel {
    background: #1c1f24;
    border: 1px solid #2b3037;
    border-radius: 8px;
}
QGroupBox {
    border: 1px solid #31363f;
    border-radius: 7px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QPushButton {
    background: #252a31;
    border: 1px solid #383f49;
    border-radius: 6px;
    padding: 7px 11px;
}
QPushButton:hover {
    background: #2d333c;
}
QPushButton:disabled {
    color: #777d86;
}
QPushButton#primaryButton {
    background: #18a9bb;
    border-color: #18a9bb;
    color: #081114;
    font-weight: 700;
}
QPushButton#primaryButton:hover {
    background: #31bdce;
}
QLineEdit, QComboBox, QDoubleSpinBox {
    background: #111318;
    border: 1px solid #363c45;
    border-radius: 5px;
    padding: 6px;
}
QTabWidget::pane {
    border: 1px solid #2b3037;
    background: #181b20;
}
QTabBar::tab {
    background: #1c1f24;
    color: #aeb4bd;
    padding: 8px 13px;
    border: 1px solid #2b3037;
}
QTabBar::tab:selected {
    color: #ffffff;
    background: #252a31;
}
QTableWidget {
    background: #111318;
    alternate-background-color: #171a1f;
    gridline-color: #2c3138;
    border: 1px solid #2c3138;
}
QHeaderView::section {
    background: #22262c;
    color: #d9dde3;
    border: 0;
    border-right: 1px solid #333942;
    padding: 6px;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #30353d;
}
QSlider::handle:horizontal {
    background: #e8ebef;
    width: 12px;
    margin: -5px 0;
    border-radius: 6px;
}
"""
