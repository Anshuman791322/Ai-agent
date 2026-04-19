from __future__ import annotations

from collections import deque
import logging
import queue
import re
import threading
from pathlib import Path
import shutil
import time
from typing import Callable

from config.settings import AppSettings
from resources import resource_path
from voice.stt_whisper import WhisperSTT


log = logging.getLogger(__name__)


class WakePhraseListener:
    def __init__(
        self,
        settings: AppSettings,
        voice: WhisperSTT,
        on_command: Callable[[str, str], None],
        on_status: Callable[[str, str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.voice = voice
        self.on_command = on_command
        self.on_status = on_status

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream = None
        self._transcribing = threading.Event()
        self._status_lock = threading.Lock()
        self._status_state = "unknown"
        self._status_detail = "inactive"

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._set_status("busy", "starting always-listening voice activation")
        self._thread = threading.Thread(target=self._run, daemon=True, name="jarvis-wake-listener")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

        stream = self._stream
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
            self._stream = None

        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

        self._set_status("warn", "voice activation offline")

    def snapshot(self) -> tuple[str, str]:
        with self._status_lock:
            return self._status_state, self._status_detail

    def _run(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
        except Exception as exc:
            self._set_status("error", f"voice activation unavailable: {exc}")
            return

        if self.settings.voice_activation_engine.lower() == "openwakeword":
            try:
                self._run_openwakeword(np, sd)
                return
            except Exception as exc:
                log.exception("OpenWakeWord listener failed; falling back to transcript wake detection")
                self._set_status("warn", f"wake detector failed, using fallback: {exc}")

        self._run_transcript_fallback(np, sd)

    def _run_openwakeword(self, np, sd) -> None:
        from openwakeword.model import Model
        from openwakeword.utils import download_models

        model_dir = self.settings.app_dir / "models" / "openwakeword"
        self._ensure_openwakeword_assets(model_dir, download_models)

        detector = Model(
            wakeword_models=[str(model_dir / "hey_jarvis_v0.1.onnx")],
            melspec_model_path=str(model_dir / "melspectrogram.onnx"),
            embedding_model_path=str(model_dir / "embedding_model.onnx"),
            inference_framework="onnx",
        )
        wake_key = next(iter(detector.models.keys()))
        predict_kwargs = {
            "threshold": {wake_key: self.settings.voice_wake_threshold},
        }
        if self.settings.voice_wake_debounce_seconds > 0:
            predict_kwargs["debounce_time"] = self.settings.voice_wake_debounce_seconds
        else:
            predict_kwargs["patience"] = {wake_key: self.settings.voice_wake_patience}

        block_size = 1280
        block_seconds = block_size / float(self.settings.voice_sample_rate)
        utterances: queue.Queue = queue.Queue()
        pre_roll = deque(maxlen=max(2, int(self.settings.voice_activation_preroll_seconds / block_seconds)))
        min_blocks = max(1, int(self.settings.voice_activation_min_seconds / block_seconds))
        max_blocks = max(min_blocks + 1, int(self.settings.voice_activation_max_seconds / block_seconds))
        silence_blocks = max(1, int(self.settings.voice_activation_end_silence_seconds / block_seconds))

        capture_state = {
            "active": False,
            "chunks": [],
            "silence_blocks": 0,
            "speech_blocks": 0,
        }

        def finalize_capture() -> None:
            chunks = capture_state["chunks"]
            speech_blocks = capture_state["speech_blocks"]
            capture_state["active"] = False
            capture_state["chunks"] = []
            capture_state["silence_blocks"] = 0
            capture_state["speech_blocks"] = 0
            pre_roll.clear()

            if not chunks or speech_blocks < 1:
                self._set_status("ok", self._listening_detail("wake detector active"))
                return

            utterances.put(np.concatenate(chunks))
            self._set_status("busy", "transcribing wake command")

        def audio_callback(indata, frames, time_info, status) -> None:
            try:
                del frames, time_info
                if status:
                    log.debug("Wake listener input status: %s", status)
                if self._stop_event.is_set() or self._transcribing.is_set():
                    return

                chunk = np.copy(indata[:, 0]).astype(np.int16)
                if chunk.size == 0:
                    return

                pre_roll.append(chunk)

                if not capture_state["active"]:
                    scores = detector.predict(chunk, **predict_kwargs)
                    score = float(scores.get(wake_key, 0.0))
                    if score < self.settings.voice_wake_threshold:
                        return

                    capture_state["active"] = True
                    capture_state["chunks"] = list(pre_roll)
                    capture_state["silence_blocks"] = 0
                    capture_state["speech_blocks"] = int(
                        self._chunk_rms(chunk.astype(np.float32) / 32768.0) >= self.settings.voice_activation_energy_threshold
                    )
                    self._set_status("busy", f"wake phrase '{self.settings.voice_wake_phrase}' detected")
                    return

                capture_state["chunks"].append(chunk)

                rms = self._chunk_rms(chunk.astype(np.float32) / 32768.0)
                if rms >= self.settings.voice_activation_energy_threshold:
                    capture_state["silence_blocks"] = 0
                    capture_state["speech_blocks"] += 1
                else:
                    capture_state["silence_blocks"] += 1

                enough_audio = len(capture_state["chunks"]) >= min_blocks
                reached_end = capture_state["silence_blocks"] >= silence_blocks
                reached_max = len(capture_state["chunks"]) >= max_blocks
                if reached_max or (enough_audio and reached_end):
                    finalize_capture()
            except Exception as exc:
                log.exception("Wake listener audio callback failed")
                self._set_status("error", f"wake callback error: {exc}")
                self._stop_event.set()

        try:
            with sd.InputStream(
                samplerate=self.settings.voice_sample_rate,
                channels=1,
                dtype="int16",
                blocksize=block_size,
                callback=audio_callback,
            ) as stream:
                self._stream = stream
                self._set_status("ok", self._listening_detail("wake detector active"))

                while not self._stop_event.is_set():
                    try:
                        audio = utterances.get(timeout=0.2)
                    except queue.Empty:
                        continue

                    self._transcribing.set()
                    try:
                        float_audio = audio.astype(np.float32) / 32768.0
                        transcript = self.voice.transcribe_audio(float_audio, domain="command").strip()
                        if not transcript:
                            self._set_status("ok", self._listening_detail("wake detector active"))
                            continue

                        command = self.clean_command_transcript(
                            transcript,
                            self.settings.voice_wake_phrase,
                            assume_wake_detected=True,
                        )
                        if not command:
                            self._set_status("ok", self._listening_detail("wake detector active"))
                            continue

                        self.on_command(command, transcript)
                    except Exception as exc:
                        log.exception("Wake command transcription failed")
                        self._set_status("error", f"voice activation error: {exc}")
                    finally:
                        self._transcribing.clear()
                        if not self._stop_event.is_set():
                            self._set_status("ok", self._listening_detail("wake detector active"))
        except Exception as exc:
            log.exception("Wake listener failed")
            self._set_status("error", f"voice activation failed: {exc}")
        finally:
            self._stream = None

    def _run_transcript_fallback(self, np, sd) -> None:
        block_seconds = 0.1
        sample_rate = self.settings.voice_sample_rate
        block_size = max(1, int(sample_rate * block_seconds))
        pre_roll_chunks = max(1, int(self.settings.voice_activation_preroll_seconds / block_seconds))
        min_blocks = max(1, int(self.settings.voice_activation_min_seconds / block_seconds))
        max_blocks = max(min_blocks + 1, int(self.settings.voice_activation_max_seconds / block_seconds))
        silence_blocks = max(1, int(self.settings.voice_activation_end_silence_seconds / block_seconds))
        utterances: queue.Queue = queue.Queue()
        pre_roll: deque = deque(maxlen=pre_roll_chunks)
        capture_state = {
            "active": False,
            "chunks": [],
            "silence_blocks": 0,
            "speech_blocks": 0,
        }
        armed_until = 0.0

        def arm_for_followup() -> None:
            nonlocal armed_until
            armed_until = time.monotonic() + max(1.0, self.settings.voice_command_arm_seconds)
            self._set_status(
                "busy",
                f"wake phrase detected, listening {self.settings.voice_command_arm_seconds:.0f}s for your command",
            )

        def finalize_capture() -> None:
            chunks = capture_state["chunks"]
            speech_blocks = capture_state["speech_blocks"]
            capture_state["active"] = False
            capture_state["chunks"] = []
            capture_state["silence_blocks"] = 0
            capture_state["speech_blocks"] = 0
            pre_roll.clear()

            if len(chunks) < min_blocks or speech_blocks < self.settings.voice_activation_min_speech_blocks:
                if armed_until > time.monotonic():
                    self._set_status(
                        "busy",
                        f"wake phrase detected, listening {self.settings.voice_command_arm_seconds:.0f}s for your command",
                    )
                else:
                    self._set_status("ok", self._listening_detail("transcript wake mode"))
                return

            utterances.put(np.concatenate(chunks))
            self._set_status("busy", "transcribing voice input")

        def audio_callback(indata, frames, time_info, status) -> None:
            try:
                del frames, time_info
                if status:
                    log.debug("Wake listener input status: %s", status)
                if self._stop_event.is_set() or self._transcribing.is_set():
                    return

                chunk = np.copy(indata[:, 0]).astype(np.float32)
                if chunk.size == 0:
                    return

                rms = self._chunk_rms(chunk)
                speech_detected = rms >= self.settings.voice_activation_energy_threshold

                if not capture_state["active"]:
                    pre_roll.append(chunk)
                    if not speech_detected:
                        return

                    capture_state["active"] = True
                    capture_state["chunks"] = list(pre_roll)
                    capture_state["chunks"].append(chunk)
                    capture_state["silence_blocks"] = 0
                    capture_state["speech_blocks"] = 1
                    self._set_status("busy", "speech detected")
                    return

                capture_state["chunks"].append(chunk)

                if speech_detected:
                    capture_state["silence_blocks"] = 0
                    capture_state["speech_blocks"] += 1
                else:
                    capture_state["silence_blocks"] += 1

                if len(capture_state["chunks"]) >= max_blocks or capture_state["silence_blocks"] >= silence_blocks:
                    finalize_capture()
            except Exception as exc:
                log.exception("Fallback wake listener audio callback failed")
                self._set_status("error", f"wake callback error: {exc}")
                self._stop_event.set()

        try:
            with sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                blocksize=block_size,
                callback=audio_callback,
            ) as stream:
                self._stream = stream
                self._set_status("ok", self._listening_detail("transcript wake mode"))

                while not self._stop_event.is_set():
                    try:
                        audio = utterances.get(timeout=0.2)
                    except queue.Empty:
                        if armed_until and time.monotonic() >= armed_until:
                            armed_until = 0.0
                            self._set_status("ok", self._listening_detail("transcript wake mode"))
                        continue

                    self._transcribing.set()
                    try:
                        transcript = self.voice.transcribe_audio(audio, domain="command").strip()
                        if not transcript:
                            if armed_until > time.monotonic():
                                self._set_status(
                                    "busy",
                                    f"wake phrase detected, listening {self.settings.voice_command_arm_seconds:.0f}s for your command",
                                )
                            else:
                                self._set_status("ok", self._listening_detail("transcript wake mode"))
                            continue

                        if armed_until > time.monotonic() and not self._is_wake_only(transcript, self.settings.voice_wake_phrase):
                            armed_until = 0.0
                            command = transcript.strip()
                            if command:
                                self.on_command(command, transcript)
                            continue

                        command = self.clean_command_transcript(
                            transcript,
                            self.settings.voice_wake_phrase,
                            assume_wake_detected=False,
                        )
                        if command:
                            armed_until = 0.0
                            self.on_command(command, transcript)
                            continue

                        if self._is_wake_only(transcript, self.settings.voice_wake_phrase):
                            arm_for_followup()
                            continue

                        if armed_until > time.monotonic():
                            self._set_status(
                                "busy",
                                f"wake phrase detected, listening {self.settings.voice_command_arm_seconds:.0f}s for your command",
                            )
                        else:
                            self._set_status("ok", self._listening_detail("transcript wake mode"))
                    except Exception as exc:
                        log.exception("Fallback wake listener transcription failed")
                        self._set_status("error", f"voice activation error: {exc}")
                    finally:
                        self._transcribing.clear()
                        if not self._stop_event.is_set():
                            if armed_until > time.monotonic():
                                self._set_status(
                                    "busy",
                                    f"wake phrase detected, listening {self.settings.voice_command_arm_seconds:.0f}s for your command",
                                )
                            else:
                                self._set_status("ok", self._listening_detail("transcript wake mode"))
        except Exception as exc:
            log.exception("Fallback wake listener failed")
            self._set_status("error", f"voice activation failed: {exc}")
        finally:
            self._stream = None

    def _ensure_openwakeword_assets(self, model_dir: Path, download_models: Callable[..., None]) -> None:
        required_files = (
            model_dir / "embedding_model.onnx",
            model_dir / "melspectrogram.onnx",
            model_dir / "hey_jarvis_v0.1.onnx",
        )
        if all(path.exists() for path in required_files):
            return

        model_dir.mkdir(parents=True, exist_ok=True)
        bundled_dir = resource_path("assets", "openwakeword")
        if bundled_dir.exists():
            for source in bundled_dir.glob("*.onnx"):
                shutil.copy2(source, model_dir / source.name)
            if all(path.exists() for path in required_files):
                return

        self._set_status("busy", "downloading wake detector models")
        download_models(model_names=["hey_jarvis_v0.1"], target_directory=str(model_dir))

    def _listening_detail(self, suffix: str) -> str:
        return f"listening for '{self.settings.voice_wake_phrase}' ({suffix})"

    def _set_status(self, state: str, detail: str) -> None:
        with self._status_lock:
            self._status_state = state
            self._status_detail = detail
        if self.on_status is not None:
            self.on_status(state, detail)

    @staticmethod
    def _chunk_rms(chunk) -> float:
        return float((chunk * chunk).mean() ** 0.5)

    @staticmethod
    def clean_command_transcript(transcript: str, wake_phrase: str, assume_wake_detected: bool) -> str:
        command = WakePhraseListener.extract_command(transcript, wake_phrase)
        if command:
            return command

        if not assume_wake_detected:
            return ""

        stripped = transcript.strip()
        if WakePhraseListener._is_wake_only(stripped, wake_phrase):
            return ""
        return stripped

    @staticmethod
    def extract_command(transcript: str, wake_phrase: str) -> str:
        wake_word = re.escape(wake_phrase.strip())
        pattern = re.compile(
            rf"^\s*(?:hey|hi|ok|okay)?\s*{wake_word}\b[\s,:-]*(?P<command>.*)$",
            re.IGNORECASE,
        )
        match = pattern.match(transcript)
        if not match:
            return ""
        return match.group("command").strip()

    @staticmethod
    def _is_wake_only(transcript: str, wake_phrase: str) -> bool:
        lowered = transcript.strip().lower()
        wake = wake_phrase.lower()
        wake_only_patterns = {
            wake,
            f"hey {wake}",
            f"hi {wake}",
            f"okay {wake}",
            f"ok {wake}",
        }
        return lowered in wake_only_patterns
