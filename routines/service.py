from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from actions.registry import ActionRegistry
from security.models import ActionRequest, ActionSource, ContextSelection


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _same_name(left: str, right: str) -> bool:
    return left.strip().casefold() == right.strip().casefold()


class RoutineStorageError(RuntimeError):
    pass


class RoutineValidationError(ValueError):
    pass


class RoutineNotFoundError(LookupError):
    pass


class RoutineStepKind(StrEnum):
    OPEN_APP = "open_app"
    OPEN_URL = "open_url"
    OPEN_EXPLORER = "open_explorer"
    LIST_FILES = "list_files"
    PREVIEW_FILE = "preview_file"
    RUN_WORKSPACE_COMMAND = "run_workspace_command"
    CLAUDE_TASK = "claude_task"


_STEP_ALIASES: dict[str, RoutineStepKind] = {
    "open_app": RoutineStepKind.OPEN_APP,
    "open-app": RoutineStepKind.OPEN_APP,
    "app": RoutineStepKind.OPEN_APP,
    "open_url": RoutineStepKind.OPEN_URL,
    "open-url": RoutineStepKind.OPEN_URL,
    "url": RoutineStepKind.OPEN_URL,
    "open_explorer": RoutineStepKind.OPEN_EXPLORER,
    "open-explorer": RoutineStepKind.OPEN_EXPLORER,
    "explorer": RoutineStepKind.OPEN_EXPLORER,
    "list": RoutineStepKind.LIST_FILES,
    "list_files": RoutineStepKind.LIST_FILES,
    "list-files": RoutineStepKind.LIST_FILES,
    "preview": RoutineStepKind.PREVIEW_FILE,
    "preview_file": RoutineStepKind.PREVIEW_FILE,
    "preview-file": RoutineStepKind.PREVIEW_FILE,
    "run": RoutineStepKind.RUN_WORKSPACE_COMMAND,
    "workspace_command": RoutineStepKind.RUN_WORKSPACE_COMMAND,
    "workspace-command": RoutineStepKind.RUN_WORKSPACE_COMMAND,
    "claude": RoutineStepKind.CLAUDE_TASK,
    "claude_task": RoutineStepKind.CLAUDE_TASK,
    "claude-task": RoutineStepKind.CLAUDE_TASK,
}


@dataclass(slots=True)
class RoutineStep:
    kind: RoutineStepKind
    target: str
    label: str = ""
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "target": self.target,
            "label": self.label,
            "options": dict(self.options),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RoutineStep":
        kind_raw = str(payload.get("kind", "")).strip().lower().replace(" ", "_")
        kind = _STEP_ALIASES.get(kind_raw)
        if kind is None:
            raise RoutineValidationError(f"Unsupported routine step kind: {payload.get('kind')!r}")
        target = str(payload.get("target", "")).strip()
        if kind not in {RoutineStepKind.LIST_FILES, RoutineStepKind.OPEN_EXPLORER} and not target:
            raise RoutineValidationError(f"Routine step {kind.value!r} requires a target.")
        return cls(
            kind=kind,
            target=target,
            label=str(payload.get("label", "")).strip(),
            options=dict(payload.get("options", {}) or {}),
        )

    @classmethod
    def from_inline_spec(cls, spec: str) -> "RoutineStep":
        token = spec.strip()
        if not token:
            raise RoutineValidationError("Routine step cannot be empty.")

        name, separator, target = token.partition(":")
        normalized_name = name.strip().lower().replace(" ", "_")
        kind = _STEP_ALIASES.get(normalized_name)
        if kind is None:
            raise RoutineValidationError(
                "Unsupported routine step. Use open-app, open-url, open-explorer, list, preview, run, or claude."
            )

        cleaned_target = target.strip() if separator else ""
        if kind in {RoutineStepKind.LIST_FILES, RoutineStepKind.OPEN_EXPLORER} and not cleaned_target:
            cleaned_target = "workspace"
        if kind not in {RoutineStepKind.LIST_FILES, RoutineStepKind.OPEN_EXPLORER} and not cleaned_target:
            raise RoutineValidationError(f"Routine step {kind.value!r} requires a target after ':'.")

        return cls(kind=kind, target=cleaned_target, label=cls._default_label(kind, cleaned_target))

    @staticmethod
    def _default_label(kind: RoutineStepKind, target: str) -> str:
        if kind == RoutineStepKind.OPEN_APP:
            return f"Open {target}"
        if kind == RoutineStepKind.OPEN_URL:
            return f"Open {target}"
        if kind == RoutineStepKind.OPEN_EXPLORER:
            return f"Open Explorer at {target}"
        if kind == RoutineStepKind.LIST_FILES:
            return f"List files in {target}"
        if kind == RoutineStepKind.PREVIEW_FILE:
            return f"Preview {target}"
        if kind == RoutineStepKind.RUN_WORKSPACE_COMMAND:
            return f"Run {target}"
        return f"Claude task: {target}"


@dataclass(slots=True)
class RoutineDefinition:
    name: str
    description: str
    steps: list[RoutineStep]
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RoutineDefinition":
        name = str(payload.get("name", "")).strip()
        if not name:
            raise RoutineValidationError("Routine name cannot be empty.")
        steps_payload = payload.get("steps", [])
        if not isinstance(steps_payload, list) or not steps_payload:
            raise RoutineValidationError(f"Routine {name!r} must contain at least one step.")
        steps = [RoutineStep.from_dict(item) for item in steps_payload]
        return cls(
            name=name,
            description=str(payload.get("description", "")).strip(),
            steps=steps,
            created_at=str(payload.get("created_at", "")).strip() or _utc_now(),
            updated_at=str(payload.get("updated_at", "")).strip() or _utc_now(),
        )


@dataclass(slots=True)
class RoutineStepResult:
    index: int
    label: str
    status: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "label": self.label,
            "status": self.status,
            "message": self.message,
        }


@dataclass(slots=True)
class RoutineExecutionResult:
    name: str
    status: str
    summary: str
    step_results: list[RoutineStepResult]
    started_at: str = field(default_factory=_utc_now)
    finished_at: str = field(default_factory=_utc_now)

    def to_history_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "summary": self.summary,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "step_results": [result.to_dict() for result in self.step_results],
        }


class RoutineStore:
    def __init__(self, path: Path, max_recent_runs: int = 8) -> None:
        self.path = Path(path)
        self.max_recent_runs = max_recent_runs
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_document(self._default_document())

    def list_routines(self) -> list[RoutineDefinition]:
        document = self._read_document()
        return [RoutineDefinition.from_dict(item) for item in document.get("routines", [])]

    def get_routine(self, name: str) -> RoutineDefinition:
        for routine in self.list_routines():
            if _same_name(routine.name, name):
                return routine
        raise RoutineNotFoundError(f"Routine {name!r} was not found.")

    def save_routine(self, routine: RoutineDefinition) -> RoutineDefinition:
        document = self._read_document()
        routines = [RoutineDefinition.from_dict(item) for item in document.get("routines", [])]
        updated = False
        for index, existing in enumerate(routines):
            if _same_name(existing.name, routine.name):
                routine.created_at = existing.created_at
                routine.updated_at = _utc_now()
                routines[index] = routine
                updated = True
                break
        if not updated:
            routine.created_at = _utc_now()
            routine.updated_at = routine.created_at
            routines.append(routine)
        document["routines"] = [item.to_dict() for item in routines]
        self._write_document(document)
        return routine

    def delete_routine(self, name: str) -> bool:
        document = self._read_document()
        routines = [RoutineDefinition.from_dict(item) for item in document.get("routines", [])]
        kept = [routine for routine in routines if not _same_name(routine.name, name)]
        if len(kept) == len(routines):
            return False
        document["routines"] = [item.to_dict() for item in kept]
        self._write_document(document)
        return True

    def recent_runs(self, limit: int = 5) -> list[dict[str, Any]]:
        document = self._read_document()
        runs = list(document.get("recent_runs", []))
        return runs[:limit]

    def record_run(self, result: RoutineExecutionResult) -> None:
        document = self._read_document()
        runs = list(document.get("recent_runs", []))
        runs.insert(0, result.to_history_dict())
        document["recent_runs"] = runs[: self.max_recent_runs]
        self._write_document(document)

    def _read_document(self) -> dict[str, Any]:
        if not self.path.exists():
            document = self._default_document()
            self._write_document(document)
            return document
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = self._default_document()
            self._write_document(payload)
            return payload
        if not isinstance(payload, dict):
            payload = self._default_document()
            self._write_document(payload)
            return payload
        payload.setdefault("version", 1)
        payload.setdefault("routines", [])
        payload.setdefault("recent_runs", [])
        if not payload["routines"]:
            payload["routines"] = [routine.to_dict() for routine in self._starter_routines()]
            self._write_document(payload)
        return payload

    def _write_document(self, document: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temporary.write_text(json.dumps(document, indent=2), encoding="utf-8")
            temporary.replace(self.path)
        except OSError as exc:
            raise RoutineStorageError(f"Unable to write routines at {self.path}: {exc}") from exc

    def _default_document(self) -> dict[str, Any]:
        return {
            "version": 1,
            "routines": [routine.to_dict() for routine in self._starter_routines()],
            "recent_runs": [],
        }

    @staticmethod
    def _starter_routines() -> list[RoutineDefinition]:
        return [
            RoutineDefinition(
                name="Work Mode",
                description="Open the main coding stack for local development work.",
                steps=[
                    RoutineStep(RoutineStepKind.OPEN_APP, "visual studio code", "Open Visual Studio Code"),
                    RoutineStep(RoutineStepKind.OPEN_APP, "claude code", "Open Claude Code"),
                    RoutineStep(RoutineStepKind.OPEN_URL, "chatgpt", "Open ChatGPT", {"browser": "edge"}),
                ],
            ),
            RoutineDefinition(
                name="Stream Mode",
                description="Bring up a browser and the current workspace for content prep.",
                steps=[
                    RoutineStep(RoutineStepKind.OPEN_APP, "edge", "Open Microsoft Edge"),
                    RoutineStep(RoutineStepKind.OPEN_URL, "youtube", "Open YouTube", {"browser": "edge"}),
                    RoutineStep(RoutineStepKind.OPEN_EXPLORER, "workspace", "Open the active workspace"),
                ],
            ),
            RoutineDefinition(
                name="Gaming Mode",
                description="Open a browser, the workspace, and PowerShell for quick gaming support tasks.",
                steps=[
                    RoutineStep(RoutineStepKind.OPEN_APP, "powershell", "Open PowerShell"),
                    RoutineStep(RoutineStepKind.OPEN_APP, "edge", "Open Microsoft Edge"),
                    RoutineStep(RoutineStepKind.OPEN_EXPLORER, "workspace", "Open the active workspace"),
                ],
            ),
        ]


class RoutineService:
    def __init__(self, store: RoutineStore, registry: ActionRegistry) -> None:
        self.store = store
        self.registry = registry

    def list_routines(self) -> list[RoutineDefinition]:
        return self.store.list_routines()

    def get_routine(self, name: str) -> RoutineDefinition:
        return self.store.get_routine(name)

    def save_routine(self, name: str, steps: list[RoutineStep], description: str = "") -> RoutineDefinition:
        cleaned_name = " ".join(name.strip().split())
        if not cleaned_name:
            raise RoutineValidationError("Routine name cannot be empty.")
        if not steps:
            raise RoutineValidationError("A routine needs at least one step.")
        routine = RoutineDefinition(
            name=cleaned_name,
            description=" ".join(description.strip().split()),
            steps=steps,
        )
        return self.store.save_routine(routine)

    def save_from_inline_command(self, raw: str) -> RoutineDefinition:
        name, separator, definition = raw.partition("::")
        if not separator:
            raise RoutineValidationError("Usage: /save-routine <name> :: <step>; <step>; ...")
        step_specs = [item.strip() for item in definition.split(";") if item.strip()]
        if not step_specs:
            raise RoutineValidationError("Provide at least one step after '::'.")
        steps = [RoutineStep.from_inline_spec(item) for item in step_specs]
        return self.save_routine(name, steps)

    def delete_routine(self, name: str) -> bool:
        return self.store.delete_routine(name)

    def recent_runs(self, limit: int = 5) -> list[dict[str, Any]]:
        return self.store.recent_runs(limit)

    def build_request(self, step: RoutineStep, source: ActionSource = ActionSource.ROUTINE) -> ActionRequest:
        if step.kind == RoutineStepKind.OPEN_APP:
            return self.registry.open_app_request(step.target, source)
        if step.kind == RoutineStepKind.OPEN_URL:
            browser = str(step.options.get("browser", "chrome"))
            return self.registry.open_url_request(step.target, browser, source)
        if step.kind == RoutineStepKind.OPEN_EXPLORER:
            return self.registry.open_explorer_request(self._resolve_path_target(step.target), source)
        if step.kind == RoutineStepKind.LIST_FILES:
            return self.registry.list_files_request(self._resolve_path_target(step.target), source)
        if step.kind == RoutineStepKind.PREVIEW_FILE:
            return self.registry.preview_file_request(self._resolve_path_target(step.target), source)
        if step.kind == RoutineStepKind.RUN_WORKSPACE_COMMAND:
            return self.registry.workspace_command_request(step.target, source)
        if step.kind == RoutineStepKind.CLAUDE_TASK:
            return self.registry.claude_task_request(step.target, source, ContextSelection())
        raise RoutineValidationError(f"Unsupported routine step kind: {step.kind.value}")

    def record_execution(self, result: RoutineExecutionResult) -> None:
        self.store.record_run(result)

    def snapshot(self, *, active_routine: str = "", status: str = "") -> dict[str, Any]:
        routines = self.list_routines()
        return {
            "available": [
                {
                    "name": routine.name,
                    "description": routine.description,
                    "step_count": len(routine.steps),
                    "updated_at": routine.updated_at,
                }
                for routine in routines
            ],
            "recent_runs": self.store.recent_runs(),
            "active_routine": active_routine,
            "status": status or f"{len(routines)} local routines ready",
        }

    def _resolve_path_target(self, target: str) -> Path:
        default_workspace = self.registry.jail.default_workspace()
        token = target.strip()
        if token in {"", ".", "workspace"}:
            if default_workspace is None:
                raise RoutineValidationError("No allowlisted workspace is configured for this routine step.")
            return default_workspace
        return self.registry.jail.resolve_path(token, base=default_workspace)
