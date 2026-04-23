"""
ui/toolbar.py
Top toolbar.

Fix: secondary element types (Video, Audio, Table, Heading, Document, Column)
moved into a "More ▾" dropdown button so the toolbar doesn't overflow at
normal window widths. Core daily-use elements (Note, To-Do, Link, Image,
File, Board) remain as direct buttons.

Font picker is a QComboBox with a curated list of cross-platform fonts.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel,
    QFrame, QComboBox, QMenu,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui  import QFont

from utils.theme import DARK, LIGHT

# Fonts likely available on Windows / macOS / most Linux desktops
FONT_OPTIONS = [
    "Segoe UI", "Arial", "Verdana", "Tahoma", "Trebuchet MS",
    "Georgia", "Times New Roman", "Courier New", "Consolas",
    "Calibri", "Comic Sans MS", "Impact",
]


def _make_qss(p: dict) -> tuple[str, str, str]:
    btn = f"""
QPushButton {{
    background: transparent; border: none; border-radius: 6px;
    padding: 5px 9px; font-size: 12px; color: {p['TEXT1']}; min-height: 28px;
}}
QPushButton:hover  {{ background: {p['CARD_HOVER']}; }}
QPushButton:pressed {{ background: {p['ACCENT_DIM']}; }}
"""
    icon = f"""
QPushButton {{
    background: transparent; border: none; border-radius: 6px;
    padding: 4px 7px; font-size: 17px; color: {p['TEXT1']};
    min-width: 30px; min-height: 28px;
}}
QPushButton:hover {{ background: {p['CARD_HOVER']}; }}
"""
# accent here is used for some of the toolbar buttons, the background is assigned 
# TEXT1 and color as BG due to the inverse in the theme.py for light and dark mode 
    accent = f"""
QPushButton {{
    background: {p['TEXT1']}; border: none; border-radius: 6px;
    padding: 5px 12px; font-size: 12px; font-weight: 600;
    color: {p['BG']}; min-height: 28px;
}}
QPushButton:hover {{ background: {p['ACCENT_H']}; }}
"""
    return btn, icon, accent


class Toolbar(QWidget):
    # Core element signals
    add_note     = Signal()
    add_todo     = Signal()
    add_link     = Signal()
    add_image    = Signal()
    add_file     = Signal()
    add_board    = Signal()
    # Secondary element signals (triggered from dropdown)
    add_video    = Signal()
    add_audio    = Signal()
    add_table    = Signal()
    add_heading  = Signal()
    add_document = Signal()
    add_column   = Signal()
    # Control signals
    zoom_in       = Signal()
    zoom_out      = Signal()
    zoom_reset    = Signal()
    toggle_grid   = Signal()
    undo          = Signal()
    redo          = Signal()
    theme_changed = Signal(str)   # "dark" / "light"
    font_changed  = Signal(str)   # font family name

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(50)
        self._mode     = "dark"
        self._all_btns: list[tuple[QPushButton, str]] = []
        self._vlines:   list[QFrame]   = []
        self._combos:   list[QComboBox] = []

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(3)
        self._lay = lay

        self._build_ui()
        self._apply_palette(DARK)

    def _build_ui(self):
        lay = self._lay

        # ── ADD label ─────────────────────────────────────────────────────
        self._add_lbl = QLabel("ADD")
        lay.addWidget(self._add_lbl)
        lay.addSpacing(2)

        # ── Core element buttons (always visible) ──────────────────────────
        self._btn(lay, "📝 Note",  self.add_note,  "accent")
        self._btn(lay, "☑ To-Do", self.add_todo,  "accent")
        self._btn(lay, "🔗 Link",  self.add_link,  "accent")
        self._btn(lay, "🖼 Image", self.add_image, "accent")
        self._btn(lay, "📎 File",  self.add_file,  "accent")
        self._btn(lay, "⊞ Board",  self.add_board, "accent")

        # ── "More ▾" dropdown for secondary elements ───────────────────────
        self._more_btn = QPushButton("More ▾")
        self._more_btn.setToolTip("More element types")
        self._more_btn.clicked.connect(self._show_more_menu)
        self._all_btns.append((self._more_btn, "accent"))
        lay.addWidget(self._more_btn)

        lay.addWidget(self._vl())
        lay.addStretch()

        # ── Font picker ────────────────────────────────────────────────────
        self._font_lbl = QLabel("Font:")
        self._font_lbl.setStyleSheet("background: transparent; font-size: 10px;")
        lay.addWidget(self._font_lbl)

        self._font_combo = QComboBox()
        self._font_combo.setFixedWidth(120)
        self._font_combo.setToolTip("Change app font")
        for f in FONT_OPTIONS:
            self._font_combo.addItem(f)
        self._font_combo.currentTextChanged.connect(self.font_changed)
        self._combos.append(self._font_combo)
        lay.addWidget(self._font_combo)

        lay.addWidget(self._vl())

        # ── Undo / Redo ────────────────────────────────────────────────────
        self._btn(lay, "↩", self.undo, "icon", "Undo  Ctrl+Z")
        self._btn(lay, "↪", self.redo, "icon", "Redo  Ctrl+Y")
        lay.addWidget(self._vl())

        # ── Grid ──────────────────────────────────────────────────────────
        self._btn(lay, "⊹", self.toggle_grid, "icon", "Toggle grid")
        lay.addWidget(self._vl())

        # ── Zoom ──────────────────────────────────────────────────────────
        self._btn(lay, "−",   self.zoom_out,   "icon",   "Zoom out")
        self._btn(lay, "1:1", self.zoom_reset, "normal", "Reset zoom  Ctrl+0")
        self._btn(lay, "+",   self.zoom_in,    "icon",   "Zoom in")
        lay.addWidget(self._vl())

        # ── Theme toggle ───────────────────────────────────────────────────
        self._theme_btn = QPushButton("☀")
        self._theme_btn.setFixedSize(32, 32)
        self._theme_btn.setCheckable(True)
        self._theme_btn.setToolTip("Switch to light mode")
        self._theme_btn.toggled.connect(self._on_theme_toggle)
        self._all_btns.append((self._theme_btn, "icon"))
        lay.addWidget(self._theme_btn)

    def _show_more_menu(self):
        """Show a dropdown QMenu with secondary element types."""
        menu = QMenu(self)
        p    = DARK if self._mode == "dark" else LIGHT
        menu.setStyleSheet(f"""
            QMenu {{
                background: {p['PANEL']}; border: 1px solid {p['BORDER']};
                border-radius: 8px; padding: 4px;
            }}
            QMenu::item {{
                padding: 7px 18px; border-radius: 5px;
                font-size: 13px; color: {p['TEXT1']};
            }}
            QMenu::item:selected {{ background: {p['CARD_HOVER']}; }}
        """)
        menu.addAction("🎬  Video",   lambda: self.add_video.emit())
        menu.addAction("🎵  Audio",    lambda: self.add_audio.emit())
        menu.addAction("📊  Table",    lambda: self.add_table.emit())
        menu.addAction("T   Heading",  lambda: self.add_heading.emit())
        menu.addAction("📄  Document", lambda: self.add_document.emit())
        menu.addAction("▥   Column",   lambda: self.add_column.emit())
        # Show below the button
        btn_pos = self._more_btn.mapToGlobal(
            self._more_btn.rect().bottomLeft()
        )
        menu.exec(btn_pos)

    def _btn(self, layout, text: str, signal, style: str = "normal",
             tooltip: str = "") -> QPushButton:
        b = QPushButton(text)
        if tooltip:
            b.setToolTip(tooltip)
        b.clicked.connect(signal)
        layout.addWidget(b)
        self._all_btns.append((b, style))
        return b

    def _vl(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.VLine)
        f.setFixedWidth(1)
        self._vlines.append(f)
        return f

    def _on_theme_toggle(self, checked: bool):
        if checked:
            self._mode = "light"
            self._theme_btn.setText("🌙")
            self._theme_btn.setToolTip("Switch to dark mode")
            self._apply_palette(LIGHT)
            self.theme_changed.emit("light")
        else:
            self._mode = "dark"
            self._theme_btn.setText("☀")
            self._theme_btn.setToolTip("Switch to light mode")
            self._apply_palette(DARK)
            self.theme_changed.emit("dark")

    def _apply_palette(self, p: dict):
        btn_qss, icon_qss, accent_qss = _make_qss(p)

        self.setStyleSheet(f"""
            Toolbar {{
                background: {p['PANEL']};
                border-bottom: 1px solid {p['BORDER']};
            }}
        """)

        lbl_css = (f"color: {p['MUTED']}; font-size: 9px; font-weight: 700;"
                   f" letter-spacing: 1px; background: transparent;")
        self._add_lbl.setStyleSheet(lbl_css)
        if hasattr(self, "_font_lbl"):
            self._font_lbl.setStyleSheet(
                f"color: {p['MUTED']}; font-size: 10px; background: transparent;"
            )

        for vl in self._vlines:
            vl.setStyleSheet(f"background: {p['BORDER']}; border: none;")

        sm = {"normal": btn_qss, "icon": icon_qss, "accent": accent_qss}
        for btn, style in self._all_btns:
            btn.setStyleSheet(sm.get(style, btn_qss))

        for combo in self._combos:
            combo.setStyleSheet(f"""
                QComboBox {{
                    background: {p['CARD']}; border: 1px solid {p['BORDER']};
                    border-radius: 5px; padding: 3px 8px;
                    color: {p['TEXT1']}; font-size: 11px;
                }}
                QComboBox::drop-down {{ border: none; width: 18px; }}
                QComboBox QAbstractItemView {{
                    background: {p['PANEL']}; border: 1px solid {p['BORDER']};
                    color: {p['TEXT1']};
                    selection-background-color: {p['ACCENT_DIM']};
                }}
            """)
