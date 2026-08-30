"""Tests for whisper_local.py — free/local transcription fallback.

Runs entirely on-machine: faster-whisper, mlx-whisper (uvx), or the system
`whisper` CLI. Nothing is uploaded anywhere.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "video-to-agent" / "scripts"))

import whisper_local as wl


class TestAudioExtractionCmd:
    def test_mono_16k_command(self):
        cmd = wl.build_ffmpeg_cmd("in.mp4", "out.wav")
        joined = " ".join(cmd)
        assert "ffmpeg" in joined
        assert "-ac" in joined and "1" in joined
        assert "16000" in joined
        assert "in.mp4" in joined and "out.wav" in joined


class TestBackendSelection:
    def test_prefers_faster_whisper(self):
        avail = {"faster_whisper": True, "mlx": True, "cli": True}
        assert wl.select_backend(avail) == "faster_whisper"

    def test_mlx_next_on_apple_silicon(self):
        avail = {"faster_whisper": False, "mlx": True, "cli": True}
        assert wl.select_backend(avail) == "mlx"

    def test_cli_last(self):
        avail = {"faster_whisper": False, "mlx": False, "cli": True}
        assert wl.select_backend(avail) == "whisper_cli"

    def test_none_raises(self):
        try:
            wl.select_backend({"faster_whisper": False, "mlx": False, "cli": False})
            raised = False
        except SystemExit:
            raised = True
        assert raised


class TestSegmentNormalization:
    def test_segments_have_start_end_text(self):
        segs = wl.normalize_segments([
            {"start": 0.0, "end": 2.5, "text": " hello "},
            {"start": 2.5, "end": 5.0, "text": "world"},
        ])
        assert segs[0] == {"start": 0.0, "end": 2.5, "text": "hello"}
        assert segs[1]["text"] == "world"

    def test_empty_text_dropped(self):
        segs = wl.normalize_segments([
            {"start": 0.0, "end": 1.0, "text": ""},
            {"start": 1.0, "end": 2.0, "text": "real"},
        ])
        assert len(segs) == 1

    def test_sorted_by_start(self):
        segs = wl.normalize_segments([
            {"start": 5.0, "end": 6.0, "text": "b"},
            {"start": 0.0, "end": 1.0, "text": "a"},
        ])
        assert segs[0]["text"] == "a"


class TestVttParsing:
    def test_parse_webvtt(self):
        vtt = """WEBVTT

00:00:01.000 --> 00:00:03.500
hello world

00:00:03.500 --> 00:00:06.000
second line
"""
        segs = wl.parse_vtt(vtt)
        assert len(segs) == 2
        assert segs[0]["start"] == 1.0
        assert segs[0]["end"] == 3.5
        assert segs[1]["text"] == "second line"

    def test_hours_timestamps(self):
        vtt = "00:01:02.000 --> 00:01:05.000\nx\n"
        segs = wl.parse_vtt(vtt)
        assert segs[0]["start"] == 62.0


class TestTranscribeDispatch:
    def test_dispatches_to_selected_backend(self):
        calls = []

        def fake_backend(audio_path, model_size):
            calls.append((audio_path, model_size))
            return [{"start": 0.0, "end": 1.0, "text": "hi"}]

        result = wl.transcribe("/tmp/a.wav", backend="stub",
                               backends={"stub": fake_backend})
        assert result[0]["text"] == "hi"
        assert calls == [("/tmp/a.wav", "small")]
