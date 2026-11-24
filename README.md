# Video to Agent Engine

Turn a video you have permission to use into a reviewable, testable procedure for an agent. The workflow compares readings, records what supports each claim, and carries the evidence and open questions into the proposed skill.

## Try the coverage check

Start with synthetic timestamps; no video, model account, API key, or network access is needed to run the check once the repo is local.

```sh
python3 skills/video-to-agent/scripts/coverage.py audit \
  --duration 24 --frames '0,1,2,21,22,23'
```

The result reports an uncovered window from **4.5 to 18.5 seconds** and recommends that range for a targeted re-scan. A coverage check identifies missing evidence; it does not establish that an interpretation is correct.

## From video to proposed skill

1. **Gather evidence.** Split long videos into chunks and collect transcript and frame notes. A separate provider-assisted reader can provide an independent interpretation if configured.
2. **Reconcile the readings.** Write a `SPEC.md` that distinguishes corroborated claims, single-source claims, and conflicts that need review. Keep unresolved questions visible.
3. **Build and review.** Turn supported claims into checks for the proposed skill. Keep the spec and evidence notes with the result, and review both before installing anything.

See the [skill guide](skills/video-to-agent/SKILL.md) for orchestration and prerequisites and the [command definition](commands/video-to-agent.md) for inputs. The full workflow uses FFmpeg/ffprobe and yt-dlp where applicable, plus the dependencies for any readers and review stages you enable. Inspect provider data-handling and costs before enabling remote processing, and use only sources you are authorised to share. Accuracy depends on source quality and the available readers.

## Run the tests

```sh
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install pytest
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -k 'not test_build_reviewers_uses_free_models_only'
```

The separate reviewer-selection integration test checks the OpenRouter model catalogue. The full suite can fail when a configured free model is missing from the catalogue. The local test command above excludes that check; the runtime still rejects unverified models.

The [test suite](tests/) covers chunk planning and coverage checks, reader parsing, review helpers, and local transcription handling. It does not validate every video or guarantee the generated skill will work without human review.

[MIT license](LICENSE)
