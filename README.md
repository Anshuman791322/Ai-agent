# JARVIS Windows Local

Windows-first, local-first AI desktop assistant boilerplate built with Python and PySide6.

## What this starter includes

- Native desktop UI with a retro terminal look
- Qt system tray icon with hide, show, and quit actions
- Local LLM integration through Ollama
- Local speech-to-text through faster-whisper
- Local SQLite conversation and memory store
- Safe Windows action helpers for opening files, URLs, and read-oriented PowerShell commands

## Quick start

1. Install Python 3.11 or newer.
2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Install and start Ollama, then pull a compact local model:

```powershell
ollama pull qwen2.5:3b
```

4. Run the app:

```powershell
python app.py
```

## Notes

- Voice transcription uses `tiny.en` by default for lower RAM and CPU load.
- Ollama is the default model runtime. If it is offline, the app stays up and shows degraded status instead of crashing.
- Settings and local data live under `%LOCALAPPDATA%\\JarvisWindowsLocal`.
- The full architecture review and migration plan are in `ARCHITECTURE_REVIEW.md`.

## Built-in console commands

- `/help`
- `/open <url-or-path>`
- `/ps <safe read-oriented PowerShell command>`
- `/remember <note>`
- `/health`
