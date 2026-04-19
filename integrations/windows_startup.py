from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class StartupRegistrationState:
    supported: bool
    enabled: bool
    detail: str
    command: str = ""


class WindowsStartupRegistration:
    _RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def __init__(self, app_name: str, entry_script: Path) -> None:
        self.app_name = app_name
        self.entry_script = entry_script.resolve(strict=False)
        self._state = StartupRegistrationState(
            supported=sys.platform.startswith("win"),
            enabled=False,
            detail="startup registration unavailable",
            command="",
        )

    def sync_enabled(self, enabled: bool) -> StartupRegistrationState:
        if not sys.platform.startswith("win"):
            self._state = StartupRegistrationState(False, False, "startup registration is only supported on Windows")
            return self._state
        try:
            import winreg
        except ImportError:
            self._state = StartupRegistrationState(False, False, "winreg is unavailable in this Python runtime")
            return self._state

        command = self.desired_command()
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self._RUN_KEY) as key:
                if enabled:
                    winreg.SetValueEx(key, self.app_name, 0, winreg.REG_SZ, command)
                else:
                    try:
                        winreg.DeleteValue(key, self.app_name)
                    except FileNotFoundError:
                        pass
        except OSError as exc:
            self._state = StartupRegistrationState(True, False, f"could not update startup registration: {exc}", command)
            return self._state

        return self.refresh()

    def refresh(self) -> StartupRegistrationState:
        if not sys.platform.startswith("win"):
            self._state = StartupRegistrationState(False, False, "startup registration is only supported on Windows")
            return self._state
        try:
            import winreg
        except ImportError:
            self._state = StartupRegistrationState(False, False, "winreg is unavailable in this Python runtime")
            return self._state

        command = self.desired_command()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, self.app_name)
        except FileNotFoundError:
            value = ""
        except OSError as exc:
            self._state = StartupRegistrationState(True, False, f"could not read startup registration: {exc}", command)
            return self._state

        enabled = bool(value)
        if not enabled:
            detail = "startup on login is off"
        elif value == command:
            detail = "startup on login is enabled; JARVIS will launch hidden in the tray"
        else:
            detail = "startup on login is enabled with a custom command"
        self._state = StartupRegistrationState(True, enabled, detail, value or command)
        return self._state

    def desired_command(self) -> str:
        if getattr(sys, "frozen", False):
            executable = Path(sys.executable).resolve(strict=False)
            return self._quote_windows_command([str(executable), "--background"])

        executable = Path(sys.executable).resolve(strict=False)
        pythonw = executable.with_name("pythonw.exe")
        interpreter = pythonw if pythonw.exists() else executable
        return self._quote_windows_command([str(interpreter), str(self.entry_script), "--background"])

    @property
    def state(self) -> StartupRegistrationState:
        return self._state

    @staticmethod
    def _quote_windows_command(parts: list[str]) -> str:
        quoted: list[str] = []
        for part in parts:
            if " " in part or "\t" in part:
                quoted.append(f'"{part}"')
            else:
                quoted.append(part)
        return " ".join(quoted)
