from __future__ import annotations

import asyncio
import logging
import os
import threading

from config.settings import AppSettings


log = logging.getLogger(__name__)


class WhisperSTT:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._model = None
        self._lock = threading.Lock()
        self._dependency_error: Exception | None = None

        try:
            import numpy as np  # noqa: F401
            import sounddevice as sd  # noqa: F401
            from faster_whisper import WhisperModel  # noqa: F401
        except Exception as exc:
            self._dependency_error = exc

    async def healthcheck(self) -> dict:
        if self._dependency_error:
            return {
                "state": "error",
                "detail": f"faster-whisper stack unavailable: {self._dependency_error}",
            }

        if self._model is None:
            return {
                "state": "ok",
                "detail": f"ready; lazy load {self.settings.whisper_model_size}",
            }

        return {
            "state": "ok",
            "detail": f"loaded {self.settings.whisper_model_size}",
        }

    async def transcribe_once(self, seconds: int | None = None) -> str:
        if self._dependency_error:
            raise RuntimeError(f"Voice stack unavailable: {self._dependency_error}")

        duration = seconds or self.settings.voice_record_seconds
        audio = await asyncio.to_thread(self._record_audio, duration)
        return await asyncio.to_thread(self.transcribe_audio, audio, "manual")

    async def warm_start(self) -> str:
        if self._dependency_error:
            raise RuntimeError(f"Voice stack unavailable: {self._dependency_error}")
        await asyncio.to_thread(self._ensure_model)
        return f"loaded {self.settings.whisper_model_size}"

    def transcribe_audio(self, audio, domain: str = "general") -> str:
        if self._dependency_error:
            raise RuntimeError(f"Voice stack unavailable: {self._dependency_error}")
        return self._transcribe_audio(audio, domain)

    def _ensure_model(self):
        if self._model is not None:
            return self._model

        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                download_root = self.settings.app_dir / "models" / "faster-whisper"
                download_root.mkdir(parents=True, exist_ok=True)
                cpu_threads = max(1, min(4, os.cpu_count() or 1))

                try:
                    self._model = WhisperModel(
                        self.settings.whisper_model_size,
                        device=self.settings.whisper_device,
                        compute_type=self.settings.whisper_compute_type,
                        cpu_threads=cpu_threads,
                        num_workers=1,
                        download_root=str(download_root),
                        local_files_only=True,
                    )
                    log.info(
                        "Loaded cached faster-whisper model: %s from %s",
                        self.settings.whisper_model_size,
                        download_root,
                    )
                except Exception:
                    log.info(
                        "Cached faster-whisper model %s was not available locally. Downloading to %s.",
                        self.settings.whisper_model_size,
                        download_root,
                    )
                    self._model = WhisperModel(
                        self.settings.whisper_model_size,
                        device=self.settings.whisper_device,
                        compute_type=self.settings.whisper_compute_type,
                        cpu_threads=cpu_threads,
                        num_workers=1,
                        download_root=str(download_root),
                        local_files_only=False,
                    )
                    log.info(
                        "Loaded faster-whisper model: %s into %s",
                        self.settings.whisper_model_size,
                        download_root,
                    )
        return self._model

    def _record_audio(self, duration: int):
        import numpy as np
        import sounddevice as sd

        frames = int(duration * self.settings.voice_sample_rate)
        recording = sd.rec(
            frames,
            samplerate=self.settings.voice_sample_rate,
            channels=1,
            dtype="float32",
        )
        sd.wait()
        return np.squeeze(recording)

    def _transcribe_audio(self, audio, domain: str = "general") -> str:
        model = self._ensure_model()
        hotwords = ", ".join(self.settings.whisper_hotwords).strip() or None
        initial_prompt = self.settings.whisper_initial_prompt if domain in {"command", "manual"} else None
        if domain == "command":
            beam_size = self.settings.whisper_command_beam_size
            best_of = self.settings.whisper_command_best_of
        else:
            beam_size = self.settings.whisper_beam_size
            best_of = self.settings.whisper_best_of
        vad_filter = domain != "command"
        segments, _ = model.transcribe(
            audio,
            language="en",
            beam_size=beam_size,
            best_of=best_of,
            condition_on_previous_text=False,
            initial_prompt=initial_prompt,
            hotwords=hotwords,
            vad_filter=vad_filter,
            temperature=0.0,
            without_timestamps=True,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
