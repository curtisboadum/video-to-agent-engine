#!/usr/bin/env python3
"""Adversarial QA gate: the council scores a built artifact against its SPEC.

Multiple free-model reviewers with distinct personalities each return a JSON
verdict: per-axis scores + critical issues. Gate rules:

  REJECT  -- any reviewer reports a critical issue (dangerous/broken)
  REVISE  -- majority of axes below threshold, or any verdict unparseable
             (an unreadable review is a failed review)
  PASS    -- majority of reviewers score every axis >= threshold

usage:
    qa_council.py --spec SPEC.md --artifact path/to/skill [--threshold 7]
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import council
import free_models


AXES = ["spec_compliance", "completeness", "correctness",
        "runnability", "provenance"]

REVIEW_PROMPT = """<persona>
{style}
</persona>

You are an adversarial QA reviewer. Score the ARTIFACT against the SPEC.
Do not be kind. Be accurate.

Score each axis 0-10:
- spec_compliance: does the artifact implement what the spec says? CONFIRMED
  spec lines MUST be implemented. SINGLE SOURCE lines must fail loudly rather
  than guess. OPEN QUESTIONS must NOT be silently guessed.
- completeness: sections, edge cases, failure modes from the spec present?
- correctness: commands, paths and logic actually correct as written?
- runnability: could you run this now and have it work? Dependencies declared?
- provenance: does the artifact carry its SPEC.md and notes/ evidence?

List critical_issues for anything dangerous or fundamentally broken
(e.g., destructive commands, fabricated dependencies, spec-inverting behavior).

Respond with ONLY this JSON (no other text):
{{"scores": {{"spec_compliance": N, "completeness": N, "correctness": N,
"runnability": N, "provenance": N}}, "critical_issues": ["..."], "notes": "..."}}

<SPEC>
{spec}
</SPEC>

<ARTIFACT>
{artifact}
</ARTIFACT>"""


class Reviewer(object):
    def __init__(self, name, model, style):
        self.name = name
        self.model = model
        self.style = style


DEFAULT_REVIEWERS = [
    Reviewer("adversarial-engineer", council.COUNCIL[1].model,
             "You break builds for a living. Assume the artifact fails at "
             "runtime until proven otherwise."),
    Reviewer("skeptical-auditor", council.COUNCIL[0].model,
             "You audit claims against evidence. Anything in the artifact "
             "not traceable to the spec is a finding."),
]


def parse_verdict(text):
    """Extract the JSON verdict; None when unparseable."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(v.get("scores"), dict):
        return None
    v.setdefault("critical_issues", [])
    return v


def run_gate(spec_text, artifact_text, reviewers=None, runner=None,
             guard=None, threshold=7):
    reviewers = reviewers if reviewers is not None else DEFAULT_REVIEWERS
    results = []
    for r in reviewers:
        if callable(r):
            # injected reviewer: fn(spec_text, artifact_text) -> verdict dict
            v = r(spec_text, artifact_text)
            results.append(v if isinstance(v, dict) or v is None else None)
            continue
        prompt = REVIEW_PROMPT.format(style=r.style, spec=spec_text,
                                      artifact=artifact_text[:60000])
        raw = council.query_model(r.model, prompt, runner=runner, guard=guard)
        v = parse_verdict(raw)
        if v is not None:
            v["reviewer"] = r.name
            v["model"] = r.model
        results.append(v)

    valid = [v for v in results if v is not None]
    if not valid:
        return {"verdict": "REVISE",
                "reason": "all reviews unparseable or models unavailable",
                "reviews": results}

    # critical issue from ANY reviewer -> REJECT
    for v in valid:
        for issue in v.get("critical_issues") or []:
            if issue and str(issue).strip().lower() not in ("none", "n/a", ""):
                return {"verdict": "REJECT", "reason": issue,
                        "reviews": results}

    # majority rule on axis thresholds (unscored axes don't count either way)
    n_axes_pass = []
    for v in valid:
        scored = [float(v["scores"][a]) for a in AXES if a in v["scores"]]
        n_axes_pass.append(bool(scored) and min(scored) >= threshold)
    verdict = "PASS" if sum(n_axes_pass) * 2 > len(n_axes_pass) else "REVISE"
    return {"verdict": verdict,
            "reason": "%d/%d reviewers passed all axes at >= %d"
                      % (sum(n_axes_pass), len(valid), threshold),
            "reviews": results}


def build_reviewers():
    """Default reviewers re-resolved live; enforces :free via council guard."""
    out = []
    for r in DEFAULT_REVIEWERS:
        free_models.assert_free(r.model)
        out.append(r)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", required=True)
    ap.add_argument("--artifact", required=True, help="skill dir or file")
    ap.add_argument("--threshold", type=int, default=7)
    args = ap.parse_args(argv)

    with open(args.spec) as f:
        spec = f.read()

    if os.path.isdir(args.artifact):
        chunks = []
        for root, _dirs, files in os.walk(args.artifact):
            for fn in sorted(files):
                p = os.path.join(root, fn)
                if fn.endswith((".md", ".py", ".sh", ".json", ".yaml", ".yml")):
                    with open(p) as f:
                        chunks.append("# file: %s\n%s" % (p, f.read()))
        artifact = "\n\n".join(chunks)
    else:
        with open(args.artifact) as f:
            artifact = f.read()

    build_reviewers()  # hard gate before any call
    result = run_gate(spec, artifact, threshold=args.threshold)

    print(json.dumps(result, indent=2))
    if result["verdict"] != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    main()
