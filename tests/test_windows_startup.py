from __future__ import annotations

import sys

from integrations.windows_startup import WindowsStartupRegistration


class _FakeRegistryKey:
    def __init__(self, storage: dict[str, str]) -> None:
        self.storage = storage

    def __enter__(self) -> "_FakeRegistryKey":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeWinreg:
    HKEY_CURRENT_USER = object()
    REG_SZ = 1

    def __init__(self) -> None:
        self.storage: dict[str, str] = {}

    def CreateKey(self, root, path):
        return _FakeRegistryKey(self.storage)

    def OpenKey(self, root, path):
        return _FakeRegistryKey(self.storage)

    def SetValueEx(self, key, name, reserved, reg_type, value):
        del reserved, reg_type
        key.storage[name] = value

    def DeleteValue(self, key, name):
        if name not in key.storage:
            raise FileNotFoundError(name)
        del key.storage[name]

    def QueryValueEx(self, key, name):
        if name not in key.storage:
            raise FileNotFoundError(name)
        return key.storage[name], self.REG_SZ


def test_windows_startup_registration_writes_hidden_launch_command(monkeypatch, tmp_path):
    fake_winreg = _FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    monkeypatch.setattr(sys, "platform", "win32", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    manager = WindowsStartupRegistration("JARVIS Local", tmp_path / "app.py")

    enabled_state = manager.sync_enabled(True)
    assert enabled_state.supported is True
    assert enabled_state.enabled is True
    assert "--background" in enabled_state.command
    assert "startup on login is enabled" in enabled_state.detail

    disabled_state = manager.sync_enabled(False)
    assert disabled_state.enabled is False
    assert disabled_state.detail == "startup on login is off"
