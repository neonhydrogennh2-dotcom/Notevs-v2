"""
ui/canvas.py
Infinite canvas (QGraphicsView/Scene).

Fix: _remove_item_local() now calls item.prepareForDelete() before
removing the item from the scene, so any open proxy widgets are closed
cleanly before scene() becomes None.

Logging added to undo/redo and all add_* methods to help diagnose issues.
"""

from __future__ import annotations
import logging
import os

from PySide6.QtWidgets import (
    QFileDialog, QGraphicsView, QGraphicsScene,
    QApplication, QMenu, QInputDialog,
)
from PySide6.QtCore  import Qt, QPointF, Signal, QRectF, QTimer
from PySide6.QtGui   import (
    QPainter, QWheelEvent, QKeyEvent, QPen, QColor,
    QUndoStack, QUndoCommand,
)

import database.db as db
from ui.elements import (
    BaseElement, ConnectionArrow, make_element,
)
from utils.theme import DARK_BG, ACCENT, BORDER_COLOR

log = logging.getLogger("canvas")
SCENE_HALF = 8000


# ── Undo / Redo commands ───────────────────────────────────────────────────────

class AddElementCmd(QUndoCommand):
    def __init__(self, canvas: "BoardCanvas", element_id: int, desc="Add element"):
        super().__init__(desc)
        self.canvas = canvas
        self.eid    = element_id

    def redo(self):
        log.debug("AddElementCmd.redo eid=%s", self.eid)
        for d in db.get_elements(self.canvas.board_id):
            if d["id"] == self.eid:
                if self.eid not in self.canvas._items:
                    self.canvas._add_item_from_data(d)
                break

    def undo(self):
        log.debug("AddElementCmd.undo eid=%s", self.eid)
        item = self.canvas._item_by_id(self.eid)
        if item:
            self.canvas._remove_item_local(item)
        db.delete_element(self.eid)


class DeleteElementCmd(QUndoCommand):
    def __init__(self, canvas: "BoardCanvas", data: dict, desc="Delete element"):
        super().__init__(desc)
        self.canvas    = canvas
        self._data     = data.copy()
        self._board_id = canvas.board_id

    def redo(self):
        log.debug("DeleteElementCmd.redo eid=%s", self._data["id"])
        item = self.canvas._item_by_id(self._data["id"])
        if item:
            self.canvas._remove_item_local(item)
        db.delete_element(self._data["id"])

    def undo(self):
        log.debug("DeleteElementCmd.undo eid=%s", self._data["id"])
        import json
        meta = self._data.get("meta", {})
        new_id = db.create_element(
            board_id=self._board_id,
            type_   =self._data["type"],
            x       =self._data["x"],
            y       =self._data["y"],
            width   =self._data["width"],
            height  =self._data["height"],
            content =self._data["content"],
            color   =self._data.get("color", "#ffffff"),
            meta    =meta if isinstance(meta, dict) else json.loads(meta),
        )
        self._data["id"] = new_id
        for d in db.get_elements(self._board_id):
            if d["id"] == new_id:
                self.canvas._add_item_from_data(d)
                break


# ── Canvas ─────────────────────────────────────────────────────────────────────

class BoardCanvas(QGraphicsView):
    """Primary infinite workspace for a single board."""

    elementSelected  = Signal(dict)
    openBoardRequest = Signal(int)
    statusMessage    = Signal(str)

    def __init__(self, board_id: int, parent=None):
        super().__init__(parent)
        self.board_id = board_id

        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(
            -SCENE_HALF, -SCENE_HALF, SCENE_HALF * 2, SCENE_HALF * 2
        )
        self.setScene(self._scene)

        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setBackgroundBrush(QColor(DARK_BG))
        self.setStyleSheet("border: none;")

        self._panning         = False
        self._pan_start       = QPointF()
        self._connect_mode    = False
        self._connect_from_id = None
        self._temp_line       = None
        self._items:  dict[int, BaseElement]     = {}
        self._arrows: dict[int, ConnectionArrow] = {}
        self._zoom            = 1.0
        self._undo_stack      = QUndoStack(self)
        self._grid_visible    = True

        # Log undo/redo stack changes for debugging
        self._undo_stack.indexChanged.connect(
            lambda idx: log.debug("UndoStack index → %s (size=%s)",
                                  idx, self._undo_stack.count())
        )

        self._load_board()

    # ── Grid ───────────────────────────────────────────────────────────────
    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        if not self._grid_visible:
            return
        grid = 30
        pen  = QPen(QColor(BORDER_COLOR), 0.4)
        pen.setCosmetic(False)
        painter.setPen(pen)
        lx = int(rect.left())  - int(rect.left())  % grid
        ty = int(rect.top())   - int(rect.top())   % grid
        x  = lx
        while x < rect.right():
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
            x += grid
        y = ty
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)
            y += grid

    # ── Load board ─────────────────────────────────────────────────────────
    def _load_board(self):
        log.debug("Loading board %s", self.board_id)
        for data in db.get_elements(self.board_id):
            self._add_item_from_data(data)
        for conn in db.get_connections(self.board_id):
            fi = self._items.get(conn["from_id"])
            ti = self._items.get(conn["to_id"])
            if fi and ti:
                arrow = ConnectionArrow(conn, fi, ti)
                self._scene.addItem(arrow)
                self._arrows[conn["id"]] = arrow
        log.debug("Board loaded: %d elements, %d connections",
                  len(self._items), len(self._arrows))

    def _add_item_from_data(self, data: dict) -> BaseElement:
        item = make_element(data, self)
        item.sig.moved.connect(self._on_element_moved)
        item.sig.deleted.connect(self._on_element_deleted)
        item.sig.edited.connect(self._on_element_edited)
        item.sig.requestConnect.connect(self._start_connect)
        item.sig.openBoard.connect(self.openBoardRequest)
        self._scene.addItem(item)
        self._items[data["id"]] = item
        return item

    # ── Signals ────────────────────────────────────────────────────────────
    def _on_element_moved(self, eid: int, x: float, y: float):
        db.update_element(eid, x=x, y=y)
        for arrow in self._arrows.values():
            arrow.update()

    def _on_element_edited(self, eid: int, content: str):
        db.update_element(eid, content=content)

    def _on_element_deleted(self, eid: int):
        item = self._items.get(eid)
        if not item:
            log.warning("_on_element_deleted: eid=%s not found", eid)
            return
        log.debug("Deleting element eid=%s type=%s", eid, item.data.get("type"))
        # CRITICAL: close any open proxy BEFORE the undo command removes from scene
        item.prepareForDelete()
        cmd = DeleteElementCmd(self, item.data)
        self._undo_stack.push(cmd)

    # ── Save ───────────────────────────────────────────────────────────────
    def _save_element(self, data: dict):
        import json
        meta = data.get("meta", {})
        if isinstance(meta, dict):
            meta = json.dumps(meta)
        db.update_element(
            data["id"],
            x      =data.get("x",       0),
            y      =data.get("y",       0),
            width  =data.get("width",   200),
            height =data.get("height",  120),
            content=data.get("content", ""),
            color  =data.get("color",   "#ffffff"),
            meta   =meta,
            z_index=data.get("z_index", 0),
            locked =1 if data.get("locked") else 0,
        )

    def _item_by_id(self, eid: int) -> BaseElement | None:
        return self._items.get(eid)

    def _remove_item_local(self, item: BaseElement):
        """
        Remove item from scene and our tracking dict.
        Calls prepareForDelete() first to cleanly close any open proxy widgets
        before scene() becomes None.
        """
        log.debug("_remove_item_local eid=%s", item.data.get("id"))
        item.prepareForDelete()           # ← close proxy safely BEFORE removal
        self._scene.removeItem(item)
        self._items.pop(item.data["id"], None)

    # ── Helpers ────────────────────────────────────────────────────────────
    def _center_scene_pos(self) -> QPointF:
        return self.mapToScene(self.viewport().rect().center())

    def _spawn(self, type_: str, x_off=0, y_off=0, w=200, h=140,
               content="", meta=None) -> BaseElement | None:
        pos = self._center_scene_pos()
        eid = db.create_element(
            board_id=self.board_id, type_=type_,
            x=pos.x() + x_off, y=pos.y() + y_off,
            width=w, height=h,
            content=content, meta=meta or {},
        )
        log.debug("Spawned %s eid=%s", type_, eid)
        for d in db.get_elements(self.board_id):
            if d["id"] == eid:
                return self._add_item_from_data(d)
        return None

    # ── Add elements ───────────────────────────────────────────────────────

    def add_note(self, color_key="yellow"):
        self._spawn("note", -100, -70, 200, 140, meta={"color_key": color_key})
        self.statusMessage.emit("Note added — double-click to edit inline")

    def add_todo(self):
        self._spawn("todo", -120, -100, 240, 200,
                    content="To-Do List",
                    meta={"items": [{"text": "First task", "done": False}]})
        self.statusMessage.emit("To-Do list added — click checkboxes to toggle")

    def add_link(self):
        url, ok = QInputDialog.getText(self, "Add Link", "Enter URL:")
        if not ok or not url.strip():
            return
        url = url.strip()
        if not url.startswith("http"):
            url = "https://" + url
        self._spawn("link", -150, -40, 300, 80,
                    content=url, meta={"title": url, "favicon": "🔗"})
        self.statusMessage.emit("Link added — right-click to fetch page title")

    def add_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)"
        )
        if path:
            self._spawn("image", -150, -100, 300, 200, content=path)
            self.statusMessage.emit("Image added")

    def add_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Video", "",
            "Video files (*.mp4 *.mkv *.avi *.mov *.wmv *.webm *.flv)"
        )
        if not path:
            return
        fn  = os.path.basename(path)
        ext = os.path.splitext(fn)[1].lstrip(".")
        self._spawn("video", -160, -90, 320, 200,
                    content=path, meta={"filename": fn, "ext": ext})
        self.statusMessage.emit("Video added — double-click to play")

    def add_audio(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Audio", "",
            "Audio files (*.mp3 *.wav *.flac *.ogg *.aac *.m4a)"
        )
        if not path:
            return
        fn  = os.path.basename(path)
        ext = os.path.splitext(fn)[1].lstrip(".")
        self._spawn("audio", -160, -50, 320, 110,
                    content=path, meta={"filename": fn, "ext": ext})
        self.statusMessage.emit("Audio added — double-click to play")

    def add_table(self):
        self._spawn("table", -150, -100, 360, 200,
                    meta={"cells": [
                        ["Column A", "Column B", "Column C"],
                        ["", "", ""],
                        ["", "", ""],
                    ]})
        self.statusMessage.emit("Table added — double-click to edit, Esc to close")

    def add_heading(self):
        text, ok = QInputDialog.getText(self, "Add Heading", "Heading text:")
        if not ok or not text.strip():
            return
        self._spawn("heading", -200, -30, 400, 60,
                    content=text.strip(), meta={"size": 28, "color": ACCENT})
        self.statusMessage.emit("Heading added")

    def add_document(self):
        name, ok = QInputDialog.getText(self, "New Document", "Document title:")
        if not ok or not name.strip():
            return
        self._spawn("document", -150, -120, 320, 280,
                    content="", meta={"title": name.strip()})
        self.statusMessage.emit("Document added — double-click to write")

    def add_column(self):
        label, ok = QInputDialog.getText(self, "New Column", "Column label:")
        if not ok or not label.strip():
            return
        self._spawn("column", -150, -200, 280, 500,
                    content=label.strip(), meta={"color": ACCENT})
        self.statusMessage.emit("Column added — drag elements inside it")

    def add_sub_board(self):
        name, ok = QInputDialog.getText(self, "New Sub-Board", "Board name:")
        if not ok or not name.strip():
            return
        sub_id = db.create_board(name=name.strip(), parent_id=self.board_id)
        self._spawn("board", -90, -60, 180, 120,
                    content=name.strip(), meta={"board_ref_id": sub_id})
        self.statusMessage.emit(f"Sub-board '{name.strip()}' created")

    def add_file(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Attach File(s)", "", "All Files (*.*)"
        )
        if not paths:
            return
        pos, offset = self._center_scene_pos(), 0
        for path in paths:
            stat     = os.stat(path)
            fn       = os.path.basename(path)
            ext      = os.path.splitext(fn)[1].lstrip(".").upper()
            size_str = _human_size(stat.st_size)
            eid = db.create_element(
                board_id=self.board_id, type_="file",
                x=pos.x() - 160, y=pos.y() - 35 + offset,
                width=320, height=70, content=path,
                meta={"filename": fn, "ext": ext, "size_str": size_str},
            )
            for d in db.get_elements(self.board_id):
                if d["id"] == eid:
                    self._add_item_from_data(d)
                    break
            offset += 84
        self.statusMessage.emit(f"{len(paths)} file(s) attached")

    # ── Connections ────────────────────────────────────────────────────────
    def _start_connect(self, from_id: int):
        self._connect_mode    = True
        self._connect_from_id = from_id
        self.setCursor(Qt.CrossCursor)
        self.statusMessage.emit("Click another element to connect… (Esc to cancel)")

    def _end_connect(self, to_id: int):
        from_id = self._connect_from_id
        self._connect_mode    = False
        self._connect_from_id = None
        self.setCursor(Qt.ArrowCursor)
        if self._temp_line:
            self._scene.removeItem(self._temp_line)
            self._temp_line = None
        if from_id == to_id:
            return
        cid       = db.create_connection(self.board_id, from_id, to_id)
        conn_data = next((c for c in db.get_connections(self.board_id)
                          if c["id"] == cid), None)
        if conn_data:
            fi = self._items.get(from_id)
            ti = self._items.get(to_id)
            if fi and ti:
                arrow = ConnectionArrow(conn_data, fi, ti)
                self._scene.addItem(arrow)
                self._arrows[cid] = arrow
        self.statusMessage.emit("Connection created")

    def _delete_connection(self, conn_id: int):
        arrow = self._arrows.pop(conn_id, None)
        if arrow:
            self._scene.removeItem(arrow)
        db.delete_connection(conn_id)

    # ── Keyboard ───────────────────────────────────────────────────────────
    def keyPressEvent(self, event: QKeyEvent):
        mod = event.modifiers()
        key = event.key()

        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            selected = list(self._scene.selectedItems())
            log.debug("Delete key: %d selected items", len(selected))
            for item in selected:
                if isinstance(item, BaseElement):
                    self._on_element_deleted(item.data["id"])
                elif isinstance(item, ConnectionArrow):
                    self._delete_connection(item.conn_data["id"])

        elif key == Qt.Key_Escape:
            if self._connect_mode:
                self._connect_mode    = False
                self._connect_from_id = None
                self.setCursor(Qt.ArrowCursor)
                if self._temp_line:
                    self._scene.removeItem(self._temp_line)
                    self._temp_line = None
            self._scene.clearSelection()

        elif mod == Qt.ControlModifier and key == Qt.Key_Z:
            log.debug("Undo triggered")
            self._undo_stack.undo()
        elif mod == (Qt.ControlModifier | Qt.ShiftModifier) and key == Qt.Key_Z:
            log.debug("Redo triggered (Ctrl+Shift+Z)")
            self._undo_stack.redo()
        elif mod == Qt.ControlModifier and key == Qt.Key_Y:
            log.debug("Redo triggered (Ctrl+Y)")
            self._undo_stack.redo()
        elif mod == Qt.ControlModifier and key == Qt.Key_A:
            for item in self._scene.items():
                item.setSelected(True)
        elif mod == Qt.ControlModifier and key == Qt.Key_0:
            self.resetTransform()
            self._zoom = 1.0
        else:
            super().keyPressEvent(event)

    # ── Zoom ───────────────────────────────────────────────────────────────
    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            factor   = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
            new_zoom = self._zoom * factor
            if 0.08 <= new_zoom <= 6.0:
                self._zoom = new_zoom
                self.scale(factor, factor)
        else:
            super().wheelEvent(event)

    # ── Pan ────────────────────────────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and event.modifiers() & Qt.AltModifier
        ):
            self._panning   = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.LeftButton and self._connect_mode:
            item = self.itemAt(event.pos())
            if isinstance(item, BaseElement):
                self._end_connect(item.data["id"])
            else:
                self._connect_mode    = False
                self._connect_from_id = None
                self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(
                int(self.verticalScrollBar().value() - delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() in (Qt.MiddleButton, Qt.LeftButton) and self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if item is None:
                pos = self.mapToScene(event.pos())
                eid = db.create_element(
                    board_id=self.board_id, type_="note",
                    x=pos.x() - 100, y=pos.y() - 70,
                    width=200, height=140, content="",
                    meta={"color_key": "yellow"},
                )
                for d in db.get_elements(self.board_id):
                    if d["id"] == eid:
                        self._add_item_from_data(d)
                        break
                return
        super().mouseDoubleClickEvent(event)

    # ── Search ─────────────────────────────────────────────────────────────
    def highlight_search(self, query: str):
        q = query.lower()
        for item in self._items.values():
            match = q in item.data.get("content", "").lower()
            item.setOpacity(1.0 if match else 0.22)

    def reset_search(self):
        for item in self._items.values():
            item.setOpacity(1.0)

    # ── Zoom controls ──────────────────────────────────────────────────────
    def zoom_in(self):
        if self._zoom < 6.0:
            self._zoom *= 1.2; self.scale(1.2, 1.2)

    def zoom_out(self):
        if self._zoom > 0.08:
            self._zoom /= 1.2; self.scale(1 / 1.2, 1 / 1.2)

    def zoom_reset(self):
        self.resetTransform(); self._zoom = 1.0

    def toggle_grid(self):
        self._grid_visible = not self._grid_visible; self._scene.update()


# ── Utility ────────────────────────────────────────────────────────────────────
def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024: return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
