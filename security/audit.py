from __future__ import annotations

import json
import threading
from pathlib import Path

from security.models import AuditEntry


class AuditLogger:
    def __init__(self, app_dir: Path, debug_sensitive_logging: bool = False) -> None:
        self._lock = threading.RLock()
        self._debug_sensitive_logging = debug_sensitive_logging
        self.path = Path(app_dir) / "audit.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, entry: AuditEntry) -> None:
        payload = entry.to_dict()
        if not self._debug_sensitive_logging and "prompt" in payload.get("metadata", {}):
            payload["metadata"]["prompt"] = "[REDACTED]"
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

