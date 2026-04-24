from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import threading


@dataclass(slots=True)
class SubsystemStatus:
    name: str
    state: str = "unknown"
    detail: str = "booting"
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "detail": self.detail,
            "updated_at": self.updated_at.strftime("%H:%M:%S"),
        }


@dataclass(slots=True)
class LogEntry:
    role: str
    text: str
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "text": self.text,
            "timestamp": self.timestamp.strftime("%H:%M:%S"),
        }


class AppState:
    def __init__(self, max_logs: int = 500) -> None:
        self._lock = threading.RLock()
        self._logs: deque[LogEntry] = deque(maxlen=max_logs)
        self._statuses = {
            "llm": SubsystemStatus(name="llm", detail="waiting for health check"),
            "voice": SubsystemStatus(name="voice", detail="waiting for health check"),
            "memory": SubsystemStatus(name="memory", detail="waiting for health check"),
            "actions": SubsystemStatus(name="actions", detail="waiting for health check"),
            "internet": SubsystemStatus(name="internet", detail="waiting for health check"),
            "routines": SubsystemStatus(name="routines", detail="waiting for routine store"),
        }

    def add_log(self, role: str, text: str) -> LogEntry:
        entry = LogEntry(role=role, text=text)
        with self._lock:
            self._logs.append(entry)
        return entry

    def set_status(self, name: str, state: str, detail: str) -> None:
        with self._lock:
            status = self._statuses.get(name, SubsystemStatus(name=name))
            status.state = state
            status.detail = detail
            status.updated_at = datetime.now()
            self._statuses[name] = status

    def snapshot_statuses(self) -> dict[str, dict]:
        with self._lock:
            return {name: status.to_dict() for name, status in self._statuses.items()}

    def recent_logs(self) -> list[dict]:
        with self._lock:
            return [entry.to_dict() for entry in self._logs]
