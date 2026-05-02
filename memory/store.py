from __future__ import annotations

import contextlib
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path

from security.models import MemoryTag
from security.redaction import redact_secrets


_BLOCKED_TAG_VALUE = "__jarvis_blocked_tag__"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=3.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA busy_timeout=3000")
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
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
                    tag TEXT NOT NULL DEFAULT 'general',
                    created_at REAL NOT NULL
                );
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(memory_items)").fetchall()}
            if "tag" not in columns:
                conn.execute("ALTER TABLE memory_items ADD COLUMN tag TEXT NOT NULL DEFAULT 'general'")
            conn.commit()

    def append_message(self, role: str, content: str, source: str = "typed") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversation_log (role, content, source, created_at) VALUES (?, ?, ?, ?)",
                (role, redact_secrets(content), source, time.time()),
            )
            conn.commit()

    def recent_messages(self, limit: int = 12) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content, source
                FROM conversation_log
                WHERE role IN ('user', 'assistant')
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def remember(self, content: str, tag: MemoryTag = MemoryTag.GENERAL) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO memory_items (content, tag, created_at) VALUES (?, ?, ?)",
                (redact_secrets(content), tag.value, time.time()),
            )
            conn.commit()

    def search_memory(
        self,
        query: str,
        limit: int = 3,
        allowed_tags: tuple[MemoryTag, ...] = (MemoryTag.SAFE, MemoryTag.GENERAL),
    ) -> list[dict]:
        like_pattern = f"%{_escape_like(query.strip())}%"
        with self._connect() as conn:
            query_sql, tag_params = self._search_memory_query(allowed_tags)
            rows = conn.execute(
                query_sql,
                (like_pattern, *tag_params, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def count_matching_memory(self, query: str, allowed_tags: tuple[MemoryTag, ...]) -> int:
        like_pattern = f"%{_escape_like(query.strip())}%"
        with self._connect() as conn:
            query_sql, tag_params = self._count_memory_query(allowed_tags)
            row = conn.execute(
                query_sql,
                (like_pattern, *tag_params),
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def list_memories(
        self,
        limit: int = 20,
        allowed_tags: tuple[MemoryTag, ...] = (MemoryTag.SAFE, MemoryTag.GENERAL, MemoryTag.SENSITIVE),
    ) -> list[dict]:
        with self._connect() as conn:
            query_sql, tag_params = self._list_memories_query(allowed_tags)
            rows = conn.execute(
                query_sql,
                (*tag_params, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def forget(self, memory_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM memory_items WHERE id = ?", (memory_id,))
            conn.commit()
            return cursor.rowcount > 0

    def healthcheck(self) -> dict:
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1").fetchone()
            return {"state": "ok", "detail": str(self.db_path)}
        except Exception as exc:
            return {"state": "error", "detail": f"SQLite unavailable: {exc}"}

    @staticmethod
    def _tag_clause(allowed_tags: tuple[MemoryTag, ...]) -> tuple[str, ...]:
        allowed_values = {tag.value for tag in allowed_tags}
        if not allowed_values:
            raise ValueError("At least one memory tag must be supplied.")
        return tuple(tag.value if tag.value in allowed_values else _BLOCKED_TAG_VALUE for tag in MemoryTag)

    def _search_memory_query(self, allowed_tags: tuple[MemoryTag, ...]) -> tuple[str, tuple[str, ...]]:
        tag_values = self._tag_clause(allowed_tags)
        sql = (
            "SELECT id, content, tag "
            "FROM memory_items "
            "WHERE content LIKE ? ESCAPE '\\' "
            "AND tag IN (?, ?, ?) "
            "ORDER BY id DESC LIMIT ?"
        )
        return sql, tag_values

    def _count_memory_query(self, allowed_tags: tuple[MemoryTag, ...]) -> tuple[str, tuple[str, ...]]:
        tag_values = self._tag_clause(allowed_tags)
        sql = (
            "SELECT COUNT(*) AS count "
            "FROM memory_items "
            "WHERE content LIKE ? ESCAPE '\\' "
            "AND tag IN (?, ?, ?)"
        )
        return sql, tag_values

    def _list_memories_query(self, allowed_tags: tuple[MemoryTag, ...]) -> tuple[str, tuple[str, ...]]:
        tag_values = self._tag_clause(allowed_tags)
        sql = (
            "SELECT id, content, tag, created_at "
            "FROM memory_items "
            "WHERE tag IN (?, ?, ?) "
            "ORDER BY id DESC LIMIT ?"
        )
        return sql, tag_values
