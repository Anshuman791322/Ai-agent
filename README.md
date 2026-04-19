# JARVIS Windows Local

Windows-first, local-first desktop assistant built with Python and PySide6.

It keeps the native desktop UI, tray behavior, local Ollama, local Whisper, Claude Code integration, and voice activation, but now runs with bounded autonomy instead of free-form command execution.

## What this app does

- Native Windows desktop UI with a retro terminal look
- Qt system tray icon with hide, show, pause, stop, and quit actions
- Local reasoning through Ollama
- Local speech-to-text through faster-whisper
- Always-on voice activation on Windows using the wake phrase `Jarvis`
- Local SQLite chat and memory store
- Policy-based action execution with approval only for higher-risk work
- Safer Claude Code handoff with scoped paths, prompt sanitization, and audit logs
- Packaging support with PyInstaller and an Inno Setup installer

## Quick start

1. Install Python 3.11 or newer.
2. Install runtime dependencies:

```powershell
pip install -r requirements.txt
```

3. If you are going to edit the repo, install the local tooling too:

```powershell
pip install -r requirements-dev.txt
pre-commit install
```

4. Install and start Ollama, then pull the default model:

```powershell
ollama pull qwen3.5:0.8b
```

5. Run the app:

```powershell
python app.py
```

## Runtime defaults

- Voice transcription uses `base.en`.
- Voice activation is enabled by default. Say `Jarvis` and then the command.
- Ollama uses `qwen3.5:0.8b` by default.
- Claude Code launches in `C:\Users\anshu\Downloads\Codex`.
- Settings, logs, audit history, and SQLite state live under `%LOCALAPPDATA%\JarvisWindowsLocal`.
- `requirements.txt` is the runtime dependency floor, `requirements-dev.txt` is for local tooling, and `requirements.lock` is the current pinned Windows snapshot.

## Security model

The assistant is designed for bounded autonomy, not constant confirmation.

### Autonomy modes

- `balanced` is the default. Low-risk actions run automatically. Medium-risk actions can run automatically only when they stay inside trusted project policy. High-risk actions require approval. Critical actions are blocked.
- `hands_free` allows low-risk and medium-risk actions automatically, still asks for high-risk actions, and still blocks critical actions.
- `strict` only auto-runs low-risk actions. Medium-risk and high-risk actions ask. Critical actions are blocked.

### Trust zones

- `allowed_workspace`: approved project roots. Autonomous read access is allowed here, and bounded code changes can run here.
- `user_documents`: Desktop, Documents, Downloads, and similar user paths. Reads or writes here are treated more cautiously.
- `sensitive`: SSH folders, browser profile data, token stores, app data, and similar locations. These are approval-gated or blocked.
- `forbidden`: Windows and program directories. These are blocked by default.

### What runs automatically

- Reading files inside the approved workspace
- Listing workspace files
- Opening approved app aliases such as Explorer, Chrome, PowerShell, VS Code, and Claude Code
- Opening approved browser destinations
- Running curated repo-local commands such as `pytest`, `ruff-check`, and `ruff-format`
- Local Ollama reasoning with minimal scoped context
- Claude Code tasks inside the approved workspace when the handoff stays within policy budget and does not include sensitive context

### What asks for approval

- Reads outside the allowlisted workspace
- Writes outside the allowlisted workspace
- High-risk file access in sensitive locations
- Unknown executable launches
- Arbitrary shell or PowerShell execution
- Destructive or potentially destructive operations
- Actions that exceed policy budgets
- External handoff that would include sensitive local data

### What is blocked by default

- Critical-risk actions
- Forbidden-zone access
- Advanced shell execution when `advanced_shell_enabled` is false
- Remote model endpoints unless explicitly enabled in settings

## Claude Code handoff rules

Claude Code support stays enabled, but it is no longer handed raw prompts plus unrestricted repo context.

Each handoff now builds a structured envelope with:

- the task objective
- allowed paths
- forbidden paths
- budget limits
- explicit warning that repo text, memory, logs, clipboard text, and prior model output are untrusted
- instructions not to read secrets, browser/session data, SSH keys, token stores, or unrelated files
- a required response shape with summary and changed file references

Sensitive-tagged memory is never injected into Claude automatically.

## Memory and privacy behavior

- Memory entries are tagged as `safe`, `general`, or `sensitive`
- Sensitive memory is not injected into Claude handoff automatically
- Raw wake transcripts are not logged by default
- Conversation and memory text are redacted for likely secrets before being stored
- Memory can be listed and deleted from the built-in commands
- Audit logs record decisions and actions without dumping full sensitive prompts unless debug logging is explicitly enabled

## UI and control behavior

The UI shows:

- current autonomy mode
- active workspace and trust zone
- whether context or memory were used for the current request
- current Claude handoff state
- pending approval count
- subsystem health

Emergency controls:

- pause autonomy
- deny all high-risk actions
- stop the active task
- clear pending approvals
- disable voice activation temporarily

## Built-in console commands

- `/help`
- `/health`
- `/mode <hands-free|balanced|strict>`
- `/pause`
- `/deny-high`
- `/approve`
- `/deny`
- `/clear-approvals`
- `/stop`
- `/voice`
- `/remember <note>`
- `/remember-sensitive <note>`
- `/memories`
- `/forget <memory-id>`
- `/open <url-or-path>`
- `/list [path]`
- `/preview <file>`
- `/run <pytest|ruff-check|ruff-format>`
- `/ps <command>`: approval-gated advanced shell path, disabled by default

## Local tooling and security checks

Before sending a change, run:

```powershell
pre-commit run --all-files
python -m pytest tests -q
bandit -q -c bandit.yaml -r .
pip-audit
```

The CI workflow runs:

- pre-commit
- pytest
- bandit
- pip-audit
- gitleaks

## Packaging for Windows

### Build the app

Use the included PowerShell build script:

```powershell
.\build.ps1
```

This will:

- create or reuse `.venv`
- install runtime dependencies
- install `pyinstaller`
- build the packaged app from `jarvis_local.spec`

Packaged output is created under:

- `dist\JARVIS Local\`
- executable: `dist\JARVIS Local\jarvis_local.exe`

### Build the installer

Install Inno Setup 6, then run:

```powershell
.\build.ps1 -BuildInstaller
```

Installer output is created under:

- `installer-output\`

### Runtime paths

The packaged app does not write logs, settings, audit logs, temp task scopes, or SQLite data into the install directory. Runtime files stay under:

- `%LOCALAPPDATA%\JarvisWindowsLocal`

### Troubleshooting packaged builds

- If the tray icon is missing, confirm `assets\app_icon.ico` was bundled and the build completed from `jarvis_local.spec`.
- If the app fails before the window opens, check `%LOCALAPPDATA%\JarvisWindowsLocal\jarvis.log`.
- If Ollama health is degraded, make sure Ollama is running on `127.0.0.1:11434` and the configured model is installed.
- If Whisper health is degraded, reinstall the environment and rebuild so the faster-whisper native dependencies are included.
- If a packaged build reports missing DLLs, rebuild from a clean virtual environment and rerun `.\build.ps1 -Clean`.
