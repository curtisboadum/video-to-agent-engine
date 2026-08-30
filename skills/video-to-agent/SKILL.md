---
name: video-to-agent
description: Turn any video (YouTube URL or local file) into a tested, QA'd, installed skill. Two independent readers watch the video (/watch local frames+transcript, Gemini native URL read), an LLM council of free models with distinct personalities cross-examines both readings into one labeled SPEC.md, a coverage audit guarantees no blind spots, then the target skill is built under TDD and gated by adversarial QA before install. Use when the user pastes a video link and says "build this", "turn this into a skill", "learn from this video", "make an agent out of this", or wants style/retention analysis of a video.
license: MIT
---

# video-to-agent

Two independent readers watch the same video. They are wrong in different
ways. The disagreement is exactly what gets checked. What ships is a skill
with its own provenance attached.

## Inputs

- `VIDEO` — YouTube URL (yt-dlp-supported hosts work: TikTok, Vimeo, Loom...)
  or a local file path.
- `GOAL` (ask if missing) — reusable workflow skill? knowledge capture?
  style clone? All three is valid.

## Stage 0 — Scope before spending anything

1. Probe duration:
   ```bash
   python3 "$SKILL_DIR/scripts/coverage.py" plan "$VIDEO"
   ```
   (`$SKILL_DIR` = this skill's folder; scripts live in `scripts/`)
2. Plan chunks: videos over 20 minutes are processed as ~10-minute chunks.
   NEVER scan a long video in one pass — density degrades and you create
   blind spots. One chunk per parallel subagent.
3. Ask the user for GOAL if not stated. Confirm scope window if they only
   care about part of the video.

## Stage 1 — Reader A (local, private)

Run the claude-video `/watch` skill per chunk:

```bash
/watch "$URL" --start <chunk.start> --end <chunk.end> --detail balanced --no-whisper
```

- Talking-head content: `--detail transcript`. Terminal/code on screen:
  add `--resolution 1024`.
- If no caption track exists, transcribe locally:
  ```bash
  python3 "$SKILL_DIR/scripts/whisper_local.py" <audio> --out notes/chunk-N-transcript.json
  ```
  Never use paid Whisper APIs.
- Write each chunk's six-section reading to `notes/claude-pass-chunk-N.md`
  BEFORE looking at Reader B's output. Anchoring kills independence.

The six sections: WHAT IS BEING BUILT / STACK AND PREREQUISITES / COMMANDS
AND CONFIG VERBATIM / BUILD ORDER / GOTCHAS / WHAT THE VIDEO DOES NOT SHOW.
Write UNREADABLE rather than guess. Cite frame timestamps for section 3.

## Stage 2 — Reader B (Gemini native, independent witness)

```bash
python3 "$SKILL_DIR/scripts/gemini_review.py" "$URL" \
  --start <chunk.start> --end <chunk.end> --samples 2 \
  --focus "$GOAL" --out notes/gemini-pass-chunk-N.md
```

Gemini reads Google-side with its own frames/audio — it never sees Reader A's
frames. Two samples: a claim in BOTH samples is evidence; a claim in one is
the model guessing.

If Gemini quota is spent: proceed with Reader A alone, mark the whole
spec SINGLE SOURCE, say so to the user.

## Stage 3 — LLM Council cross-examination

```bash
python3 "$SKILL_DIR/scripts/council.py" \
  --file notes/claude-pass-chunk-N.md "Reconcile this video reading against the goal: $GOAL"
```

Four free-model personas (skeptic/engineer/teacher/reader) answer
independently, rank each other anonymized, GLM-5.2 chairmans the synthesis.
Every model passes the free-pricing guard — paid credits are never spent,
by construction.

## Stage 4 — Reconcile into SPEC.md

Merge all readings into ONE `SPEC.md` where every line carries a label:

- **CONFIRMED** — two+ independent readings agree. Build on it.
- **SINGLE SOURCE** — one reading only. Keep it, label it, name the source.
- **CONFLICT** — do not average. List both versions, go back to the specific
  frames yourself, record what you saw.

Rules: delete every timestamp/duration/count (vision models have no clock);
keep exact strings literal; flag the archetype trap (a step that reads like
generic documentation came from training data, not this video); end with an
OPEN QUESTIONS list — it is the most valuable artifact in the system.

## Stage 5 — Coverage audit (the no-blind-spots gate)

```bash
python3 "$SKILL_DIR/scripts/coverage.py" audit \
  --duration <seconds> \
  --frames "<comma-separated extracted-frame timestamps>" \
  --transcript notes/transcript-segments.json
```

Any returned gap escalates to a targeted 1 fps exhaust re-scan via focused
`--start/--end` `/watch` runs until the audit returns zero gaps longer than
5 seconds. A spec written over unwatched footage is void.

## Stage 6 — Style & retention analyst (when GOAL includes style)

From the merged timeline produce `notes/style-analysis.md`:

- Retention-curve hypothesis: where curiosity spikes/drops and WHY
  (hook structure, open loops, payoff timing) with timestamps.
- Visual grammar: pacing, transitions, motion-graphic patterns, color/type.
- Testable principles extracted from each pattern (one falsifiable claim
  per pattern).
Format output so downstream filmmaking skills (motion-builder,
editorial-collage, shot-builder) can consume it directly.

## Stage 7 — Skill forge (TDD)

Build the target skill from SPEC.md:

1. Write failing tests first (or a check.sh that fails) for every CONFIRMED
   behavior.
2. SINGLE SOURCE lines fail loudly at runtime rather than assume.
3. OPEN QUESTIONS: ask the user. Never silently guess.
4. Ship `SPEC.md` + `notes/` INSIDE the new skill — provenance travels with it.

## Stage 8 — QA gate

```bash
python3 "$SKILL_DIR/scripts/qa_council.py" --spec SPEC.md --artifact <new-skill-dir>
```

Adversarial reviewers score spec_compliance / completeness / correctness /
runnability / provenance. REJECT on critical issues, REVISE below threshold.
Loop revise->re-run up to 3 times, then escalate to the user with the diff.

## Stage 9 — Run once, then install

Run the new skill once on a real input. Fix what breaks. Then symlink into
every harness skills dir (~/.config/opencode/skills, ~/.claude/skills,
~/.codex/skills). Report PASS + artifacts list to the user.

## Failure modes

- No captions: Whisper-local covers audio; say so in the spec.
- Gemini 429s everywhere: Reader A alone; whole spec marked SINGLE SOURCE.
- Readers disagree about everything: window too wide — narrow and rerun.
- yt-dlp cannot reach the video (private/auth): tell the user; no fallback.
