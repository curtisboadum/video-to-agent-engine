#!/usr/bin/env python3
"""Reader B: independent second opinion via Gemini's native video reading.

Gemini fetches the YouTube URL on Google's side -- its own frames, its own
audio. It never sees the frames the local pipeline picked, which is exactly
what makes its failures independent of /watch's failures.

Free tier by design: flash-model chain (falls forward on 429/404),
--samples 2 so a claim appearing in BOTH samples is evidence and a claim in
one is the model guessing.

usage:
    gemini_review.py <youtube-url-or-file> [--focus "..."] [--samples 2]
                     [--fps 1] [--start 0] [--end 600] [--out notes/gemini-pass.md]

Key: $GEMINI_API_KEY or ~/.config/watch/.env
"""
import argparse
import os
import re
import sys
import time

WATCH_ENV_PATH = os.path.expanduser("~/.config/watch/.env")

MODEL_CHAIN = [
    "gemini-flash-latest",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
]

# per-model retry before falling to the next link in the chain
MODEL_RETRIES = 2
RETRY_BACKOFF_SECONDS = 8

SPEC_PROMPT = """You are writing a build spec for a coding agent that will reproduce what this tutorial teaches. The agent cannot watch video. Your text is the only thing it will have.

Focus: {focus}

Report exactly this, in this order:

1. WHAT IS BEING BUILT. One paragraph. The actual outcome, not the pitch.

2. STACK AND PREREQUISITES. Every tool, package, model, service and account that appears on screen or is named out loud. Give exact names and versions when they are visible. Mark anything that costs money.

3. COMMANDS AND CONFIG, VERBATIM. Every command typed into a terminal, every file path, every env var, every config value you can actually read on screen. Quote it exactly. If a value is blurred, truncated or scrolled past, write UNREADABLE rather than guessing it.

4. THE BUILD ORDER. The steps in the order they were performed, including any step that was undone or redone. Say plainly where the video skips ahead or cuts to a finished state.

5. GOTCHAS. Every error hit on screen, every warning given out loud, every "make sure you" aside. These are the highest value part of the spec.

6. WHAT THE VIDEO DOES NOT SHOW. The gaps a builder would fall into: setup done off camera, values pasted from somewhere unexplained, steps asserted but never demonstrated.

Rules:
- Describe only what is in THIS video. If something you would expect from a tutorial of this kind is absent, say it is absent. Do not fill it in from general knowledge.
- Prefer the exact string on screen over a paraphrase of it.
- Timestamps are your weakest output. Give them as rough markers only and never as a measurement."""


def resolve_key(cli_key, env_path=WATCH_ENV_PATH):
    key = cli_key or os.environ.get("GEMINI_API_KEY")
    if not key and os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                m = re.match(r"\s*GEMINI_API_KEY\s*=\s*(\S+)", line)
                if m:
                    key = m.group(1)
                    break
    if not key:
        sys.exit("[gemini-review] no Gemini key. Set GEMINI_API_KEY "
                 "(free: https://aistudio.google.com/apikey)")
    return key


class GeminiUnavailable(Exception):
    """Quota/model-availability error; the chain should fall forward."""


def make_video_part(source, client=None):
    """Return (part_dict, uploaded_bool). URLs stream; files upload first."""
    if source.startswith("http"):
        return {"file_uri": source}, False
    if client is None:
        try:
            from google import genai
        except ImportError:
            sys.exit("[gemini-review] local file needs google-genai: pip install google-genai")
        client = genai.Client(api_key=resolve_key(None))
    f = client.files.upload(file=source)
    deadline = time.time() + 300
    while getattr(f.state, "name", "ACTIVE") == "PROCESSING" and time.time() < deadline:
        time.sleep(3)
        f = client.files.get(name=f.name)
    return {"file_uri": f.uri, "mime_type": f.mime_type}, True


def generate_with_chain(source, prompt, generate=None, chain=None,
                        fps=1, start=0, end=600, client=None):
    """Try each model in the chain until one answers."""
    generate = generate or _default_generate
    chain = chain or MODEL_CHAIN
    part, _uploaded = make_video_part(source, client=client)
    part["_fps"] = fps
    part["_start"] = start
    part["_end"] = end
    last_err = None
    for model in chain:
        for attempt in range(MODEL_RETRIES + 1):
            try:
                return generate(model, part, prompt)
            except GeminiUnavailable as e:
                last_err = e
                if attempt < MODEL_RETRIES:
                    print("[gemini-review] %s unavailable (%s), retrying in %ds"
                          % (model, e, RETRY_BACKOFF_SECONDS), file=sys.stderr)
                    time.sleep(RETRY_BACKOFF_SECONDS)
                    continue
                print("[gemini-review] %s unavailable (%s), trying next"
                      % (model, e), file=sys.stderr)
                break
            except SystemExit:
                raise
    raise GeminiUnavailable("all models unavailable: %s" % last_err)


def _default_generate(model, part, prompt):
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        sys.exit("[gemini-review] pip install google-genai")
    client = genai.Client(api_key=resolve_key(None))
    meta = types.VideoMetadata(
        fps=int(part.get("_fps", 1)),
        start_offset="%ds" % int(part.get("_start", 0)),
        end_offset="%ds" % int(part.get("_end", 600)),
    )
    contents = types.Content(parts=[
        types.Part(file_data=types.FileData(file_uri=part["file_uri"],
                                            mime_type=part.get("mime_type")),
                   video_metadata=meta),
        types.Part(text=prompt),
    ])
    try:
        r = client.models.generate_content(model=model, contents=contents)
    except Exception as e:
        msg = str(e)
        # quota, model-gone, and transient server errors all fall forward
        if any(s in msg for s in ("429", "404", "RESOURCE_EXHAUSTED",
                                  "503", "500", "UNAVAILABLE")):
            raise GeminiUnavailable(msg[:120])
        raise
    u = r.usage_metadata
    print("[gemini-review] %s (%s+%s+%s tok)"
          % (model, getattr(u, "prompt_token_count", "?"),
             getattr(u, "thoughts_token_count", 0) or 0,
             getattr(u, "candidates_token_count", "?")), file=sys.stderr)
    return {"model": model, "text": r.text, "ok": True}


def collect_samples(source, focus, samples=2, generate=None,
                    fps=1, start=0, end=600, client=None):
    """N samples through the model chain: agreement across samples = evidence."""
    prompt = build_prompt(focus)
    outs = []
    for i in range(samples):
        try:
            r = generate_with_chain(source, prompt, generate=generate,
                                    fps=fps, start=start, end=end, client=client)
            outs.append(r)
        except GeminiUnavailable as e:
            print("[gemini-review] sample %d failed: %s" % (i + 1, e),
                  file=sys.stderr)
            break
        time.sleep(2)
    if not outs:
        sys.exit("[gemini-review] no samples succeeded (quota likely spent). "
                 "Run Reader A alone and mark spec SINGLE SOURCE.")
    print("\n===== HOW TO READ THESE =====")
    print("Keep: claims appearing in BOTH samples.")
    print("Flag: anything in only one sample -- that is where it guesses.")
    return outs


def build_prompt(focus="the whole build, start to finish"):
    return SPEC_PROMPT.format(focus=focus)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", help="YouTube URL or local video file")
    ap.add_argument("--focus", default="the whole build, start to finish")
    ap.add_argument("--samples", type=int, default=2)
    ap.add_argument("--fps", type=int, default=1)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=600)
    ap.add_argument("--key", default=None)
    ap.add_argument("--out", default=None, help="write result to file")
    args = ap.parse_args(argv)

    resolve_key(args.key)

    results = collect_samples(args.source, args.focus, samples=args.samples,
                              fps=args.fps, start=args.start, end=args.end)
    text = "\n\n".join("===== SAMPLE %d/%d (%s) =====\n%s"
                       % (i + 1, len(results), r["model"], r["text"])
                       for i, r in enumerate(results))
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as f:
            f.write(text)
        print("[gemini-review] wrote %s" % args.out)
    else:
        print(text)


if __name__ == "__main__":
    main()
