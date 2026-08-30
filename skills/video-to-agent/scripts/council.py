#!/usr/bin/env python3
"""3-stage LLM council, Karpathy-style, free models only.

Stage 1: each council model answers the query independently (with its own
         personality).
Stage 2: each council model ranks the OTHERS' responses, anonymized as
         "Response A/B/C" so nobody plays favorites.
Stage 3: the chairman synthesizes a final answer from all opinions and
         aggregate peer rankings.

Every model is passed through free_models.assert_free() before use. Paid
credits are never spent -- fail closed.

usage:
    council.py "question or artifact to review"
    council.py --file notes/claude-pass.md "review this spec"

Backends: default runner shells out to `opencode run` (uses opencode's
existing OpenRouter auth). Override with VTA_RUNNER for tests.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import free_models


class Persona(object):
    def __init__(self, name, model, style):
        self.name = name
        self.model = model
        self.style = style


# 4 voting personas + chairman. All :free. Distinct personalities on purpose:
# they are wrong in different ways, and the disagreement is the signal.
COUNCIL = [
    Persona("skeptic",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "You are a ruthless skeptic. Assume every claim is wrong until "
            "evidence in the material supports it. Attack weak reasoning, "
            "name exactly what is unverified, and refuse flattery."),
    Persona("engineer",
            "poolside/laguna-s-2.1:free",
            "You are a senior software engineer. Judge everything by whether "
            "it can be built and will run. Demand exact commands, versions, "
            "and failure modes. Flag anything that would break at runtime."),
    Persona("teacher",
            "thinkingmachines/inkling:free",
            "You are a patient teacher. Check that the material is complete, "
            "correctly ordered, and learnable. Find the gaps a beginner would "
            "fall into and the steps assumed but never explained."),
    Persona("reader",
            "nvidia/nemotron-3.5-lightning:free",
            "You are a meticulous long-document reader. Track internal "
            "consistency end to end. Catch contradictions between sections, "
            "duplicated content, and claims that quietly change meaning."),
]

CHAIRMAN = Persona("chairman", "z-ai/glm-5.2:free",
                   "You are the council chairman. Synthesize honestly.")


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENCODE_AUTH = os.path.expanduser("~/.local/share/opencode/auth.json")


def _openrouter_key():
    """Locate an OpenRouter key without printing it: env, then opencode auth."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    try:
        with open(OPENCODE_AUTH) as f:
            d = json.load(f)
        return (d.get("openrouter") or {}).get("key")
    except (OSError, ValueError):
        return None


def http_runner(model_id, prompt, timeout=600):
    """Direct OpenRouter chat completion. Returns text or None on failure."""
    key = _openrouter_key()
    if not key:
        print("[council] no OpenRouter key found", file=sys.stderr)
        return None
    body = json.dumps({
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        OPENROUTER_URL, data=body, method="POST",
        headers={"Authorization": "Bearer %s" % key,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        choices = payload.get("choices") or []
        if not choices:
            return None
        return (choices[0].get("message") or {}).get("content")
    except Exception as e:
        print("[council] %s failed: %s" % (model_id, str(e)[:120]),
              file=sys.stderr)
        return None


def opencode_runner(model_id, prompt, timeout=600):
    """Fallback backend: `opencode run` with the openrouter provider."""
    cmd = ["opencode", "run", "--model", "openrouter/%s" % model_id, prompt]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if out.returncode != 0:
            return None
        return out.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def resilient_runner(model_id, prompt):
    """Try direct OpenRouter first; fall back to the opencode CLI."""
    out = http_runner(model_id, prompt)
    if out:
        return out
    return opencode_runner(model_id, prompt)


def query_model(model_id, prompt, runner=None, guard=None):
    runner = runner or resilient_runner
    (guard or free_models.assert_free)(model_id)
    return runner(model_id, prompt)


def anonymize(stage1_results):
    """Map responses to anonymous letter labels; keep de-anon mapping private."""
    labels = {}
    mapping = {}
    for i, r in enumerate(stage1_results):
        label = "Response %s" % chr(65 + i)
        labels[label] = r["response"]
        mapping[label] = r["model"]
    return labels, mapping


def build_first_opinion_prompt(persona, query):
    return (
        "<persona>\n%s\n</persona>\n\n"
        "<task>\nAnswer the following. Be specific and concrete.\n</task>\n\n"
        "%s" % (persona.style, query)
    )


def build_ranking_prompt(query, labels):
    body = "\n\n".join("%s:\n%s" % (label, text) for label, text in sorted(labels.items()))
    return (
        "You are evaluating different responses to the following question:\n\n"
        "%s\n\n%s\n\nYour task:\n"
        "1. Evaluate each response individually: what it does well, what it does poorly.\n"
        "2. At the very end, provide a final ranking.\n\n"
        "IMPORTANT: your final ranking MUST be formatted EXACTLY as follows:\n"
        '- Start with the line "FINAL RANKING:"\n'
        "- Then list responses best to worst, one per line: \"1. Response A\"\n"
        "- No other text after the ranking section.\n\n"
        "Now provide your evaluation and ranking:" % (query, body)
    )


def build_chairman_prompt(persona, query, stage1_results, stage2_results, aggregate):
    s1 = "\n\n".join("Model: %s\nResponse: %s" % (r["model"], r["response"])
                     for r in stage1_results)
    s2 = "\n".join("- %s (avg rank %.2f)" % (a["model"], a["average_rank"])
                   for a in aggregate) or "(no rankings parsed)"
    peers = "\n\n".join("%s ranked: %s" % (r["model"], "; ".join(r.get("parsed_ranking") or []))
                        for r in stage2_results)
    return (
        "<persona>\n%s\n</persona>\n\n"
        "You are the Chairman of an LLM Council. Multiple models answered a "
        "question and then ranked each other's answers anonymously.\n\n"
        "Original question:\n%s\n\n"
        "STAGE 1 - individual responses (de-anonymized):\n%s\n\n"
        "STAGE 2 - aggregate peer rankings (best first):\n%s\n\n"
        "Individual peer ballots:\n%s\n\n"
        "Synthesize a single final answer representing the council's collective "
        "wisdom. Note where the council disagreed and say which position the "
        "evidence supports." % (persona.style, query, s1, s2, peers)
    )


RANKING_RE = re.compile(r"^\s*\d+\.\s*(Response\s+[A-Z])\s*$", re.MULTILINE)


def parse_ranking_from_text(text):
    """Extract the FINAL RANKING list; [] when absent/malformed."""
    if not text or "FINAL RANKING:" not in text:
        return []
    section = text.split("FINAL RANKING:", 1)[1]
    # stop at the first blank-line-separated paragraph after the list items
    items = []
    for line in section.splitlines():
        m = RANKING_RE.match(line)
        if m:
            items.append(m.group(1).replace("  ", " "))
        elif items:
            break
    return items


def calculate_aggregate_rankings(stage2_results, label_to_model):
    positions = defaultdict(list)
    for r in stage2_results:
        for pos, label in enumerate(r.get("parsed_ranking") or [], start=1):
            if label in label_to_model:
                positions[label_to_model[label]].append(pos)
    agg = [
        {"model": model, "average_rank": round(sum(ps) / float(len(ps)), 2),
         "rankings_count": len(ps)}
        for model, ps in positions.items()
    ]
    agg.sort(key=lambda a: a["average_rank"])
    return agg


def _query_all(personas, prompt_builder, runner, guard=None):
    results = []
    for p in personas:
        resp = query_model(p.model, prompt_builder(p), runner=runner, guard=guard)
        results.append({"model": p.model, "persona": p.name,
                        "response": resp or ""})
    return [r for r in results if r["response"]]


def run_full_council(query, runner=None, models=None, chairman=None, guard=None):
    models = models if models is not None else COUNCIL
    chairman = chairman or CHAIRMAN
    guard = guard or free_models.assert_free

    # Stage 1: independent first opinions
    stage1 = _query_all(
        models, lambda p: build_first_opinion_prompt(p, query), runner,
        guard=guard)

    if not stage1:
        return {"stage1": [], "stage2": [], "stage3":
                {"model": chairman.model, "response": "Error: all council models failed."},
                "aggregate_rankings": []}

    # Stage 2: anonymized peer review
    labels, mapping = anonymize(stage1)
    rank_prompt = build_ranking_prompt(query, labels)
    stage2 = []
    for p in models:
        resp = query_model(p.model, rank_prompt, runner=runner, guard=guard)
        if not resp:
            continue
        stage2.append({"model": p.model, "ranking": resp,
                       "parsed_ranking": parse_ranking_from_text(resp)})
    aggregate = calculate_aggregate_rankings(stage2, mapping)

    # Stage 3: chairman synthesis (falls back to top-ranked council model)
    chair_prompt = build_chairman_prompt(chairman, query, stage1, stage2, aggregate)
    chair_resp = query_model(chairman.model, chair_prompt, runner=runner, guard=guard)
    chair_model = chairman.model
    if not chair_resp:
        fallback = aggregate[0]["model"] if aggregate else stage1[0]["model"]
        print("[council] chairman unavailable; falling back to %s" % fallback,
              file=sys.stderr)
        chair_resp = query_model(fallback, chair_prompt, runner=runner, guard=guard) or ""
        chair_model = fallback

    return {
        "stage1": stage1,
        "stage2": [{"model": r["model"], "parsed_ranking": r["parsed_ranking"]}
                   for r in stage2],
        "aggregate_rankings": aggregate,
        "stage3": {"model": chair_model, "response": chair_resp},
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query", nargs="?", help="the question / material to review")
    ap.add_argument("--file", help="read query material from a file")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)

    if args.file:
        with open(args.file) as f:
            material = f.read()
        query = ("%s\n\n<material>\n%s\n</material>" % (args.query or "", material)).strip()
    else:
        query = args.query
    if not query:
        ap.error("provide a query or --file")

    result = run_full_council(query)
    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print("===== AGGREGATE PEER RANKINGS =====")
        for a in result["aggregate_rankings"]:
            print("%d. %-50s avg %.2f (%d ballots)"
                  % (result["aggregate_rankings"].index(a) + 1, a["model"],
                     a["average_rank"], a["rankings_count"]))
        print("\n===== CHAIRMAN SYNTHESIS =====")
        print(result["stage3"]["response"])


if __name__ == "__main__":
    main()
