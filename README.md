# Milanote Clone — Desktop App

A feature-rich, offline-first visual workspace desktop app inspired by Milanote.
Built with **Python + PySide6 + SQLite**.

---

## ✨ Features

| Category        | Feature                                           |
|-----------------|---------------------------------------------------|
| **Canvas**      | Infinite scrollable/zoomable canvas               |
|                 | Background dot-grid (toggle on/off)               |
|                 | Pan via Middle-mouse or Alt+Drag                  |
|                 | Zoom via Ctrl+Scroll or toolbar buttons           |
| **Boards**      | Create / rename / delete boards                   |
|                 | Nested sub-boards (click card to open)            |
|                 | Breadcrumb navigation with back button            |
| **Elements**    | 📝 Sticky Notes (8 colour themes)                 |
|                 | ☑ To-Do lists (check/uncheck, add/remove tasks)  |
|                 | 🔗 Link cards (click to open in browser)          |
|                 | 🖼 Image cards (PNG, JPG, GIF, WebP, BMP)         |
|                 | ⊞ Sub-board cards (nested boards)                |
| **Interactions**| Drag to move elements                             |
|                 | Corner handles to resize elements                 |
|                 | Double-click to edit content                      |
|                 | Right-click context menu on all elements          |
|                 | Lock / unlock elements                            |
|                 | Bring to front / send to back (z-index)           |
| **Connections** | Draw bezier arrows between any two elements       |
|                 | Delete connections via right-click                |
| **Editing**     | Undo / Redo (Ctrl+Z / Ctrl+Y)                    |
|                 | Select all (Ctrl+A)                               |
|                 | Delete selected (Delete / Backspace)              |
| **Search**      | Live search filters elements by content           |
| **Persistence** | Auto-save on move/resize/edit (debounced 800 ms)  |
|                 | SQLite database in `data/app.db`                  |

---

## 🚀 Quick Start

### 1. Install Python ≥ 3.10

### 2. Install dependencies
```bash
pip install PySide6
```

### 3. Run the app
```bash
python main.py
```

---

## 🗂 Project Structure

```
milanote_clone/
├── main.py                 # Entry point
├── requirements.txt
├── data/
│   └── app.db              # SQLite database (auto-created)
├── database/
│   └── db.py               # All DB access functions
├── models/                 # (reserved for future model layer)
├── ui/
│   ├── main_window.py      # Top-level QMainWindow
│   ├── sidebar.py          # Left sidebar (boards list, search)
│   ├── toolbar.py          # Top toolbar (add, zoom, undo)
│   ├── canvas.py           # Infinite canvas (QGraphicsView)
│   ├── elements.py         # All element graphics items
│   └── dialogs.py          # Modal dialogs (Todo editor, Rename)
└── utils/
    └── theme.py            # Colors, QSS stylesheet
```

---

## ⌨️ Keyboard Shortcuts

| Shortcut         | Action              |
|------------------|---------------------|
| Ctrl+Z           | Undo                |
| Ctrl+Y / Ctrl+Shift+Z | Redo          |
| Ctrl+A           | Select all          |
| Ctrl+0           | Reset zoom          |
| Ctrl+Scroll      | Zoom in/out         |
| Delete/Backspace | Delete selected     |
| Escape           | Cancel / Deselect   |
| Middle-mouse drag| Pan canvas          |
| Alt+Left-drag    | Pan canvas          |
| Double-click canvas | Add quick note  |
| Double-click element | Edit element   |

---

## 🗄 Database Schema

### `boards`
| Column     | Type    | Description                  |
|------------|---------|------------------------------|
| id         | INTEGER | Primary key                  |
| parent_id  | INTEGER | Parent board (null = root)   |
| name       | TEXT    | Board display name           |
| color      | TEXT    | Board accent colour          |
| created_at | TEXT    | ISO 8601 timestamp           |
| updated_at | TEXT    | ISO 8601 timestamp           |

### `elements`
| Column     | Type    | Description                  |
|------------|---------|------------------------------|
| id         | INTEGER | Primary key                  |
| board_id   | INTEGER | Owning board                 |
| type       | TEXT    | note / todo / link / image / board |
| content    | TEXT    | Main text / URL / file path  |
| meta       | TEXT    | JSON blob (extra data)       |
| x, y       | REAL    | Canvas position              |
| width, height | REAL | Dimensions                  |
| z_index    | INTEGER | Layer order                  |
| locked     | INTEGER | 0=unlocked, 1=locked         |
| color      | TEXT    | Element colour               |
| tags       | TEXT    | JSON array of tag strings    |

### `connections`
| Column   | Type    | Description                    |
|----------|---------|--------------------------------|
| id       | INTEGER | Primary key                    |
| board_id | INTEGER | Owning board                   |
| from_id  | INTEGER | Source element id              |
| to_id    | INTEGER | Target element id              |
| label    | TEXT    | Optional arrow label           |
| style    | TEXT    | solid / dashed / dotted        |
| color    | TEXT    | Arrow colour                   |

---

## 🔧 Extending

### Add a new element type
1. Create a subclass of `BaseElement` in `ui/elements.py`
2. Implement `paint()` and (optionally) `mouseDoubleClickEvent()`
3. Register it in the `ELEMENT_CLASSES` dict at the bottom of `elements.py`
4. Add a toolbar button in `ui/toolbar.py` and wire it up in `ui/main_window.py`
5. Add the `add_xxx()` method to `ui/canvas.py`

### Change the colour scheme
Edit `utils/theme.py` — all colours are defined as module-level constants
and the `APP_QSS` stylesheet references them.

---

## 📋 Roadmap / Future Features
- [ ] Export board as PNG / PDF
- [ ] Markdown rendering in notes
- [ ] Tags and filters panel
- [ ] Real-time collaboration (WebSocket)
- [ ] Board templates
- [ ] Keyboard shortcut cheat-sheet overlay
- [ ] Snap-to-grid alignment
