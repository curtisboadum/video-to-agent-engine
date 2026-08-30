#!/usr/bin/env python3
"""Local transcription fallback -- free, offline, nothing uploaded.

Backend preference:
  1. faster-whisper (python, best control)
  2. mlx-whisper via uvx (fastest on Apple Silicon, installs nothing permanent)
  3. whisper CLI (brew install whisper-cpp or pip openai-whisper)

usage:
    whisper_local.py <video-or-audio> [--out segments.json] [--model small]

Output: JSON [{start, end, text}, ...]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

DEFAULT_MODEL = "small"


def build_ffmpeg_cmd(src, dst):
    """Mono 16 kHz WAV: all Whisper backends accept it."""
    return ["ffmpeg", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", dst]


def extract_audio(src, dst=None, tmpdir=None):
    dst = dst or os.path.join(tmpdir or "/tmp",
                              "vtae_%s.wav" % abs(hash(src)) )
    cmd = build_ffmpeg_cmd(src, dst)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if r.returncode != 0 or not os.path.exists(dst):
        sys.exit("[whisper-local] ffmpeg audio extraction failed: %s"
                 % r.stderr[-300:])
    return dst


def detect_backends():
    avail = {"faster_whisper": False, "mlx": False, "cli": False}
    try:
        import faster_whisper  # noqa: F401
        avail["faster_whisper"] = True
    except ImportError:
        pass
    if shutil.which("uvx") and shutil.which("ffmpeg"):
        avail["mlx"] = True
    if shutil.which("whisper"):
        avail["cli"] = True
    return avail


def select_backend(avail):
    for name in ("faster_whisper", "mlx", "cli"):
        if avail.get(name):
            return {"faster_whisper": "faster_whisper",
                    "mlx": "mlx",
                    "cli": "whisper_cli"}[name]
    sys.exit("[whisper-local] no local transcription backend. Install one of:\n"
             "  pip install faster-whisper\n"
             "  brew install whisper-cpp   (provides `whisper`)\n")


# --- backends: each returns [{start,end,text}] -----------------------------

def _via_faster_whisper(audio_path, model_size=DEFAULT_MODEL):
    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segments, _info = model.transcribe(audio_path)
    return normalize_segments([
        {"start": s.start, "end": s.end, "text": s.text}
        for s in segments
    ])


def _via_mlx(audio_path, model_size=DEFAULT_MODEL):
    r = subprocess.run(
        ["uvx", "--from", "mlx-whisper", "mlx_whisper", audio_path,
         "--model", "mlx-community/whisper-large-v3-turbo",
         "--output-dir", "/tmp/vtae-asr", "--output_format", "vtt",
         "--task", "transcribe"],
        capture_output=True, text=True, timeout=7200)
    vtt_path = os.path.join("/tmp/vtae-asr",
                            os.path.splitext(os.path.basename(audio_path))[0] + ".vtt")
    if r.returncode != 0:
        if not os.path.exists(vtt_path):
            raise RuntimeError(r.stderr[-300:])
    with open(vtt_path) as f:
        return parse_vtt(f.read())


def _via_cli(audio_path, model_size=DEFAULT_MODEL):
    outdir = "/tmp/vtae-asr"
    r = subprocess.run(
        ["whisper", audio_path, "--model", model_size, "--output_format", "vtt",
         "--output_dir", outdir],
        capture_output=True, text=True, timeout=7200)
    vtt_path = os.path.join(outdir,
                            os.path.splitext(os.path.basename(audio_path))[0] + ".vtt")
    if not os.path.exists(vtt_path):
        raise RuntimeError((r.stderr or r.stdout)[-300:])
    with open(vtt_path) as f:
        return parse_vtt(f.read())


BACKENDS = {
    "faster_whisper": _via_faster_whisper,
    "mlx": _via_mlx,
    "whisper_cli": _via_cli,
}


# --- shared helpers ---------------------------------------------------------

_VTT_TS = re.compile(r"(\d+):(\d+):([\d.]+)\s*-->\s*(\d+):(\d+):([\d.]+)")


def parse_vtt(text):
    segs = []
    for m in _VTT_TS.finditer(text):
        start = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        end = int(m.group(4)) * 3600 + int(m.group(5)) * 60 + float(m.group(6))
        # text lines follow until blank line
        tail = text[m.end():]
        line = ""
        seen_text = False
        for ln in tail.splitlines():
            if not ln.strip():
                if seen_text:
                    break
                continue
            if "-->" in ln:
                break
            seen_text = True
            line += (" " if line else "") + ln.strip()
        segs.append({"start": start, "end": end, "text": line})
    return normalize_segments(segs)


def normalize_segments(raw):
    out = []
    for s in raw:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        out.append({"start": round(float(s["start"]), 3),
                    "end": round(float(s["end"]), 3),
                    "text": text})
    out.sort(key=lambda x: x["start"])
    return out


def transcribe(source, backend=None, model_size=DEFAULT_MODEL, backends=None,
               skip_extract=False):
    backends = backends or BACKENDS
    if backend is None:
        backend = select_backend(detect_backends())
    if backend == "stub":
        # test hook: caller supplied their own dict
        pass
    fn = backends[backend]
    audio = source if skip_extract or source.lower().endswith(".wav") \
        else extract_audio(source)
    return fn(audio, model_size)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source")
    ap.add_argument("--out", default=None)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args(argv)

    segs = transcribe(args.source, model_size=args.model)
    payload = json.dumps(segs, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(payload)
        print("[whisper-local] %d segments -> %s" % (len(segs), args.out))
    else:
        print(payload)


if __name__ == "__main__":
    main()
