from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
import sys
from typing import Protocol

from config.settings import AppSettings
from security.redaction import looks_sensitive


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


@dataclass(slots=True)
class SecretState:
    available: bool
    has_key: bool
    source: str
    detail: str

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "available": self.available,
            "has_key": self.has_key,
            "source": self.source,
            "detail": self.detail,
        }


class SecretBackend(Protocol):
    def available(self) -> bool: ...

    def read(self, target_name: str) -> str: ...

    def write(self, target_name: str, value: str) -> None: ...

    def delete(self, target_name: str) -> None: ...


class _FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialBackend:
    def __init__(self) -> None:
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True) if sys.platform == "win32" else None
        if self._advapi32 is None:
            return

        self._advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
        ]
        self._advapi32.CredReadW.restype = wintypes.BOOL
        self._advapi32.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
        self._advapi32.CredWriteW.restype = wintypes.BOOL
        self._advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._advapi32.CredDeleteW.restype = wintypes.BOOL
        self._advapi32.CredFree.argtypes = [ctypes.c_void_p]
        self._advapi32.CredFree.restype = None

    def available(self) -> bool:
        return self._advapi32 is not None

    def read(self, target_name: str) -> str:
        if self._advapi32 is None:
            return ""

        credential_ptr = ctypes.POINTER(_CREDENTIALW)()
        ok = self._advapi32.CredReadW(target_name, CRED_TYPE_GENERIC, 0, ctypes.byref(credential_ptr))
        if not ok:
            return ""

        try:
            credential = credential_ptr.contents
            if not credential.CredentialBlob or credential.CredentialBlobSize <= 0:
                return ""
            raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return raw.decode("utf-8", errors="ignore").strip()
        finally:
            self._advapi32.CredFree(credential_ptr)

    def write(self, target_name: str, value: str) -> None:
        if self._advapi32 is None:
            raise RuntimeError("Windows Credential Manager is unavailable")

        blob = value.encode("utf-8")
        if len(blob) > 2048:
            raise ValueError("Gemini API key is too long")

        blob_buffer = ctypes.create_string_buffer(blob)
        credential = _CREDENTIALW()
        credential.Type = CRED_TYPE_GENERIC
        credential.TargetName = target_name
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(blob_buffer, ctypes.POINTER(ctypes.c_byte))
        credential.Persist = CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = "jarvis"

        ok = self._advapi32.CredWriteW(ctypes.byref(credential), 0)
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def delete(self, target_name: str) -> None:
        if self._advapi32 is None:
            return
        self._advapi32.CredDeleteW(target_name, CRED_TYPE_GENERIC, 0)


class GeminiKeyStore:
    def __init__(self, settings: AppSettings, backend: SecretBackend | None = None) -> None:
        self.settings = settings
        self.target_name = f"{settings.app_id}.gemini_api_key"
        self.backend = backend or WindowsCredentialBackend()

    def get_key(self) -> str:
        credential_key = self.backend.read(self.target_name).strip() if self.backend.available() else ""
        if credential_key:
            return credential_key
        for env_name in self._env_names():
            env_key = os.getenv(env_name, "").strip()
            if env_key:
                return env_key
        return ""

    def set_key(self, value: str) -> None:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Gemini API key cannot be empty")
        if len(cleaned) > 256 or any(char.isspace() for char in cleaned):
            raise ValueError("Gemini API key format is invalid")
        if not self.backend.available():
            raise RuntimeError("Windows Credential Manager is unavailable")
        self.backend.write(self.target_name, cleaned)

    def clear_key(self) -> None:
        if self.backend.available():
            self.backend.delete(self.target_name)

    def state(self) -> SecretState:
        if self.backend.available() and self.backend.read(self.target_name).strip():
            return SecretState(True, True, "Windows Credential Manager", "Gemini key is stored securely for this Windows user")
        for env_name in self._env_names():
            if os.getenv(env_name, "").strip():
                return SecretState(self.backend.available(), True, env_name, f"Gemini key is loaded from {env_name}")
        detail = "Set the key in the Gemini access panel"
        if not self.backend.available():
            detail = "Windows Credential Manager is unavailable; use an environment variable"
        return SecretState(self.backend.available(), False, "missing", detail)

    def safe_source_detail(self) -> str:
        state = self.state()
        return state.detail if not looks_sensitive(state.detail) else "Gemini key state available"

    def _env_names(self) -> tuple[str, ...]:
        if self.settings.gemini_api_key_env == "GEMINI_API_KEY":
            return ("GEMINI_API_KEY",)
        return (self.settings.gemini_api_key_env, "GEMINI_API_KEY")
