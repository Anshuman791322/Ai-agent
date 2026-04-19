from __future__ import annotations

from dataclasses import dataclass

from config.settings import AppSettings
from integrations.windows_context import WindowContext
from memory.store import MemoryStore
from security.models import ContextSelection, MemoryTag
from security.redaction import sanitize_untrusted_text


@dataclass(slots=True)
class ContextBundle:
    notes: list[str]
    selection: ContextSelection
    memory_items_used: int = 0
    sensitive_items_blocked: int = 0

    @property
    def summary(self) -> str:
        if not self.notes:
            return "minimal"
        return self.selection.summary


class ContextManager:
    def __init__(self, settings: AppSettings, memory: MemoryStore) -> None:
        self.settings = settings
        self.memory = memory

    def infer_selection(self, text: str, *, include_recent_chat: bool = True) -> ContextSelection:
        lowered = text.lower()
        return ContextSelection(
            current_window=any(token in lowered for token in ("current window", "this window", "active window", "active app")),
            project_memory=any(token in lowered for token in ("remember", "memory", "previous note", "project note")),
            recent_chat=include_recent_chat,
        )

    def build_context_bundle(
        self,
        query: str,
        selection: ContextSelection,
        window_context: WindowContext,
        *,
        for_handoff: bool = False,
    ) -> ContextBundle:
        notes: list[str] = []
        memory_items_used = 0
        sensitive_items_blocked = 0

        if selection.current_window and window_context.summary:
            notes.append(
                "Current window (redacted): "
                + sanitize_untrusted_text(window_context.summary, max_chars=self.settings.max_context_chars // 3)
            )

        if selection.project_memory:
            memories = self.memory.search_memory(
                query,
                limit=self.settings.max_memory_items_injected,
                allowed_tags=(MemoryTag.SAFE, MemoryTag.GENERAL),
            )
            sensitive_items_blocked = self.memory.count_matching_memory(query, allowed_tags=(MemoryTag.SENSITIVE,))
            for memory in memories:
                notes.append(
                    "Project memory (untrusted): "
                    + sanitize_untrusted_text(memory["content"], max_chars=self.settings.max_context_chars // 3)
                )
            memory_items_used = len(memories)

        if for_handoff:
            selection = ContextSelection(
                current_window=selection.current_window,
                project_memory=selection.project_memory,
                recent_chat=False,
            )

        return ContextBundle(
            notes=notes,
            selection=selection,
            memory_items_used=memory_items_used,
            sensitive_items_blocked=sensitive_items_blocked,
        )

    def recent_chat_messages(self, limit: int) -> list[dict]:
        rows = self.memory.recent_messages(limit=limit)
        sanitized: list[dict] = []
        for row in rows:
            sanitized.append(
                {
                    "role": row["role"],
                    "content": sanitize_untrusted_text(row["content"], max_chars=self.settings.max_context_chars // 2),
                }
            )
        return sanitized

