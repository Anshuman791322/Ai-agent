# JARVIS Windows Local

Windows-first, local-first AI desktop assistant boilerplate built with Python and PySide6.

## What this starter includes

- Native desktop UI with a retro terminal look
- Qt system tray icon with hide, show, and quit actions
- Local LLM integration through Ollama
- Local speech-to-text through faster-whisper
- Always-on local voice activation on Windows using a wake phrase
- Local SQLite conversation and memory store
- Safe Windows action helpers for opening files, URLs, and read-oriented PowerShell commands
- Packaging support with PyInstaller and an Inno Setup installer

## Quick start

1. Install Python 3.11 or newer.
2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Install and start Ollama, then pull the default local model:

```powershell
ollama pull qwen3.5:0.8b
```

4. Run the app:

```powershell
python app.py
```

## Notes

- Voice transcription uses `base.en` by default for better command recognition on Windows hardware that can handle it.
- Voice activation is enabled by default. Say `Jarvis` followed by a request, or use the `VOICE` button for one-shot recording.
- Ollama uses `qwen3.5:0.8b` by default and disables thinking mode in API calls for faster desktop responses.
- When you ask JARVIS to open Claude Code, it launches in `C:\Users\anshu\Downloads\Codex`.
- Settings and local data live under `%LOCALAPPDATA%\\JarvisWindowsLocal`.
- The full architecture review and migration plan are in `ARCHITECTURE_REVIEW.md`.
- The app now supports single-instance startup behavior and packaging-safe resource lookup.

## Built-in console commands

- `/help`
- `/open <url-or-path>`
- `/ps <safe read-oriented PowerShell command>`
- `/remember <note>`
- `/health`

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

The packaged app does not write logs, settings, or the SQLite database into the install directory. Runtime files stay under:

- `%LOCALAPPDATA%\JarvisWindowsLocal`

### Troubleshooting packaged builds

- If the tray icon is missing, confirm `assets\app_icon.ico` was bundled and the build completed from `jarvis_local.spec`.
- If the app fails before the window opens, check `%LOCALAPPDATA%\JarvisWindowsLocal\jarvis.log`.
- If Ollama health is degraded, make sure Ollama is running on `127.0.0.1:11434` and the configured model is installed.
- If Whisper health is degraded, reinstall the environment and rebuild so the faster-whisper native dependencies are included.
- If a packaged build reports missing DLLs, rebuild from a clean virtual environment and rerun `.\build.ps1 -Clean`.
