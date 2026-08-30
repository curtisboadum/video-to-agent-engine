#!/usr/bin/env python3
"""Free-model guard for the video-to-agent-engine council.

Queries OpenRouter's public models endpoint, filters to models whose pricing
is exactly $0 on BOTH prompt and completion, and hard-fails any model that
cannot be verified free. Fail closed: an unknown model is treated as paid.

The $20 OpenRouter credit is preserved by construction -- paid models never
pass the guard.

usage:
    free_models.py assert <model-id>     # exit 0 if verifiably free, else SystemExit
    free_models.py list                  # print the free roster as JSON
    free_models.py --check               # refresh cache and print count

Cache: ~/.cache/vtae/models-cache.json (1 hour TTL).
"""
import argparse
import json
import os
import sys
import time
try:
    from urllib.request import urlopen
    from urllib.error import URLError
except ImportError:  # pragma: no cover
    from urllib2 import urlopen, URLError

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_DIR = os.path.expanduser("~/.cache/vtae")
CACHE_PATH = os.path.join(CACHE_DIR, "models-cache.json")
CACHE_TTL_SECONDS = 3600


def _fetch_models():
    with urlopen(OPENROUTER_MODELS_URL, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload.get("data", [])


def load_cache(max_age=CACHE_TTL_SECONDS, cache_path=CACHE_PATH):
    """Return cached model list or None if missing/stale."""
    try:
        st = os.stat(cache_path)
        if time.time() - st.st_mtime > max_age:
            return None
        with open(cache_path) as f:
            payload = json.load(f)
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload
    except (OSError, ValueError):
        return None


def refresh_cache(cache_path=CACHE_PATH):
    """Fetch the live model list and write it to cache. Returns the list."""
    data = _fetch_models()
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    tmp = cache_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, cache_path)
    return data


def get_models(force=False, cache_path=CACHE_PATH):
    if not force:
        cached = load_cache(cache_path=cache_path)
        if cached is not None:
            return cached
    return refresh_cache(cache_path=cache_path)


def is_free(pricing):
    """True only when both prompt and completion are exactly zero."""
    if not isinstance(pricing, dict):
        return False
    if "prompt" not in pricing or "completion" not in pricing:
        return False
    try:
        prompt = float(pricing["prompt"])
        completion = float(pricing["completion"])
    except (TypeError, ValueError):
        return False
    return prompt == 0.0 and completion == 0.0


def filter_free(models):
    """Keep only genuinely-free chat models, preserving metadata."""
    out = []
    for m in models:
        if m.get("id") == "openrouter/free":
            # meta-router picks random models; exclude so we control cost exactly
            continue
        if is_free(m.get("pricing")):
            out.append(m)
    return out


def find_model(model_id, cache_path=CACHE_PATH):
    models = get_models(cache_path=cache_path)
    for m in models:
        if m.get("id") == model_id:
            return m
    return None


def assert_free(model_id, cache_path=CACHE_PATH):
    """Hard gate: SystemExit unless model_id is verifiably $0/$0."""
    m = find_model(model_id, cache_path=cache_path)
    if m is None:
        sys.exit(
            "[free-models] FAIL CLOSED: '%s' not found in OpenRouter catalog. "
            "Unknown models are treated as paid." % model_id
        )
    if not is_free(m.get("pricing")):
        p = m.get("pricing", {})
        sys.exit(
            "[free-models] REFUSED: '%s' costs prompt=%s completion=%s. "
            "Paid credits must never be spent by this system."
            % (model_id, p.get("prompt"), p.get("completion"))
        )
    return True


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")

    p_assert = sub.add_parser("assert", help="exit nonzero unless model is free")
    p_assert.add_argument("model_id")

    sub.add_parser("list", help="print free roster as JSON")
    sub.add_parser("check", help="refresh cache, print free-model count")

    if argv and "--check" in argv:
        argv = ["check" if a == "--check" else a for a in argv]
    args = ap.parse_args(argv)

    if args.cmd == "assert":
        assert_free(args.model_id)
        print("[free-models] OK: %s is $0/$0" % args.model_id)
    elif args.cmd == "list":
        print(json.dumps(filter_free(get_models()), indent=2))
    elif args.cmd == "check":
        n = len(filter_free(refresh_cache()))
        print("[free-models] %d free models available" % n)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
