from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

import pytest

from actions.registry import ActionRegistry
from actions.system_actions import ActionResult, SystemActions
from core.app_state import AppState
from core.event_bus import EventBus
from core.orchestrator import Orchestrator
from memory.store import MemoryStore
from routines import RoutineService, RoutineStore
from security.approvals import ApprovalManager
from security.audit import AuditLogger
from security.context_manager import ContextManager
from security.handoff import HandoffManager
from security.models import ActionSource
from security.policy import PolicyEngine
from security.workspace import WorkspaceJail


class _DummyLlm:
    async def close(self) -> None:
        return None

    async def healthcheck(self):
        return type("Health", (), {"state": "ok", "detail": "llm ready"})()


class _DummyVoice:
    async def healthcheck(self) -> dict[str, str]:
        return {"state": "ok", "detail": "voice ready"}


@dataclass
class _FakeStartupState:
    supported: bool = True
    enabled: bool = False
    detail: str = "startup on login is off"
    command: str = ""


class _FakeStartupManager:
    def __init__(self) -> None:
        self.state = _FakeStartupState()

    def refresh(self) -> _FakeStartupState:
        return self.state

    def sync_enabled(self, enabled: bool) -> _FakeStartupState:
        self.state.enabled = enabled
        return self.state


def _build_runtime(security_workspace_factory):
    settings, workspace, documents, sensitive, forbidden = security_workspace_factory()
    memory = MemoryStore(settings.app_dir / "memory.sqlite")
    jail = WorkspaceJail(settings)
    actions = SystemActions(settings)
    context_manager = ContextManager(settings, memory)
    registry = ActionRegistry(settings, actions, jail, HandoffManager(settings, jail, context_manager))
    routine_service = RoutineService(RoutineStore(settings.routines_file), registry)
    orchestrator = Orchestrator(
        settings=settings,
        state=AppState(),
        bus=EventBus(),
        memory=memory,
        llm=_DummyLlm(),
        voice=_DummyVoice(),
        actions=actions,
        registry=registry,
        policy=PolicyEngine(settings, jail),
        approvals=ApprovalManager(),
        audit=AuditLogger(settings.app_dir),
        context_manager=context_manager,
        jail=jail,
        context_probe=None,
        web_tools=None,
        startup_manager=_FakeStartupManager(),
        routine_service=routine_service,
    )
    return settings, workspace, documents, sensitive, forbidden, orchestrator, routine_service, registry


def test_routine_store_seeds_starters_and_persists_custom_routine(security_workspace_factory):
    settings, _, _, _, _, _, _, registry = _build_runtime(security_workspace_factory)
    service = RoutineService(RoutineStore(settings.routines_file), registry)

    names = [routine.name for routine in service.list_routines()]
    assert names[:3] == ["Work Mode", "Stream Mode", "Gaming Mode"]

    saved = service.save_from_inline_command("Docs Mode :: open-app:edge ; open-explorer:workspace")
    assert saved.name == "Docs Mode"

    reloaded = RoutineService(RoutineStore(settings.routines_file), registry)
    reloaded_names = [routine.name for routine in reloaded.list_routines()]
    assert "Docs Mode" in reloaded_names


def test_run_routine_records_success_and_uses_registry(security_workspace_factory, monkeypatch):
    _, _, _, _, _, orchestrator, routine_service, registry = _build_runtime(security_workspace_factory)
    calls: list[tuple[str, str]] = []

    async def fake_execute(self, request, desktop_context):
        del self
        del desktop_context
        calls.append((request.action_type.value, request.target))
        return ActionResult(True, f"Executed {request.target}")

    monkeypatch.setattr(ActionRegistry, "execute", fake_execute)

    response = asyncio.run(orchestrator._handle_local_command("/run-routine Work Mode", ActionSource.TYPED))

    assert "Routine Work Mode completed" in response
    assert len(calls) == 3
    assert [item[0] for item in calls] == ["open_app", "open_app", "open_url"]
    recent = routine_service.recent_runs(1)[0]
    assert recent["name"] == "Work Mode"
    assert recent["status"] == "success"


def test_run_routine_stops_after_failure(security_workspace_factory, monkeypatch):
    _, _, _, _, _, orchestrator, routine_service, registry = _build_runtime(security_workspace_factory)
    routine_service.save_from_inline_command("Break Mode :: open-app:edge ; open-app:claude code")
    call_count = {"value": 0}

    async def fake_execute(self, request, desktop_context):
        del self, desktop_context, request
        call_count["value"] += 1
        if call_count["value"] == 1:
            return ActionResult(False, "Open failed")
        return ActionResult(True, "should not execute")

    monkeypatch.setattr(ActionRegistry, "execute", fake_execute)

    response = asyncio.run(orchestrator._handle_local_command("/run-routine Break Mode", ActionSource.TYPED))

    assert "Routine Break Mode failed at step 1." in response
    assert call_count["value"] == 1
    recent = routine_service.recent_runs(1)[0]
    assert recent["status"] == "failed"


def test_run_routine_respects_policy_for_sensitive_preview(security_workspace_factory):
    _, _, _, sensitive, _, orchestrator, routine_service, _ = _build_runtime(security_workspace_factory)
    secret_file = sensitive / "secret.txt"
    secret_file.write_text("do not auto-open", encoding="utf-8")
    routine_service.save_from_inline_command(f"Sensitive Read :: preview:{secret_file}")

    response = asyncio.run(orchestrator._handle_local_command("/run-routine Sensitive Read", ActionSource.TYPED))

    assert "Routine Sensitive Read needs approval at step 1." in response
    assert orchestrator.approvals.snapshot()["count"] == 1
    recent = routine_service.recent_runs(1)[0]
    assert recent["status"] == "approval_required"


def test_main_window_updates_routines_panel(security_workspace_factory):
    qt_widgets = pytest.importorskip("PySide6.QtWidgets")
    QApplication = qt_widgets.QApplication
    from ui.main_window import MainWindow

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    settings, _, _, _, _ = security_workspace_factory()
    window = MainWindow(settings)

    window.update_routines(
        {
            "available": [
                {"name": "Work Mode", "description": "work stack", "step_count": 3},
                {"name": "Stream Mode", "description": "stream stack", "step_count": 3},
            ],
            "recent_runs": [
                {"name": "Work Mode", "status": "success", "finished_at": "2026-04-25T11:40:00Z"},
            ],
            "active_routine": "Work Mode",
            "status": "running Work Mode",
        }
    )

    assert "Loaded 2 routines" in window.routines_summary_label.text()
    assert "Active routine: Work Mode" in window.routines_status_label.text()
    assert "Work Mode [SUCCESS]" in window.routines_recent_label.text()

    window.close()
    if app is not None:
        app.processEvents()
