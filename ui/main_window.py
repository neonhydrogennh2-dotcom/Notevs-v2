"""
ui/main_window.py
Top-level QMainWindow.

Assembles sidebar, toolbar, breadcrumb bar, canvas placeholder and status bar.
Wires all toolbar signals to canvas methods, including new element types.
Preserves user's adjustSize() calls on back-button and add-board button.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStatusBar, QFrame, QApplication,
)
from PySide6.QtCore  import Qt, Signal
from PySide6.QtGui   import QFont

import database.db as db
from ui.sidebar  import Sidebar
from ui.toolbar  import Toolbar
from ui.canvas   import BoardCanvas
from utils.theme import (
    DARK, LIGHT,
    DARK_BG, PANEL_BG, BORDER_COLOR,
    ACCENT, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, CARD_BG,
    get_stylesheet,
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NoteVS")
        self.resize(1300, 690)
        self.setMinimumSize(800, 500)

        self._canvas: BoardCanvas | None = None
        self._board_stack: list[int]     = []
        self._mode = "dark"

        # Apply initial dark theme
        self._apply_theme()

        # ── Central widget layout ─────────────────────────────────────────
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Sidebar ───────────────────────────────────────────────────────
        self._sidebar = Sidebar()
        self._sidebar.boardSelected.connect(self._open_board)
        self._sidebar.searchChanged.connect(self._on_search)
        root.addWidget(self._sidebar)

        # ── Right panel (toolbar + breadcrumb + canvas) ───────────────────
        self._right = QWidget()
        right_lay   = QVBoxLayout(self._right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)

        # Toolbar — wire every signal
        self._toolbar = Toolbar()
        self._toolbar.add_note.connect(self._add_note)
        self._toolbar.add_todo.connect(self._add_todo)
        self._toolbar.add_link.connect(self._add_link)
        self._toolbar.add_image.connect(self._add_image)
        self._toolbar.add_file.connect(self._add_file)
        self._toolbar.add_board.connect(self._add_board)
        self._toolbar.add_video.connect(self._add_video)
        self._toolbar.add_audio.connect(self._add_audio)
        self._toolbar.add_table.connect(self._add_table)
        self._toolbar.add_heading.connect(self._add_heading)
        self._toolbar.add_document.connect(self._add_document)
        self._toolbar.add_column.connect(self._add_column)
        self._toolbar.zoom_in.connect(self._zoom_in)
        self._toolbar.zoom_out.connect(self._zoom_out)
        self._toolbar.zoom_reset.connect(self._zoom_reset)
        self._toolbar.toggle_grid.connect(self._toggle_grid)
        self._toolbar.undo.connect(self._undo)
        self._toolbar.redo.connect(self._redo)
        self._toolbar.theme_changed.connect(self._on_theme_changed)
        self._toolbar.font_changed.connect(self._on_font_changed)
        right_lay.addWidget(self._toolbar)

        # Breadcrumb bar (back button + board path)
        self._breadcrumb_bar = _BreadcrumbBar()
        self._breadcrumb_bar.go_back.connect(self._go_back)
        right_lay.addWidget(self._breadcrumb_bar)

        # Canvas placeholder shown when no board is selected
        self._canvas_placeholder = _EmptyState()
        right_lay.addWidget(self._canvas_placeholder, 1)

        root.addWidget(self._right, 1)

        # ── Status bar ────────────────────────────────────────────────────
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Welcome!  Select or create a board to begin.")
        self._apply_palette(DARK)

        # Auto-open the first board if any exists
        boards = db.get_all_boards()
        if boards:
            self._open_board(boards[0]["id"])
            self._sidebar._select_board(boards[0]["id"])

    # ── Theme ──────────────────────────────────────────────────────────────

    def _apply_theme(self):
        """Set the global QSS stylesheet."""
        self.setStyleSheet(get_stylesheet(self._mode))

    def _on_theme_changed(self, mode: str):
        self._mode = mode
        # Propagate to all widgets in one call
        QApplication.instance().setStyleSheet(get_stylesheet(mode))
        p = DARK if mode == "dark" else LIGHT
        self._apply_palette(p)
        # Update canvas background colour
        if self._canvas:
            from PySide6.QtGui import QColor
            self._canvas.setBackgroundBrush(QColor(p["CANVAS_BG"]))
            self._canvas.scene().update()

    def _apply_palette(self, p: dict):
        """Apply palette-specific inline styles that QSS can't cover."""
        self._right.setStyleSheet(f"background: {p['BG']};")
        self._status.setStyleSheet(f"""
            QStatusBar {{
                background: {p['PANEL']};
                border-top: 1px solid {p['BORDER']};
                color: {p['MUTED']};
                font-size: 11px;
                padding: 0 8px;
            }}
        """)
        self._breadcrumb_bar.apply_palette(p)
        self._canvas_placeholder.apply_palette(p)
        self._sidebar.apply_palette(p)

    def _on_font_changed(self, family: str):
        """Change the application-wide font."""
        app = QApplication.instance()
        f   = app.font()
        f.setFamily(family)
        app.setFont(f)

    # ── Board navigation ───────────────────────────────────────────────────

    def _open_board(self, board_id: int, push_stack: bool = True):
        board = db.get_board(board_id)
        if not board:
            return

        # Tear down the previous canvas
        if self._canvas:
            self._canvas.setParent(None)
            self._canvas.deleteLater()
            self._canvas = None

        # Hide empty-state placeholder
        if self._canvas_placeholder:
            self._canvas_placeholder.setVisible(False)

        # Create new canvas for this board
        self._canvas = BoardCanvas(board_id)
        self._canvas.elementSelected.connect(self._on_element_selected)
        self._canvas.openBoardRequest.connect(self._open_sub_board)
        self._canvas.statusMessage.connect(self._status.showMessage)

        # Apply the current theme's canvas background
        from PySide6.QtGui import QColor
        p = DARK if self._mode == "dark" else LIGHT
        self._canvas.setBackgroundBrush(QColor(p["CANVAS_BG"]))

        # Attach canvas to the right panel layout
        right_widget = self.centralWidget().layout().itemAt(1).widget()
        right_widget.layout().addWidget(self._canvas, 1)

        if push_stack:
            self._board_stack.append(board_id)

        self._breadcrumb_bar.set_stack(self._board_stack, self._mode)
        self._status.showMessage(f"Opened board: {board['name']}")

    def _open_sub_board(self, board_id: int):
        self._open_board(board_id, push_stack=True)

    def _go_back(self):
        if len(self._board_stack) > 1:
            self._board_stack.pop()
            prev_id = self._board_stack[-1]
            self._board_stack.pop()   # will be re-pushed by _open_board
            self._open_board(prev_id, push_stack=True)

    # ── Search ─────────────────────────────────────────────────────────────

    def _on_search(self, query: str):
        if self._canvas:
            if query:
                self._canvas.highlight_search(query)
            else:
                self._canvas.reset_search()

    # ── Element additions ──────────────────────────────────────────────────

    def _add_note(self):
        if self._canvas: self._canvas.add_note()

    def _add_todo(self):
        if self._canvas: self._canvas.add_todo()

    def _add_link(self):
        if self._canvas: self._canvas.add_link()

    def _add_image(self):
        if self._canvas: self._canvas.add_image()

    def _add_file(self):
        if self._canvas: self._canvas.add_file()

    def _add_board(self):
        if self._canvas:
            self._canvas.add_sub_board()
            self._sidebar.refresh_boards()

    def _add_video(self):
        if self._canvas: self._canvas.add_video()

    def _add_audio(self):
        if self._canvas: self._canvas.add_audio()

    def _add_table(self):
        if self._canvas: self._canvas.add_table()

    def _add_heading(self):
        if self._canvas: self._canvas.add_heading()

    def _add_document(self):
        if self._canvas: self._canvas.add_document()

    def _add_column(self):
        if self._canvas: self._canvas.add_column()

    # ── Canvas controls ────────────────────────────────────────────────────

    def _zoom_in(self):
        if self._canvas: self._canvas.zoom_in()

    def _zoom_out(self):
        if self._canvas: self._canvas.zoom_out()

    def _zoom_reset(self):
        if self._canvas: self._canvas.zoom_reset()

    def _toggle_grid(self):
        if self._canvas: self._canvas.toggle_grid()

    def _undo(self):
        if self._canvas: self._canvas._undo_stack.undo()

    def _redo(self):
        if self._canvas: self._canvas._undo_stack.redo()

    def _on_element_selected(self, data: dict):
        if data:
            self._status.showMessage(
                f"Selected: {data.get('type','?')} — "
                f"{data.get('content','')[:40]}"
            )
        else:
            self._status.showMessage("Ready")


# ── Breadcrumb bar ─────────────────────────────────────────────────────────────
class _BreadcrumbBar(QWidget):
    go_back = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self._p = DARK

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(4)

        # Back button — preserves user's adjustSize() call intent
        self._back_btn = QPushButton("←")
        self._back_btn.adjustSize()
        self._back_btn.setToolTip("Go back")
        self._back_btn.clicked.connect(self.go_back)
        lay.addWidget(self._back_btn)

        # Crumb labels injected here
        self._crumb_widget = QWidget()
        self._crumb_widget.setStyleSheet("background: transparent;")
        self._crumb_lay = QHBoxLayout(self._crumb_widget)
        self._crumb_lay.setContentsMargins(0, 0, 0, 0)
        self._crumb_lay.setSpacing(4)
        lay.addWidget(self._crumb_widget)
        lay.addStretch()

        self.apply_palette(DARK)

    def apply_palette(self, p: dict):
        self._p = p
        self.setStyleSheet(f"""
            _BreadcrumbBar {{
                background: {p['PANEL']};
                border-bottom: 1px solid {p['BORDER']};
            }}
        """)
        self._back_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {p['BORDER']};
                border-radius: 5px;
                color: {p['TEXT2']};
                font-size: 13px;
                padding: 2px 7px;
            }}
            QPushButton:hover {{
                background: {p['CARD']};
                color: {p['ACCENT']};
                border-color: {p['ACCENT']};
            }}
            QPushButton:disabled {{
                color: {p['MUTED']};
                border-color: {p['DISABLED']};
            }}
        """)

    def set_stack(self, stack: list[int], mode: str = "dark"):
        p = DARK if mode == "dark" else LIGHT
        self._p = p
        self.apply_palette(p)

        # Clear existing crumbs
        for i in reversed(range(self._crumb_lay.count())):
            w = self._crumb_lay.itemAt(i)
            if w and w.widget():
                w.widget().deleteLater()

        self._back_btn.setEnabled(len(stack) > 1)

        for i, board_id in enumerate(stack):
            board   = db.get_board(board_id)
            if not board:
                continue
            is_last = i == len(stack) - 1
            lbl     = QLabel(board["name"])
            lbl.setStyleSheet(
                f"color: {p['ACCENT'] if is_last else p['MUTED']};"
                f" font-size: 11px; font-weight: {'600' if is_last else '400'};"
                " background: transparent;"
            )
            self._crumb_lay.addWidget(lbl)
            if not is_last:
                sep = QLabel("›")
                sep.setStyleSheet(
                    f"color: {p['MUTED']}; background: transparent; font-size: 11px;"
                )
                self._crumb_lay.addWidget(sep)


# ── Empty-state placeholder ────────────────────────────────────────────────────
class _EmptyState(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)

        self._icon = QLabel("⊞")
        self._icon.setFont(QFont("Segoe UI", 64))
        self._icon.setAlignment(Qt.AlignCenter)

        self._lbl = QLabel(
            "Select a board from the sidebar\nor create a new one to begin."
        )
        self._lbl.setAlignment(Qt.AlignCenter)

        lay.addWidget(self._icon)
        lay.addWidget(self._lbl)
        self.apply_palette(DARK)

    def apply_palette(self, p: dict):
        self.setStyleSheet(f"background: {p['BG']};")
        self._icon.setStyleSheet(f"color: {p['EMPTY_ICON']}; background: transparent;")
        self._lbl.setStyleSheet(
            f"color: {p['MUTED']}; font-size: 13px; background: transparent;"
        )
