# video-to-agent-engine

Turn any video into a tested, installed, QA'd skill. Two independent readers
watch the same video, an LLM council cross-examines the readings, one labeled
spec emerges, and the skill gets built under TDD and gated by adversarial QA.

## Default working method (non-negotiable)

Every task in this repo is executed the same way:

1. **TDD first.** Write the failing test before the implementation. Red,
   green, refactor. No exceptions for "simple" code.
2. **Agent teams.** Stages of the pipeline are dispatched to subagents with
   their own context windows. Long videos are chunked so per-second density
   never degrades with length.
3. **LLM council QA.** Finished work is reviewed by the council
   (`skills/video-to-agent/scripts/council.py`). Free OpenRouter models only.
4. **Watchdog review.** Before declaring a stage done, re-read the stage's
   acceptance criteria and verify each one against the actual artifact. A
   stage with unmet criteria is not done.
5. **Free models only.** `scripts/free_models.py` hard-fails any model whose
   pricing is not exactly $0 on both prompt and completion. The $20 OpenRouter
   credit is preserved by design; do not bypass this guard.
6. **Provenance ships.** Every generated skill carries its own SPEC.md and
   notes/ folder. Skills without provenance are summaries wearing clothes.

## Layout

```
skills/video-to-agent/
    SKILL.md          # orchestrator contract — source of truth
    scripts/          # council.py, gemini_review.py, coverage.py,
                      # whisper_local.py, free_models.py, qa_council.py
tests/                # pytest suite; ffmpeg-synthesized fixtures, no network
```

## Commands

```bash
python3 -m pytest -q                 # run the test suite
python3 skills/video-to-agent/scripts/free_models.py --list   # audit free models
```

## Hard rules

- Python 3.9 compatibility (the system interpreter). No 3.10+ syntax.
- Never commit keys. GEMINI_API_KEY lives in ~/.zshrc and ~/.config/watch/.env.
- Timestamps produced by vision models are reconstructions, not measurements.
  The reconciler deletes them; exact on-screen strings always win.
- SINGLE SOURCE claims fail loudly rather than assume. OPEN QUESTIONS get
  asked, never guessed.
