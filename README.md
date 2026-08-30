# video-to-agent-engine

Send a video. Get back a tested skill that runs what the video taught — plus
the evidence behind every line of it.

Two independent readers watch the same video: `/watch` (frames + timestamped
transcript, fully local) and Gemini (reads the YouTube URL natively on
Google's side). An LLM council of five free models with distinct personalities
cross-examines both readings, one labeled spec emerges
(`CONFIRMED` / `SINGLE SOURCE` / `CONFLICT`), and the target skill is built
under TDD and gated by adversarial QA before install.

## Install

```bash
git clone https://github.com/YOU/video-to-agent-engine.git
ln -s "$(pwd)/video-to-agent-engine/skills/video-to-agent" ~/.config/opencode/skills/video-to-agent
ln -s "$(pwd)/video-to-agent-engine/skills/video-to-agent" ~/.claude/skills/video-to-agent
ln -s "$(pwd)/video-to-agent-engine/skills/video-to-agent" ~/.codex/skills/video-to-agent
```

Prerequisites: `ffmpeg`, `yt-dlp`, `python3`. A free Gemini key in
`~/.config/watch/.env` (`GEMINI_API_KEY=...`) enables the second reader.
OpenRouter auth for the council (free models only — enforced).

## Usage

Paste a video URL and say "turn this into a skill":

```
https://youtube.com/watch?v=... build this into a reusable skill
```

The orchestrator handles everything: scoping, chunking long videos, both
reader passes, council reconciliation, coverage audit, style/retention
analysis, TDD build, QA gate, run-once verification, and provenance shipping.

## Design guarantees

- **No blind spots**: adaptive dense frames + scene-detect densify + full
  local transcript + targeted 1 fps exhaust re-scan of any low-confidence
  segment + coverage audit before spec finalization.
- **Length-proof**: videos are processed in ~10-minute chunks by parallel
  subagents; a 1-hour video gets the same per-second density as a 5-minute one.
- **Zero cost**: every model call is either local, Gemini free tier, or an
  OpenRouter `:free` model. `free_models.py` hard-fails anything paid.
- **No blind trust**: every line of the spec carries its evidence label;
  timestamps from vision models are deleted as fabrications; exact on-screen
  strings always win over paraphrase.

## Testing

```bash
python3 -m pytest -q
```
