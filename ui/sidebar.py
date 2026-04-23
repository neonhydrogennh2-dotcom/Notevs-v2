"""
ui/sidebar.py
Left sidebar.

Fixes in this version:
  - Board pills now correctly show coloured backgrounds (was broken by
    QColor.HexArgb name() not being supported on all Qt builds).
    Colours are now set as explicit rgba() strings.
  - Move Up / Move Down call db.move_board_up / db.move_board_down which
    swap sort_order values (proper DB-level reorder, not a timestamp hack).
  - apply_palette() covers every sub-widget: header, search, section row,
    scroll area, list background, footer — fixing the light-mode sidebar bug.
  - Width kept at 190 px.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMenu, QFrame, QScrollArea,
)
from PySide6.QtCore  import Qt, Signal
from PySide6.QtGui   import QFont, QColor

import database.db as db
from utils.theme import (
    DARK, LIGHT,
    SIDEBAR_BG, CARD_BG, CARD_HOVER, BORDER_COLOR,
    ACCENT, ACCENT_DIM, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    PANEL_BG,
)

# Eight hues that cycle based on board id — deterministic, always same colour
PILL_HUES = [210, 155, 270, 35, 0, 185, 300, 55]


def _pill_colors(board_id: int, mode: str) -> tuple[str, str]:
    """Return (bg_rgba_str, text_hex_str) for a board pill."""
    hue = PILL_HUES[board_id % len(PILL_HUES)]
    if mode == "dark":
        bg  = QColor.fromHsl(hue, 70, 45) 
        txt = QColor.fromHsl(hue, 120, 210)
    else:
        bg  = QColor.fromHsl(hue, 55, 225)
        txt = QColor.fromHsl(hue, 90, 65)
    # Use rgba() string — universally supported, no HexArgb issues
    bg_str  = f"rgba({bg.red()},{bg.green()},{bg.blue()},180)"
    txt_str = txt.name()
    return bg_str, txt_str


class Sidebar(QWidget):
    boardSelected = Signal(int)
    searchChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(190)
        self.setObjectName("Sidebar")

        self._active_board_id: int | None = None
        self._board_buttons: dict[int, "_BoardPill"] = {}
        self._mode = "dark"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Logo header ────────────────────────────────────────────────────
        self._header = QWidget()
        self._header.setFixedHeight(50)
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(14, 0, 14, 0)
        self._logo = QLabel("⊞  NoteVS")
        self._logo.setFont(QFont("Segoe UI", 13, QFont.Bold))
        hl.addWidget(self._logo)
        hl.addStretch()
        root.addWidget(self._header)
        root.addWidget(self._divider())

        # ── Search ─────────────────────────────────────────────────────────
        self._search_wrap = QWidget()
        sl = QHBoxLayout(self._search_wrap)
        sl.setContentsMargins(10, 6, 10, 6)
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Search…")
        self._search.textChanged.connect(self.searchChanged)
        sl.addWidget(self._search)
        root.addWidget(self._search_wrap)
        root.addWidget(self._divider())

        # ── Section header + add board button ──────────────────────────────
        self._sec_row = QWidget()
        sec_lay = QHBoxLayout(self._sec_row)
        sec_lay.setContentsMargins(14, 8, 10, 5)
        self._sec_lbl = QLabel("BOARDS")
        self._add_btn = QPushButton("+")
        self._add_btn.adjustSize()
        self._add_btn.setToolTip("New Board")
        self._add_btn.clicked.connect(self._new_board)
        sec_lay.addWidget(self._sec_lbl)
        sec_lay.addStretch()
        sec_lay.addWidget(self._add_btn)
        root.addWidget(self._sec_row)

        # ── Board list ─────────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(6, 0, 6, 6)
        self._list_layout.setSpacing(3)
        self._list_layout.addStretch()

        self._scroll.setWidget(self._list_widget)
        root.addWidget(self._scroll, 1)
        root.addWidget(self._divider())

        # ── Footer ─────────────────────────────────────────────────────────
        self._footer = QWidget()
        self._footer.setFixedHeight(38)
        fl = QHBoxLayout(self._footer)
        fl.setContentsMargins(12, 0, 12, 0)
        self._ver_lbl = QLabel("v1.0  •  SQLite")
        fl.addWidget(self._ver_lbl)
        fl.addStretch()
        root.addWidget(self._footer)

        self.apply_palette(DARK)
        self.refresh_boards()

    # ── Helpers ────────────────────────────────────────────────────────────
    def _divider(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setFixedHeight(1)
        f.setStyleSheet(f"background: {BORDER_COLOR}; border: none;")
        return f

    # ── Board management ───────────────────────────────────────────────────
    def refresh_boards(self, parent_id=None):
        """Rebuild the board pill list from DB."""
        for i in reversed(range(self._list_layout.count())):
            w = self._list_layout.itemAt(i)
            if w and w.widget():
                w.widget().deleteLater()
        self._board_buttons.clear()

        boards = db.get_all_boards(parent_id)
        if not boards:
            ph = QLabel("No boards yet.\nClick + to create one.")
            ph.setAlignment(Qt.AlignCenter)
            ph.setStyleSheet(
                f"color: {TEXT_MUTED}; font-size: 10px; background: transparent;"
            )
            self._list_layout.insertWidget(0, ph)
            return

        for b in boards:
            pill = _BoardPill(b, self._mode)
            pill.clicked_board.connect(self._select_board)
            pill.rename_board.connect(self._rename_board)
            pill.delete_board.connect(self._delete_board)
            pill.move_up.connect(self._move_up)
            pill.move_down.connect(self._move_down)
            self._list_layout.insertWidget(self._list_layout.count() - 1, pill)
            self._board_buttons[b["id"]] = pill

        # Re-highlight the active board after rebuild
        if self._active_board_id in self._board_buttons:
            self._board_buttons[self._active_board_id].set_active(True)

    def _select_board(self, board_id: int):
        self._active_board_id = board_id
        for bid, pill in self._board_buttons.items():
            pill.set_active(bid == board_id)
        self.boardSelected.emit(board_id)

    def _new_board(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Board", "Board name:")
        if ok and name.strip():
            db.create_board(name=name.strip())
            self.refresh_boards()

    def _rename_board(self, board_id: int):
        from ui.dialogs import RenameDialog
        board = db.get_board(board_id)
        if not board:
            return
        dlg = RenameDialog(board["name"])
        if dlg.exec():
            db.update_board(board_id, name=dlg.new_name)
            self.refresh_boards()

    def _delete_board(self, board_id: int):
        from PySide6.QtWidgets import QMessageBox
        ans = QMessageBox.question(
            self, "Delete Board",
            "Delete this board and all its elements?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            if self._active_board_id == board_id:
                self._active_board_id = None
            db.delete_board(board_id)
            self.refresh_boards()

    def _move_up(self, board_id: int):
        db.move_board_up(board_id)
        self.refresh_boards()

    def _move_down(self, board_id: int):
        db.move_board_down(board_id)
        self.refresh_boards()

    # ── Theme ──────────────────────────────────────────────────────────────
    def apply_palette(self, p: dict):
        """Re-skin every sidebar widget for the given palette."""
        mode = "dark" if p is DARK else "light"
        self._mode = mode

        self.setStyleSheet(f"""
            Sidebar {{
                background: {p['SIDEBAR']};
                border-right: 1px solid {p['BORDER']};
            }}
        """)
        self._header.setStyleSheet(f"background: {p['SIDEBAR']};")
        self._logo.setStyleSheet(f"color: {p['ACCENT']}; background: transparent;")

        self._search_wrap.setStyleSheet(f"background: {p['SIDEBAR']};")
        self._search.setStyleSheet(f"""
            QLineEdit {{
                background: {p['CARD']};
                border: 1px solid {p['BORDER']};
                border-radius: 7px;
                padding: 5px 9px;
                color: {p['TEXT1']};
                font-size: 11px;
            }}
            QLineEdit:focus {{ border-color: {p['ACCENT']}; }}
        """)

        self._sec_row.setStyleSheet(f"background: {p['SIDEBAR']};")
        self._sec_lbl.setStyleSheet(
            f"color: {p['MUTED']}; font-size: 9px; font-weight: 700;"
            f" letter-spacing: 1px; background: transparent;"
        )
        self._add_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {p['BORDER']};
                border-radius: 4px;
                color: {p['TEXT2']};
                font-size: 14px; font-weight: bold;
            }}
            QPushButton:hover {{
                background: {p['CARD_HOVER']};
                color: {p['ACCENT']};
                border-color: {p['ACCENT']};
            }}
        """)

        self._scroll.setStyleSheet(f"""
            QScrollArea {{ border: none; background: {p['SIDEBAR']}; }}
            QScrollBar:vertical {{
                background: {p['SIDEBAR']}; width: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: {p['BORDER']}; border-radius: 2px;
            }}
        """)
        self._list_widget.setStyleSheet(f"background: {p['SIDEBAR']};")

        self._footer.setStyleSheet(f"background: {p['SIDEBAR']};")
        self._ver_lbl.setStyleSheet(
            f"color: {p['MUTED']}; font-size: 9px; background: transparent;"
        )

        for pill in self._board_buttons.values():
            pill.apply_palette(p, mode)


# ── Board pill widget ──────────────────────────────────────────────────────────
class _BoardPill(QWidget):
    """
    Single board entry styled as a coloured pill.
    Each board id maps to a deterministic hue.
    """
    clicked_board = Signal(int)
    rename_board  = Signal(int)
    delete_board  = Signal(int)
    move_up       = Signal(int)
    move_down     = Signal(int)

    def __init__(self, board: dict, mode: str = "dark", parent=None):
        super().__init__(parent)
        self._board_id = board["id"]
        self._name     = board["name"]
        self._active   = False
        self._mode     = mode

        self.setFixedHeight(32)
        self.setCursor(Qt.PointingHandCursor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._ctx_menu)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(6)

        self._dot = QLabel("●")
        self._dot.setFixedWidth(12)
        self._dot.setAlignment(Qt.AlignCenter)

        self._lbl = QLabel(self._name)
        self._lbl.setMaximumWidth(130)

        lay.addWidget(self._dot)
        lay.addWidget(self._lbl, 1)

        self._apply_look()

    def _apply_look(self):
        bg_str, txt_str = _pill_colors(self._board_id, self._mode)

        if self._active:
            # Full opacity when active
            self.setStyleSheet(f"""
                _BoardPill {{
                    background: {bg_str};
                    border-radius: 8px;
                    border: 1.5px solid {txt_str};
                }}
            """)
            self._lbl.setStyleSheet(
                f"color: {txt_str}; background: transparent;"
                f" font-size: 12px; font-weight: 600;"
            )
            self._dot.setStyleSheet(
                f"color: {txt_str}; background: transparent; font-size: 7px;"
            )
        else:
            # Dimmer inactive — use lower alpha via rgba
            dim_bg = _pill_colors(self._board_id, self._mode)[0].replace(",180)", ",60)")
            self.setStyleSheet(f"""
                _BoardPill {{
                    background: {dim_bg};
                    border-radius: 8px;
                    border: 1px solid transparent;
                }}
                _BoardPill:hover {{
                    background: {bg_str};
                }}
            """)
            self._lbl.setStyleSheet(
                f"color: {TEXT_SECONDARY}; background: transparent; font-size: 12px;"
            )
            dot_c = _pill_colors(self._board_id, self._mode)[0]
            # Use accent colour for dot in inactive state so it's still visible
            self._dot.setStyleSheet(
                f"color: {txt_str}; background: transparent; font-size: 7px;"
            )

    def set_active(self, active: bool):
        self._active = active
        self._apply_look()

    def apply_palette(self, p: dict, mode: str = "dark"):
        self._mode = mode
        self._apply_look()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked_board.emit(self._board_id)
        super().mousePressEvent(event)

    def _ctx_menu(self, pos):
        p = DARK if self._mode == "dark" else LIGHT
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {p['PANEL']}; border: 1px solid {p['BORDER']};
                border-radius: 7px; padding: 3px;
            }}
            QMenu::item {{
                padding: 6px 14px; border-radius: 4px;
                color: {p['TEXT1']}; font-size: 12px;
            }}
            QMenu::item:selected {{ background: {p['CARD_HOVER']}; }}
        """)
        menu.addAction("✏  Rename",    lambda: self.rename_board.emit(self._board_id))
        menu.addAction("↑  Move Up",   lambda: self.move_up.emit(self._board_id))
        menu.addAction("↓  Move Down", lambda: self.move_down.emit(self._board_id))
        menu.addSeparator()
        menu.addAction("🗑  Delete",   lambda: self.delete_board.emit(self._board_id))
        menu.exec(self.mapToGlobal(pos))
