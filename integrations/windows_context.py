from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
import sys


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


@dataclass(slots=True)
class WindowContext:
    title: str = ""
    process_name: str = ""
    pid: int = 0

    @property
    def summary(self) -> str:
        parts = []
        if self.process_name:
            parts.append(self.process_name)
        if self.title:
            parts.append(self.title)
        if not parts:
            return "desktop idle"
        return " - ".join(parts)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "process_name": self.process_name,
            "pid": self.pid,
            "summary": self.summary,
        }


class WindowsContextProbe:
    def __init__(self) -> None:
        self._available = sys.platform.startswith("win")
        if not self._available:
            return

        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self._user32.GetWindowTextLengthW.restype = ctypes.c_int
        self._user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self._user32.GetWindowTextW.restype = ctypes.c_int
        self._user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

    def available(self) -> bool:
        return self._available

    def snapshot(self) -> WindowContext:
        if not self._available:
            return WindowContext()

        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return WindowContext()

        title = self._window_title(hwnd)
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_name = self._process_name(pid.value)
        return WindowContext(title=title, process_name=process_name, pid=int(pid.value))

    def _window_title(self, hwnd) -> str:
        length = max(0, self._user32.GetWindowTextLengthW(hwnd))
        if length == 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value.strip()

    def _process_name(self, pid: int) -> str:
        if pid <= 0:
            return ""

        handle = self._kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""

        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            ok = self._kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
            if not ok:
                return ""
            return Path(buffer.value).stem
        finally:
            self._kernel32.CloseHandle(handle)
