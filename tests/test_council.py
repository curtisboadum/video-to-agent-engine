"""Tests for council.py — Karpathy-style 3-stage LLM council.

Free models only (asserted through free_models), anonymized peer review,
parseable FINAL RANKING, chairman synthesis.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "video-to-agent" / "scripts"))

import council


class TestPersonas:
    def test_five_distinct_personalities(self):
        names = [p.name for p in council.COUNCIL]
        assert len(names) == len(set(names)) == 4  # 4 voters + chairman

    def test_chairman_is_glm(self):
        assert "glm" in council.CHAIRMAN.model.lower()

    def test_all_council_models_are_free_ids(self):
        for p in council.COUNCIL + [council.CHAIRMAN]:
            assert ":free" in p.model, "council must use :free models"


class TestParseRanking:
    def test_standard_format(self):
        text = "good analysis...\nFINAL RANKING:\n1. Response B\n2. Response A\n3. Response C"
        assert council.parse_ranking_from_text(text) == ["Response B", "Response A", "Response C"]

    def test_missing_section_returns_empty(self):
        assert council.parse_ranking_from_text("no ranking here") == []

    def test_extra_text_after_ignored(self):
        text = ("FINAL RANKING:\n1. Response A\n2. Response B\n\n"
                "(A was stronger because of X)")
        assert council.parse_ranking_from_text(text) == ["Response A", "Response B"]


class TestAggregate:
    STAGE2 = [
        {"model": "m1", "ranking": "FINAL RANKING:\n1. Response A\n2. Response B",
         "parsed_ranking": ["Response A", "Response B"]},
        {"model": "m2", "ranking": "FINAL RANKING:\n1. Response A\n2. Response B",
         "parsed_ranking": ["Response A", "Response B"]},
        {"model": "m3", "ranking": "FINAL RANKING:\n1. Response B\n2. Response A",
         "parsed_ranking": ["Response B", "Response A"]},
    ]
    LABELS = {"Response A": "model-alpha", "Response B": "model-beta"}

    def test_average_positions(self):
        agg = council.calculate_aggregate_rankings(self.STAGE2, self.LABELS)
        by_model = {a["model"]: a["average_rank"] for a in agg}
        assert by_model["model-alpha"] == 1.33
        assert by_model["model-beta"] == 1.67

    def test_sorted_best_first(self):
        agg = council.calculate_aggregate_rankings(self.STAGE2, self.LABELS)
        assert agg[0]["model"] == "model-alpha"

    def test_unranked_models_excluded(self):
        agg = council.calculate_aggregate_rankings([], self.LABELS)
        assert agg == []


class TestAnonymization:
    def test_labels_are_letters_not_models(self):
        stage1 = [{"model": "a/x:free", "response": "r1"}, {"model": "b/y:free", "response": "r2"}]
        labels, mapping = council.anonymize(stage1)
        assert labels == {"Response A": "r1", "Response B": "r2"}
        assert set(mapping.values()) == {"a/x:free", "b/y:free"}
        # the prompt sent to reviewers must not contain raw model ids
        prompt = council.build_ranking_prompt("query", labels)
        assert "x:free" not in prompt and "y:free" not in prompt


class TestFullCouncil:
    def test_three_stages_run_with_stub_runner(self):
        calls = []

        def stub_runner(model_id, prompt):
            calls.append(model_id)
            if "RANK EACH OTHER" in prompt.upper() or "evaluate" in prompt.lower():
                return "FINAL RANKING:\n1. Response A\n2. Response B"
            if "CHAIRMAN" in prompt.upper():
                return "synthesis"
            return "opinion of %s" % model_id

        result = council.run_full_council(
            "test question",
            runner=stub_runner,
            guard=lambda mid: True,
            models=[council.Persona("p1", "a/x:free", "be brief"),
                    council.Persona("p2", "b/y:free", "be thorough")],
            chairman=council.Persona("chair", "c/z:free", "synthesize"),
        )
        assert result["stage1"][0]["response"].startswith("opinion")
        assert result["stage3"]["response"] == "synthesis"
        assert result["aggregate_rankings"][0]["model"] == "a/x:free"

    def test_free_guard_called_for_every_model(self):
        guarded = []

        def stub_runner(model_id, prompt):
            return "FINAL RANKING:\n1. Response A\n2. Response B" if "Response" in prompt else "op"

        def spy_guard(model_id):
            guarded.append(model_id)
            return True

        council.run_full_council(
            "q", runner=stub_runner, guard=spy_guard,
            models=[council.Persona("p1", "a/x:free", "b"),
                    council.Persona("p2", "b/y:free", "b")],
            chairman=council.Persona("chair", "c/z:free", "s"),
        )
        assert set(guarded) == {"a/x:free", "b/y:free", "c/z:free"}
