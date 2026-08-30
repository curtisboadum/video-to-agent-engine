"""Tests for coverage.py — chunk planning and the no-blind-spots audit.

Pure functions; ffprobe is mocked. The invariant: every second of a video
must be covered by frame evidence OR transcript evidence, or it escalates.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "video-to-agent" / "scripts"))

import coverage


class TestProbeDuration:
    def test_parses_ffprobe_output(self, monkeypatch):
        monkeypatch.setattr(coverage, "_ffprobe", lambda path: "125.5")
        assert coverage.probe_duration("video.mp4") == 125.5

    def test_raises_on_garbage(self, monkeypatch):
        def boom(path):
            raise ValueError("bad")
        monkeypatch.setattr(coverage, "_ffprobe", boom)
        try:
            coverage.probe_duration("video.mp4")
            raised = False
        except SystemExit:
            raised = True
        assert raised


class TestPlanChunks:
    def test_short_video_single_chunk(self):
        chunks = coverage.plan_chunks(300)
        assert len(chunks) == 1
        assert chunks[0] == {"index": 0, "start": 0.0, "end": 300.0}

    def test_one_hour_gets_six_chunks(self):
        chunks = coverage.plan_chunks(3600, chunk_seconds=600)
        assert len(chunks) == 6
        assert chunks[0]["start"] == 0.0
        assert chunks[-1]["end"] == 3600.0
        # contiguous, no gaps between chunks
        for a, b in zip(chunks, chunks[1:]):
            assert a["end"] == b["start"]
        # indices ordered
        assert [c["index"] for c in chunks] == list(range(len(chunks)))

    def test_uneven_tail_included(self):
        chunks = coverage.plan_chunks(1300, chunk_seconds=600)
        assert len(chunks) == 3
        assert chunks[-1]["end"] == 1300.0
        assert chunks[-1]["end"] - chunks[-1]["start"] == 100.0

    def test_zero_duration_raises(self):
        try:
            coverage.plan_chunks(0)
            raised = False
        except ValueError:
            raised = True
        assert raised


class TestCoverageAudit:
    DUR = 100.0

    def test_full_coverage_passes(self):
        frames = [float(i) for i in range(0, 100)]
        transcript = [{"start": 0, "end": 100, "text": "all spoken"}]
        gaps = coverage.audit_coverage(self.DUR, frames, transcript)
        assert gaps == []

    def test_silent_unfilmed_gap_flagged(self):
        frames = [0.0, 10.0]
        transcript = [{"start": 0, "end": 40, "text": "talk"}]
        gaps = coverage.audit_coverage(self.DUR, frames, transcript,
                                       gap_tolerance=5.0)
        # 40 -> 100 has neither frames nor transcript
        assert any(g["start"] <= 41 and g["end"] >= 99 for g in gaps)

    def test_frame_alone_covers(self):
        # dense frames but zero transcript: still covered visually
        frames = [float(i) for i in range(0, 100)]
        gaps = coverage.audit_coverage(self.DUR, frames, [])
        assert gaps == []

    def test_transcript_alone_covers(self):
        # no frames at all but continuous speech: covered audibly
        transcript = [{"start": 0, "end": 100, "text": "talking head"}]
        gaps = coverage.audit_coverage(self.DUR, [], transcript)
        assert gaps == []

    def test_small_holes_within_tolerance_ignored(self):
        frames = [0.0, 50.0, 100.0]
        transcript = [{"start": 0, "end": 100, "text": "x"}]
        gaps = coverage.audit_coverage(self.DUR, frames, transcript,
                                       gap_tolerance=10.0)
        assert gaps == []


class TestEscalation:
    def test_gaps_become_exhaust_windows(self):
        gaps = [{"start": 40.0, "end": 70.0}, {"start": 90.0, "end": 100.0}]
        windows = coverage.exhaust_windows(gaps, min_length=10.0)
        assert windows == [(40.0, 70.0), (90.0, 100.0)]

    def test_tiny_gaps_skipped(self):
        gaps = [{"start": 40.0, "end": 42.0}, {"start": 90.0, "end": 100.0}]
        windows = coverage.exhaust_windows(gaps, min_length=5.0)
        assert windows == [(90.0, 100.0)]

    def test_window_caps_enforced(self):
        gaps = [{"start": 0.0, "end": 2000.0}]
        windows = coverage.exhaust_windows(gaps, min_length=10.0, max_length=600.0)
        # long gap splits into capped sub-windows, contiguous
        assert windows[0][0] == 0.0
        assert windows[-1][1] == 2000.0
        for a, b in zip(windows, windows[1:]):
            assert a[1] == b[0]


class TestFrameTimestamps:
    def test_parse_from_watch_output_paths(self):
        paths = [
            "/tmp/frames/frame_t00m12s.jpg",
            "/tmp/frames/frame_t01m02s.jpg",
            "not-a-frame.png",
        ]
        ts = coverage.frame_timestamps(paths)
        assert 12.0 in ts and 62.0 in ts
