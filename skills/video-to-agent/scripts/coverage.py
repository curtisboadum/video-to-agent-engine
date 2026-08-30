#!/usr/bin/env python3
"""Chunk planning + the no-blind-spots coverage audit.

Long videos are planned into ~10-minute chunks so per-second frame density
never degrades with length: a 1-hour video is six chunks, each processed by
its own subagent with a full frame budget.

The audit invariant: every second of the video must be covered by frame
evidence OR transcript evidence (within a tolerance), otherwise the gap is
returned and escalates to a targeted 1 fps exhaust re-scan before any spec
is finalized.

usage:
    coverage.py plan <video-or-url> [--chunk-seconds 600]
    coverage.py audit --duration S --frames t1,t2,... --transcript segments.json
"""
import argparse
import json
import os
import re
import subprocess
import sys


def _ffprobe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise ValueError(out.stderr.strip())
    return out.stdout.strip()


def probe_duration(path):
    """Duration in seconds via ffprobe. SystemExit on failure."""
    try:
        return float(_ffprobe(path))
    except (ValueError, OSError) as e:
        sys.exit("[coverage] cannot probe duration of %s: %s" % (path, e))


def plan_chunks(duration, chunk_seconds=600):
    """Contiguous chunk plan covering [0, duration] exactly."""
    if duration <= 0:
        raise ValueError("duration must be positive")
    chunks = []
    start = 0.0
    idx = 0
    while start < duration - 1e-9:
        end = min(start + float(chunk_seconds), duration)
        chunks.append({"index": idx, "start": round(start, 3),
                       "end": round(end, 3)})
        start = end
        idx += 1
    return chunks


def _merge_intervals(intervals):
    if not intervals:
        return []
    intervals = sorted((float(a), float(b)) for a, b in intervals)
    merged = [list(intervals[0])]
    for a, b in intervals[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def audit_coverage(duration, frame_times, transcript_segments,
                   gap_tolerance=5.0):
    """Return uncovered ranges [{start,end}] longer than gap_tolerance.

    A second is covered when it falls inside some transcript segment or
    within half the tolerance of an extracted frame timestamp.
    """
    covered = []
    for t in frame_times:
        covered.append((float(t) - gap_tolerance / 2.0,
                        float(t) + gap_tolerance / 2.0))
    for seg in transcript_segments:
        covered.append((float(seg["start"]), float(seg["end"])))

    covered = _merge_intervals([(a, b) for a, b in covered if b > a])

    gaps = []
    cursor = 0.0
    for a, b in covered:
        if a > cursor:
            gaps.append([cursor, min(a, duration)])
        cursor = max(cursor, b)
        if cursor >= duration:
            break
    if cursor < duration:
        gaps.append([cursor, duration])

    return [{"start": round(g[0], 3), "end": round(g[1], 3)}
            for g in gaps if g[1] - g[0] > gap_tolerance]


def exhaust_windows(gaps, min_length=10.0, max_length=600.0):
    """Convert audit gaps into targeted 1 fps exhaust re-scan windows."""
    windows = []
    for g in gaps:
        length = g["end"] - g["start"]
        if length < min_length:
            continue
        start = g["start"]
        while start < g["end"] - 1e-9:
            end = min(start + max_length, g["end"])
            windows.append((round(start, 3), round(end, 3)))
            start = end
    return windows


_FRAME_TS_RE = re.compile(r"_t(?:(\d+)h)?(?:m(\d+)s|(\d+)m(\d+)s)?\.jpg$")


def frame_timestamps(paths):
    """Extract seconds from /watch frame filenames like frame_t00m12s.jpg."""
    ts = set()
    for p in paths or []:
        m = re.search(r"_t(\d+)h(\d+)m(\d+)s", p)
        if m:
            ts.add(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)))
            continue
        m = re.search(r"_t(\d+)m(\d+)s", p)
        if m:
            ts.add(int(m.group(1)) * 60 + int(m.group(2)))
            continue
        m = re.search(r"_t(\d+)s", p)
        if m:
            ts.add(int(m.group(1)))
    return sorted(float(t) for t in ts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")

    p_plan = sub.add_parser("plan", help="chunk plan for a video")
    p_plan.add_argument("source")
    p_plan.add_argument("--chunk-seconds", type=int, default=600)

    p_audit = sub.add_parser("audit", help="coverage audit")
    p_audit.add_argument("--duration", type=float, required=True)
    p_audit.add_argument("--frames", help="comma-separated frame timestamps (s)")
    p_audit.add_argument("--transcript", help="JSON file of {start,end,text} segments")

    args = ap.parse_args(argv)
    if args.cmd == "plan":
        dur = probe_duration(args.source)
        print(json.dumps(plan_chunks(dur, args.chunk_seconds), indent=2))
    elif args.cmd == "audit":
        frames = [float(x) for x in args.frames.split(",")] if args.frames else []
        segs = []
        if args.transcript:
            with open(args.transcript) as f:
                segs = json.load(f)
        gaps = audit_coverage(args.duration, frames, segs)
        windows = exhaust_windows(gaps)
        print(json.dumps({"gaps": gaps,
                          "exhaust_windows": [{"start": w[0], "end": w[1]}
                                              for w in windows]}, indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
