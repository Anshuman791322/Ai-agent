from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import os
import platform
import re
import shutil
import subprocess  # nosec B404
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config.settings import AppSettings
from security.models import ActionBudget, HandoffEnvelope, HandoffType
from security.redaction import sanitize_for_log


@dataclass(slots=True)
class ActionResult:
    success: bool
    message: str
    output: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class SystemActions:
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
        "file explorer": ("file explorer", "windows explorer", "explorer"),
        "powershell": ("powershell", "power shell", "windows terminal"),
        "command prompt": ("command prompt", "cmd", "cmd.exe"),
        "notepad": ("notepad", "note pad"),
        "microsoft word": ("microsoft word", "ms word", "word", "winword"),
        "codex": ("codex", "code x", "kodeks", "codex app"),
        "visual studio code": ("visual studio code", "vs code", "vscode", "code"),
        "chrome": ("chrome", "google chrome"),
        "edge": ("edge", "microsoft edge"),
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
    _WORKSPACE_COMMANDS: dict[str, list[str]] = {
        "pytest": ["python", "-m", "pytest"],
        "ruff-check": ["python", "-m", "ruff", "check", "."],
        "ruff-format": ["python", "-m", "ruff", "format", "."],
    }

    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings

    def healthcheck(self) -> dict:
        claude = shutil.which("claude")
        if platform.system() != "Windows":
            return {"state": "warn", "detail": "designed for Windows; running in compatibility mode"}
        if not claude:
            return {"state": "warn", "detail": "Claude Code CLI not found in PATH"}
        return {"state": "ok", "detail": "safe action registry ready"}

    def allowlisted_app_targets(self) -> set[str]:
        return set(self._APP_ALIASES.keys())

    def is_approved_url(self, target: str) -> bool:
        host = self._extract_host(target)
        if host is None or self.settings is None:
            return False
        return host in self.settings.approved_browser_hosts

    def preview_budget(self) -> ActionBudget:
        return ActionBudget(files_read=1, runtime_seconds=5, context_chars=2400)

    def workspace_command_budget(self) -> ActionBudget:
        return ActionBudget(runtime_seconds=120, subprocess_count=1, files_modified=2)

    def claude_task_budget(self) -> ActionBudget:
        runtime = 180 if self.settings is None else self.settings.max_task_runtime_seconds
        return ActionBudget(runtime_seconds=runtime, subprocess_count=1, files_modified=6, context_chars=2000, memory_items=3)

    def advanced_shell_budget(self) -> ActionBudget:
        runtime = 180 if self.settings is None else self.settings.max_task_runtime_seconds
        return ActionBudget(runtime_seconds=runtime, subprocess_count=1, files_modified=20, context_chars=4000)

    async def open_target(self, target: str) -> ActionResult:
        return await asyncio.to_thread(self._open_target_sync, target)

    async def launch_named_app(self, target: str) -> ActionResult:
        return await asyncio.to_thread(self._launch_named_app_sync, target)

    async def open_in_browser(self, target: str, browser: str = "chrome") -> ActionResult:
        return await asyncio.to_thread(self._open_in_browser_sync, target, browser)

    async def open_explorer(self, target_path: Path) -> ActionResult:
        return await asyncio.to_thread(self._open_explorer_sync, target_path)

    async def search_files(self, root_path: Path, query: str, limit: int = 40) -> ActionResult:
        return await asyncio.to_thread(self._search_files_sync, root_path, query, limit)

    async def list_workspace_files(self, target_path: Path, limit: int = 40) -> ActionResult:
        return await asyncio.to_thread(self._list_workspace_files_sync, target_path, limit)

    async def preview_file(self, target_path: Path, max_chars: int = 2400) -> ActionResult:
        return await asyncio.to_thread(self._preview_file_sync, target_path, max_chars)

    async def write_text_file(self, target_path: Path, content: str, *, overwrite: bool = False) -> ActionResult:
        return await asyncio.to_thread(self._write_text_file_sync, target_path, content, overwrite)

    async def run_workspace_command(self, command_id: str, timeout: int | None = None) -> ActionResult:
        runtime = timeout or (self.settings.max_task_runtime_seconds if self.settings is not None else 180)
        if self.settings is not None and command_id not in self.settings.allowed_workspace_commands:
            return ActionResult(False, f"Workspace command {command_id!r} is not enabled by policy.")
        command = self._WORKSPACE_COMMANDS.get(command_id)
        if command is None:
            return ActionResult(False, f"Workspace command {command_id!r} is not allowlisted.")

        workspace = self._claude_workspace()
        if workspace is None:
            return ActionResult(False, "No approved workspace is configured.")

        executable = shutil.which(command[0])
        if executable is None:
            return ActionResult(False, f"{command[0]} was not found on this machine.")

        process = await asyncio.create_subprocess_exec(
            executable,
            *command[1:],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workspace),
            creationflags=self._no_window_flags(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=runtime)
        except asyncio.TimeoutError:
            process.kill()
            return ActionResult(False, f"Workspace command {command_id} timed out.")
        except asyncio.CancelledError:
            process.kill()
            await process.communicate()
            raise

        output = stdout.decode(errors="ignore").strip()
        error = stderr.decode(errors="ignore").strip()
        if process.returncode != 0:
            return ActionResult(False, error or f"Workspace command {command_id} failed.", output=output[:2400])
        summary = output[:2400] if output else f"Workspace command {command_id} completed successfully."
        return ActionResult(True, summary, output=summary)

    async def launch_claude_interactive(self) -> ActionResult:
        return await asyncio.to_thread(self._launch_claude_code_sync)

    async def execute_secured_claude_handoff(self, envelope: HandoffEnvelope, timeout: int = 240) -> ActionResult:
        if not self._looks_like_secured_claude_handoff(envelope):
            return ActionResult(False, "Claude Code handoff was rejected before execution.")
        return await self._run_claude_handoff_subprocess(envelope, timeout)

    async def _run_claude_handoff_subprocess(self, envelope: HandoffEnvelope, timeout: int) -> ActionResult:
        workspace = next((path for path in envelope.allowed_paths if path.exists()), None)
        before = self._git_changed_files(workspace)
        process = await asyncio.create_subprocess_exec(
            *envelope.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(envelope.working_directory),
            creationflags=self._no_window_flags(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            return ActionResult(False, "Claude Code task timed out.")
        except asyncio.CancelledError:
            process.kill()
            await process.communicate()
            raise

        output = stdout.decode(errors="ignore").strip()
        error = stderr.decode(errors="ignore").strip()
        if process.returncode != 0:
            return ActionResult(False, error or "Claude Code task failed.", output=output[:3200])

        after = self._git_changed_files(workspace)
        changed_files = sorted(after.difference(before))
        summary = self._summarize_claude_output(output)
        return ActionResult(
            True,
            summary,
            output=summary,
            details={
                "handoff_type": envelope.handoff_type.value,
                "changed_files": changed_files,
                "working_directory": str(envelope.working_directory),
                "allowed_paths": [str(path) for path in envelope.allowed_paths],
                "forbidden_paths": [str(path) for path in envelope.forbidden_paths[:10]],
                "prompt_chars": envelope.prompt_chars,
                "memory_items_used": envelope.memory_items_used,
                "sensitive_items_blocked": envelope.sensitive_items_blocked,
                "context_flags": envelope.context.enabled(),
            },
        )

    async def run_advanced_shell(self, command: str, timeout: int = 180) -> ActionResult:
        return ActionResult(False, "Advanced shell access is not available in this build.")

    def canonicalize_launch_target(self, target: str) -> str | None:
        normalized = self._normalize_target(target)
        if not normalized:
            return None

        if normalized in {"codex", "code x", "kodeks", "codex app"}:
            return "codex"

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
            return self._launch_start_menu_app_sync(target)

        if canonical == "claude code":
            return self._launch_claude_code_sync()
        if canonical == "file explorer":
            return self._open_explorer_sync(self._claude_workspace() or Path.home())
        if canonical == "powershell":
            shell = shutil.which("powershell") or shutil.which("pwsh")
            if not shell:
                return ActionResult(False, "PowerShell was not found on this machine.")
            return self._spawn_process([shell], "Opened PowerShell.")
        if canonical == "command prompt":
            return self._spawn_process(["cmd.exe"], "Opened Command Prompt.")
        if canonical == "notepad":
            return self._spawn_process(["notepad.exe"], "Opened Notepad.")
        if canonical == "microsoft word":
            word = shutil.which("winword") or shutil.which("winword.exe")
            if word:
                return self._spawn_process([word], "Opened Microsoft Word.")
            return self._launch_start_menu_app_sync("microsoft word")
        if canonical == "codex":
            return self._launch_codex_sync()
        if canonical == "visual studio code":
            code_path = shutil.which("code")
            if not code_path:
                return ActionResult(False, "Visual Studio Code was not found in PATH.")
            workspace = self._claude_workspace()
            command = [code_path]
            if workspace is not None:
                command.append(str(workspace))
            return self._spawn_process(command, "Opened Visual Studio Code.", cwd=workspace)
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
        return self._launch_start_menu_app_sync(target)

    def _open_in_browser_sync(self, target: str, browser: str = "chrome") -> ActionResult:
        resolved_url = self.resolve_site_target(target)
        if resolved_url is None:
            return ActionResult(False, f"Could not resolve browser target: {target}")

        browser_name = self.canonicalize_launch_target(browser) or browser.lower().strip()
        executable = self._browser_path(browser_name)
        if executable is None:
            return ActionResult(False, f"{browser_name.title()} was not found on this machine.")

        display_name = "Google Chrome" if browser_name == "chrome" else "Microsoft Edge"
        return self._spawn_process([executable, resolved_url], f"Opened {resolved_url} in {display_name}.")

    def _open_explorer_sync(self, target_path: Path) -> ActionResult:
        target_path = Path(target_path).expanduser()
        if not target_path.exists():
            return ActionResult(False, f"Path not found: {target_path}")
        return self._spawn_process(["explorer.exe", str(target_path)], f"Opened File Explorer at {target_path}.")

    def _search_files_sync(self, root_path: Path, query: str, limit: int) -> ActionResult:
        root_path = Path(root_path).expanduser()
        cleaned_query = " ".join(query.strip().split())
        if not cleaned_query:
            return ActionResult(False, "No file search query was provided.")
        if not root_path.exists():
            return ActionResult(False, f"Search root not found: {root_path}")
        if not root_path.is_dir():
            return ActionResult(False, f"Search root is not a directory: {root_path}")

        needle = cleaned_query.lower()
        ignored = {
            ".git",
            ".venv",
            "__pycache__",
            "node_modules",
            "AppData",
            "Windows",
            "Program Files",
            "Program Files (x86)",
        }
        matches: list[Path] = []
        scanned = 0
        stack = [root_path]
        while stack and len(matches) < limit and scanned < 25000:
            current = stack.pop()
            try:
                children = list(current.iterdir())
            except OSError:
                continue
            for child in children:
                scanned += 1
                if child.name in ignored:
                    continue
                if needle in child.name.lower():
                    matches.append(child)
                    if len(matches) >= limit:
                        break
                if child.is_dir():
                    stack.append(child)
                if scanned >= 25000:
                    break

        if not matches:
            return ActionResult(True, f"No files matched {cleaned_query!r} under {root_path}.", details={"scanned": scanned})

        lines = [f"File search results for {cleaned_query!r} under {root_path}:"]
        lines.extend(str(path) for path in matches[:limit])
        if scanned >= 25000:
            lines.append("[search stopped at safety scan limit]")
        return ActionResult(True, "\n".join(lines), details={"matches": len(matches), "scanned": scanned})

    def _list_workspace_files_sync(self, target_path: Path, limit: int) -> ActionResult:
        target_path = Path(target_path).expanduser()
        if not target_path.exists():
            return ActionResult(False, f"Path not found: {target_path}")
        if not target_path.is_dir():
            return ActionResult(False, f"{target_path} is not a directory.")

        entries = []
        for item in sorted(target_path.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower()))[:limit]:
            marker = "[DIR]" if item.is_dir() else "     "
            entries.append(f"{marker} {item.name}")
        summary = "\n".join(entries) if entries else "(empty directory)"
        return ActionResult(True, f"Files in {target_path}:\n{summary}", output=summary)

    def _preview_file_sync(self, target_path: Path, max_chars: int) -> ActionResult:
        target_path = Path(target_path).expanduser()
        if not target_path.exists():
            return ActionResult(False, f"Path not found: {target_path}")
        if not target_path.is_file():
            return ActionResult(False, f"{target_path} is not a file.")
        try:
            content = target_path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            return ActionResult(False, f"Could not read {target_path}: {exc}")

        preview = content[:max_chars]
        if len(content) > max_chars:
            preview = preview.rstrip() + "\n[preview truncated]"
        return ActionResult(True, f"Preview of {target_path.name}:\n{preview}", output=preview)

    def _write_text_file_sync(self, target_path: Path, content: str, overwrite: bool) -> ActionResult:
        target_path = Path(target_path).expanduser()
        if target_path.exists() and not overwrite:
            return ActionResult(False, f"Refusing to overwrite existing file without approval: {target_path}")
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ActionResult(False, f"Could not write {target_path}: {exc}")
        return ActionResult(
            True,
            f"Wrote {target_path}.",
            details={"path": str(target_path), "bytes": len(content.encode("utf-8"))},
        )

    def _launch_claude_code_sync(self) -> ActionResult:
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
        command = f"Set-Location -LiteralPath '{escaped_workspace}'; claude"
        return self._spawn_process(
            [shell, "-NoExit", "-Command", command],
            f"Opened Claude Code in {workspace}.",
            cwd=workspace,
        )

    def _launch_codex_sync(self) -> ActionResult:
        launched = self._launch_start_menu_app_sync("codex")
        if launched.success:
            return launched
        codex_cli = shutil.which("codex") or shutil.which("codex.exe")
        workspace = self._claude_workspace()
        if codex_cli:
            return self._spawn_process([codex_cli], "Opened Codex.", cwd=workspace)
        return ActionResult(False, "Codex was not found as a Start Menu app or PATH command.")

    def _launch_start_menu_app_sync(self, target: str) -> ActionResult:
        normalized = self._normalize_target(target)
        candidates = self._start_menu_candidates()
        best_path: Path | None = None
        best_score = 0.0
        for candidate in candidates:
            candidate_name = self._normalize_target(candidate.stem)
            if normalized == candidate_name:
                best_path = candidate
                best_score = 1.0
                break
            score = SequenceMatcher(None, normalized, candidate_name).ratio()
            if score > best_score:
                best_path = candidate
                best_score = score
        if best_path is None or best_score < 0.82:
            return ActionResult(False, f"Could not find a Windows app shortcut for {target}.")
        try:
            if hasattr(os, "startfile"):
                os.startfile(str(best_path))
            else:
                return self._spawn_process([str(best_path)], f"Opened {best_path.stem}.")
        except Exception as exc:
            return ActionResult(False, f"Failed to open {best_path}: {exc}")
        return ActionResult(True, f"Opened {best_path.stem}.")

    def _start_menu_candidates(self) -> list[Path]:
        roots = (
            Path(os.getenv("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.getenv("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.getenv("LOCALAPPDATA", "")) / "Programs",
        )
        candidates: list[Path] = []
        for root in roots:
            if not root.exists():
                continue
            try:
                candidates.extend(path for path in root.rglob("*") if path.suffix.lower() in {".lnk", ".exe", ".appref-ms"})
            except OSError:
                continue
        return candidates

    def _spawn_process(self, command: list[str], message: str, cwd: Path | None = None) -> ActionResult:
        try:
            subprocess.Popen(
                command,
                cwd=str(cwd) if cwd is not None else None,
                creationflags=self._spawn_flags(),
            )  # nosec B603
        except Exception as exc:
            safe_command = sanitize_for_log(" ".join(command), max_chars=200)
            return ActionResult(False, f"Failed to launch {safe_command}: {exc}")
        return ActionResult(True, message)

    @staticmethod
    def _spawn_flags() -> int:
        if platform.system() != "Windows":
            return 0
        return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NEW_CONSOLE", 0)

    @staticmethod
    def _no_window_flags() -> int:
        if platform.system() != "Windows":
            return 0
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)

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

    def _extract_host(self, target: str) -> str | None:
        resolved = self.resolve_site_target(target)
        if resolved is None:
            return None
        parsed = re.sub(r"^https?://", "", resolved).split("/", 1)[0].lower()
        return parsed

    @staticmethod
    def _normalize_target(target: str) -> str:
        normalized = re.sub(r"[^a-z0-9\s]+", " ", target.lower())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized.removeprefix("the ").strip()

    def _claude_workspace(self) -> Path | None:
        raw_path = None if self.settings is None else self.settings.claude_code_workspace
        candidate = Path(raw_path) if raw_path else Path.home()
        return candidate if candidate.exists() else None

    @staticmethod
    def _summarize_claude_output(output: str) -> str:
        cleaned = output.strip()
        if not cleaned:
            return "Claude Code completed the task."
        if len(cleaned) <= 3200:
            return f"Claude Code:\n{cleaned}"
        return f"Claude Code:\n{cleaned[:3200].rstrip()}\n\n[output truncated]"

    @staticmethod
    def _looks_like_secured_claude_handoff(envelope: HandoffEnvelope) -> bool:
        if envelope.handoff_type != HandoffType.CLAUDE_CODE:
            return False
        if envelope.context.recent_chat:
            return False
        if envelope.prompt_chars != len(envelope.prompt):
            return False
        if len(envelope.command) < 3:
            return False
        cli_name = Path(envelope.command[0]).name.lower()
        if cli_name not in {"claude", "claude.exe"}:
            return False
        if envelope.command[1] != "-p":
            return False
        return envelope.command[-1] == envelope.prompt

    def _git_changed_files(self, workspace: Path | None) -> set[str]:
        git_exe = shutil.which("git")
        if workspace is None or git_exe is None:
            return set()
        try:
            completed = subprocess.run(
                [git_exe, "status", "--porcelain"],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                check=False,
                creationflags=self._no_window_flags(),
            )  # nosec B603
        except Exception:
            return set()
        if completed.returncode != 0:
            return set()
        changed: set[str] = set()
        for line in completed.stdout.splitlines():
            if not line.strip():
                continue
            changed.add(line[3:].strip())
        return changed
