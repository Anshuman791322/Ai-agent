from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=3.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA busy_timeout=3000")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'typed',
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            """
        )
        conn.commit()
        conn.close()

    def append_message(self, role: str, content: str, source: str = "typed") -> None:
        conn = self._connect()
        conn.execute(
            "INSERT INTO conversation_log (role, content, source, created_at) VALUES (?, ?, ?, ?)",
            (role, content, source, time.time()),
        )
        conn.commit()
        conn.close()

    def recent_messages(self, limit: int = 12) -> list[dict]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT role, content
            FROM conversation_log
            WHERE role IN ('user', 'assistant')
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(row) for row in reversed(rows)]

    def remember(self, content: str) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT INTO memory_items (content, created_at) VALUES (?, ?)",
            (content, time.time()),
        )
        conn.commit()
        conn.close()

    def search_memory(self, query: str, limit: int = 3) -> list[str]:
        conn = self._connect()
        rows = conn.execute(
            """
            SELECT content
            FROM memory_items
            WHERE content LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (f"%{query.strip()}%", limit),
        ).fetchall()
        conn.close()
        return [row["content"] for row in rows]

    def healthcheck(self) -> dict:
        try:
            conn = self._connect()
            conn.execute("SELECT 1").fetchone()
            conn.close()
            return {"state": "ok", "detail": str(self.db_path)}
        except Exception as exc:
            return {"state": "error", "detail": f"SQLite unavailable: {exc}"}
