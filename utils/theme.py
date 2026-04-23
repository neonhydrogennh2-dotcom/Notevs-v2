"""
utils/theme.py
Central design tokens: colors, fonts, sizes, and QSS stylesheets.
Supports dark and light modes via get_stylesheet(mode).
"""

# ── Dark Palette ──────────────────────────────────────────────────────────────
DARK = {
    "BG":         "#000000",
    "PANEL":      "#17171f",
    "SIDEBAR":    "#111118",
    "CARD":       "#1e1e28",
    "CARD_HOVER": "#25252f",
    "BORDER":     "#2a2a38",
    "ACCENT":     "#765df4",
    "ACCENT_H":   "#6fa3ff",
    "ACCENT_DIM": "#1e3460",
    "TEXT1":      "#e8e8f0",
    "TEXT2":      "#8888aa",
    "MUTED":      "#55556a",
    "DANGER":     "#f05050",
    "DANGER_BG":  "#2d1414",
    "CANVAS_BG":  "#0f0f13",
    "DISABLED":   "#22222f",
    "EMPTY_ICON": "#2a2a40",
}

# ── Light Palette ─────────────────────────────────────────────────────────────
LIGHT = {
    "BG":         "#eaeaf1",
    "PANEL":      "#ffffff",
    "SIDEBAR":    "#E4E4EF",
    "CARD":       "#ffffff",
    "CARD_HOVER": "#e2e2ec",
    "BORDER":     "#ccccdc",
    "ACCENT":     "#5053FC",
    "ACCENT_H":   "#2260e0",
    "ACCENT_DIM": "#d0e0ff",
    "TEXT1":      "#1a1a2e",
    "TEXT2":      "#55556a",
    "MUTED":      "#9090aa",
    "DANGER":     "#d93030",
    "DANGER_BG":  "#fde8e8",
    "CANVAS_BG":  "#e8e8f2",
    "DISABLED":   "#c8c8d8",
    "EMPTY_ICON": "#c0c0d8",
}

# ── Note colors ───────────────────────────────────────────────────────────────
NOTE_COLORS_DARK = {
    "yellow": "#2d2a1a",
    "blue":   "#1a2040",
    "green":  "#1a2d1e",
    "purple": "#2a1a40",
    "red":    "#2d1a1a",
    "white":  "#22222e",
    "teal":   "#1a2d2d",
    "orange": "#2d2218",
    "black":   "#000000",
}

NOTE_COLORS_LIGHT = {
    "yellow": "#fffbe6",
    "blue":   "#e8f0ff",
    "green":  "#e8faf0",
    "purple": "#f3e8ff",
    "red":    "#ffe8e8",
    "white":  "#ffffff",
    "teal":   "#e8fafa",
    "orange": "#fff3e8",
}

NOTE_ACCENT_COLORS = {
    "yellow": "#f5c842",
    "blue":   "#4f8cff",
    "green":  "#3dd68c",
    "purple": "#a855f7",
    "red":    "#f05050",
    "white":  "#aaaacc",
    "teal":   "#2dd4bf",
    "orange": "#f5a623",
}

# ── Runtime mode tracker ──────────────────────────────────────────────────────
_current_mode = "dark"

def current_mode() -> str:
    return _current_mode

def note_colors_for_mode(mode: str = None) -> dict:
    m = mode or _current_mode
    return NOTE_COLORS_DARK if m == "dark" else NOTE_COLORS_LIGHT

# ── Backward-compat module-level aliases (dark defaults) ─────────────────────
DARK_BG        = DARK["BG"]
LIGHT_BG       = LIGHT["BG"]
PANEL_BG       = DARK["PANEL"]
SIDEBAR_BG     = DARK["SIDEBAR"]
LIGHT_SIDEBAR_BG = LIGHT["SIDEBAR"]
WHITE           = LIGHT["CARD"]
CARD_BG        = DARK["CARD"]
CARD_HOVER     = DARK["CARD_HOVER"]
BORDER_COLOR   = DARK["BORDER"]
ACCENT         = DARK["ACCENT"]
ACCENT_HOVER   = DARK["ACCENT_H"]
ACCENT_DIM     = DARK["ACCENT_DIM"]
TEXT_PRIMARY   = DARK["TEXT1"]
TEXT_SECONDARY = DARK["TEXT2"]
TEXT_MUTED     = DARK["MUTED"]
DANGER         = DARK["DANGER"]
SELECTION      = "#4f8cff44"
SUCCESS        = "#3dd68c"
WARNING        = "#f5a623"
NOTE_COLORS    = NOTE_COLORS_DARK


def get_stylesheet(mode: str = "dark") -> str:
    """
    Return the full app QSS for 'dark' or 'light'.
    Usage:  QApplication.instance().setStyleSheet(get_stylesheet('light'))
    """
    global _current_mode
    _current_mode = mode
    p = DARK if mode == "dark" else LIGHT

    return f"""
/* ── Global ── */
* {{
    font-family: 'Segoe UI', 'SF Pro Text', sans-serif;
    color: {p['TEXT1']};
    outline: none;
}}

#Sidebar {{
    background: {p['SIDEBAR']};
    border-right: 1px solid {p['BORDER']};
}}

QMainWindow, QDialog {{
    background: {p['BG']};
}}
QWidget {{
    background: transparent;
}}

/* ── Scrollbars ── */
QScrollBar:vertical, QScrollBar:horizontal {{
    background: {p['BG']};
    width: 6px;
    height: 6px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {p['BORDER']};
    border-radius: 3px;
    min-height: 20px;
    min-width: 20px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: {p['MUTED']};
}}
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
    border: none;
}}

/* ── Buttons ── */
QPushButton {{
    background: {p['CARD']};
    border: 1px solid {p['BORDER']};
    border-radius: 6px;
    padding: 6px 14px;
    font-size: 13px;
    color: {p['TEXT1']};
}}
QPushButton:hover {{
    background: {p['CARD_HOVER']};
    border-color: {p['ACCENT']};
}}
QPushButton:pressed {{
    background: {p['ACCENT_DIM']};
}}
QPushButton#accentBtn {{
    background: {p['ACCENT']};
    border: none;
    color: white;
    font-weight: 600;
}}
QPushButton#accentBtn:hover {{
    background: {p['ACCENT_H']};
}}
QPushButton#dangerBtn {{
    background: transparent;
    border: 1px solid {p['DANGER']};
    color: {p['DANGER']};
}}
QPushButton#dangerBtn:hover {{
    background: {p['DANGER_BG']};
}}
QPushButton#toolBtn {{
    background: transparent;
    border: none;
    padding: 6px;
    border-radius: 6px;
    font-size: 16px;
}}
QPushButton#toolBtn:hover {{
    background: {p['CARD_HOVER']};
}}
QPushButton#toolBtn:checked {{
    background: {p['ACCENT_DIM']};
    color: {p['ACCENT']};
}}

/* ── Inputs ── */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background: {p['CARD']};
    border: 1px solid {p['BORDER']};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 13px;
    color: {p['TEXT1']};
    selection-background-color: {p['ACCENT_DIM']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {p['ACCENT']};
}}

/* ── Labels ── */
QLabel {{
    color: {p['TEXT1']};
    background: transparent;
}}
QLabel#muted {{
    color: {p['MUTED']};
    font-size: 11px;
}}
QLabel#heading {{
    font-size: 18px;
    font-weight: 700;
    color: {p['TEXT1']};
}}
QLabel#subheading {{
    font-size: 13px;
    font-weight: 600;
    color: {p['TEXT2']};
    letter-spacing: 0.5px;
}}

/* ── List widgets ── */
QListWidget {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget::item {{
    background: transparent;
    border-radius: 8px;
    padding: 6px 10px;
    margin: 1px 4px;
    color: {p['TEXT1']};
}}
QListWidget::item:hover {{
    background: {p['CARD_HOVER']};
}}
QListWidget::item:selected {{
    background: {p['ACCENT_DIM']};
    color: {p['ACCENT']};
}}

/* ── Menus ── */
QMenu {{
    background: {p['PANEL']};
    border: 1px solid {p['BORDER']};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 7px 20px 7px 12px;
    border-radius: 5px;
    font-size: 13px;
    color: {p['TEXT1']};
}}
QMenu::item:selected {{
    background: {p['CARD_HOVER']};
}}
QMenu::separator {{
    height: 1px;
    background: {p['BORDER']};
    margin: 4px 8px;
}}

/* ── Tooltips ── */
QToolTip {{
    background: {p['PANEL']};
    border: 1px solid {p['BORDER']};
    color: {p['TEXT1']};
    border-radius: 5px;
    padding: 4px 8px;
    font-size: 12px;
}}

/* ── Graphics View ── */
QGraphicsView {{
    border: none;
    background: {p['CANVAS_BG']};
}}

/* ── Splitter ── */
QSplitter::handle {{
    background: {p['BORDER']};
}}
QSplitter::handle:horizontal {{
    width: 1px;
}}

/* ── Checkboxes ── */
QCheckBox {{
    color: {p['TEXT1']};
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {p['BORDER']};
    border-radius: 3px;
    background: {p['CARD']};
}}
QCheckBox::indicator:checked {{
    background: {p['ACCENT']};
    border-color: {p['ACCENT']};
}}

/* ── Message boxes ── */
QMessageBox {{
    background: {p['PANEL']};
}}
QMessageBox QLabel {{
    color: {p['TEXT1']};
}}

/* ── Dialog buttons ── */
QDialogButtonBox QPushButton {{
    min-width: 80px;
}}
"""

# Default (dark) stylesheet for initial app load
APP_QSS = get_stylesheet("dark")
