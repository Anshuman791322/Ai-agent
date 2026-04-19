from __future__ import annotations

import json

from actions.registry import ActionRegistry
from actions.system_actions import SystemActions
from config.settings import AppSettings
from security.models import ActionSource, ActionType, AutonomyMode
from security.workspace import WorkspaceJail


def test_app_settings_load_sanitizes_untrusted_config(tmp_path):
    settings = AppSettings()
    config_file = settings.config_file
    config_file.parent.mkdir(parents=True, exist_ok=True)

    workspace = tmp_path / "workspace"
    documents = tmp_path / "documents"
    sensitive = tmp_path / "sensitive"
    forbidden = tmp_path / "forbidden"
    for path in (workspace, documents, sensitive, forbidden):
        path.mkdir(parents=True, exist_ok=True)

    config_file.write_text(
        json.dumps(
            {
                "autonomy_mode": "reckless",
                "allow_remote_model_endpoint": False,
                "ollama_base_url": "https://example.com",
                "ollama_model": "bad model!",
                "voice_activation_engine": "openwakeword",
                "claude_code_workspace": str(workspace),
                "allowed_workspace_roots": [str(workspace), str(tmp_path / "missing"), str(workspace)],
                "user_documents_roots": [str(documents)],
                "sensitive_roots": [str(sensitive)],
                "forbidden_roots": [str(forbidden)],
                "allowed_workspace_commands": ["pytest", "format", "ruff-format"],
                "max_files_read_per_task": 9999,
                "max_subprocess_count": 99,
            }
        ),
        encoding="utf-8",
    )

    loaded = AppSettings.load()

    assert loaded.autonomy_mode == AutonomyMode.BALANCED
    assert loaded.ollama_base_url == "http://127.0.0.1:11434"
    assert loaded.ollama_model == "qwen3.5:0.8b"
    assert loaded.voice_activation_engine == "transcript"
    assert loaded.allowed_workspace_roots[0] == str(workspace.resolve())
    assert loaded.allowed_workspace_commands == ["pytest", "ruff-format"]
    assert loaded.max_files_read_per_task == 200
    assert loaded.max_subprocess_count == 12
    assert loaded.validation_warnings
    assert any("autonomy_mode" in warning for warning in loaded.validation_warnings)
    assert any("remote model endpoints are disabled" in warning for warning in loaded.validation_warnings)


def test_action_registry_canonicalizes_launch_targets_and_url_metadata(security_workspace_factory):
    settings, workspace, _, _, _ = security_workspace_factory()
    jail = WorkspaceJail(settings)
    actions = SystemActions(settings)
    registry = ActionRegistry(settings, actions, jail, handoff_manager=object())

    app_request = registry.open_app_request("clawed code", ActionSource.VOICE)
    assert app_request.action_type == ActionType.OPEN_APP
    assert app_request.target == "claude code"
    assert app_request.unknown_executable is False

    url_request = registry.open_url_request("chatgpt", "chrome", ActionSource.TYPED)
    assert url_request.action_type == ActionType.OPEN_URL
    assert url_request.target == "https://chatgpt.com/"
    assert url_request.external_network is True
    assert url_request.metadata["browser"] == "chrome"
    assert url_request.metadata["approved_network"] is True

    shell_request = registry.advanced_shell_request("Get-ChildItem", ActionSource.INTERNAL)
    assert shell_request.action_type == ActionType.ADVANCED_SHELL
    assert shell_request.workspace == workspace
    assert shell_request.external_network is True
    assert shell_request.write_access is True
    assert shell_request.budget.subprocess_count == 1
