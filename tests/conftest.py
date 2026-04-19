from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def isolated_windows_env(monkeypatch, tmp_path):
    env_roots = {
        "USERPROFILE": tmp_path / "home",
        "LOCALAPPDATA": tmp_path / "localappdata",
        "APPDATA": tmp_path / "appdata",
        "WINDIR": tmp_path / "windows",
        "PROGRAMFILES": tmp_path / "program files",
        "PROGRAMFILES(X86)": tmp_path / "program files (x86)",
    }
    for path in env_roots.values():
        path.mkdir(parents=True, exist_ok=True)
    for name, path in env_roots.items():
        monkeypatch.setenv(name, str(path))

    for name in (
        "JARVIS_OLLAMA_BASE_URL",
        "JARVIS_OLLAMA_MODEL",
        "JARVIS_WHISPER_MODEL",
        "JARVIS_VOICE_WAKE_PHRASE",
        "JARVIS_AUTONOMY_MODE",
        "JARVIS_ADVANCED_SHELL",
        "JARVIS_REMOTE_MODEL_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)

    yield


@pytest.fixture
def security_workspace_factory(tmp_path):
    from config.settings import AppSettings
    from security.models import AutonomyMode

    def build(*, autonomy_mode: AutonomyMode = AutonomyMode.BALANCED):
        workspace = tmp_path / "workspace"
        documents = tmp_path / "documents"
        sensitive = tmp_path / "sensitive"
        forbidden = tmp_path / "forbidden"
        app_dir = tmp_path / "app"
        for path in (workspace, documents, sensitive, forbidden, app_dir):
            path.mkdir(parents=True, exist_ok=True)

        settings = AppSettings()
        settings.app_dir = app_dir
        settings.claude_code_workspace = str(workspace)
        settings.allowed_workspace_roots = [str(workspace)]
        settings.user_documents_roots = [str(documents)]
        settings.sensitive_roots = [str(sensitive)]
        settings.forbidden_roots = [str(forbidden)]
        settings.autonomy_mode = autonomy_mode
        settings.ensure_directories()
        return settings, workspace, documents, sensitive, forbidden

    return build
