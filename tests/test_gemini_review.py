"""Tests for gemini_review.py — the independent second reader.

Gemini reads the YouTube URL natively on Google's side; it never sees the
frames our local pipeline picked. Model chain falls forward through flash
models on 429/404/RESOURCE_EXHAUSTED.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "video-to-agent" / "scripts"))

import gemini_review as gr


class TestKeyResolution:
    def test_env_key(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "env-key")
        assert gr.resolve_key(None) == "env-key"

    def test_watch_env_file_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        env = tmp_path / ".env"
        env.write_text("# comment\nGEMINI_API_KEY=file-key\n")
        assert gr.resolve_key(None, env_path=str(env)) == "file-key"

    def test_missing_key_exits(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        try:
            gr.resolve_key(None, env_path=str(tmp_path / "nope"))
            raised = False
        except SystemExit:
            raised = True
        assert raised


class TestModelChain:
    def test_first_model_wins(self):
        calls = []

        def fake_generate(model, part, prompt):
            calls.append(model)
            return {"model": model, "text": "spec", "ok": True}

        result = gr.generate_with_chain("http://youtu.be/x", "p",
                                        generate=fake_generate,
                                        chain=["m1", "m2"])
        assert calls == ["m1"]
        assert result["text"] == "spec"

    def test_falls_forward_on_429(self, monkeypatch):
        monkeypatch.setattr(gr.time, "sleep", lambda s: None)
        calls = []

        def fake_generate(model, part, prompt):
            calls.append(model)
            if model == "m1":
                raise gr.GeminiUnavailable("429 RESOURCE_EXHAUSTED")
            return {"model": model, "text": "spec", "ok": True}

        result = gr.generate_with_chain("https://youtu.be/x", "p",
                                        generate=fake_generate,
                                        chain=["m1", "m2"])
        # m1 retried MODEL_RETRIES+1 times, then m2 answered
        assert calls == ["m1"] * (gr.MODEL_RETRIES + 1) + ["m2"]
        assert result["text"] == "spec"

    def test_all_fail_raises_unavailable(self, monkeypatch):
        monkeypatch.setattr(gr.time, "sleep", lambda s: None)
        def fake_generate(model, part, prompt):
            raise gr.GeminiUnavailable("429")
        try:
            gr.generate_with_chain("https://youtu.be/x", "p",
                                   generate=fake_generate,
                                   chain=["m1", "m2"])
            raised = False
        except gr.GeminiUnavailable:
            raised = True
        assert raised

    def test_hard_errors_propagate(self):
        # a non-quota error is a bug, not a fallback condition
        def fake_generate(model, part, prompt):
            raise ValueError("bad request shape")
        try:
            gr.generate_with_chain("https://youtu.be/x", "p", generate=fake_generate, chain=["m1"])
            raised = False
        except ValueError:
            raised = True
        except gr.GeminiUnavailable:
            raised = False
        assert raised


class TestSamples:
    def test_two_samples_collected(self):
        n = []

        def fake_generate(model, part, prompt):
            n.append(1)
            return {"model": model, "text": "s%d" % len(n), "ok": True}

        outs = gr.collect_samples("https://youtu.be/x", "focus", samples=2,
                                  generate=lambda m, p, pr: fake_generate(m, p, pr))
        assert [o["text"] for o in outs] == ["s1", "s2"]


class TestPromptContract:
    def test_six_sections_present(self):
        text = gr.SPEC_PROMPT
        for section in ["WHAT IS BEING BUILT", "STACK AND PREREQUISITES",
                        "COMMANDS AND CONFIG", "BUILD ORDER", "GOTCHAS",
                        "DOES NOT SHOW"]:
            assert section in text

    def test_focus_interpolated(self):
        prompt = gr.build_prompt("only the auth section")
        assert "only the auth section" in prompt

    def test_unreadable_rule_present(self):
        assert "UNREADABLE" in gr.build_prompt("all")


class TestVideoPartRouting:
    def test_url_not_uploaded(self):
        part, uploaded = gr.make_video_part("https://youtube.com/v=1", client=None)
        assert uploaded is False
        assert part["file_uri"].startswith("https://")

    def test_local_file_upload_flow(self):
        class FakeFile(object):
            name = "f1"
            uri = "https://files.google.com/f1"
            mime_type = "video/mp4"
            state = type("S", (), {"name": "ACTIVE"})()

        class FakeFiles(object):
            def upload(self, file):
                return FakeFile()
            def get(self, name):
                return FakeFile()

        class FakeClient(object):
            files = FakeFiles()

        part, uploaded = gr.make_video_part("/tmp/video.mp4", client=FakeClient())
        assert uploaded is True
        assert part["file_uri"] == "https://files.google.com/f1"
