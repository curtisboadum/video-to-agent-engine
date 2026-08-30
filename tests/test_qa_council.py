"""Tests for qa_council.py — adversarial QA gate over built artifacts."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "video-to-agent" / "scripts"))

import qa_council as q


VERDICT_JSON = json.dumps({
    "scores": {"spec_compliance": 9, "completeness": 8,
               "correctness": 9, "runnability": 7},
    "critical_issues": [],
    "notes": "solid",
})


class TestVerdictParsing:
    def test_parse_clean_json(self):
        v = q.parse_verdict(VERDICT_JSON)
        assert v["scores"]["runnability"] == 7

    def test_parse_json_in_fenced_block(self):
        fenced = "```json\n%s\n```" % VERDICT_JSON
        assert q.parse_verdict(fenced)["scores"]["completeness"] == 8

    def test_parse_json_with_prose(self):
        noisy = "Here is my review:\n%s\nhope that helps" % VERDICT_JSON
        assert q.parse_verdict(noisy)["scores"]["correctness"] == 9

    def test_unparseable_returns_none(self):
        assert q.parse_verdict("no json at all") is None


class TestGate:
    def make_reviewer(self, scores, critical=None):
        def reviewer(spec_text, artifact_text):
            return {"scores": scores, "critical_issues": critical or [],
                    "notes": ""}
        return reviewer

    SPEC = "SPEC"
    ART = "ARTIFACT"

    def test_pass_when_all_above_threshold(self):
        reviewers = [self.make_reviewer({"spec_compliance": 9, "correctness": 8})]
        result = q.run_gate(self.SPEC, self.ART, reviewers=reviewers,
                            threshold=7)
        assert result["verdict"] == "PASS"

    def test_fail_below_threshold(self):
        reviewers = [self.make_reviewer({"spec_compliance": 5, "correctness": 9})]
        result = q.run_gate(self.SPEC, self.ART, reviewers=reviewers,
                            threshold=7)
        assert result["verdict"] == "REVISE"

    def test_critical_issue_fails_regardless_of_scores(self):
        reviewers = [self.make_reviewer({"spec_compliance": 10, "correctness": 10},
                                        critical=["command would delete ~"])]
        result = q.run_gate(self.SPEC, self.ART, reviewers=reviewers,
                            threshold=7)
        assert result["verdict"] == "REJECT"

    def test_majority_rule_across_reviewers(self):
        # one harsh reviewer, two passing -> majority PASS but flagged
        reviewers = [
            self.make_reviewer({"spec_compliance": 4, "correctness": 4}),
            self.make_reviewer({"spec_compliance": 9, "correctness": 9}),
            self.make_reviewer({"spec_compliance": 9, "correctness": 8}),
        ]
        result = q.run_gate(self.SPEC, self.ART, reviewers=reviewers,
                            threshold=7)
        assert result["verdict"] == "PASS"

    def test_unparseable_verdict_counts_as_failure(self):
        def bad_reviewer(spec_text, artifact_text):
            return None
        reviewers = [bad_reviewer]
        result = q.run_gate(self.SPEC, self.ART, reviewers=reviewers,
                            threshold=7)
        assert result["verdict"] == "REVISE"


class TestCouncilIntegration:
    def test_build_reviewers_uses_free_models_only(self):
        reviewers = q.build_reviewers()
        models = [r.model for r in reviewers]
        assert len(models) >= 2
        for m in models:
            assert ":free" in m
        # distinct personalities
        names = [r.name for r in reviewers]
        assert len(names) == len(set(names))
