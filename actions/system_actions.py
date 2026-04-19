from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import os
import platform
import re
import shutil
import subprocess
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from config.settings import AppSettings


@dataclass(slots=True)
class ActionResult:
    success: bool
    message: str
    output: str = ""


class SystemActions:
    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings

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
    _APP_ALIASES: dict[str, tuple[str, ...]] = {
        "claude code": (
            "claude code",
            "claude",
            "cloud code",
            "claude dode",
            "claude ode",
            "claude odes",
            "claude noodles",
            "cloud noodles",
            "clawed code",
        ),
        "file explorer": (
            "file explorer",
            "windows explorer",
            "explorer",
        ),
        "powershell": (
            "powershell",
            "power shell",
            "terminal",
            "windows terminal",
        ),
        "command prompt": (
            "command prompt",
            "cmd",
            "cmd.exe",
        ),
        "visual studio code": (
            "visual studio code",
            "vs code",
            "vscode",
            "code",
        ),
        "chrome": (
            "chrome",
            "google chrome",
        ),
        "edge": (
            "edge",
            "microsoft edge",
        ),
    }
    _SITE_ALIASES: dict[str, str] = {
        "chatgpt": "https://chatgpt.com/",
        "chat gpt": "https://chatgpt.com/",
        "claude": "https://claude.ai/",
        "claude ai": "https://claude.ai/",
        "github": "https://github.com/",
        "gmail": "https://mail.google.com/",
        "google": "https://www.google.com/",
        "youtube": "https://www.youtube.com/",
        "whatsapp": "https://web.whatsapp.com/",
        "instagram": "https://www.instagram.com/",
        "x": "https://x.com/",
        "twitter": "https://x.com/",
    }

    def healthcheck(self) -> dict:
        shell = shutil.which("powershell") or shutil.which("pwsh")
        if platform.system() != "Windows":
            return {"state": "warn", "detail": "designed for Windows; running in compatibility mode"}
        if not shell:
            return {"state": "warn", "detail": "PowerShell not found"}
        return {"state": "ok", "detail": f"PowerShell ready at {shell}"}

    async def open_target(self, target: str) -> ActionResult:
        return await asyncio.to_thread(self._open_target_sync, target)

    async def launch_named_app(self, target: str) -> ActionResult:
        return await asyncio.to_thread(self._launch_named_app_sync, target)

    async def open_in_browser(self, target: str, browser: str = "chrome") -> ActionResult:
        return await asyncio.to_thread(self._open_in_browser_sync, target, browser)

    async def run_claude_code_task(self, prompt: str, timeout: int = 240) -> ActionResult:
        prompt = prompt.strip()
        if not prompt:
            return ActionResult(False, "No Claude Code task was provided.")

        claude = shutil.which("claude")
        workspace = self._claude_workspace()
        if not claude:
            return ActionResult(False, "Claude Code was not found in PATH.")
        if workspace is None:
            return ActionResult(False, "Claude Code workspace path was not found.")

        process = await asyncio.create_subprocess_exec(
            claude,
            "-p",
            self._claude_task_prompt(prompt),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workspace),
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            return ActionResult(False, "Claude Code task timed out.")

        output = stdout.decode(errors="ignore").strip()
        error = stderr.decode(errors="ignore").strip()
        if process.returncode != 0:
            return ActionResult(False, error or "Claude Code task failed.", output=output[:2000])

        summary = self._summarize_claude_output(output)
        return ActionResult(True, summary, output=summary)

    def canonicalize_launch_target(self, target: str) -> str | None:
        normalized = self._normalize_target(target)
        if not normalized:
            return None

        claude_match = re.match(r"^claude(?:\s+(?P<suffix>[a-z0-9]+))?$", normalized)
        if claude_match:
            suffix = claude_match.group("suffix")
            if not suffix:
                return "claude code"
            if SequenceMatcher(None, suffix, "code").ratio() >= 0.34:
                return "claude code"

        if normalized in {"cloud code", "cloud noodles"}:
            return "claude code"

        best_match = None
        best_score = 0.0
        for canonical, aliases in self._APP_ALIASES.items():
            for alias in aliases:
                if normalized == alias:
                    return canonical
                score = SequenceMatcher(None, normalized, alias).ratio()
                if score > best_score:
                    best_match = canonical
                    best_score = score

        if best_match is not None and best_score >= 0.74:
            return best_match
        return None

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

    def _launch_named_app_sync(self, target: str) -> ActionResult:
        canonical = self.canonicalize_launch_target(target)
        if canonical is None:
            return ActionResult(False, f"Unknown Windows app target: {target}")

        if canonical == "claude code":
            return self._launch_claude_code()
        if canonical == "file explorer":
            return self._spawn_process(["explorer.exe"], "Opened File Explorer.")
        if canonical == "powershell":
            shell = shutil.which("powershell") or shutil.which("pwsh")
            if not shell:
                return ActionResult(False, "PowerShell was not found on this machine.")
            return self._spawn_process([shell], "Opened PowerShell.")
        if canonical == "command prompt":
            return self._spawn_process(["cmd.exe"], "Opened Command Prompt.")
        if canonical == "visual studio code":
            code_path = shutil.which("code")
            if not code_path:
                return ActionResult(False, "Visual Studio Code was not found in PATH.")
            return self._spawn_process([code_path], "Opened Visual Studio Code.")
        if canonical == "chrome":
            chrome_path = self._find_chrome_path()
            if chrome_path is None:
                return ActionResult(False, "Chrome was not found on this machine.")
            return self._spawn_process([chrome_path], "Opened Chrome.")
        if canonical == "edge":
            edge_path = self._find_edge_path()
            if edge_path is None:
                return ActionResult(False, "Microsoft Edge was not found on this machine.")
            return self._spawn_process([edge_path], "Opened Microsoft Edge.")
        return ActionResult(False, f"No launcher is defined for {canonical}.")

    def _open_in_browser_sync(self, target: str, browser: str = "chrome") -> ActionResult:
        resolved_url = self.resolve_site_target(target)
        if resolved_url is None:
            return ActionResult(False, f"Could not resolve browser target: {target}")

        browser_name = self.canonicalize_launch_target(browser) or browser.lower().strip()
        executable = self._browser_path(browser_name)
        if executable is None:
            return ActionResult(False, f"{browser_name.title()} was not found on this machine.")

        display_name = browser_name.title()
        if browser_name == "chrome":
            display_name = "Google Chrome"
        elif browser_name == "edge":
            display_name = "Microsoft Edge"

        return self._spawn_process([executable, resolved_url], f"Opened {resolved_url} in {display_name}.")

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

    def _launch_claude_code(self) -> ActionResult:
        shell = shutil.which("powershell") or shutil.which("pwsh")
        claude = shutil.which("claude")
        if not shell:
            return ActionResult(False, "PowerShell is required to launch Claude Code.")
        if not claude:
            return ActionResult(False, "Claude Code was not found in PATH.")
        workspace = self._claude_workspace()
        if workspace is None:
            return ActionResult(False, "Claude Code workspace path was not found.")
        escaped_workspace = str(workspace).replace("'", "''")
        command = (
            f"Set-Location -LiteralPath '{escaped_workspace}'; "
            "claude"
        )
        return self._spawn_process(
            [shell, "-NoExit", "-Command", command],
            f"Opened Claude Code in {workspace}.",
            cwd=workspace,
        )

    def _spawn_process(self, command: list[str], message: str, cwd: Path | None = None) -> ActionResult:
        creationflags = 0
        if platform.system() == "Windows":
            creationflags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            )

        try:
            subprocess.Popen(
                command,
                cwd=str(cwd) if cwd is not None else None,
                creationflags=creationflags,
            )
        except Exception as exc:
            return ActionResult(False, f"Failed to launch {' '.join(command)}: {exc}")
        return ActionResult(True, message)

    def _find_chrome_path(self) -> str | None:
        chrome = shutil.which("chrome") or shutil.which("chrome.exe")
        if chrome:
            return chrome

        candidates = (
            Path(os.getenv("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.getenv("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
            Path(os.getenv("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        )
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return None

    def _find_edge_path(self) -> str | None:
        edge = shutil.which("msedge") or shutil.which("msedge.exe")
        if edge:
            return edge

        candidates = (
            Path(os.getenv("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.getenv("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
            Path(os.getenv("LOCALAPPDATA", "")) / "Microsoft/Edge/Application/msedge.exe",
        )
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return None

    def _browser_path(self, browser: str) -> str | None:
        if browser == "chrome":
            return self._find_chrome_path()
        if browser == "edge":
            return self._find_edge_path()
        return None

    def resolve_site_target(self, target: str) -> str | None:
        cleaned = target.strip().strip('"').strip("'")
        if not cleaned:
            return None

        normalized = self._normalize_target(cleaned)
        if normalized in self._SITE_ALIASES:
            return self._SITE_ALIASES[normalized]

        if cleaned.startswith(("http://", "https://")):
            return cleaned
        if "." in cleaned and " " not in cleaned:
            return f"https://{cleaned}"
        return None

    def _normalize_target(self, target: str) -> str:
        normalized = re.sub(r"[^a-z0-9\s]+", " ", target.lower())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized.removeprefix("the ").strip()

    def _claude_workspace(self) -> Path | None:
        raw_path = None if self.settings is None else self.settings.claude_code_workspace
        candidate = Path(raw_path) if raw_path else Path.home()
        return candidate if candidate.exists() else None

    @staticmethod
    def _claude_task_prompt(user_task: str) -> str:
        return " ".join(user_task.split()).strip()

    @staticmethod
    def _summarize_claude_output(output: str) -> str:
        cleaned = output.strip()
        if not cleaned:
            return "Claude Code completed the task."
        if len(cleaned) <= 3200:
            return f"Claude Code:\n{cleaned}"
        return f"Claude Code:\n{cleaned[:3200].rstrip()}\n\n[output truncated]"
