from __future__ import annotations

import asyncio
import logging
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
        return await asyncio.to_thread(self._transcribe_audio, audio)

    def _ensure_model(self):
        if self._model is not None:
            return self._model

        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(
                    self.settings.whisper_model_size,
                    device=self.settings.whisper_device,
                    compute_type=self.settings.whisper_compute_type,
                )
                log.info("Loaded faster-whisper model: %s", self.settings.whisper_model_size)
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

    def _transcribe_audio(self, audio) -> str:
        model = self._ensure_model()
        segments, _ = model.transcribe(
            audio,
            language="en",
            beam_size=1,
            vad_filter=True,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()
