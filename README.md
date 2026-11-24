# Video to Agent Engine

An experimental workflow for turning a video you have permission to use into a written, testable procedure. The aim is to make it clear what came from the video and where a reviewer still needs to make a judgment.

## How it works

1. Read a local transcript and extracted frames. A second, model-assisted read is optional and requires provider credentials.
2. Label claims as corroborated, single-source or conflicting before turning them into a procedure.
3. Draft the skill and run checks before choosing whether to install it.

Coverage and accuracy vary with source quality, model availability and access to the original video. A generated procedure needs human review. Remote processing can have provider costs and data-handling implications; use only sources you are authorised to share.

## Inspect and test

```sh
git clone https://github.com/curtisboadum/video-to-agent-engine.git
cd video-to-agent-engine
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install pytest
python3 -m pytest -q
```

See [the skill guide](skills/video-to-agent/SKILL.md) and [the command](commands/video-to-agent.md) for the orchestration and prerequisites. Inspect the files before adding the skill to your agent configuration. The media path uses tools such as FFmpeg and yt-dlp.

[MIT license](LICENSE)
