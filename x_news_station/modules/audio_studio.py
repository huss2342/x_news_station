"""TTS and audio-cache handling for generated bulletin clips."""

from __future__ import annotations

import base64
import hashlib
import logging
import math
import subprocess
import sys
import threading
import wave
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)

KOKORO_MODEL_FILENAMES = [
    "kokoro-v1.0.int8.onnx",
    "kokoro-v1.0.fp16.onnx",
    "kokoro-v1.0.onnx",
]
KOKORO_VOICES_FILENAMES = [
    "voices-v1.0.bin",
    "voices.bin",
]


class VoiceGenerator:
    """Text-to-speech generator with deterministic file-based caching."""

    def __init__(self) -> None:
        """Initialize TTS engines and prepare cache directory."""
        self.cache_dir = config.get_cache_dir()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._kokoro: Any | None = None
        self._pyttsx3: Any | None = None
        self._using_fallback = False
        self._using_windows_speech_fallback = False
        self._using_builtin_wave_fallback = False
        self._cache_lock = threading.Lock()
        self._kokoro_model_path: Path | None = None
        self._kokoro_voices_path: Path | None = None

        if self._init_kokoro():
            logger.info("VoiceGenerator initialized with kokoro-onnx")
            return

        if self._init_pyttsx3():
            self._using_fallback = True
            logger.warning(
                "VoiceGenerator using pyttsx3 fallback; install kokoro-onnx models for better quality"
            )
            return

        if self._init_windows_speech():
            self._using_fallback = True
            self._using_windows_speech_fallback = True
            logger.warning("VoiceGenerator using Windows SpeechSynthesizer fallback")
            return

        self._using_fallback = True
        self._using_builtin_wave_fallback = True
        logger.warning("No TTS engine found; using built-in sine-wave fallback audio")

    @staticmethod
    def _find_first_existing(candidates: list[Path]) -> Path | None:
        for path in candidates:
            if path.exists():
                return path
        return None

    @classmethod
    def detect_kokoro_assets(cls) -> tuple[Path | None, Path | None]:
        """Detect installed Kokoro model assets in common locations."""
        search_roots = [
            config.get_project_root(),
            Path.cwd(),
            Path.home() / ".kokoro",
            Path("/usr/local/share/kokoro"),
        ]
        search_roots = list(dict.fromkeys(search_roots))

        model_candidates: list[Path] = []
        voices_candidates: list[Path] = []
        for root in search_roots:
            model_candidates.extend(root / filename for filename in KOKORO_MODEL_FILENAMES)
            voices_candidates.extend(root / filename for filename in KOKORO_VOICES_FILENAMES)

        return cls._find_first_existing(model_candidates), cls._find_first_existing(voices_candidates)

    def _init_kokoro(self) -> bool:
        """Initialize kokoro TTS when dependency and model files are available."""
        try:
            from kokoro_onnx import Kokoro
        except ImportError:
            logger.debug("kokoro-onnx not installed")
            return False

        model_path, voices_path = self.detect_kokoro_assets()
        if model_path is None or voices_path is None:
            logger.debug("kokoro model files not found")
            return False

        try:
            self._kokoro = Kokoro(str(model_path), str(voices_path))
            self._kokoro_model_path = model_path
            self._kokoro_voices_path = voices_path
            return True
        except Exception as exc:
            logger.debug("Failed to initialize kokoro: %s", exc)
            return False

    def describe_backend(self) -> str:
        """Return a short human-readable description of the active TTS backend."""
        if self._kokoro is not None and self._kokoro_model_path is not None:
            return f"kokoro-onnx ({self._kokoro_model_path.name})"
        if self._using_windows_speech_fallback:
            return "Windows SpeechSynthesizer fallback"
        if self._pyttsx3 is not None:
            return "pyttsx3 fallback"
        if self._using_builtin_wave_fallback:
            return "built-in tone fallback"
        return "unknown audio mode"

    def _init_pyttsx3(self) -> bool:
        """Initialize pyttsx3 fallback TTS."""
        try:
            import pyttsx3

            self._pyttsx3 = pyttsx3.init()
            return True
        except ImportError:
            logger.debug("pyttsx3 not installed")
            return False
        except Exception as exc:
            logger.debug("Failed to initialize pyttsx3: %s", exc)
            return False

    @staticmethod
    def _encode_powershell_script(script: str) -> str:
        """Encode a PowerShell script for -EncodedCommand."""
        return base64.b64encode(script.encode("utf-16le")).decode("ascii")

    def _init_windows_speech(self) -> bool:
        """Check whether the built-in Windows speech synthesizer is available."""
        if sys.platform != "win32":
            return False

        script = "Add-Type -AssemblyName System.Speech"
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-EncodedCommand",
                    self._encode_powershell_script(script),
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
            logger.debug("Windows speech probe failed: %s", exc)
            return False

        if result.returncode != 0:
            logger.debug("Windows speech probe failed with exit code %s", result.returncode)
            return False

        return True

    def _get_cache_key(self, text: str, voice_id: str) -> str:
        """Return SHA-256 cache key for text+voice combination."""
        content = f"{text}:{voice_id}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _get_cache_path(self, cache_key: str) -> Path:
        """Return cache file path for a key."""
        return self.cache_dir / f"{cache_key}.wav"

    def _is_valid_cache_file(self, path: Path) -> bool:
        """Return True when a cache file exists and is non-empty."""
        try:
            return path.exists() and path.stat().st_size > 0
        except OSError:
            return False

    def _generate_with_kokoro(self, text: str, voice_id: str, output_path: Path) -> bool:
        """Generate WAV audio with kokoro model output."""
        if self._kokoro is None:
            return False

        try:
            import numpy as np

            audio_array, sample_rate = self._kokoro.create(text, voice=voice_id)
            pcm_audio = (audio_array * 32767).astype(np.int16).tobytes()

            with wave.open(str(output_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(int(sample_rate))
                wav_file.writeframes(pcm_audio)
            return self._is_valid_cache_file(output_path)
        except Exception as exc:
            logger.error("Kokoro generation failed: %s", exc)
            return False

    def _select_pyttsx3_voice(self, voice_id: str) -> None:
        """Configure pyttsx3 to a closer voice match when possible."""
        if self._pyttsx3 is None:
            return

        preferred_gender = self._get_windows_voice_gender(voice_id).lower()
        try:
            voices = self._pyttsx3.getProperty("voices") or []
        except Exception:
            voices = []

        selected_voice_id: str | None = None
        for voice in voices:
            descriptor = " ".join(
                str(part)
                for part in (getattr(voice, "name", ""), getattr(voice, "id", ""))
                if part
            ).lower()
            if preferred_gender and preferred_gender in descriptor:
                selected_voice_id = getattr(voice, "id", None)
                break

        try:
            if selected_voice_id:
                self._pyttsx3.setProperty("voice", selected_voice_id)
            self._pyttsx3.setProperty("rate", 175)
            self._pyttsx3.setProperty("volume", 1.0)
        except Exception as exc:
            logger.debug("pyttsx3 voice configuration failed: %s", exc)

    def _generate_with_pyttsx3(self, text: str, voice_id: str, output_path: Path) -> bool:
        """Generate WAV audio using pyttsx3 engine."""
        if self._pyttsx3 is None:
            return False

        try:
            self._select_pyttsx3_voice(voice_id)
            self._pyttsx3.save_to_file(text, str(output_path))
            self._pyttsx3.runAndWait()
            return self._is_valid_cache_file(output_path)
        except Exception as exc:
            logger.error("pyttsx3 generation failed: %s", exc)
            return False

    @staticmethod
    def _get_windows_voice_gender(voice_id: str) -> str:
        """Map kokoro-style voice IDs to a coarse Windows voice gender hint."""
        normalized = voice_id.lower().strip()
        if normalized.startswith(("af_", "bf_")):
            return "Female"
        if normalized.startswith(("am_", "bm_")):
            return "Male"
        return ""

    def _generate_with_windows_speech(self, text: str, voice_id: str, output_path: Path) -> bool:
        """Generate WAV audio using the built-in Windows speech engine."""
        if not self._using_windows_speech_fallback:
            return False

        encoded_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
        output_literal = str(output_path).replace("'", "''")
        preferred_gender = self._get_windows_voice_gender(voice_id).replace("'", "''")
        script = f"""
Add-Type -AssemblyName System.Speech
$text = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{encoded_text}'))
$outputPath = '{output_literal}'
$preferredGender = '{preferred_gender}'
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {{
    if ($preferredGender -ne '') {{
        $gender = [System.Enum]::Parse([System.Speech.Synthesis.VoiceGender], $preferredGender)
        $voice = $synth.GetInstalledVoices() |
            ForEach-Object {{ $_.VoiceInfo }} |
            Where-Object {{ $_.Gender -eq $gender }} |
            Select-Object -First 1
        if ($voice) {{
            $synth.SelectVoice($voice.Name)
        }}
    }}
    $synth.Rate = -1
    $synth.Volume = 100
    $synth.SetOutputToWaveFile($outputPath)
    $synth.Speak($text)
}}
finally {{
    $synth.Dispose()
}}
"""

        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-EncodedCommand",
                    self._encode_powershell_script(script),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
            logger.error("Windows speech generation failed: %s", exc)
            return False

        if result.returncode != 0:
            logger.error(
                "Windows speech generation failed with exit code %s: %s",
                result.returncode,
                result.stderr.strip(),
            )
            return False

        return self._is_valid_cache_file(output_path)

    def _generate_builtin_wave(self, output_path: Path) -> bool:
        """Generate a short sine-wave WAV clip when no TTS engine is present."""
        sample_rate = config.BUILTIN_TTS_SAMPLE_RATE
        frequency = config.BUILTIN_TTS_FREQUENCY_HZ
        duration_seconds = config.BUILTIN_TTS_SECONDS
        frame_count = max(1, int(sample_rate * duration_seconds))
        amplitude = 11000

        try:
            with wave.open(str(output_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)

                for index in range(frame_count):
                    sample = int(amplitude * math.sin(2 * math.pi * frequency * (index / sample_rate)))
                    wav_file.writeframesraw(sample.to_bytes(2, byteorder="little", signed=True))
            return self._is_valid_cache_file(output_path)
        except Exception as exc:
            logger.error("Built-in wave fallback generation failed: %s", exc)
            return False

    def _maybe_clean_cache(self, max_files: int = config.MAX_CACHE_FILES) -> None:
        """Prune cache when file count exceeds configured limit."""
        with self._cache_lock:
            try:
                cache_files = list(self.cache_dir.glob("*.wav"))
            except OSError as exc:
                logger.warning("Could not inspect cache directory %s: %s", self.cache_dir, exc)
                return

        if len(cache_files) > max_files:
            self.clean_cache(max_files=max_files)

    def generate(self, text: str, voice_id: str = config.VOICE_ID) -> Path:
        """Generate or reuse cached WAV clip for given text."""
        cache_key = self._get_cache_key(text, voice_id)
        cache_path = self._get_cache_path(cache_key)

        if self._is_valid_cache_file(cache_path):
            logger.debug("Voice cache hit: %s", cache_key[:10])
            return cache_path

        logger.debug("Voice cache miss: %s", cache_key[:10])

        generated = False
        if not self._using_fallback and self._kokoro is not None:
            generated = self._generate_with_kokoro(text, voice_id, cache_path)
            if not generated:
                logger.warning("Kokoro generation failed; trying fallback engine")

        if not generated and self._pyttsx3 is not None:
            generated = self._generate_with_pyttsx3(text, voice_id, cache_path)

        if not generated and self._using_windows_speech_fallback:
            generated = self._generate_with_windows_speech(text, voice_id, cache_path)

        if not generated and self._using_builtin_wave_fallback:
            generated = self._generate_builtin_wave(cache_path)

        if not generated:
            raise RuntimeError("Audio generation failed across all available paths")

        self._maybe_clean_cache(max_files=config.MAX_CACHE_FILES)
        return cache_path

    def clean_cache(self, max_files: int = config.MAX_CACHE_FILES) -> int:
        """Delete oldest cached files until cache contains at most `max_files` clips."""
        with self._cache_lock:
            try:
                cache_files = list(self.cache_dir.glob("*.wav"))
            except OSError as exc:
                logger.warning("Unable to scan cache directory %s: %s", self.cache_dir, exc)
                return 0

            if len(cache_files) <= max_files:
                return 0

            sortable_files: list[Path] = []
            for file_path in cache_files:
                try:
                    _ = file_path.stat().st_mtime
                    sortable_files.append(file_path)
                except OSError as exc:
                    logger.warning("Could not stat cache file %s: %s", file_path, exc)

            sortable_files.sort(key=lambda path: path.stat().st_mtime)
            to_delete = sortable_files[:-max_files]

            deleted_count = 0
            for file_path in to_delete:
                try:
                    file_path.unlink()
                    deleted_count += 1
                except OSError as exc:
                    logger.warning("Failed deleting cache file %s: %s", file_path, exc)

        logger.info("Cache cleanup removed %s files; max retained is %s", deleted_count, max_files)
        return deleted_count

    def get_cache_stats(self) -> dict[str, int]:
        """Return cache file count and byte size."""
        with self._cache_lock:
            try:
                cache_files = list(self.cache_dir.glob("*.wav"))
            except OSError:
                return {"file_count": 0, "total_size_bytes": 0}

            total_size = 0
            for file_path in cache_files:
                try:
                    total_size += file_path.stat().st_size
                except OSError:
                    continue

        return {"file_count": len(cache_files), "total_size_bytes": total_size}

    def clear_cache(self) -> int:
        """Delete all cached WAV files."""
        with self._cache_lock:
            try:
                cache_files = list(self.cache_dir.glob("*.wav"))
            except OSError as exc:
                logger.warning("Unable to scan cache directory %s: %s", self.cache_dir, exc)
                return 0

            deleted_count = 0
            for file_path in cache_files:
                try:
                    file_path.unlink()
                    deleted_count += 1
                except OSError as exc:
                    logger.warning("Failed deleting cache file %s: %s", file_path, exc)

        logger.info("Cleared %s cached audio files", deleted_count)
        return deleted_count
