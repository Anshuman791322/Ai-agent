# JARVIS Windows Local

Windows-first desktop assistant built with Python and PySide6.

It keeps the native desktop UI, tray behavior, local Whisper, Gemini Flash reasoning, Claude Code integration, voice activation, and a constrained internet path, but still runs with bounded autonomy instead of free-form command execution.

## What this app does

- Native Windows desktop UI with a retro terminal look
- Qt system tray icon with hide/show, voice capture, health check, open Claude Code, pause, stop, and quit actions
- Explicit opt-in startup-on-login that launches the packaged app hidden in the tray
- Native Windows notifications for background task completion and degraded subsystem health
- LLM responses through Gemini Flash using Windows Credential Manager or a backend-only environment variable
- Local speech-to-text through faster-whisper
- Always-on voice activation on Windows using the wake phrase `Jarvis`
- Local SQLite chat and memory store
- Policy-based action execution with approval only for higher-risk work
- Safer Claude Code handoff with scoped paths, prompt sanitization, and audit logs
- Constrained web search, fetch, open-result, and summarize tools with deterministic routing before model use
- Natural app and file intents, including safer handling for Claude Code, Codex, Notepad, Word, Start Menu app lookup, and local file search
- Research/write workflow that searches the web, drafts locally, writes only verified workspace text files, and opens the result
- Lightweight local routines with starter presets and recent-run history
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

4. Configure the Gemini API key from the app UI or as a user environment variable. Do not put it in source code, frontend files, or packaged assets.

Preferred UI path:

- Open the right-side `Gemini access` panel.
- Paste the key into the hidden password field.
- Press `SAVE KEY`.
- Jarvis stores it in Windows Credential Manager for the current Windows user, then rechecks Gemini health.

Environment fallback:

```powershell
[Environment]::SetEnvironmentVariable("JARVIS_GEMINI_API_KEY", "<your-key>", "User")
```

`GEMINI_API_KEY` is also accepted as a fallback. The Python backend reads the key from Windows Credential Manager first, then `JARVIS_GEMINI_API_KEY`, then `GEMINI_API_KEY`. It is not written into UI files, settings JSON, or packaged assets.

5. Run the app:

```powershell
python app.py
```

## Runtime defaults

- Voice transcription uses `base.en`.
- Voice activation is enabled by default. Say `Jarvis` and then the command.
- Gemini uses `gemini-2.5-flash` by default through Windows Credential Manager, `JARVIS_GEMINI_API_KEY`, or the fallback `GEMINI_API_KEY`.
- Startup on login is off by default and must be enabled explicitly from the UI or `/startup on`.
- Claude Code launches in `C:\Users\anshu\Downloads\Codex`.
- Settings, logs, audit history, and SQLite state live under `%LOCALAPPDATA%\JarvisWindowsLocal`.
- Local routines are stored in `%LOCALAPPDATA%\JarvisWindowsLocal\routines.json`.
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
- Opening approved app aliases such as Explorer, Chrome, Edge, Notepad, Word, Codex, VS Code, and Claude Code
- Opening approved browser destinations
- Constrained web search, readable fetch, and page summaries through the built-in internet tools
- Opening a numbered cached search result in Chrome
- Searching file names inside the approved workspace
- Creating new `.txt`, `.md`, or `.rtf` files inside the approved workspace after direct-write safety checks
- Running curated repo-local commands such as `pytest`, `ruff-check`, and `ruff-format`
- Gemini Flash reasoning with a fixed base system prompt plus explicit untrusted reference notes when context is enabled
- Claude Code tasks inside the approved workspace when the handoff stays within policy budget, passes envelope validation, and does not include sensitive context

### What asks for approval

- Reads outside the allowlisted workspace
- Writes outside the allowlisted workspace
- High-risk file access in sensitive locations
- Unknown executable launches
- Destructive or potentially destructive operations
- File searches outside the allowlisted workspace, such as Documents, Downloads, Desktop, or the broader user profile
- Any direct text write outside the allowlisted workspace
- Actions that exceed policy budgets
- External handoff that would include sensitive local data

### What is blocked by default

- Critical-risk actions
- Forbidden-zone access
- Legacy advanced shell execution and arbitrary PowerShell command routing
- Arbitrary model endpoints. Gemini requests are restricted to the official Google Generative Language endpoint.

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

The runtime validates that envelope before launching Claude Code. If the command shape, task scope, or context budget is wrong, the handoff is blocked before any subprocess starts.

Sensitive-tagged memory is never injected into Claude automatically.

## Memory and privacy behavior

- Memory entries are tagged as `safe`, `general`, or `sensitive`
- Sensitive memory is not injected into Claude handoff automatically
- Raw wake transcripts are not logged or stored
- Conversation and memory text are redacted for likely secrets before being stored
- Memory can be listed and deleted from the built-in commands
- Desktop context and memory notes are passed to Gemini as explicit untrusted reference messages, not concatenated into the base system prompt
- Audit logs record decisions and actions without dumping full sensitive prompts unless debug logging is explicitly enabled

## UI and control behavior

The UI shows:

- current autonomy mode
- active workspace and trust zone
- whether context or memory were used for the current request
- current Claude handoff state
- pending approval count
- subsystem health, including the internet path
- routine availability, last routine status, and recent routine runs
- background assistant status, startup-on-login state, and tray behavior
- Gemini key status and a hidden key entry field backed by Windows Credential Manager
- the explicit internet command surface for search, fetch, and summarize

### Routine behavior

- Routines are local JSON definitions that replay curated action-registry steps instead of arbitrary shell text.
- Every step still goes through the same policy engine, trust-zone checks, approvals, and audit trail as a normal typed or voice command.
- The built-in starters are `Work Mode`, `Stream Mode`, and `Gaming Mode`.
- Starter routines stay lightweight by using existing safe actions such as approved apps, approved URLs, and workspace Explorer opens.
- Recent routine outcomes are kept locally and shown in the UI so you can see whether a routine completed, failed, or paused for approval.

Emergency controls:

- pause autonomy
- deny all high-risk actions
- stop the active task
- clear pending approvals
- disable voice activation temporarily

### Background assistant behavior

- Closing the window hides JARVIS to the tray when the Windows tray is available.
- Enabling startup on login writes a per-user `Run` entry that starts JARVIS with `--background`, so the app comes up hidden in the tray instead of stealing focus.
- Tray notifications surface important completions such as workspace command or Claude Code task completion, plus subsystem degradations after startup.

### Internet tools behavior

- `/search` runs a constrained DuckDuckGo HTML search and caches a small numbered result list locally.
- `/open-result <n>` opens a cached result in Chrome.
- `/fetch <url-or-n>` downloads readable page text only and keeps the response short.
- `/summarize <url-or-n>` produces a short deterministic summary from the fetched page instead of handing the task straight to the model.
- Natural commands such as `search the web for ...`, `open result 1`, `fetch page 2`, and `summarize https://...` route into the same tool path before model inference.
- Requests fail cleanly when the network is unavailable or the target is not a public HTTP(S) page.

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
- `/startup <on|off|status>`
- `/search <query>`
- `/open-result <n>`
- `/fetch <url-or-result-number>`
- `/summarize <url-or-result-number>`
- `/remember <note>`
- `/remember-sensitive <note>`
- `/memories`
- `/forget <memory-id>`
- `/routines`
- `/run-routine <name>`
- `/save-routine <name> :: <step>; <step>; ...`
- `/delete-routine <name>`
- `/open <url-or-path>`
- `/find <file-name> [in <folder>]`
- `/list [path]`
- `/preview <file>`
- `/run <pytest|ruff-check|ruff-format>`

Natural command examples:

- `open claude code` opens the Claude Code CLI workspace.
- `open claude on chrome` opens the Claude web app in Chrome.
- `open codex` or `open code x` opens the Codex app through the allowlisted app resolver or Start Menu lookup.
- `find file notes.txt` searches the approved workspace.
- `find file notes.txt on my pc` is policy-gated because it searches outside the approved workspace.
- `write an essay about AI in notepad` runs a bounded web research and local draft workflow, writes a verified text file under the workspace, then opens it.

Routine step syntax:

- `open-app:<alias>`
- `open-url:<target>`
- `open-explorer:<path-or-workspace>`
- `list[:path-or-workspace]`
- `preview:<file>`
- `run:<pytest|ruff-check|ruff-format>`
- `claude:<task>`

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

The installer is per-user by default and installs to `%LOCALAPPDATA%\Programs\JARVIS Local`, so it can update the app without requiring an elevated shell. Older machine-wide installs under `C:\Program Files\JARVIS Local` may still exist until removed manually.

### Runtime paths

The packaged app does not write logs, settings, audit logs, temp task scopes, or SQLite data into the install directory. Runtime files stay under:

- `%LOCALAPPDATA%\JarvisWindowsLocal`

If startup on login is enabled, the packaged build registers the installed executable under the current user `Run` key and starts it with `--background`, which keeps the flow compatible with the existing PyInstaller and Inno Setup output.

### Troubleshooting packaged builds

- If the tray icon is missing, confirm `assets\app_icon.ico` was bundled and the build completed from `jarvis_local.spec`.
- If startup on login does not stick, confirm the app can write the current user `Run` key and that you enabled it from the background assistant panel or `/startup on`.
- If internet tools show degraded health, check basic network access and retry `/search`; the feature fails closed when it cannot reach the network.
- If the app fails before the window opens, check `%LOCALAPPDATA%\JarvisWindowsLocal\jarvis.log`.
- If Gemini health is degraded, save the key in the `Gemini access` UI panel or confirm `JARVIS_GEMINI_API_KEY` or `GEMINI_API_KEY` is set for the current Windows user and network access to `generativelanguage.googleapis.com` is available.
- If Whisper health is degraded, reinstall the environment and rebuild so the faster-whisper native dependencies are included.
- If a packaged build reports missing DLLs, rebuild from a clean virtual environment and rerun `.\build.ps1 -Clean`.
