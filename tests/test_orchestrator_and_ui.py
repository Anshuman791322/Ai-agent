from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

import httpx
import pytest

pytest.importorskip("PySide6")

from actions.registry import ActionRegistry
from actions.system_actions import SystemActions
from config.settings import AppSettings
from core.app_state import AppState
from core.event_bus import EventBus
from core.orchestrator import Orchestrator
from integrations.windows_context import WindowContext
from integrations.web_tools import ConstrainedWebTools
from memory.store import MemoryStore
from security.approvals import ApprovalManager
from security.audit import AuditLogger
from security.context_manager import ContextManager
from security.handoff import HandoffManager
from security.models import MemoryTag
from security.models import ActionSource
from security.policy import PolicyEngine
from security.workspace import WorkspaceJail


class _DummyLlm:
    def __init__(self) -> None:
        self.last_messages = []
        self.last_system_prompt = ""

    async def close(self) -> None:
        return None

    async def healthcheck(self):
        return type("Health", (), {"state": "ok", "detail": "llm ready"})()

    async def chat(self, messages, system_prompt):
        self.last_messages = list(messages)
        self.last_system_prompt = system_prompt
        return type("ChatResult", (), {"text": "ok", "model": "dummy"})()


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
        self.state.detail = (
            "startup on login is enabled; JARVIS will launch hidden in the tray"
            if enabled
            else "startup on login is off"
        )
        return self.state


def _build_web_tools() -> ConstrainedWebTools:
    search_html = """
    <html><body>
      <a class="result__a" href="https://docs.python.org/3/library/asyncio.html">asyncio docs</a>
      <div class="result__snippet">Python asyncio reference.</div>
    </body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "html.duckduckgo.com":
            return httpx.Response(200, text=search_html, headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(
            200,
            text="<html><head><title>asyncio</title></head><body><p>asyncio uses async and await.</p></body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )

    return ConstrainedWebTools(transport=httpx.MockTransport(handler))


def test_orchestrator_routes_search_and_startup_commands(security_workspace_factory):
    settings, workspace, _, _, _ = security_workspace_factory()
    memory = MemoryStore(settings.app_dir / "memory.sqlite")
    jail = WorkspaceJail(settings)
    actions = SystemActions(settings)
    context_manager = ContextManager(settings, memory)
    llm = _DummyLlm()
    orchestrator = Orchestrator(
        settings=settings,
        state=AppState(),
        bus=EventBus(),
        memory=memory,
        llm=llm,
        voice=_DummyVoice(),
        actions=actions,
        registry=ActionRegistry(settings, actions, jail, HandoffManager(settings, jail, context_manager)),
        policy=PolicyEngine(settings, jail),
        approvals=ApprovalManager(),
        audit=AuditLogger(settings.app_dir),
        context_manager=context_manager,
        jail=jail,
        context_probe=None,
        web_tools=_build_web_tools(),
        startup_manager=_FakeStartupManager(),
    )

    search_response = asyncio.run(orchestrator._handle_local_command("/search python asyncio", ActionSource.TYPED))
    assert 'Search results for "python asyncio"' in search_response
    assert orchestrator.state.snapshot_statuses()["internet"]["state"] == "ok"

    natural_response = asyncio.run(orchestrator._handle_natural_command("search the web for asyncio", ActionSource.TYPED))
    assert natural_response is not None
    assert 'Search results for "asyncio"' in natural_response

    startup_response = asyncio.run(orchestrator._handle_local_command("/startup on", ActionSource.TYPED))
    assert startup_response == "Startup on login enabled. JARVIS will launch hidden in the tray."
    assert settings.start_on_login is True
    assert asyncio.run(orchestrator._startup_status_message()).startswith("Startup on login is on.")
    assert workspace.exists()


def test_orchestrator_keeps_base_system_prompt_and_avoids_raw_wake_transcript_logging(security_workspace_factory, monkeypatch):
    settings, _, _, _, _ = security_workspace_factory()
    memory = MemoryStore(settings.app_dir / "memory.sqlite")
    memory.remember("use current window and memory for alpha", MemoryTag.GENERAL)
    memory.append_message("user", "use current window and memory for alpha", source="typed")
    jail = WorkspaceJail(settings)
    actions = SystemActions(settings)
    context_manager = ContextManager(settings, memory)
    llm = _DummyLlm()
    state = AppState()
    orchestrator = Orchestrator(
        settings=settings,
        state=state,
        bus=EventBus(),
        memory=memory,
        llm=llm,
        voice=_DummyVoice(),
        actions=actions,
        registry=ActionRegistry(settings, actions, jail, HandoffManager(settings, jail, context_manager)),
        policy=PolicyEngine(settings, jail),
        approvals=ApprovalManager(),
        audit=AuditLogger(settings.app_dir),
        context_manager=context_manager,
        jail=jail,
        context_probe=None,
        web_tools=_build_web_tools(),
        startup_manager=_FakeStartupManager(),
    )
    orchestrator._desktop_context = WindowContext(title="token=sk-abcdef1234567890", process_name="browser")

    response = asyncio.run(orchestrator._generate_llm_response("use current window and memory for alpha", ActionSource.TYPED))

    assert response == "ok"
    assert llm.last_system_prompt == settings.system_prompt
    assert "Current window" not in llm.last_system_prompt
    assert llm.last_messages[0].role == "user"
    assert "Reference context only." in llm.last_messages[0].content
    assert "Current window (redacted):" in llm.last_messages[0].content
    assert "Project memory (untrusted):" in llm.last_messages[0].content

    orchestrator._running = True

    def _consume(coro, loop):
        coro.close()
        return type("Future", (), {"result": staticmethod(lambda timeout=None: None)})()

    monkeypatch.setattr("core.orchestrator.asyncio.run_coroutine_threadsafe", _consume)
    orchestrator.submit_voice_transcript("search the web for alpha", raw_transcript="Jarvis search for my token")

    assert all("Wake phrase transcript:" not in entry["text"] for entry in state.recent_logs())


def test_main_window_updates_internet_and_background_panels(security_workspace_factory):
    qt_widgets = pytest.importorskip("PySide6.QtWidgets")
    QApplication = qt_widgets.QApplication
    from ui.main_window import MainWindow

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    settings, workspace, _, _, _ = security_workspace_factory()
    window = MainWindow(settings)

    window.update_statuses(
        {
            "llm": {"state": "ok", "detail": "llm ready"},
            "voice": {"state": "ok", "detail": "voice ready"},
            "memory": {"state": "ok", "detail": "memory ready"},
            "actions": {"state": "ok", "detail": "actions ready"},
            "internet": {"state": "warn", "detail": "internet offline: request timed out"},
        }
    )
    window.update_policy_state(
        {
            "mode": "balanced",
            "autonomy_paused": False,
            "deny_high_risk": False,
            "trust_zone": "allowed_workspace",
            "active_workspace": str(workspace),
            "context_usage": "recent_chat",
            "handoff_state": "idle",
            "active_task": "idle",
            "memory_items_used": 1,
            "sensitive_items_blocked": 0,
            "tray_available": True,
            "start_on_login_enabled": True,
            "start_on_login_detail": "startup on login is enabled; JARVIS will launch hidden in the tray",
        }
    )

    assert window.internet_detail_label.text() == "internet offline: request timed out"
    assert "internet offline" in window.runtime_label.text()
    assert "Startup on login: on" in window.background_startup_label.text()
    assert window.startup_toggle_button.text() == "DISABLE STARTUP"
    assert "capture voice" in window.background_detail_label.text().lower()

    window.close()
    if app is not None:
        app.processEvents()
