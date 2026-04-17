from __future__ import annotations

import asyncio
import os
import platform
import re
import shutil
import webbrowser
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ActionResult:
    success: bool
    message: str
    output: str = ""


class SystemActions:
    _DANGEROUS_PATTERNS = [
        r"\bremove-item\b",
        r"\bdel\b",
        r"\berase\b",
        r"\brmdir\b",
        r"\bformat\b",
        r"\bshutdown\b",
        r"\brestart-computer\b",
        r"\bstop-computer\b",
        r"\bclear-disk\b",
        r"\bset-executionpolicy\b",
        r"\breg\s+delete\b",
    ]

    def healthcheck(self) -> dict:
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if platform.system() != "Windows":
            return {"state": "warn", "detail": "designed for Windows; running in compatibility mode"}
        if not shell:
            return {"state": "warn", "detail": "PowerShell not found"}
        return {"state": "ok", "detail": f"PowerShell ready at {shell}"}

    async def open_target(self, target: str) -> ActionResult:
        return await asyncio.to_thread(self._open_target_sync, target)

    def _open_target_sync(self, target: str) -> ActionResult:
        target = target.strip().strip('"')
        if not target:
            return ActionResult(False, "No target provided.")

        if target.startswith(("http://", "https://")):
            webbrowser.open(target)
            return ActionResult(True, f"Opened {target}.")

        path = Path(target).expanduser()
        if not path.exists():
            return ActionResult(False, f"Path not found: {path}")

        if hasattr(os, "startfile"):
            os.startfile(str(path))
        else:
            webbrowser.open(path.as_uri())
        return ActionResult(True, f"Opened {path}.")

    async def run_powershell_safe(self, command: str, timeout: int = 15) -> ActionResult:
        command = command.strip()
        if not command:
            return ActionResult(False, "No PowerShell command provided.")

        if self._looks_dangerous(command):
            return ActionResult(False, "Blocked potentially destructive PowerShell command.")

        shell = shutil.which("powershell") or shutil.which("pwsh")
        if not shell:
            return ActionResult(False, "PowerShell was not found on this machine.")

        process = await asyncio.create_subprocess_exec(
            shell,
            "-NoProfile",
            "-Command",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            return ActionResult(False, "PowerShell command timed out.")

        output = stdout.decode(errors="ignore").strip()
        error = stderr.decode(errors="ignore").strip()

        if process.returncode != 0:
            return ActionResult(False, error or "PowerShell command failed.", output=output)

        return ActionResult(True, "PowerShell command completed.", output=output[:1200])

    def _looks_dangerous(self, command: str) -> bool:
        lowered = command.lower()
        return any(re.search(pattern, lowered) for pattern in self._DANGEROUS_PATTERNS)
