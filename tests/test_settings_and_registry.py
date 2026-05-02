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
                "gemini_api_base_url": "https://example.com",
                "gemini_api_key_env": "bad env",
                "gemini_model": "bad model!",
                "ollama_model": "legacy",
                "advanced_shell_enabled": True,
                "voice_activation_engine": "openwakeword",
                "log_raw_wake_transcripts": True,
                "start_on_login": "yes",
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
    assert loaded.llm_provider == "gemini"
    assert loaded.gemini_api_base_url == "https://generativelanguage.googleapis.com/v1beta"
    assert loaded.gemini_api_key_env == "JARVIS_GEMINI_API_KEY"
    assert loaded.gemini_model == "gemini-2.5-flash"
    assert loaded.voice_activation_engine == "transcript"
    assert loaded.start_on_login is True
    assert loaded.allowed_workspace_roots[0] == str(workspace.resolve())
    assert loaded.allowed_workspace_commands == ["pytest", "ruff-format"]
    assert loaded.max_files_read_per_task == 200
    assert loaded.max_subprocess_count == 12
    assert loaded.validation_warnings
    assert any("autonomy_mode" in warning for warning in loaded.validation_warnings)
    assert any("advanced_shell_enabled" in warning for warning in loaded.validation_warnings)
    assert any("log_raw_wake_transcripts" in warning for warning in loaded.validation_warnings)
    assert any("official Google Generative Language endpoint" in warning for warning in loaded.validation_warnings)
    assert any("legacy Ollama settings" in warning for warning in loaded.validation_warnings)

    persisted = json.loads(config_file.read_text(encoding="utf-8"))
    assert "advanced_shell_enabled" not in persisted
    assert "log_raw_wake_transcripts" not in persisted


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

    search_result_request = registry.open_url_request("https://docs.python.org/3/", "chrome", ActionSource.TYPED, approved_network=True)
    assert search_result_request.metadata["approved_network"] is True
