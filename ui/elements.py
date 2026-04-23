"""
ui/elements.py

Bug fixes in this version:
  1. PROXY CRASH (NoneType has no attribute 'removeItem'):
     - focusOutEvent lambdas now use QTimer.singleShot(0, ...) to defer cleanup
       until after the current Qt event is fully processed.
     - All _finish_*() methods guard with "if self.scene()" before calling removeItem.
     - Calling the super() focusOutEvent is wrapped in try/except to handle the
       case where the C++ widget is already deleted.

  2. UNDO CRASH (delete fires focusOut while scene is tearing down):
     - BaseElement.prepareForDelete() closes any open proxy widget BEFORE
       the item is removed from the scene. Canvas calls this before pushing
       the undo command.

  3. TABLE keypress eating Delete/Backspace:
     - TableElement now overrides keyPressEvent to swallow those keys so
       typing in cells does not trigger canvas deletion.

  4. HEADING ("Label") element now works — paint was correct but the
     HeadingElement was registered as "heading" not "label"; toolbar sends
     add_heading which spawns type="heading". Confirmed correct.

  5. FONT change: MainWindow._on_font_changed now also calls update() on
     canvas so text items repaint. (Fixed in main_window.py)
"""

from __future__ import annotations
import json
import math
import os
import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QGraphicsItem, QGraphicsProxyWidget, QWidget, QTextEdit,
    QApplication, QMenu, QInputDialog,
    QTableWidget, QTableWidgetItem, QHeaderView,
)
from PySide6.QtCore  import Qt, QRectF, QPointF, Signal, QObject, QTimer
from PySide6.QtGui   import (
    QPainter, QColor, QPen, QBrush, QFont,
    QPainterPath, QLinearGradient, QPixmap, QTextCursor,
)

from utils.theme import (
    ACCENT, BORDER_COLOR, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED,
    CARD_BG, NOTE_COLORS, NOTE_ACCENT_COLORS,
    NOTE_COLORS_DARK, NOTE_COLORS_LIGHT,
)

if TYPE_CHECKING:
    from ui.canvas import BoardCanvas

log = logging.getLogger("elements")

# ── Constants ─────────────────────────────────────────────────────────────────
HANDLE_SIZE   = 8
CORNER_RADIUS = 10
MIN_W         = 100
MIN_H         = 60


# ── Signals ────────────────────────────────────────────────────────────────────
class ElementSignals(QObject):
    """Carrier object so QGraphicsItem subclasses can emit signals."""
    moved          = Signal(int, float, float)
    resized        = Signal(int, float, float)
    edited         = Signal(int, str)
    deleted        = Signal(int)
    zChanged       = Signal(int, int)
    requestConnect = Signal(int)
    openBoard      = Signal(int)


# ── Safe proxy cleanup helper ─────────────────────────────────────────────────
def _safe_remove_proxy(scene, proxy):
    """
    Remove a QGraphicsProxyWidget from the scene safely.
    Guards against scene being None (item already removed) and
    the proxy's C++ object already being deleted.
    """
    if proxy is None:
        return
    try:
        if scene is not None:
            scene.removeItem(proxy)
    except RuntimeError:
        pass  # C++ object already deleted — nothing to do


# ── Base element ───────────────────────────────────────────────────────────────
class BaseElement(QGraphicsItem):
    """
    Base class for all canvas items.
    Provides: resize handles, move/resize events, selection overlay,
              context menu, lock, z-order, auto-save debounce.
    """
    ELEMENT_TYPE = "base"

    def __init__(self, data: dict, canvas: "BoardCanvas"):
        super().__init__()
        self.data   = data
        self.canvas = canvas
        self.sig    = ElementSignals()

        self._resizing      = False
        self._resize_handle = None
        self._drag_start    = QPointF()
        self._orig_rect     = QRectF()

        # Debounce DB writes — 600 ms after last change
        self._auto_save_timer = QTimer()
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.setInterval(600)
        self._auto_save_timer.timeout.connect(self._persist)

        self.setFlag(QGraphicsItem.ItemIsMovable,    not data.get("locked", False))
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)

        self.setPos(data.get("x", 0), data.get("y", 0))
        self.setZValue(data.get("z_index", 0))

    # ── Geometry helpers ──────────────────────────────────────────────────
    def w(self) -> float: return self.data.get("width",  200)
    def h(self) -> float: return self.data.get("height", 120)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.w(), self.h())

    def _handle_rects(self) -> dict[str, QRectF]:
        s, w, h = HANDLE_SIZE, self.w(), self.h()
        return {
            "br": QRectF(w - s, h - s, s, s),
            "bl": QRectF(0,     h - s, s, s),
            "tr": QRectF(w - s, 0,     s, s),
            "tl": QRectF(0,     0,     s, s),
        }

    def _hit_handle(self, pos: QPointF) -> str | None:
        for name, rect in self._handle_rects().items():
            if rect.contains(pos):
                return name
        return None

    # ── Called by canvas BEFORE removing the item from the scene ─────────
    def prepareForDelete(self):
        """
        Hook called by canvas before deletion.
        Subclasses that have open proxy widgets must close them here
        so focusOut doesn't fire after scene() becomes None.
        """
        pass  # overridden by NoteElement, DocumentElement, TableElement

    # ── Position tracking → auto-save ────────────────────────────────────
    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.data["x"] = self.pos().x()
            self.data["y"] = self.pos().y()
            self._auto_save_timer.start()
        return super().itemChange(change, value)

    # ── Hover: show resize cursors near corner handles ────────────────────
    def hoverMoveEvent(self, event):
        h = self._hit_handle(event.pos())
        if h in ("br", "tl"):    self.setCursor(Qt.SizeFDiagCursor)
        elif h in ("bl", "tr"):  self.setCursor(Qt.SizeBDiagCursor)
        else:                    self.setCursor(Qt.ArrowCursor)
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.setCursor(Qt.ArrowCursor)
        super().hoverLeaveEvent(event)

    # ── Resize via corner drag ────────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            h = self._hit_handle(event.pos())
            if h:
                self._resizing      = True
                self._resize_handle = h
                self._drag_start    = event.scenePos()
                self._orig_rect     = QRectF(self.pos().x(), self.pos().y(),
                                             self.w(), self.h())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            delta = event.scenePos() - self._drag_start
            r, h  = self._orig_rect, self._resize_handle
            nx, ny, nw, nh = r.x(), r.y(), r.width(), r.height()
            if "r" in h: nw = max(MIN_W, r.width() + delta.x())
            if "l" in h:
                nx = min(r.x() + r.width() - MIN_W, r.x() + delta.x())
                nw = max(MIN_W, r.width() - delta.x())
            if "b" in h: nh = max(MIN_H, r.height() + delta.y())
            if "t" in h:
                ny = min(r.y() + r.height() - MIN_H, r.y() + delta.y())
                nh = max(MIN_H, r.height() - delta.y())
            self.prepareGeometryChange()
            self.setPos(nx, ny)
            self.data["width"]  = nw
            self.data["height"] = nh
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            self._auto_save_timer.start()
            self.sig.resized.emit(self.data["id"], self.w(), self.h())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ── Context menu (base — subclasses extend) ───────────────────────────
    def contextMenuEvent(self, event):
        menu = QMenu()
        menu.addAction("Bring to Front", self._bring_front)
        menu.addAction("Send to Back",   self._send_back)
        menu.addSeparator()
        menu.addAction("Unlock" if self.data.get("locked") else "Lock",
                       self._toggle_lock)
        menu.addSeparator()
        menu.addAction("Connect…", lambda: self.sig.requestConnect.emit(self.data["id"]))
        menu.addSeparator()
        menu.addAction("Delete", self._delete)
        menu.exec(event.screenPos())

    def _bring_front(self):
        z = int(self.zValue()) + 1
        self.setZValue(z); self.data["z_index"] = z; self._persist()

    def _send_back(self):
        z = max(0, int(self.zValue()) - 1)
        self.setZValue(z); self.data["z_index"] = z; self._persist()

    def _toggle_lock(self):
        locked = not self.data.get("locked", False)
        self.data["locked"] = locked
        self.setFlag(QGraphicsItem.ItemIsMovable, not locked)
        self._persist()

    def _delete(self):
        self.sig.deleted.emit(self.data["id"])

    def _persist(self):
        if hasattr(self.canvas, "_save_element"):
            self.canvas._save_element(self.data)

    # ── Selection border + corner handles ─────────────────────────────────
    def _paint_selection(self, painter: QPainter):
        if not self.isSelected():
            return
        pen = QPen(QColor(ACCENT), 1.5, Qt.DashLine)
        pen.setDashPattern([4, 3])
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(
            self.boundingRect().adjusted(0.5, 0.5, -0.5, -0.5),
            CORNER_RADIUS, CORNER_RADIUS
        )
        painter.setPen(QPen(QColor(ACCENT), 1))
        painter.setBrush(QBrush(QColor(CARD_BG)))
        for rect in self._handle_rects().values():
            painter.drawRect(rect)


# ── Note element ───────────────────────────────────────────────────────────────
class NoteElement(BaseElement):
    """
    Sticky note with inline editing.
    Double-click embeds a transparent QTextEdit directly on the card.
    The proxy is closed safely via a deferred QTimer when focus leaves,
    to avoid the scene() == None crash during deletion.
    """
    ELEMENT_TYPE = "note"

    def __init__(self, data: dict, canvas):
        super().__init__(data, canvas)
        self._color_key    = data.get("meta", {}).get("color_key", "yellow")
        self._bg_color     = QColor(NOTE_COLORS.get(self._color_key, NOTE_COLORS["yellow"]))
        self._accent_color = QColor(NOTE_ACCENT_COLORS.get(
            self._color_key, NOTE_ACCENT_COLORS["yellow"]))
        self._proxy: QGraphicsProxyWidget | None = None

    def prepareForDelete(self):
        """Close proxy before the item leaves the scene."""
        self._close_proxy()

    def _close_proxy(self):
        """Safely remove the inline editor proxy."""
        if self._proxy is not None:
            proxy, self._proxy = self._proxy, None
            _safe_remove_proxy(self.scene(), proxy)
            self.update()

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        r = self.boundingRect()

        # Drop shadow
        shadow = QPainterPath()
        shadow.addRoundedRect(r.adjusted(2, 3, 2, 3), CORNER_RADIUS, CORNER_RADIUS)
        painter.fillPath(shadow, QColor(0, 0, 0, 50))

        # Card body
        body = QPainterPath()
        body.addRoundedRect(r, CORNER_RADIUS, CORNER_RADIUS)
        painter.fillPath(body, self._bg_color)

        # Accent bar (top 4 px)
        painter.fillRect(QRectF(0, 0, self.w(), 4), self._accent_color)

        # Text preview (hidden while editing)
        if self._proxy is None:
            content = self.data.get("content", "")
            painter.setPen(QColor(TEXT_MUTED if not content else TEXT_PRIMARY))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(
                r.adjusted(12, 14, -12, -10),
                Qt.TextWordWrap | Qt.AlignTop,
                content or "Double-click to edit…"
            )
        self._paint_selection(painter)

    def mouseDoubleClickEvent(self, event):
        if self._proxy:
            return
        self._open_proxy()
        event.accept()

    def _open_proxy(self):
        te = QTextEdit()
        te.setPlainText(self.data.get("content", ""))
        te.setStyleSheet(f"""
            QTextEdit {{
                background: transparent; border: none;
                color: {TEXT_PRIMARY};
                font-family: 'Segoe UI'; font-size: 12pt; padding: 0;
            }}
        """)
        te.setFixedSize(int(self.w() - 24), int(self.h() - 22))

        self._proxy = QGraphicsProxyWidget(self)
        self._proxy.setWidget(te)
        self._proxy.setPos(12, 14)
        te.setFocus()
        te.moveCursor(QTextCursor.End)

        # Defer finish to avoid re-entrancy during scene changes
        def _on_focus_out(event, _te=te):
            QTimer.singleShot(0, lambda: self._finish_inline_edit(_te))
            try:
                QTextEdit.focusOutEvent(_te, event)
            except RuntimeError:
                pass

        te.focusOutEvent = _on_focus_out

    def _finish_inline_edit(self, te: QTextEdit):
        """Save text and close the proxy — always safe to call."""
        try:
            text = te.toPlainText()
        except RuntimeError:
            text = self.data.get("content", "")  # widget already gone
        self.data["content"] = text
        self._close_proxy()
        self._auto_save_timer.start()
        try:
            self.sig.edited.emit(self.data["id"], text)
        except Exception:
            pass

    def contextMenuEvent(self, event):
        menu = QMenu()
        cm = menu.addMenu("🎨  Color")
        for key in NOTE_COLORS:
            cm.addAction(key.capitalize(), lambda k=key: self._set_color(k))
        menu.addSeparator()
        menu.addAction("✏  Edit (popup)", self._popup_edit)
        menu.addSeparator()
        for label, fn in [
            ("Bring to Front", self._bring_front),
            ("Send to Back",   self._send_back),
            ("Lock/Unlock",    self._toggle_lock),
            ("Connect…",       lambda: self.sig.requestConnect.emit(self.data["id"])),
            ("Delete",         self._delete),
        ]:
            menu.addAction(label, fn)
        menu.exec(event.screenPos())

    def _popup_edit(self):
        text, ok = QInputDialog.getMultiLineText(
            None, "Edit Note", "Content:", self.data.get("content", "")
        )
        if ok:
            self.data["content"] = text
            self.update()
            self._auto_save_timer.start()
            self.sig.edited.emit(self.data["id"], text)

    def _set_color(self, key: str):
        if not isinstance(self.data.get("meta"), dict):
            self.data["meta"] = {}
        self.data["meta"]["color_key"] = key
        self._color_key    = key
        self._bg_color     = QColor(NOTE_COLORS[key])
        self._accent_color = QColor(NOTE_ACCENT_COLORS[key])
        self.update()
        self._auto_save_timer.start()


# ── Heading element ────────────────────────────────────────────────────────────
class HeadingElement(BaseElement):
    """Large bold section heading. Double-click to rename, right-click for style."""
    ELEMENT_TYPE = "heading"

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        r         = self.boundingRect()
        meta      = self.data.get("meta", {})
        size      = int(meta.get("size", 28))
        color_hex = meta.get("color", ACCENT)

        # Faint background
        bg = QPainterPath()
        bg.addRoundedRect(r, 8, 8)
        painter.fillPath(bg, QColor(0, 0, 0, 18))

        # Left accent stripe
        painter.fillRect(QRectF(0, 10, 4, self.h() - 20), QColor(color_hex))

        # Heading text
        painter.setPen(QColor(color_hex))
        painter.setFont(QFont("Segoe UI", size, QFont.Bold))
        painter.drawText(
            r.adjusted(16, 0, -12, 0),
            Qt.AlignVCenter | Qt.AlignLeft,
            self.data.get("content", "Heading")
        )
        self._paint_selection(painter)

    def mouseDoubleClickEvent(self, event):
        text, ok = QInputDialog.getText(
            None, "Edit Heading", "Text:", text=self.data.get("content", "")
        )
        if ok and text.strip():
            self.data["content"] = text.strip()
            self.update(); self._auto_save_timer.start()

    def contextMenuEvent(self, event):
        menu = QMenu()
        sm = menu.addMenu("📐  Size")
        for label, sz in [("Small", 20), ("Medium", 28), ("Large", 36), ("XL", 48)]:
            sm.addAction(label, lambda s=sz: self._set_size(s))
        cm = menu.addMenu("🎨  Color")
        for name, hex_ in [("Blue", ACCENT), ("Green", "#3dd68c"),
                            ("Yellow", "#f5c842"), ("Red", "#f05050"),
                            ("Purple", "#a855f7"), ("White", "#e8e8f0")]:
            cm.addAction(name, lambda h=hex_: self._set_color(h))
        menu.addSeparator()
        for label, fn in [
            ("Bring to Front", self._bring_front), ("Send to Back", self._send_back),
            ("Lock/Unlock", self._toggle_lock),
            ("Connect…", lambda: self.sig.requestConnect.emit(self.data["id"])),
            ("Delete", self._delete),
        ]:
            menu.addAction(label, fn)
        menu.exec(event.screenPos())

    def _set_size(self, sz: int):
        if not isinstance(self.data.get("meta"), dict): self.data["meta"] = {}
        self.data["meta"]["size"] = sz
        self.update(); self._auto_save_timer.start()

    def _set_color(self, hex_: str):
        if not isinstance(self.data.get("meta"), dict): self.data["meta"] = {}
        self.data["meta"]["color"] = hex_
        self.update(); self._auto_save_timer.start()


# ── Document element ───────────────────────────────────────────────────────────
class DocumentElement(BaseElement):
    """
    In-app text document. Double-click opens an inline QTextEdit.
    Uses the same deferred-close pattern as NoteElement to avoid crashes.
    """
    ELEMENT_TYPE = "document"

    def __init__(self, data: dict, canvas):
        super().__init__(data, canvas)
        self._proxy: QGraphicsProxyWidget | None = None

    def prepareForDelete(self):
        self._close_proxy()

    def _close_proxy(self):
        if self._proxy is not None:
            proxy, self._proxy = self._proxy, None
            _safe_remove_proxy(self.scene(), proxy)
            self.update()

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        r    = self.boundingRect()
        path = QPainterPath()
        path.addRoundedRect(r, CORNER_RADIUS, CORNER_RADIUS)
        painter.fillPath(path, QColor("#1e2030"))
        painter.setPen(QPen(QColor("#2a2d50"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        # Header strip
        hdr = QPainterPath()
        hdr.addRoundedRect(QRectF(0, 0, self.w(), 32), CORNER_RADIUS, CORNER_RADIUS)
        clip = QPainterPath(); clip.addRect(QRectF(0, 0, self.w(), 32))
        painter.fillPath(hdr.intersected(clip), QColor("#252840"))

        painter.setPen(QColor(ACCENT))
        painter.setFont(QFont("Segoe UI", 13))
        painter.drawText(QRectF(10, 6, 22, 20), Qt.AlignCenter, "📄")

        painter.setPen(QColor(TEXT_PRIMARY))
        painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
        title = self.data.get("meta", {}).get("title", "Document")
        painter.drawText(QRectF(36, 8, self.w() - 50, 18),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         title[:35] + ("…" if len(title) > 35 else ""))

        if self._proxy is None:
            content = self.data.get("content", "")
            painter.setPen(QColor(TEXT_SECONDARY if content else TEXT_MUTED))
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(r.adjusted(10, 38, -10, -10),
                             Qt.TextWordWrap | Qt.AlignTop,
                             content[:300] or "Double-click to write…")
        self._paint_selection(painter)

    def mouseDoubleClickEvent(self, event):
        if self._proxy:
            return
        te = QTextEdit()
        te.setPlainText(self.data.get("content", ""))
        te.setStyleSheet(f"""
            QTextEdit {{
                background: #12141e; border: none;
                color: {TEXT_PRIMARY};
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11pt; padding: 4px;
            }}
        """)
        te.setFixedSize(int(self.w() - 4), int(self.h() - 36))

        self._proxy = QGraphicsProxyWidget(self)
        self._proxy.setWidget(te)
        self._proxy.setPos(2, 34)
        te.setFocus()
        te.moveCursor(QTextCursor.End)

        def _on_focus_out(event, _te=te):
            QTimer.singleShot(0, lambda: self._finish_edit(_te))
            try:
                QTextEdit.focusOutEvent(_te, event)
            except RuntimeError:
                pass

        te.focusOutEvent = _on_focus_out
        event.accept()

    def _finish_edit(self, te: QTextEdit):
        try:
            text = te.toPlainText()
        except RuntimeError:
            text = self.data.get("content", "")
        self.data["content"] = text
        self._close_proxy()
        self._auto_save_timer.start()
        try:
            self.sig.edited.emit(self.data["id"], text)
        except Exception:
            pass

    def contextMenuEvent(self, event):
        menu = QMenu()
        menu.addAction("✏  Rename", self._rename)
        menu.addSeparator()
        for label, fn in [
            ("Bring to Front", self._bring_front), ("Send to Back", self._send_back),
            ("Lock/Unlock", self._toggle_lock),
            ("Connect…", lambda: self.sig.requestConnect.emit(self.data["id"])),
            ("Delete", self._delete),
        ]:
            menu.addAction(label, fn)
        menu.exec(event.screenPos())

    def _rename(self):
        name, ok = QInputDialog.getText(
            None, "Rename Document", "Title:",
            text=self.data.get("meta", {}).get("title", "")
        )
        if ok and name.strip():
            if not isinstance(self.data.get("meta"), dict): self.data["meta"] = {}
            self.data["meta"]["title"] = name.strip()
            self.update(); self._auto_save_timer.start()


# ── Todo element ───────────────────────────────────────────────────────────────
class TodoElement(BaseElement):
    """
    Checklist. Checkboxes are toggled directly by clicking them on the card.
    Double-click opens the full editor dialog for add/remove/rename tasks.
    """
    ELEMENT_TYPE = "todo"

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        r    = self.boundingRect()
        path = QPainterPath()
        path.addRoundedRect(r, CORNER_RADIUS, CORNER_RADIUS)
        painter.fillPath(path, QColor("#1a2040"))
        painter.setPen(QPen(QColor("#2a3060"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        # Header
        painter.setPen(QColor(ACCENT))
        painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
        painter.drawText(QRectF(12, 10, self.w() - 24, 20), Qt.AlignLeft, "☑  TO-DO")

        # Done / total badge
        items = self._get_items()
        done  = sum(1 for i in items if i.get("done"))
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor(TEXT_MUTED))
        painter.drawText(QRectF(12, 10, self.w() - 24, 20),
                         Qt.AlignRight, f"{done}/{len(items)}")

        # Individual items with checkboxes
        y = 36
        painter.setFont(QFont("Segoe UI", 11))
        for item in items:
            is_done = item.get("done", False)
            text    = item.get("text", "")
            cb_rect = QRectF(12, y, 14, 14)
            painter.setPen(QPen(QColor(ACCENT) if is_done else QColor(BORDER_COLOR), 1.5))
            painter.setBrush(QColor(ACCENT) if is_done else Qt.NoBrush)
            painter.drawRoundedRect(cb_rect, 3, 3)
            if is_done:
                painter.setPen(QPen(QColor("white"), 1.5))
                painter.drawText(cb_rect, Qt.AlignCenter, "✓")
            painter.setPen(QColor(TEXT_MUTED) if is_done else QColor(TEXT_PRIMARY))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(QRectF(30, y - 1, self.w() - 42, 16),
                             Qt.AlignVCenter | Qt.AlignLeft,
                             text[:35] + ("…" if len(text) > 35 else ""))
            y += 22
            if y > self.h() - 20:
                break
        self._paint_selection(painter)

    def _get_items(self) -> list:
        meta = self.data.get("meta", {})
        if isinstance(meta, str): meta = json.loads(meta)
        return meta.get("items", [])

    def mousePressEvent(self, event):
        """Toggle checkboxes by clicking directly on the card."""
        if event.button() == Qt.LeftButton and not self._hit_handle(event.pos()):
            items = self._get_items()
            y = 36
            for idx, item in enumerate(items):
                if QRectF(12, y, 18, 18).contains(event.pos()):
                    items[idx]["done"] = not item.get("done", False)
                    if not isinstance(self.data.get("meta"), dict):
                        self.data["meta"] = {}
                    self.data["meta"]["items"] = items
                    self.update()
                    self._auto_save_timer.start()
                    event.accept()
                    return
                y += 22
                if y > self.h() - 20:
                    break
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        from ui.dialogs import TodoDialog
        dlg = TodoDialog(self.data)
        if dlg.exec():
            self.data = dlg.result_data
            self.update()
            self._auto_save_timer.start()


# ── Link element ───────────────────────────────────────────────────────────────
class LinkElement(BaseElement):
    """URL bookmark card. Right-click to fetch title or set a custom name."""
    ELEMENT_TYPE = "link"

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        r    = self.boundingRect()
        path = QPainterPath()
        path.addRoundedRect(r, CORNER_RADIUS, CORNER_RADIUS)
        painter.fillPath(path, QColor("#1a2d1a"))
        painter.setPen(QPen(QColor("#2a4030"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        meta  = self.data.get("meta", {})
        url   = self.data.get("content", "")
        title = meta.get("custom_name") or meta.get("title") or url
        icon  = meta.get("favicon", "🔗")

        painter.setPen(QColor(TEXT_PRIMARY))
        painter.setFont(QFont("Segoe UI", 20))
        painter.drawText(QRectF(12, 10, 36, 36), Qt.AlignCenter, icon)

        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        painter.drawText(QRectF(54, 12, self.w() - 66, 20),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         title[:40] + ("…" if len(title) > 40 else ""))

        painter.setPen(QColor("#3dd68c"))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(QRectF(54, 34, self.w() - 66, 16),
                         Qt.AlignLeft,
                         url[:55] + ("…" if len(url) > 55 else ""))
        self._paint_selection(painter)

    def mouseDoubleClickEvent(self, event):
        import webbrowser
        url = self.data.get("content", "")
        if url:
            webbrowser.open(url)

    def contextMenuEvent(self, event):
        menu = QMenu()
        menu.addAction("🖊  Set Custom Name", self._set_name)
        menu.addAction("🔄  Fetch Page Title", self._fetch_title)
        menu.addAction("🌐  Open in Browser",  lambda: self.mouseDoubleClickEvent(None))
        menu.addSeparator()
        for label, fn in [
            ("Bring to Front", self._bring_front), ("Send to Back", self._send_back),
            ("Lock/Unlock", self._toggle_lock),
            ("Connect…", lambda: self.sig.requestConnect.emit(self.data["id"])),
            ("Delete", self._delete),
        ]:
            menu.addAction(label, fn)
        menu.exec(event.screenPos())

    def _set_name(self):
        meta = self.data.get("meta", {})
        name, ok = QInputDialog.getText(
            None, "Custom Name", "Display name:",
            text=meta.get("custom_name", "")
        )
        if ok:
            if not isinstance(meta, dict): meta = {}
            meta["custom_name"] = name.strip()
            self.data["meta"] = meta
            self.update(); self._auto_save_timer.start()

    def _fetch_title(self):
        url = self.data.get("content", "")
        if not url: return
        try:
            import urllib.request, html.parser
            class _P(html.parser.HTMLParser):
                title = ""; _in = False
                def handle_starttag(self, t, a):
                    if t == "title": self._in = True
                def handle_data(self, d):
                    if self._in: self.title += d
                def handle_endtag(self, t):
                    if t == "title": self._in = False
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                raw = resp.read(4096).decode("utf-8", errors="ignore")
            p = _P(); p.feed(raw)
            title = p.title.strip()
        except Exception:
            title = ""
        if title:
            if not isinstance(self.data.get("meta"), dict): self.data["meta"] = {}
            self.data["meta"]["title"] = title
            self.update(); self._auto_save_timer.start()


# ── Image element ──────────────────────────────────────────────────────────────
class ImageElement(BaseElement):
    ELEMENT_TYPE = "image"

    def __init__(self, data: dict, canvas):
        super().__init__(data, canvas)
        self._pixmap = None
        self._load_image()

    def _load_image(self):
        path = self.data.get("content", "")
        if path and os.path.exists(path):
            pm = QPixmap(path)
            if not pm.isNull():
                self._pixmap = pm

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        r    = self.boundingRect()
        path = QPainterPath()
        path.addRoundedRect(r, CORNER_RADIUS, CORNER_RADIUS)
        painter.setClipPath(path)
        if self._pixmap:
            painter.drawPixmap(r.toRect(), self._pixmap)
        else:
            painter.fillPath(path, QColor(CARD_BG))
            painter.setPen(QColor(TEXT_MUTED))
            painter.setFont(QFont("Segoe UI", 11))
            painter.drawText(r, Qt.AlignCenter, "🖼  Double-click to load image")
        painter.setClipping(False)
        painter.setPen(QPen(QColor(BORDER_COLOR), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        self._paint_selection(painter)

    def mouseDoubleClickEvent(self, event):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            None, "Select Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)"
        )
        if path:
            self.data["content"] = path
            self._load_image()
            self.update()
            self._auto_save_timer.start()


# ── Video element ──────────────────────────────────────────────────────────────
class VideoElement(BaseElement):
    ELEMENT_TYPE = "video"

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        r    = self.boundingRect()
        path = QPainterPath()
        path.addRoundedRect(r, CORNER_RADIUS, CORNER_RADIUS)
        grad = QLinearGradient(0, 0, 0, self.h())
        grad.setColorAt(0, QColor("#1a1a2a"))
        grad.setColorAt(1, QColor("#0d0d18"))
        painter.fillPath(path, QBrush(grad))
        painter.setPen(QPen(QColor("#2a2a45"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        meta     = self.data.get("meta", {})
        filename = meta.get("filename", os.path.basename(self.data.get("content", "video")))
        ext      = meta.get("ext", "")

        cx, cy = self.w() / 2, self.h() / 2 - 10
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 30)))
        painter.drawEllipse(QPointF(cx, cy), 28, 28)
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Segoe UI", 22))
        painter.drawText(QRectF(cx - 12, cy - 14, 30, 28), Qt.AlignCenter, "▶")

        painter.setPen(QColor(TEXT_PRIMARY))
        painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
        painter.drawText(QRectF(10, self.h() - 34, self.w() - 20, 16),
                         Qt.AlignHCenter, filename[:40] + ("…" if len(filename) > 40 else ""))
        painter.setPen(QColor(TEXT_MUTED))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(QRectF(10, self.h() - 18, self.w() - 20, 14),
                         Qt.AlignHCenter, ext.upper() + " • Double-click to play")
        self._paint_selection(painter)

    def mouseDoubleClickEvent(self, event):
        import subprocess, sys
        path = self.data.get("content", "")
        if not os.path.exists(path): return
        if sys.platform == "win32":    os.startfile(path)
        elif sys.platform == "darwin": subprocess.Popen(["open", path])
        else:                          subprocess.Popen(["xdg-open", path])

    def contextMenuEvent(self, event):
        menu = QMenu()
        menu.addAction("▶  Play", lambda: self.mouseDoubleClickEvent(None))
        menu.addAction("📂  Change File", self._change_file)
        menu.addSeparator()
        for label, fn in [
            ("Bring to Front", self._bring_front), ("Send to Back", self._send_back),
            ("Lock/Unlock", self._toggle_lock),
            ("Connect…", lambda: self.sig.requestConnect.emit(self.data["id"])),
            ("Delete", self._delete),
        ]:
            menu.addAction(label, fn)
        menu.exec(event.screenPos())

    def _change_file(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            None, "Select Video", "",
            "Video files (*.mp4 *.mkv *.avi *.mov *.wmv *.webm *.flv)"
        )
        if path:
            fn = os.path.basename(path)
            ext = os.path.splitext(fn)[1].lstrip(".")
            self.data["content"] = path
            if not isinstance(self.data.get("meta"), dict): self.data["meta"] = {}
            self.data["meta"].update({"filename": fn, "ext": ext})
            self.update(); self._auto_save_timer.start()


# ── Audio element ──────────────────────────────────────────────────────────────
class AudioElement(BaseElement):
    ELEMENT_TYPE = "audio"

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        r    = self.boundingRect()
        path = QPainterPath()
        path.addRoundedRect(r, CORNER_RADIUS, CORNER_RADIUS)
        painter.fillPath(path, QColor("#1a2535"))
        painter.setPen(QPen(QColor("#253050"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        meta     = self.data.get("meta", {})
        filename = meta.get("filename", os.path.basename(self.data.get("content", "audio")))
        ext      = meta.get("ext", "")

        painter.setPen(QColor(ACCENT))
        painter.setFont(QFont("Segoe UI", 28))
        painter.drawText(QRectF(10, 8, 50, 50), Qt.AlignCenter, "🎵")

        bar_heights = [12, 20, 28, 16, 32, 24, 18, 30, 22, 14, 26, 20, 16]
        bx = 70
        mid_y = self.h() / 2
        for bh in bar_heights:
            by = mid_y - (bh / 2)
            painter.setPen(Qt.NoPen)
            # Build colour with alpha manually to avoid f-string hex concat issues
            bar_color = QColor(ACCENT)
            bar_color.setAlpha(150)
            painter.setBrush(QBrush(bar_color))
            painter.drawRoundedRect(QRectF(bx, by, 5, bh), 2, 2)
            bx += 8
            if bx > self.w() - 20: break

        painter.setPen(QColor(TEXT_PRIMARY))
        painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
        painter.drawText(QRectF(10, self.h() - 34, self.w() - 20, 16),
                         Qt.AlignHCenter, filename[:40] + ("…" if len(filename) > 40 else ""))
        painter.setPen(QColor(TEXT_MUTED))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(QRectF(10, self.h() - 18, self.w() - 20, 14),
                         Qt.AlignHCenter, ext.upper() + " • Double-click to play")
        self._paint_selection(painter)

    def mouseDoubleClickEvent(self, event):
        import subprocess, sys
        path = self.data.get("content", "")
        if not os.path.exists(path): return
        if sys.platform == "win32":    os.startfile(path)
        elif sys.platform == "darwin": subprocess.Popen(["open", path])
        else:                          subprocess.Popen(["xdg-open", path])


# ── Table element ──────────────────────────────────────────────────────────────
class TableElement(BaseElement):
    """
    Spreadsheet grid. Preview painted via QPainter; double-click embeds
    a live QTableWidget. Uses deferred close to avoid C++ deletion crashes.
    Swallows Delete/Backspace so typing in cells doesn't delete the element.
    """
    ELEMENT_TYPE = "table"

    def __init__(self, data: dict, canvas):
        super().__init__(data, canvas)
        self._proxy: QGraphicsProxyWidget | None = None
        self._tw_ref: QTableWidget | None = None   # keep reference to avoid GC

    def prepareForDelete(self):
        self._close_proxy()

    def _close_proxy(self):
        if self._proxy is not None:
            proxy, self._proxy = self._proxy, None
            self._tw_ref = None
            _safe_remove_proxy(self.scene(), proxy)
            self.update()

    def _get_cells(self) -> list[list[str]]:
        meta = self.data.get("meta", {})
        if isinstance(meta, str): meta = json.loads(meta)
        return meta.get("cells", [["", "", ""], ["", "", ""], ["", "", ""]])

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        r  = self.boundingRect()
        bg = QPainterPath()
        bg.addRoundedRect(r, CORNER_RADIUS, CORNER_RADIUS)
        painter.fillPath(bg, QColor("#141e2a"))
        painter.setPen(QPen(QColor("#1e2d40"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(bg)

        if self._proxy:
            self._paint_selection(painter)
            return

        cells = self._get_cells()
        rows  = len(cells)
        cols  = len(cells[0]) if cells else 3
        cell_h = max(20, (self.h() - 14) / max(rows, 1))
        cell_w = (self.w() - 4)  / max(cols, 1)

        for ri, row in enumerate(cells):
            for ci, val in enumerate(row):
                cx = 2 + ci * cell_w
                cy = 6 + ri * cell_h
                cr = QRectF(cx, cy, cell_w, cell_h)
                painter.fillRect(cr, QColor("#1e2d40") if ri == 0 else QColor("#14202e"))
                painter.setPen(QPen(QColor("#2a3d55"), 0.5))
                painter.drawRect(cr)
                painter.setPen(QColor(ACCENT) if ri == 0 else QColor(TEXT_PRIMARY))
                painter.setFont(QFont("Segoe UI", 9,
                                      QFont.Bold if ri == 0 else QFont.Normal))
                painter.drawText(cr.adjusted(3, 2, -3, -2),
                                 Qt.AlignLeft | Qt.AlignVCenter, str(val)[:15])
        self._paint_selection(painter)

    def mouseDoubleClickEvent(self, event):
        if self._proxy:
            return
        cells = self._get_cells()
        rows, cols = len(cells), (len(cells[0]) if cells else 3)

        tw = QTableWidget(rows, cols)
        self._tw_ref = tw   # prevent garbage collection
        tw.setStyleSheet(f"""
            QTableWidget {{
                background: #0d1520; gridline-color: #2a3d55;
                color: {TEXT_PRIMARY}; font-size: 10pt; border: none;
            }}
            QHeaderView::section {{
                background: #1e2d40; color: {ACCENT};
                font-weight: bold; border: 1px solid #2a3d55; padding: 2px;
            }}
            QTableWidget::item:selected {{ background: #1e3460; }}
        """)
        tw.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        tw.verticalHeader().setVisible(False)

        for ri, row in enumerate(cells):
            for ci, val in enumerate(row):
                tw.setItem(ri, ci, QTableWidgetItem(str(val)))

        tw.setFixedSize(int(self.w() - 4), int(self.h() - 10))
        self._proxy = QGraphicsProxyWidget(self)
        self._proxy.setWidget(tw)
        self._proxy.setPos(2, 6)
        tw.setFocus()
        tw.cellChanged.connect(lambda r, c, _tw=tw: self._cell_changed(_tw, r, c))

        def _on_focus_out(event, _tw=tw):
            QTimer.singleShot(0, lambda: self._finish_table(_tw))
            try:
                QTableWidget.focusOutEvent(_tw, event)
            except RuntimeError:
                pass

        tw.focusOutEvent = _on_focus_out
        event.accept()

    def keyPressEvent(self, event):
        """
        Swallow Delete/Backspace so typing in the embedded table
        does not accidentally trigger canvas element deletion.
        """
        if self._proxy and event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            event.accept()   # eat the event — let the table widget handle it
            return
        super().keyPressEvent(event)

    def _cell_changed(self, tw: QTableWidget, row: int, col: int):
        cells = self._get_cells()
        while row >= len(cells):      cells.append([""] * max(len(cells[0]) if cells else 3, 1))
        while col >= len(cells[row]): cells[row].append("")
        item = tw.item(row, col)
        cells[row][col] = item.text() if item else ""
        if not isinstance(self.data.get("meta"), dict): self.data["meta"] = {}
        self.data["meta"]["cells"] = cells
        self._auto_save_timer.start()

    def _finish_table(self, tw: QTableWidget):
        try:
            # Sync final cell values before closing
            cells = self._get_cells()
            for ri in range(tw.rowCount()):
                while ri >= len(cells): cells.append([""] * (len(cells[0]) if cells else 3))
                for ci in range(tw.columnCount()):
                    while ci >= len(cells[ri]): cells[ri].append("")
                    item = tw.item(ri, ci)
                    cells[ri][ci] = item.text() if item else ""
            if not isinstance(self.data.get("meta"), dict): self.data["meta"] = {}
            self.data["meta"]["cells"] = cells
        except RuntimeError:
            pass  # widget already deleted — use whatever we have
        self._close_proxy()
        self._auto_save_timer.start()

    def contextMenuEvent(self, event):
        menu = QMenu()
        menu.addAction("➕  Add Row",    self._add_row)
        menu.addAction("➕  Add Column", self._add_col)
        menu.addSeparator()
        for label, fn in [
            ("Bring to Front", self._bring_front), ("Send to Back", self._send_back),
            ("Lock/Unlock", self._toggle_lock),
            ("Connect…", lambda: self.sig.requestConnect.emit(self.data["id"])),
            ("Delete", self._delete),
        ]:
            menu.addAction(label, fn)
        menu.exec(event.screenPos())

    def _add_row(self):
        cells = self._get_cells()
        cells.append([""] * (len(cells[0]) if cells else 3))
        if not isinstance(self.data.get("meta"), dict): self.data["meta"] = {}
        self.data["meta"]["cells"] = cells
        self.update(); self._auto_save_timer.start()

    def _add_col(self):
        cells = self._get_cells()
        for row in cells: row.append("")
        if not isinstance(self.data.get("meta"), dict): self.data["meta"] = {}
        self.data["meta"]["cells"] = cells
        self.update(); self._auto_save_timer.start()


# ── File element ───────────────────────────────────────────────────────────────
class FileElement(BaseElement):
    """Generic file attachment — double-click opens with OS default app."""
    ELEMENT_TYPE = "file"

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        r    = self.boundingRect()
        path = QPainterPath()
        path.addRoundedRect(r, CORNER_RADIUS, CORNER_RADIUS)
        painter.fillPath(path, QColor("#1e2535"))
        painter.setPen(QPen(QColor("#2a3550"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        meta     = self.data.get("meta", {})
        filename = meta.get("filename", "Unknown file")
        ext      = meta.get("ext", "").upper()
        size_str = meta.get("size_str", "")

        painter.setPen(QColor(ACCENT))
        painter.setFont(QFont("Segoe UI", 26))
        painter.drawText(QRectF(10, 10, 50, 50), Qt.AlignCenter, _ext_icon(ext))

        painter.setPen(QColor(TEXT_PRIMARY))
        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        painter.drawText(QRectF(64, 12, self.w() - 76, 20),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         filename[:35] + ("…" if len(filename) > 35 else ""))

        painter.setPen(QColor(TEXT_SECONDARY))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(QRectF(64, 34, self.w() - 76, 16),
                         Qt.AlignLeft, f"{ext}  •  {size_str}")

        painter.setPen(QColor(TEXT_MUTED))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(QRectF(64, self.h() - 20, self.w() - 76, 16),
                         Qt.AlignLeft, "Double-click to open")
        self._paint_selection(painter)

    def mouseDoubleClickEvent(self, event):
        import subprocess, sys
        path = self.data.get("content", "")
        if not os.path.exists(path): return
        if sys.platform == "win32":    os.startfile(path)
        elif sys.platform == "darwin": subprocess.Popen(["open", path])
        else:                          subprocess.Popen(["xdg-open", path])


# ── Sub-board card ─────────────────────────────────────────────────────────────
class BoardCard(BaseElement):
    ELEMENT_TYPE = "board"

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        r    = self.boundingRect()
        grad = QLinearGradient(0, 0, 0, self.h())
        grad.setColorAt(0, QColor("#1e2545"))
        grad.setColorAt(1, QColor("#151a38"))
        path = QPainterPath()
        path.addRoundedRect(r, CORNER_RADIUS, CORNER_RADIUS)
        painter.fillPath(path, QBrush(grad))
        painter.setPen(QPen(QColor("#2a3060"), 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        painter.setPen(QColor(ACCENT))
        painter.setFont(QFont("Segoe UI", 22))
        painter.drawText(QRectF(0, 14, self.w(), 36), Qt.AlignHCenter, "⊞")

        painter.setPen(QColor(TEXT_PRIMARY))
        painter.setFont(QFont("Segoe UI", 12, QFont.Bold))
        painter.drawText(QRectF(12, 56, self.w() - 24, 24),
                         Qt.AlignHCenter, self.data.get("content", "Board"))

        painter.setPen(QColor(TEXT_MUTED))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(QRectF(12, self.h() - 22, self.w() - 24, 16),
                         Qt.AlignHCenter, "Double-click to open")
        self._paint_selection(painter)

    def mouseDoubleClickEvent(self, event):
        ref_id = self.data.get("meta", {}).get("board_ref_id")
        if ref_id:
            self.sig.openBoard.emit(ref_id)


# ── Straight-line connection ───────────────────────────────────────────────────
class ConnectionArrow(QGraphicsItem):
    """Straight line with arrowhead between two element centres."""

    def __init__(self, conn_data: dict, from_item: BaseElement, to_item: BaseElement):
        super().__init__()
        self.conn_data = conn_data
        self.from_item = from_item
        self.to_item   = to_item
        self.setZValue(-1)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

    def boundingRect(self) -> QRectF:
        p1, p2 = self._points()
        return QRectF(p1, p2).normalized().adjusted(-16, -16, 16, 16)

    def _points(self):
        return (
            self.from_item.mapToScene(self.from_item.boundingRect().center()),
            self.to_item.mapToScene(self.to_item.boundingRect().center()),
        )

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        p1, p2 = self._points()

        color = QColor(self.conn_data.get("color", "#888888"))
        style = self.conn_data.get("style", "solid")
        pen   = QPen(color if not self.isSelected() else QColor(ACCENT), 1.8)
        if style == "dashed": pen.setStyle(Qt.DashLine)
        elif style == "dotted": pen.setStyle(Qt.DotLine)
        if self.isSelected(): pen.setWidth(2)

        painter.setPen(pen)
        painter.drawLine(p1, p2)

        if p1 != p2:
            angle = math.atan2(p2.y() - p1.y(), p2.x() - p1.x())
            arr   = 11
            a1 = QPointF(p2.x() - arr * math.cos(angle - 0.38),
                         p2.y() - arr * math.sin(angle - 0.38))
            a2 = QPointF(p2.x() - arr * math.cos(angle + 0.38),
                         p2.y() - arr * math.sin(angle + 0.38))
            arrow = QPainterPath()
            arrow.moveTo(p2); arrow.lineTo(a1); arrow.lineTo(a2); arrow.closeSubpath()
            arrowhead_color = QColor(ACCENT) if self.isSelected() else color
            painter.setPen(Qt.NoPen)
            painter.fillPath(arrow, QBrush(arrowhead_color))

        label = self.conn_data.get("label", "")
        if label:
            mid = QPointF((p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2)
            painter.setPen(QColor(TEXT_SECONDARY))
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(QRectF(mid.x() - 40, mid.y() - 10, 80, 20),
                             Qt.AlignCenter, label)

    def contextMenuEvent(self, event):
        menu = QMenu()
        menu.addAction("Delete Connection",
                       lambda: self.scene().canvas._delete_connection(self.conn_data["id"]))
        menu.exec(event.screenPos())


# ── Extension → emoji icon ─────────────────────────────────────────────────────
def _ext_icon(ext: str) -> str:
    return {
        "PDF": "📄", "DOC": "📝", "DOCX": "📝",
        "XLS": "📊", "XLSX": "📊", "CSV": "📊",
        "PPT": "📋", "PPTX": "📋",
        "ZIP": "🗜",  "RAR": "🗜",  "7Z": "🗜",
        "MP3": "🎵", "WAV": "🎵", "FLAC": "🎵",
        "MP4": "🎬", "MOV": "🎬", "AVI": "🎬",
        "PY":  "🐍", "JS":  "📜", "TS":  "📜",
        "HTML":"🌐", "CSS": "🎨", "JSON":"📦",
    }.get(ext, "📎")


# ── Factory ────────────────────────────────────────────────────────────────────
ELEMENT_CLASSES: dict[str, type[BaseElement]] = {
    "note":     NoteElement,
    "heading":  HeadingElement,
    "document": DocumentElement,
    "todo":     TodoElement,
    "link":     LinkElement,
    "image":    ImageElement,
    "video":    VideoElement,
    "audio":    AudioElement,
    "table":    TableElement,
    "file":     FileElement,
    "board":    BoardCard,
}

def make_element(data: dict, canvas) -> BaseElement:
    cls = ELEMENT_CLASSES.get(data.get("type", "note"), NoteElement)
    return cls(data, canvas)
