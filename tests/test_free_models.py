"""Tests for free_models.py — the $0-pricing guard.

The guard must hard-fail any model whose OpenRouter pricing is not exactly
zero on both prompt and completion. Curtis's paid credits are never touched.
"""
import json
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "video-to-agent" / "scripts"))

import free_models


SAMPLE_RESPONSE = {
    "data": [
        {
            "id": "z-ai/glm-5.2:free",
            "name": "GLM 5.2 (free)",
            "context_length": 262144,
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": ["tools", "structured_outputs"],
            "description": "reasoning + agentic coding",
        },
        {
            "id": "z-ai/glm-5.2",
            "name": "GLM 5.2",
            "context_length": 131072,
            "pricing": {"prompt": "0.000002", "completion": "0.000008"},
            "supported_parameters": ["tools"],
            "description": "paid tier",
        },
        {
            "id": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "name": "Nemotron Ultra (free)",
            "context_length": 1000000,
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": ["tools", "reasoning_effort"],
            "description": "frontier reasoning MoE",
        },
        {
            "id": "sneaky/freemium",
            "name": "Freemium",
            "context_length": 32000,
            "pricing": {"prompt": "0", "completion": "0.000003"},
            "supported_parameters": [],
            "description": "free in, paid out — must be rejected",
        },
    ]
}


def _write_cache(tmp_path, payload):
    cache = tmp_path / "models-cache.json"
    cache.write_text(json.dumps(payload))
    return str(cache)


class TestIsFree:
    def test_free_when_both_zero(self):
        assert free_models.is_free({"prompt": "0", "completion": "0"}) is True

    def test_paid_completion_rejected(self):
        assert free_models.is_free({"prompt": "0", "completion": "0.000003"}) is False

    def test_paid_prompt_rejected(self):
        assert free_models.is_free({"prompt": "0.5", "completion": "0"}) is False

    def test_float_zero_accepted(self):
        assert free_models.is_free({"prompt": 0, "completion": 0}) is True

    def test_missing_pricing_rejected(self):
        assert free_models.is_free(None) is False

    def test_missing_completion_key_rejected(self):
        assert free_models.is_free({"prompt": "0"}) is False


class TestFilterFree:
    def test_only_genuinely_free_models_pass(self):
        free = free_models.filter_free(SAMPLE_RESPONSE["data"])
        ids = [m["id"] for m in free]
        assert "z-ai/glm-5.2:free" in ids
        assert "nvidia/nemotron-3-ultra-550b-a55b:free" in ids
        assert "z-ai/glm-5.2" not in ids          # paid
        assert "sneaky/freemium" not in ids       # half-free trap

    def test_preserves_metadata(self):
        free = free_models.filter_free(SAMPLE_RESPONSE["data"])
        glm = [m for m in free if m["id"] == "z-ai/glm-5.2:free"][0]
        assert glm["context_length"] == 262144
        assert "tools" in glm["supported_parameters"]


class TestAssertFree:
    def setup_method(self):
        self.cache = _write_cache(Path(os.environ.get("TMPDIR", "/tmp")), SAMPLE_RESPONSE)

    def test_accepts_known_free_model(self, tmp_path):
        cache = _write_cache(tmp_path, SAMPLE_RESPONSE)
        assert free_models.assert_free("z-ai/glm-5.2:free", cache_path=cache) is True

    def test_raises_on_paid_model(self, tmp_path):
        cache = _write_cache(tmp_path, SAMPLE_RESPONSE)
        try:
            free_models.assert_free("z-ai/glm-5.2", cache_path=cache)
            raised = False
        except SystemExit:
            raised = True
        assert raised, "paid model must hard-fail"

    def test_raises_on_unknown_model(self, tmp_path):
        # fail closed: a model we cannot verify as free is treated as paid
        cache = _write_cache(tmp_path, SAMPLE_RESPONSE)
        try:
            free_models.assert_free("openai/gpt-5.6", cache_path=cache)
            raised = False
        except SystemExit:
            raised = True
        assert raised, "unknown model must fail closed"

    def test_suffix_free_not_trusted_alone(self, tmp_path):
        # ":free" suffix alone is not proof; the freemium trap has the pricing data
        cache = _write_cache(tmp_path, SAMPLE_RESPONSE)
        try:
            free_models.assert_free("sneaky/freemium", cache_path=cache)
            raised = False
        except SystemExit:
            raised = True
        assert raised
