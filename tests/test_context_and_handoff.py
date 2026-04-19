from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from memory.store import MemoryStore
from security.context_manager import ContextBundle, ContextManager
from security.handoff import HandoffManager
from security.models import ActionRequest, ActionSource, ActionType, ContextSelection, DataSensitivity, MemoryTag
from security.workspace import WorkspaceJail


def test_context_manager_filters_memory_and_recent_chat(security_workspace_factory):
    settings, _, _, _, _ = security_workspace_factory()
    memory = MemoryStore(settings.app_dir / "memory.sqlite")
    memory.remember("safe alpha note", MemoryTag.SAFE)
    memory.remember("general alpha note", MemoryTag.GENERAL)
    memory.remember("sensitive alpha note", MemoryTag.SENSITIVE)
    memory.append_message("user", "api_key = sk-1234567890abcdef123456", source="typed")
    memory.append_message("assistant", "password=opensesame", source="assistant")

    manager = ContextManager(settings, memory)
    selection = ContextSelection(current_window=True, project_memory=True, recent_chat=True)
    bundle = manager.build_context_bundle(
        "alpha",
        selection,
        SimpleNamespace(summary="token=sk-1234567890abcdef123456"),
        for_handoff=False,
    )

    assert bundle.selection == selection
    assert bundle.memory_items_used == 2
    assert bundle.sensitive_items_blocked == 1
    assert len(bundle.notes) == 3
    assert all("sk-" not in note for note in bundle.notes)
    assert any(note.startswith("Current window (redacted):") for note in bundle.notes)
    assert any(note.startswith("Project memory (untrusted):") for note in bundle.notes)

    recent = manager.recent_chat_messages(limit=10)
    assert len(recent) == 2
    assert all("sk-" not in row["content"] for row in recent)
    assert all("password=" not in row["content"] for row in recent)
    assert all("[REDACTED" in row["content"] for row in recent)


def test_handoff_envelope_sanitizes_prompt_and_disables_recent_chat_for_handoff(security_workspace_factory, monkeypatch):
    settings, workspace, _, _, _ = security_workspace_factory()
    jail = WorkspaceJail(settings)

    context_manager = Mock()

    def build_context_bundle(*args, **kwargs):
        selection = ContextSelection(
            current_window=True,
            project_memory=True,
            recent_chat=not kwargs.get("for_handoff", False),
        )
        return ContextBundle(
            notes=[
                "Current window (redacted): [REDACTED_SECRET_ASSIGNMENT]",
                "Project memory (untrusted): [REDACTED_SECRET_ASSIGNMENT]",
            ],
            selection=selection,
            memory_items_used=2,
            sensitive_items_blocked=1,
        )

    context_manager.build_context_bundle.side_effect = build_context_bundle

    monkeypatch.setattr(
        "security.handoff.shutil.which",
        lambda name: r"C:\Tools\claude.exe" if name == "claude" else None,
    )

    manager = HandoffManager(settings, jail, context_manager)
    desktop_context = SimpleNamespace(summary="clipboard contains token=sk-1234567890abcdef123456")
    request = ActionRequest(
        action_type=ActionType.CLAUDE_TASK,
        source=ActionSource.CLAUDE,
        description="Run Claude task",
        target="audit token=sk-1234567890abcdef123456\x00 password=opensesame",
        workspace=workspace,
        allowed_paths=(workspace,),
        read_access=True,
        write_access=True,
        external_network=True,
        external_handoff=True,
        data_sensitivity=DataSensitivity.GENERAL,
        context=ContextSelection(current_window=True, project_memory=True, recent_chat=True),
    )

    envelope = manager.build_claude_envelope(request, request.target, request.context, desktop_context)

    assert envelope.command[0] == r"C:\Tools\claude.exe"
    assert envelope.allowed_paths == (workspace,)
    assert envelope.context.recent_chat is False
    assert envelope.memory_items_used == 2
    assert envelope.sensitive_items_blocked == 1
    assert envelope.prompt_chars == len(envelope.prompt)
    assert "\x00" not in envelope.prompt
    assert "sk-1234567890abcdef123456" not in envelope.prompt
    assert "password=opensesame" not in envelope.prompt
    assert "[REDACTED_SECRET_ASSIGNMENT]" in envelope.prompt
    assert context_manager.build_context_bundle.call_count == 1
    assert context_manager.build_context_bundle.call_args.kwargs["for_handoff"] is True
