"""
database/db.py
All SQLite persistence: schema init, CRUD for boards, elements, connections.

Changes:
  - boards table now has a sort_order INTEGER column for drag-to-reorder
  - get_all_boards() orders by sort_order ASC
  - swap_board_order() swaps two boards' positions
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "app.db")


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    cur  = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS boards (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id   INTEGER REFERENCES boards(id) ON DELETE CASCADE,
            name        TEXT    NOT NULL DEFAULT 'Untitled Board',
            color       TEXT    DEFAULT '#1a1a2e',
            sort_order  INTEGER DEFAULT 0,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS elements (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            board_id    INTEGER NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
            type        TEXT    NOT NULL,
            content     TEXT    DEFAULT '',
            meta        TEXT    DEFAULT '{}',
            x           REAL    DEFAULT 0,
            y           REAL    DEFAULT 0,
            width       REAL    DEFAULT 200,
            height      REAL    DEFAULT 120,
            z_index     INTEGER DEFAULT 0,
            locked      INTEGER DEFAULT 0,
            color       TEXT    DEFAULT '#ffffff',
            tags        TEXT    DEFAULT '[]',
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS connections (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            board_id    INTEGER NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
            from_id     INTEGER NOT NULL REFERENCES elements(id) ON DELETE CASCADE,
            to_id       INTEGER NOT NULL REFERENCES elements(id) ON DELETE CASCADE,
            label       TEXT    DEFAULT '',
            style       TEXT    DEFAULT 'solid',
            color       TEXT    DEFAULT '#888888',
            created_at  TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tags (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT UNIQUE NOT NULL,
            color   TEXT DEFAULT '#4a9eff'
        );
    """)
    conn.commit()

    # Migration: add sort_order if it doesn't exist (for users with older DBs)
    try:
        cur.execute("ALTER TABLE boards ADD COLUMN sort_order INTEGER DEFAULT 0")
        conn.commit()
        # Populate sort_order for existing rows by their rowid
        cur.execute("UPDATE boards SET sort_order = id")
        conn.commit()
    except Exception:
        pass  # column already exists — safe to ignore

    conn.close()


def _now() -> str:
    return datetime.utcnow().isoformat()


# ── Boards ────────────────────────────────────────────────────────────────────

def create_board(name="Untitled Board", parent_id=None, color="#1a1a2e") -> int:
    conn = get_connection()
    cur  = conn.cursor()
    now  = _now()
    # Sort new boards at the top (sort_order = 0, shift others down)
    cur.execute("UPDATE boards SET sort_order = sort_order + 1 WHERE parent_id IS ?",
                (parent_id,))
    cur.execute(
        "INSERT INTO boards (name, parent_id, color, sort_order, created_at, updated_at)"
        " VALUES (?,?,?,0,?,?)",
        (name, parent_id, color, now, now)
    )
    board_id = cur.lastrowid
    conn.commit()
    conn.close()
    return board_id


def get_all_boards(parent_id=None):
    conn = get_connection()
    cur  = conn.cursor()
    if parent_id is None:
        cur.execute(
            "SELECT * FROM boards WHERE parent_id IS NULL ORDER BY sort_order ASC"
        )
    else:
        cur.execute(
            "SELECT * FROM boards WHERE parent_id=? ORDER BY sort_order ASC",
            (parent_id,)
        )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_board(board_id: int):
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM boards WHERE id=?", (board_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def update_board(board_id: int, **kwargs):
    if not kwargs:
        return
    kwargs["updated_at"] = _now()
    fields = ", ".join(f"{k}=?" for k in kwargs)
    vals   = list(kwargs.values()) + [board_id]
    conn = get_connection()
    conn.execute(f"UPDATE boards SET {fields} WHERE id=?", vals)
    conn.commit()
    conn.close()


def delete_board(board_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM boards WHERE id=?", (board_id,))
    conn.commit()
    conn.close()


def move_board_up(board_id: int):
    """Decrease sort_order of this board, swap with the one above it."""
    boards = get_all_boards()
    ids    = [b["id"] for b in boards]
    if board_id not in ids:
        return
    idx = ids.index(board_id)
    if idx == 0:
        return  # already at top
    # Swap sort_order with the board above
    a, b_ = boards[idx - 1], boards[idx]
    conn = get_connection()
    conn.execute("UPDATE boards SET sort_order=? WHERE id=?", (b_["sort_order"], a["id"]))
    conn.execute("UPDATE boards SET sort_order=? WHERE id=?", (a["sort_order"], b_["id"]))
    conn.commit()
    conn.close()


def move_board_down(board_id: int):
    """Increase sort_order of this board, swap with the one below it."""
    boards = get_all_boards()
    ids    = [b["id"] for b in boards]
    if board_id not in ids:
        return
    idx = ids.index(board_id)
    if idx >= len(ids) - 1:
        return  # already at bottom
    a, b_ = boards[idx], boards[idx + 1]
    conn = get_connection()
    conn.execute("UPDATE boards SET sort_order=? WHERE id=?", (b_["sort_order"], a["id"]))
    conn.execute("UPDATE boards SET sort_order=? WHERE id=?", (a["sort_order"], b_["id"]))
    conn.commit()
    conn.close()


# ── Elements ──────────────────────────────────────────────────────────────────

def create_element(board_id: int, type_: str, x=0.0, y=0.0,
                   width=200.0, height=120.0, content="",
                   color="#ffffff", meta=None) -> int:
    conn     = get_connection()
    cur      = conn.cursor()
    now      = _now()
    meta_str = json.dumps(meta or {})
    cur.execute(
        "INSERT INTO elements"
        " (board_id, type, content, meta, x, y, width, height, color, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (board_id, type_, content, meta_str, x, y, width, height, color, now, now)
    )
    eid = cur.lastrowid
    conn.commit()
    conn.close()
    return eid


def get_elements(board_id: int):
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(
        "SELECT * FROM elements WHERE board_id=? ORDER BY z_index ASC", (board_id,)
    )
    rows = []
    for r in cur.fetchall():
        d = dict(r)
        d["meta"] = json.loads(d.get("meta") or "{}")
        d["tags"]  = json.loads(d.get("tags")  or "[]")
        rows.append(d)
    conn.close()
    return rows


def update_element(element_id: int, **kwargs):
    if not kwargs:
        return
    if "meta" in kwargs and isinstance(kwargs["meta"], dict):
        kwargs["meta"] = json.dumps(kwargs["meta"])
    if "tags" in kwargs and isinstance(kwargs["tags"], list):
        kwargs["tags"] = json.dumps(kwargs["tags"])
    kwargs["updated_at"] = _now()
    fields = ", ".join(f"{k}=?" for k in kwargs)
    vals   = list(kwargs.values()) + [element_id]
    conn = get_connection()
    conn.execute(f"UPDATE elements SET {fields} WHERE id=?", vals)
    conn.commit()
    conn.close()


def delete_element(element_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM elements WHERE id=?", (element_id,))
    conn.commit()
    conn.close()


# ── Connections ───────────────────────────────────────────────────────────────

def create_connection(board_id: int, from_id: int, to_id: int,
                      label="", style="solid", color="#888888") -> int:
    conn = get_connection()
    cur  = conn.cursor()
    now  = _now()
    cur.execute(
        "INSERT INTO connections"
        " (board_id, from_id, to_id, label, style, color, created_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (board_id, from_id, to_id, label, style, color, now)
    )
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return cid


def get_connections(board_id: int):
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM connections WHERE board_id=?", (board_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def delete_connection(conn_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM connections WHERE id=?", (conn_id,))
    conn.commit()
    conn.close()


def search_elements(query: str, board_id: int = None):
    conn = get_connection()
    cur  = conn.cursor()
    q    = f"%{query}%"
    if board_id:
        cur.execute(
            "SELECT * FROM elements WHERE board_id=? AND content LIKE ?", (board_id, q)
        )
    else:
        cur.execute("SELECT * FROM elements WHERE content LIKE ?", (q,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows
