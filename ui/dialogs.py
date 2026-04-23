"""
ui/dialogs.py
Modal dialogs: TodoEditor, BoardRenameDialog, SearchDialog.
"""

from __future__ import annotations
import json

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QCheckBox,
    QDialogButtonBox, QWidget, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from utils.theme import (
    PANEL_BG, CARD_BG, BORDER_COLOR, ACCENT, TEXT_PRIMARY,
    TEXT_SECONDARY, TEXT_MUTED, DARK_BG,
)


class _BaseDialog(QDialog):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setStyleSheet(f"""
            QDialog {{
                background: {PANEL_BG};
                border-radius: 12px;
            }}
            QLabel {{ color: {TEXT_PRIMARY}; background: transparent; }}
            QLineEdit {{
                background: {CARD_BG};
                border: 1px solid {BORDER_COLOR};
                border-radius: 6px;
                padding: 6px 10px;
                color: {TEXT_PRIMARY};
                font-size: 13px;
            }}
            QLineEdit:focus {{ border-color: {ACCENT}; }}
            QPushButton {{
                background: {CARD_BG};
                border: 1px solid {BORDER_COLOR};
                border-radius: 6px;
                padding: 6px 14px;
                color: {TEXT_PRIMARY};
                font-size: 13px;
            }}
            QPushButton:hover {{ border-color: {ACCENT}; }}
            QPushButton#ok {{
                background: {ACCENT};
                border: none;
                color: white;
                font-weight: 600;
            }}
            QPushButton#ok:hover {{ background: #6fa3ff; }}
        """)
        self.setMinimumWidth(400)


class TodoDialog(_BaseDialog):
    """Edit a to-do element's list of items."""

    def __init__(self, data: dict, parent=None):
        super().__init__("Edit To-Do List", parent)
        self._data = {k: v for k, v in data.items()}
        meta = self._data.get("meta", {})
        if isinstance(meta, str):
            meta = json.loads(meta)
        self._items: list[dict] = list(meta.get("items", []))
        self.result_data = self._data

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        lbl = QLabel("To-Do List")
        lbl.setFont(QFont("Segoe UI", 14, QFont.Bold))
        layout.addWidget(lbl)

        # Item list
        self._list = QListWidget()
        self._list.setStyleSheet(f"""
            QListWidget {{
                background: {CARD_BG};
                border: 1px solid {BORDER_COLOR};
                border-radius: 8px;
                padding: 4px;
            }}
            QListWidget::item {{
                background: transparent;
                border-radius: 5px;
                padding: 4px;
                color: {TEXT_PRIMARY};
            }}
            QListWidget::item:hover {{ background: #25252f; }}
        """)
        self._list.setMinimumHeight(200)
        layout.addWidget(self._list)
        self._refresh_list()

        # Add item row
        add_row = QHBoxLayout()
        self._new_edit = QLineEdit()
        self._new_edit.setPlaceholderText("New task…")
        self._new_edit.returnPressed.connect(self._add_item)
        add_btn = QPushButton("+ Add")
        add_btn.clicked.connect(self._add_item)
        add_row.addWidget(self._new_edit)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        # Delete selected
        del_btn = QPushButton("Remove Selected")
        del_btn.clicked.connect(self._remove_selected)
        layout.addWidget(del_btn)

        # OK / Cancel
        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Save")
        ok.setObjectName("ok")
        ok.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        layout.addLayout(btns)

    def _refresh_list(self):
        self._list.clear()
        for item in self._items:
            lw = QListWidgetItem()
            widget = _TodoRow(item)
            lw.setSizeHint(widget.sizeHint())
            self._list.addItem(lw)
            self._list.setItemWidget(lw, widget)

    def _add_item(self):
        text = self._new_edit.text().strip()
        if text:
            self._items.append({"text": text, "done": False})
            self._new_edit.clear()
            self._refresh_list()

    def _remove_selected(self):
        row = self._list.currentRow()
        if 0 <= row < len(self._items):
            self._items.pop(row)
            self._refresh_list()

    def _save(self):
        # Collect done states from widgets
        for i in range(self._list.count()):
            widget = self._list.itemWidget(self._list.item(i))
            if widget and i < len(self._items):
                self._items[i]["done"] = widget.is_done()

        meta = self._data.get("meta", {})
        if isinstance(meta, str):
            meta = json.loads(meta)
        meta["items"]       = self._items
        self._data["meta"]  = meta
        self.result_data    = self._data
        self.accept()


class _TodoRow(QWidget):
    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        self._cb = QCheckBox()
        self._cb.setChecked(item.get("done", False))
        self._cb.setStyleSheet(f"QCheckBox {{ color: {TEXT_PRIMARY}; }}")
        lbl = QLabel(item.get("text", ""))
        lbl.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(self._cb)
        layout.addWidget(lbl)
        layout.addStretch()

    def is_done(self) -> bool:
        return self._cb.isChecked()


class RenameDialog(_BaseDialog):
    def __init__(self, current_name: str, parent=None):
        super().__init__("Rename Board", parent)
        self.new_name = current_name

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        lbl = QLabel("Board Name")
        lbl.setFont(QFont("Segoe UI", 12, QFont.Bold))
        layout.addWidget(lbl)

        self._edit = QLineEdit(current_name)
        self._edit.selectAll()
        layout.addWidget(self._edit)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Rename")
        ok.setObjectName("ok")
        ok.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        layout.addLayout(btns)

    def _save(self):
        self.new_name = self._edit.text().strip() or "Untitled"
        self.accept()
