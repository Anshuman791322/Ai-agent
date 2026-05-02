from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4


class AutonomyMode(StrEnum):
    HANDS_FREE = "hands_free"
    BALANCED = "balanced"
    STRICT = "strict"


class RiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyDecisionType(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    BLOCK = "block"


class ActionType(StrEnum):
    OPEN_APP = "open_app"
    OPEN_URL = "open_url"
    OPEN_EXPLORER = "open_explorer"
    OPEN_PATH = "open_path"
    SEARCH_FILES = "search_files"
    LIST_FILES = "list_files"
    PREVIEW_FILE = "preview_file"
    WRITE_TEXT_FILE = "write_text_file"
    RUN_WORKSPACE_COMMAND = "run_workspace_command"
    LAUNCH_CLAUDE_INTERACTIVE = "launch_claude_interactive"
    CLAUDE_TASK = "claude_task"
    ADVANCED_SHELL = "advanced_shell"
    MEMORY_WRITE = "memory_write"
    SETTINGS_CHANGE = "settings_change"


class ActionSource(StrEnum):
    TYPED = "typed"
    VOICE = "voice"
    ROUTINE = "routine"
    MEMORY_TRIGGERED = "memory_triggered"
    CLAUDE = "claude"
    CODEX = "codex"
    INTERNAL = "internal"


class TrustZone(StrEnum):
    ALLOWED_WORKSPACE = "allowed_workspace"
    USER_DOCUMENTS = "user_documents"
    SENSITIVE = "sensitive"
    FORBIDDEN = "forbidden"
    UNKNOWN = "unknown"


class DataSensitivity(StrEnum):
    SAFE = "safe"
    GENERAL = "general"
    SENSITIVE = "sensitive"


class MemoryTag(StrEnum):
    SAFE = "safe"
    GENERAL = "general"
    SENSITIVE = "sensitive"


class HandoffType(StrEnum):
    NONE = "none"
    CLAUDE_CODE = "claude_code"


@dataclass(slots=True)
class ContextSelection:
    current_window: bool = False
    project_memory: bool = False
    recent_chat: bool = True

    def enabled(self) -> list[str]:
        enabled: list[str] = []
        if self.current_window:
            enabled.append("current_window")
        if self.project_memory:
            enabled.append("project_memory")
        if self.recent_chat:
            enabled.append("recent_chat")
        return enabled

    @property
    def summary(self) -> str:
        flags = self.enabled()
        return ", ".join(flags) if flags else "minimal"


@dataclass(slots=True)
class ActionBudget:
    files_read: int = 0
    files_modified: int = 0
    runtime_seconds: int = 0
    subprocess_count: int = 0
    context_chars: int = 0
    memory_items: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "files_read": self.files_read,
            "files_modified": self.files_modified,
            "runtime_seconds": self.runtime_seconds,
            "subprocess_count": self.subprocess_count,
            "context_chars": self.context_chars,
            "memory_items": self.memory_items,
        }


@dataclass(slots=True)
class ActionRequest:
    action_type: ActionType
    source: ActionSource
    description: str
    request_id: str = field(default_factory=lambda: uuid4().hex)
    target: str = ""
    target_path: Path | None = None
    workspace: Path | None = None
    allowed_paths: tuple[Path, ...] = ()
    forbidden_paths: tuple[Path, ...] = ()
    context: ContextSelection = field(default_factory=ContextSelection)
    data_sensitivity: DataSensitivity = DataSensitivity.GENERAL
    external_network: bool = False
    external_handoff: bool = False
    destructive: bool = False
    privilege_escalation: bool = False
    write_access: bool = False
    read_access: bool = False
    unknown_executable: bool = False
    budget: ActionBudget = field(default_factory=ActionBudget)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolicyDecision:
    decision: PolicyDecisionType
    risk: RiskTier
    reasons: tuple[str, ...]
    trust_zone: TrustZone = TrustZone.UNKNOWN
    balanced_auto: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "risk": self.risk.value,
            "reasons": list(self.reasons),
            "trust_zone": self.trust_zone.value,
            "balanced_auto": self.balanced_auto,
        }


@dataclass(slots=True)
class PathAssessment:
    raw_target: str
    resolved_path: Path | None
    zone: TrustZone
    workspace_root: Path | None
    exists: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_target": self.raw_target,
            "resolved_path": str(self.resolved_path) if self.resolved_path is not None else "",
            "zone": self.zone.value,
            "workspace_root": str(self.workspace_root) if self.workspace_root is not None else "",
            "exists": self.exists,
            "reason": self.reason,
        }


@dataclass(slots=True)
class HandoffEnvelope:
    handoff_type: HandoffType
    command: list[str]
    prompt: str
    working_directory: Path
    allowed_paths: tuple[Path, ...]
    forbidden_paths: tuple[Path, ...]
    context: ContextSelection
    prompt_chars: int
    memory_items_used: int
    sensitive_items_blocked: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "handoff_type": self.handoff_type.value,
            "command": list(self.command),
            "working_directory": str(self.working_directory),
            "allowed_paths": [str(path) for path in self.allowed_paths],
            "forbidden_paths": [str(path) for path in self.forbidden_paths],
            "context": self.context.enabled(),
            "prompt_chars": self.prompt_chars,
            "memory_items_used": self.memory_items_used,
            "sensitive_items_blocked": self.sensitive_items_blocked,
        }


@dataclass(slots=True)
class AuditEntry:
    event_type: str
    source: ActionSource
    message: str
    request_id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"))
    action_type: str = ""
    decision: str = ""
    risk: str = ""
    trust_zone: str = ""
    target: str = ""
    workspace: str = ""
    external_network: bool = False
    external_handoff: bool = False
    context_flags: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "source": self.source.value,
            "message": self.message,
            "action_type": self.action_type,
            "decision": self.decision,
            "risk": self.risk,
            "trust_zone": self.trust_zone,
            "target": self.target,
            "workspace": self.workspace,
            "external_network": self.external_network,
            "external_handoff": self.external_handoff,
            "context_flags": list(self.context_flags),
            "reasons": list(self.reasons),
            "metadata": self.metadata,
        }
