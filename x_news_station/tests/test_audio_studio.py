"""Tests for the audio_studio module."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from modules.audio_studio import VoiceGenerator


class TestVoiceGeneratorInit:
    """Tests for VoiceGenerator initialization."""

    def test_creates_cache_directory(self, tmp_path: Path) -> None:
        """Test that cache directory is created on init."""
        cache_dir = tmp_path / "test_cache"

        with patch("config.get_cache_dir", return_value=cache_dir):
            # Mock both TTS engines to fail
            with patch.object(VoiceGenerator, "_init_kokoro", return_value=False):
                with patch.object(VoiceGenerator, "_init_pyttsx3", return_value=False):
                    with patch.object(VoiceGenerator, "_init_windows_speech", return_value=False):
                        VoiceGenerator()

        assert cache_dir.exists()

    def test_uses_kokoro_when_available(self, tmp_path: Path) -> None:
        """Test that kokoro is used when available."""
        cache_dir = tmp_path / "test_cache"

        with patch("config.get_cache_dir", return_value=cache_dir):
            with patch.object(VoiceGenerator, "_init_kokoro", return_value=True):
                with patch.object(VoiceGenerator, "_init_pyttsx3"):
                    with patch.object(VoiceGenerator, "_init_windows_speech"):
                        vg = VoiceGenerator()

        assert not vg._using_fallback

    def test_falls_back_to_pyttsx3(self, tmp_path: Path) -> None:
        """Test that pyttsx3 is used when kokoro unavailable."""
        cache_dir = tmp_path / "test_cache"

        with patch("config.get_cache_dir", return_value=cache_dir):
            with patch.object(VoiceGenerator, "_init_kokoro", return_value=False):
                with patch.object(VoiceGenerator, "_init_pyttsx3", return_value=True):
                    with patch.object(VoiceGenerator, "_init_windows_speech", return_value=False):
                        vg = VoiceGenerator()

        assert vg._using_fallback

    def test_uses_windows_speech_when_other_tts_engines_unavailable(self, tmp_path: Path) -> None:
        """Test Windows speech fallback path before tone-only fallback."""
        cache_dir = tmp_path / "test_cache"

        with patch("config.get_cache_dir", return_value=cache_dir):
            with patch.object(VoiceGenerator, "_init_kokoro", return_value=False):
                with patch.object(VoiceGenerator, "_init_pyttsx3", return_value=False):
                    with patch.object(VoiceGenerator, "_init_windows_speech", return_value=True):
                        vg = VoiceGenerator()

        assert vg._using_windows_speech_fallback is True
        assert vg._using_builtin_wave_fallback is False

    def test_uses_builtin_wave_fallback_when_no_tts_engines(self, tmp_path: Path) -> None:
        """Test built-in fallback path when kokoro and pyttsx3 are unavailable."""
        cache_dir = tmp_path / "test_cache"

        with patch("config.get_cache_dir", return_value=cache_dir):
            with patch.object(VoiceGenerator, "_init_kokoro", return_value=False):
                with patch.object(VoiceGenerator, "_init_pyttsx3", return_value=False):
                    with patch.object(VoiceGenerator, "_init_windows_speech", return_value=False):
                        vg = VoiceGenerator()

        output_path = vg.generate("Fallback audio check", "am_michael")
        assert vg._using_builtin_wave_fallback is True
        assert output_path.exists()
        assert output_path.suffix == ".wav"

    def test_windows_speech_fallback_generates_file(self, tmp_path: Path) -> None:
        """Test Windows speech fallback generation path."""
        cache_dir = tmp_path / "test_cache"

        with patch("config.get_cache_dir", return_value=cache_dir):
            with patch.object(VoiceGenerator, "_init_kokoro", return_value=False):
                with patch.object(VoiceGenerator, "_init_pyttsx3", return_value=False):
                    with patch.object(VoiceGenerator, "_init_windows_speech", return_value=True):
                        vg = VoiceGenerator()

        def mock_generate(text: str, voice_id: str, output_path: Path) -> bool:
            _ = (text, voice_id)
            output_path.write_bytes(b"fake windows speech")
            return True

        with patch.object(vg, "_generate_with_windows_speech", side_effect=mock_generate):
            output_path = vg.generate("Windows speech check", "am_michael")

        assert output_path.exists()
        assert vg._using_windows_speech_fallback is True

    def test_detect_kokoro_assets_prefers_int8_model(self, tmp_path: Path) -> None:
        """Asset detection should pick the official int8 release artifact when present."""
        model_path = tmp_path / "kokoro-v1.0.int8.onnx"
        voices_path = tmp_path / "voices-v1.0.bin"
        model_path.write_bytes(b"model")
        voices_path.write_bytes(b"voices")

        with patch("config.get_project_root", return_value=tmp_path):
            detected_model, detected_voices = VoiceGenerator.detect_kokoro_assets()

        assert detected_model == model_path
        assert detected_voices == voices_path


class TestVoiceGeneratorCache:
    """Tests for VoiceGenerator caching."""

    def test_cache_hit_returns_same_path(self, tmp_path: Path) -> None:
        """Test that same text+voice returns same path without regenerating."""
        cache_dir = tmp_path / "test_cache"
        cache_dir.mkdir()

        # Create a fake cached file
        text = "Hello world"
        voice_id = "am_michael"

        with patch("config.get_cache_dir", return_value=cache_dir):
            with patch.object(VoiceGenerator, "_init_kokoro", return_value=False):
                with patch.object(VoiceGenerator, "_init_pyttsx3", return_value=True):
                    with patch.object(VoiceGenerator, "_init_windows_speech", return_value=False):
                        vg = VoiceGenerator()

        # Pre-create the cache file
        cache_key = vg._get_cache_key(text, voice_id)
        cache_path = vg._get_cache_path(cache_key)
        cache_path.write_bytes(b"fake audio data")

        # Call should return cached path without generating
        with patch.object(vg, "_generate_with_pyttsx3") as mock_gen:
            result_path = vg.generate(text, voice_id)
            mock_gen.assert_not_called()

        assert result_path == cache_path

    def test_cache_miss_generates_new_file(self, tmp_path: Path) -> None:
        """Test that new text generates new file."""
        cache_dir = tmp_path / "test_cache"
        cache_dir.mkdir()

        with patch.object(VoiceGenerator, "_init_kokoro", return_value=False):
            with patch.object(VoiceGenerator, "_init_windows_speech", return_value=False):
                vg = VoiceGenerator()
        vg.cache_dir = cache_dir
        vg._kokoro = None
        vg._pyttsx3 = MagicMock()
        vg._using_fallback = True

        # Mock pyttsx3 generation
        def mock_generate(text: str, voice_id: str, output_path: Path) -> bool:
            _ = (text, voice_id)
            output_path.write_bytes(b"fake audio")
            return True

        with patch.object(vg, "_generate_with_pyttsx3", side_effect=mock_generate):
            path1 = vg.generate("Hello world", "am_michael")
            path2 = vg.generate("Different text", "am_michael")

        assert path1 != path2
        assert path1.exists()
        assert path2.exists()

    def test_different_voices_generate_different_files(self, tmp_path: Path) -> None:
        """Test that different voice_ids generate different cache entries."""
        cache_dir = tmp_path / "test_cache"
        cache_dir.mkdir()

        with patch.object(VoiceGenerator, "_init_kokoro", return_value=False):
            with patch.object(VoiceGenerator, "_init_windows_speech", return_value=False):
                vg = VoiceGenerator()
        vg.cache_dir = cache_dir
        vg._kokoro = None
        vg._pyttsx3 = MagicMock()
        vg._using_fallback = True

        def mock_generate(text: str, voice_id: str, output_path: Path) -> bool:
            _ = (text, voice_id)
            output_path.write_bytes(b"fake audio")
            return True

        with patch.object(vg, "_generate_with_pyttsx3", side_effect=mock_generate):
            path1 = vg.generate("Hello world", "am_michael")
            path2 = vg.generate("Hello world", "bf_emma")

        assert path1 != path2


class TestVoiceGeneratorCleanCache:
    """Tests for cache cleanup functionality."""

    def test_clean_cache_removes_oldest_files(self, tmp_path: Path) -> None:
        """Test that clean_cache removes oldest files when over limit."""
        cache_dir = tmp_path / "test_cache"
        cache_dir.mkdir()

        with patch.object(VoiceGenerator, "_init_kokoro", return_value=False):
            with patch.object(VoiceGenerator, "_init_windows_speech", return_value=False):
                vg = VoiceGenerator()
        vg.cache_dir = cache_dir

        # Create 5 cache files with different modification times
        for i in range(5):
            cache_file = cache_dir / f"file{i}.wav"
            cache_file.write_bytes(b"fake audio")
            # Set modification time (older files first)
            os.utime(cache_file, (i, i))

        # Clean with max_files=3
        deleted = vg.clean_cache(max_files=3)

        assert deleted == 2
        remaining = list(cache_dir.glob("*.wav"))
        assert len(remaining) == 3

    def test_clean_cache_does_nothing_when_under_limit(self, tmp_path: Path) -> None:
        """Test that clean_cache does nothing when under limit."""
        cache_dir = tmp_path / "test_cache"
        cache_dir.mkdir()

        with patch.object(VoiceGenerator, "_init_kokoro", return_value=False):
            with patch.object(VoiceGenerator, "_init_windows_speech", return_value=False):
                vg = VoiceGenerator()
        vg.cache_dir = cache_dir

        # Create 2 cache files
        for i in range(2):
            cache_file = cache_dir / f"file{i}.wav"
            cache_file.write_bytes(b"fake audio")

        # Clean with max_files=5
        deleted = vg.clean_cache(max_files=5)

        assert deleted == 0
        remaining = list(cache_dir.glob("*.wav"))
        assert len(remaining) == 2


class TestVoiceGeneratorCacheKey:
    """Tests for cache key generation."""

    def test_same_text_voice_same_key(self, tmp_path: Path) -> None:
        """Test that identical text and voice produce same cache key."""
        cache_dir = tmp_path / "test_cache"

        with patch("config.get_cache_dir", return_value=cache_dir):
            with patch.object(VoiceGenerator, "_init_kokoro", return_value=False):
                with patch.object(VoiceGenerator, "_init_pyttsx3", return_value=True):
                    with patch.object(VoiceGenerator, "_init_windows_speech", return_value=False):
                        vg = VoiceGenerator()

        key1 = vg._get_cache_key("Hello world", "am_michael")
        key2 = vg._get_cache_key("Hello world", "am_michael")

        assert key1 == key2
        assert len(key1) == 64  # SHA256 hex is 64 chars

    def test_different_text_different_key(self, tmp_path: Path) -> None:
        """Test that different text produces different cache key."""
        cache_dir = tmp_path / "test_cache"

        with patch("config.get_cache_dir", return_value=cache_dir):
            with patch.object(VoiceGenerator, "_init_kokoro", return_value=False):
                with patch.object(VoiceGenerator, "_init_pyttsx3", return_value=True):
                    with patch.object(VoiceGenerator, "_init_windows_speech", return_value=False):
                        vg = VoiceGenerator()

        key1 = vg._get_cache_key("Hello world", "am_michael")
        key2 = vg._get_cache_key("Goodbye world", "am_michael")

        assert key1 != key2

    def test_different_voice_different_key(self, tmp_path: Path) -> None:
        """Test that different voice produces different cache key."""
        cache_dir = tmp_path / "test_cache"

        with patch("config.get_cache_dir", return_value=cache_dir):
            with patch.object(VoiceGenerator, "_init_kokoro", return_value=False):
                with patch.object(VoiceGenerator, "_init_pyttsx3", return_value=True):
                    with patch.object(VoiceGenerator, "_init_windows_speech", return_value=False):
                        vg = VoiceGenerator()

        key1 = vg._get_cache_key("Hello world", "am_michael")
        key2 = vg._get_cache_key("Hello world", "bf_emma")

        assert key1 != key2


class TestVoiceGeneratorStats:
    """Tests for cache statistics."""

    def test_get_cache_stats(self, tmp_path: Path) -> None:
        """Test that cache stats return correct values."""
        cache_dir = tmp_path / "test_cache"
        cache_dir.mkdir()

        with patch.object(VoiceGenerator, "_init_kokoro", return_value=False):
            with patch.object(VoiceGenerator, "_init_windows_speech", return_value=False):
                vg = VoiceGenerator()
        vg.cache_dir = cache_dir

        # Initially empty
        stats = vg.get_cache_stats()
        assert stats["file_count"] == 0
        assert stats["total_size_bytes"] == 0

        # Add a file
        cache_file = cache_dir / "test.wav"
        cache_file.write_bytes(b"fake audio data")

        stats = vg.get_cache_stats()
        assert stats["file_count"] == 1
        assert stats["total_size_bytes"] == len(b"fake audio data")

    def test_clear_cache(self, tmp_path: Path) -> None:
        """Test that clear_cache removes all files."""
        cache_dir = tmp_path / "test_cache"
        cache_dir.mkdir()

        with patch.object(VoiceGenerator, "_init_kokoro", return_value=False):
            with patch.object(VoiceGenerator, "_init_windows_speech", return_value=False):
                vg = VoiceGenerator()
        vg.cache_dir = cache_dir

        # Create some files
        for i in range(3):
            (cache_dir / f"file{i}.wav").write_bytes(b"fake")

        deleted = vg.clear_cache()

        assert deleted == 3
        assert len(list(cache_dir.glob("*.wav"))) == 0


class TestVoiceGeneratorValidCache:
    """Tests for cache validation."""

    def test_empty_file_is_invalid(self, tmp_path: Path) -> None:
        """Test that empty files are not considered valid cache."""
        cache_dir = tmp_path / "test_cache"

        with patch("config.get_cache_dir", return_value=cache_dir):
            with patch.object(VoiceGenerator, "_init_kokoro", return_value=False):
                with patch.object(VoiceGenerator, "_init_pyttsx3", return_value=True):
                    with patch.object(VoiceGenerator, "_init_windows_speech", return_value=False):
                        vg = VoiceGenerator()

        # Create empty file
        empty_file = tmp_path / "empty.wav"
        empty_file.write_text("")

        assert not vg._is_valid_cache_file(empty_file)

    def test_nonexistent_file_is_invalid(self, tmp_path: Path) -> None:
        """Test that nonexistent files are not considered valid cache."""
        cache_dir = tmp_path / "test_cache"

        with patch("config.get_cache_dir", return_value=cache_dir):
            with patch.object(VoiceGenerator, "_init_kokoro", return_value=False):
                with patch.object(VoiceGenerator, "_init_pyttsx3", return_value=True):
                    with patch.object(VoiceGenerator, "_init_windows_speech", return_value=False):
                        vg = VoiceGenerator()

        nonexistent = tmp_path / "nonexistent.wav"

        assert not vg._is_valid_cache_file(nonexistent)
