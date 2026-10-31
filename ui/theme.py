# -*- coding: utf-8 -*-
"""پوستهٔ روشن/تیره، فونت وزیرمتن و آیکون‌های SVG."""
from __future__ import annotations

import os
import sys

from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtSvg import QSvgRenderer

LIGHT = {
    "bg": "#f3f6fb", "surface": "#ffffff", "surface2": "#f8fafc", "border": "#dbe3ee",
    "text": "#172033", "muted": "#64748b", "primary": "#2563eb", "primary_dark": "#1d4ed8",
    "success": "#059669", "danger": "#dc2626", "warning": "#d97706", "sidebar": "#0f172a",
    "sidebar_text": "#cbd5e1", "sidebar_active": "#2563eb",
}
DARK = {
    "bg": "#0b1220", "surface": "#111a2c", "surface2": "#162238", "border": "#26344d",
    "text": "#e5edf8", "muted": "#94a3b8", "primary": "#60a5fa", "primary_dark": "#3b82f6",
    "success": "#34d399", "danger": "#f87171", "warning": "#fbbf24", "sidebar": "#070d18",
    "sidebar_text": "#cbd5e1", "sidebar_active": "#2563eb",
}

_ICONS = {
    "dashboard": '<path d="M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z"/>',
    "users": '<path d="M16 11c1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3 1.34 3 3 3zm-8 0c1.66 0 3-1.34 3-3S9.66 5 8 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5C15 14.17 10.33 13 8 13zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/>',
    "box": '<path d="M21 8l-9-5-9 5v8l9 5 9-5V8zm-9 3.5L6.2 8.3 12 5.1l5.8 3.2L12 11.5zM5 9.9l6 3.4v6.2l-6-3.3V9.9zm8 9.6v-6.2l6-3.4v6.3l-6 3.3z"/>',
    "invoice": '<path d="M6 2h9l5 5v15H6V2zm8 1.5V8h4.5L14 3.5zM8 11h8v2H8v-2zm0 4h8v2H8v-2z"/>',
    "cash": '<path d="M2 6h20v12H2V6zm10 9a3 3 0 100-6 3 3 0 000 6zM4 8v8h2a2 2 0 012-2V10a2 2 0 01-2-2H4zm14 0a2 2 0 01-2 2v4a2 2 0 012 2h2V8h-2z"/>',
    "cheque": '<path d="M3 5h18v14H3V5zm2 2v10h14V7H5zm2 2h6v2H7V9zm0 4h4v2H7v-2zm8-4h2v6h-2V9z"/>',
    "chart": '<path d="M4 20h16v2H2V2h2v18zm3-3V9h3v8H7zm5 0V4h3v13h-3zm5 0v-6h3v6h-3z"/>',
    "settings": '<path d="M19.4 13a7.8 7.8 0 000-2l2-1.6-2-3.4-2.4 1a7.6 7.6 0 00-1.7-1L15 3h-4l-.3 2.6a7.6 7.6 0 00-1.7 1l-2.4-1-2 3.4L6.6 11a7.8 7.8 0 000 2l-2 1.6 2 3.4 2.4-1c.5.4 1.1.8 1.7 1L11 21h4l.3-2.6c.6-.2 1.2-.6 1.7-1l2.4 1 2-3.4-2-1.6zM13 15a3 3 0 110-6 3 3 0 010 6z"/>',
    "plus": '<path d="M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6V5z"/>',
    "check": '<path d="M9 16.2l-3.5-3.5L4 14.2 9 19.2 20 8.2l-1.5-1.5z"/>',
    "cancel": '<path d="M12 2a10 10 0 100 20 10 10 0 000-20zM5.6 7L17 18.4A8 8 0 017 5.6zM18.4 17L7 5.6A8 8 0 0118.4 17z"/>',
    "print": '<path d="M6 2h12v5H6V2zm-3 7h18v8h-4v5H7v-5H3V9zm6 6v5h6v-5H9zm9-3a1 1 0 100-2 1 1 0 000 2z"/>',
    "search": '<path d="M10 2a8 8 0 105.3 14l4.8 4.8 1.4-1.4-4.8-4.8A8 8 0 0010 2zm0 2a6 6 0 110 12 6 6 0 010-12z"/>',
    "backup": '<path d="M12 3a9 9 0 00-9 9h3l-4 5-4-5h3a11 11 0 0111-11v2zm0 18a9 9 0 009-9h-3l4-5 4 5h-3A11 11 0 0112 23v-2z"/>',
    "logout": '<path d="M10 3H4v18h6v-2H6V5h4V3zm5 4l-1.4 1.4L16.2 11H9v2h7.2l-2.6 2.6L15 17l5-5-5-5z"/>',
}


def asset_path(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)


def load_font(app) -> str:
    family = "Vazirmatn"
    for name in ("Vazirmatn-Regular.ttf", "Vazirmatn-Medium.ttf", "Vazirmatn-Bold.ttf"):
        path = asset_path("assets", "fonts", name)
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)
    if family not in QFontDatabase.families():
        family = "Tahoma"
    app.setFont(QFont(family, 10))
    return family


def icon(name: str, color: str = "#ffffff", size: int = 20) -> QIcon:
    body = _ICONS.get(name, _ICONS["dashboard"])
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{color}">{body}</svg>'
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    renderer.render(p)
    p.end()
    return QIcon(pix)


def qss(colors: dict) -> str:
    c = colors
    return f"""
QWidget {{ color: {c['text']}; font-size: 13px; }}
QMainWindow, QDialog {{ background: {c['bg']}; }}
QFrame#Sidebar {{ background: {c['sidebar']}; border: none; }}
QLabel#Brand {{ color: white; font-size: 18px; font-weight: 700; padding: 18px 16px 4px 16px; }}
QLabel#BrandSub {{ color: {c['sidebar_text']}; font-size: 11px; padding: 0 16px 16px 16px; }}
QPushButton#NavButton {{
    background: transparent; color: {c['sidebar_text']}; border: none; border-radius: 10px;
    padding: 12px 16px; text-align: right; font-size: 13px;
}}
QPushButton#NavButton:hover {{ background: rgba(255,255,255,0.08); color: white; }}
QPushButton#NavButton:checked {{ background: {c['sidebar_active']}; color: white; font-weight: 700; }}
QFrame#TopBar {{ background: {c['surface']}; border-bottom: 1px solid {c['border']}; }}
QLabel#PageTitle {{ font-size: 20px; font-weight: 700; color: {c['text']}; }}
QLabel#PageHint {{ color: {c['muted']}; font-size: 12px; }}
QFrame#Card, QGroupBox {{
    background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 14px;
}}
QGroupBox {{ margin-top: 14px; padding-top: 14px; font-weight: 700; }}
QGroupBox::title {{ subcontrol-origin: margin; right: 14px; padding: 0 6px; color: {c['primary']}; }}
QPushButton {{
    background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 9px;
    padding: 8px 14px; color: {c['text']};
}}
QPushButton:hover {{ border-color: {c['primary']}; color: {c['primary']}; }}
QPushButton:pressed {{ background: {c['surface2']}; }}
QPushButton:disabled {{ color: {c['muted']}; background: {c['surface2']}; border-color: {c['border']}; }}
QPushButton[accent="primary"] {{ background: {c['primary']}; border-color: {c['primary']}; color: white; font-weight: 700; }}
QPushButton[accent="primary"]:hover {{ background: {c['primary_dark']}; color: white; }}
QPushButton[accent="danger"] {{ background: {c['danger']}; border-color: {c['danger']}; color: white; }}
QPushButton[accent="success"] {{ background: {c['success']}; border-color: {c['success']}; color: white; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {{
    background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px;
    padding: 7px 10px; selection-background-color: {c['primary']}; selection-color: white;
}}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{ border-color: {c['primary']}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QTableWidget {{
    background: {c['surface']}; alternate-background-color: {c['surface2']};
    gridline-color: {c['border']}; border: 1px solid {c['border']}; border-radius: 10px;
    selection-background-color: {c['primary']}; selection-color: white;
}}
QHeaderView::section {{
    background: {c['surface2']}; color: {c['muted']}; border: none;
    border-bottom: 2px solid {c['border']}; padding: 9px 8px; font-weight: 700;
}}
QTableWidget::item {{ padding: 6px; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {c['muted']}; padding: 10px 16px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {c['primary']}; border-bottom: 2px solid {c['primary']}; font-weight: 700; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QStatusBar {{ background: {c['surface']}; color: {c['muted']}; border-top: 1px solid {c['border']}; }}
QToolTip {{ background: {c['sidebar']}; color: white; border: none; padding: 6px; }}
QMessageBox {{ background: {c['surface']}; }}
"""


def apply_theme(app, mode: str = "light") -> dict:
    colors = DARK if mode == "dark" else LIGHT
    app.setStyleSheet(qss(colors))
    app.setProperty("theme_colors", colors)
    return colors


def color(app, key: str, default="#000000") -> str:
    return (app.property("theme_colors") or LIGHT).get(key, default)
