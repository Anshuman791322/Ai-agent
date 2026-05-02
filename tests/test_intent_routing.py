from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from actions.registry import ActionRegistry
from actions.system_actions import ActionResult, SystemActions
from core.app_state import AppState
from core.event_bus import EventBus
from core.orchestrator import Orchestrator
from memory.store import MemoryStore
from providers.llm.base import ChatMessage
from security.approvals import ApprovalManager
from security.audit import AuditLogger
from security.context_manager import ContextManager
from security.handoff import HandoffManager
from security.models import ActionSource, ActionType, PolicyDecisionType
from security.policy import PolicyEngine
from security.workspace import WorkspaceJail


class _DummyLlm:
    provider_name = "Dummy LLM"
    requires_network = False

    async def close(self) -> None:
        return None

    async def healthcheck(self):
        return type("Health", (), {"state": "ok", "detail": "llm ready"})()

    async def chat(self, messages: list[ChatMessage], system_prompt: str):
        del messages, system_prompt
        return type("ChatResult", (), {"text": "AI essay draft", "model": "dummy"})()


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


class _FakeWebTools:
    def healthcheck(self) -> dict[str, str]:
        return {"state": "ok", "detail": "fake web ready"}

    async def search(self, query: str, *, limit: int = 5):
        del limit
        return type(
            "WebToolResult",
            (),
            {
                "success": True,
                "message": f'Search results for "{query}":\n1. AI overview (example.com)',
                "state": "ok",
                "detail": "fake search ready",
                "payload": {},
            },
        )()

    async def summarize(self, target: str):
        return type(
            "WebToolResult",
            (),
            {
                "success": True,
                "message": f"Summary {target}: AI is a field of computer science.",
                "state": "ok",
                "detail": "fake summary ready",
                "payload": {},
            },
        )()


def _build_orchestrator(security_workspace_factory):
    settings, workspace, documents, sensitive, forbidden = security_workspace_factory()
    memory = MemoryStore(settings.app_dir / "memory.sqlite")
    jail = WorkspaceJail(settings)
    actions = SystemActions(settings)
    context_manager = ContextManager(settings, memory)
    registry = ActionRegistry(settings, actions, jail, HandoffManager(settings, jail, context_manager))
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
        web_tools=_FakeWebTools(),
        startup_manager=_FakeStartupManager(),
    )
    return orchestrator, registry, workspace, documents, sensitive, forbidden


def test_voice_open_claude_routes_to_claude_code_app(security_workspace_factory, monkeypatch):
    orchestrator, _, _, _, _, _ = _build_orchestrator(security_workspace_factory)
    captured = {}

    async def fake_execute(request):
        captured["request"] = request
        return request.description

    monkeypatch.setattr(orchestrator, "_execute_policy_request", fake_execute)

    normalized = orchestrator._normalize_user_text("can you open Claude?")
    response = asyncio.run(orchestrator._handle_natural_command(normalized, ActionSource.VOICE))

    assert response == "Open claude code."
    assert captured["request"].action_type == ActionType.OPEN_APP
    assert captured["request"].target == "claude code"


def test_open_codex_does_not_route_to_visual_studio_code(security_workspace_factory, monkeypatch):
    orchestrator, _, _, _, _, _ = _build_orchestrator(security_workspace_factory)
    captured = {}

    async def fake_execute(request):
        captured["request"] = request
        return request.description

    monkeypatch.setattr(orchestrator, "_execute_policy_request", fake_execute)

    normalized = orchestrator._normalize_user_text("Open Code X.")
    response = asyncio.run(orchestrator._handle_natural_command(normalized, ActionSource.VOICE))

    assert response == "Open codex."
    assert captured["request"].action_type == ActionType.OPEN_APP
    assert captured["request"].target == "codex"


def test_browser_specific_claude_still_routes_to_web(security_workspace_factory, monkeypatch):
    orchestrator, _, _, _, _, _ = _build_orchestrator(security_workspace_factory)
    captured = {}

    async def fake_execute(request):
        captured["request"] = request
        return request.description

    monkeypatch.setattr(orchestrator, "_execute_policy_request", fake_execute)

    response = asyncio.run(orchestrator._handle_natural_command("open claude on google chrome", ActionSource.TYPED))

    assert response == "Open https://claude.ai/ in chrome."
    assert captured["request"].action_type == ActionType.OPEN_URL
    assert captured["request"].target == "https://claude.ai/"


def test_file_search_routes_through_policy_action(security_workspace_factory):
    orchestrator, _, workspace, _, _, _ = _build_orchestrator(security_workspace_factory)
    (workspace / "notes_ai.txt").write_text("hello", encoding="utf-8")

    response = asyncio.run(orchestrator._handle_natural_command("find file notes_ai.txt", ActionSource.TYPED))

    assert "File search results for 'notes_ai.txt'" in response
    assert "notes_ai.txt" in response


def test_safe_write_policy_allows_workspace_and_gates_documents(security_workspace_factory):
    orchestrator, registry, workspace, documents, _, _ = _build_orchestrator(security_workspace_factory)
    safe_request = registry.write_text_file_request(workspace / "jarvis_outputs" / "essay.txt", "safe essay", ActionSource.TYPED)
    unsafe_request = registry.write_text_file_request(documents / "essay.txt", "safe essay", ActionSource.TYPED)

    safe_decision = orchestrator.policy.evaluate(safe_request)
    unsafe_decision = orchestrator.policy.evaluate(unsafe_request)

    assert safe_decision.decision == PolicyDecisionType.ALLOW
    assert unsafe_decision.decision == PolicyDecisionType.REQUIRE_APPROVAL


def test_research_write_creates_verified_workspace_file(security_workspace_factory, monkeypatch):
    orchestrator, _, workspace, _, _, _ = _build_orchestrator(security_workspace_factory)

    async def fake_execute(self, request, desktop_context):
        del self, desktop_context
        if request.action_type == ActionType.WRITE_TEXT_FILE:
            assert request.metadata["safety_verified"] is True
            target = Path(request.target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(request.metadata["content"]), encoding="utf-8")
            return ActionResult(True, f"Wrote {request.target}.")
        if request.action_type == ActionType.OPEN_PATH:
            return ActionResult(True, f"Opened {request.target}.")
        return ActionResult(False, "unexpected action")

    monkeypatch.setattr(ActionRegistry, "execute", fake_execute)

    response = asyncio.run(orchestrator._handle_natural_command("write an essay about AI in notepad", ActionSource.TYPED))

    assert "Wrote" in response
    assert "Opened" in response
    assert "Draft preview" in response
    assert (workspace / "jarvis_outputs" / "ai_essay.txt").parent.exists()
