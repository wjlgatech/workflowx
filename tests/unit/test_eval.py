"""Comprehensive test suite for evaluation system."""

import json
from pathlib import Path

import pytest

from workflowx.eval.graders.friction_grader import FrictionGrader
from workflowx.eval.graders.intent_grader import IntentGrader
from workflowx.eval.graders.roi_grader import ROIGrader
from workflowx.eval.runner import EvalRunner


class TestIntentGrader:
    """Tests for IntentGrader."""

    def setup_method(self):
        """Set up grader for each test."""
        self.grader = IntentGrader(similarity_threshold=0.60)

    def test_intent_grader_perfect_match(self):
        """Test that identical intents score 1.0 accuracy."""
        predicted = ["Read documentation", "Write unit tests", "Debug issues"]
        gold = ["Read documentation", "Write unit tests", "Debug issues"]

        result = self.grader.grade(predicted, gold)

        assert result["intent_accuracy"] == 1.0
        assert result["n_correct"] == 3
        assert all(item["match"] for item in result["per_session"])

    def test_intent_grader_similar_intents(self):
        """Test that similar intents pass similarity threshold."""
        predicted = ["Competitive research using Chrome tabs"]
        gold = ["Competitive research in Chrome"]

        result = self.grader.grade(predicted, gold)

        # Should pass because text overlap is > 0.60
        assert result["n_correct"] >= 1
        assert result["per_session"][0]["similarity"] > 0.60

    def test_intent_grader_dissimilar_intents(self):
        """Test that dissimilar intents don't match."""
        predicted = ["Email triage"]
        gold = ["Code review in VS Code"]

        result = self.grader.grade(predicted, gold)

        assert result["n_correct"] == 0
        assert result["per_session"][0]["similarity"] < 0.60
        assert not result["per_session"][0]["match"]

    def test_intent_grader_partial_accuracy(self):
        """Test partial accuracy with mix of matches and mismatches."""
        predicted = [
            "Writing code in editor",
            "Reading docs in browser",
            "Email management",
            "Debugging issues",
        ]
        gold = [
            "Implement function in VS Code",
            "Reading documentation in browser",
            "Managing files in terminal",
            "Debug integration tests",
        ]

        result = self.grader.grade(predicted, gold)

        # Some intents should match due to semantic overlap
        assert 0 < result["intent_accuracy"] < 1.0
        assert result["n_sessions"] == 4

    def test_intent_grader_empty_threshold(self):
        """Test grading with custom threshold."""
        grader = IntentGrader(similarity_threshold=0.90)
        predicted = ["Reading documentation"]
        gold = ["Reading docs"]

        result = grader.grade(predicted, gold)

        # Should fail with strict threshold
        assert result["n_correct"] == 0

    def test_intent_grader_assertion_length_mismatch(self):
        """Test that mismatched list lengths raise AssertionError."""
        predicted = ["Intent 1", "Intent 2"]
        gold = ["Gold 1"]

        with pytest.raises(AssertionError):
            self.grader.grade(predicted, gold)


class TestFrictionGrader:
    """Tests for FrictionGrader."""

    def setup_method(self):
        """Set up grader for each test."""
        self.grader = FrictionGrader()

    def test_friction_grader_perfect(self):
        """Test that all correct predictions score 1.0."""
        predicted = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        gold = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

        result = self.grader.grade(predicted, gold)

        assert result["friction_accuracy"] == 1.0
        assert result["n_exact"] == 4
        assert result["n_sessions"] == 4

    def test_friction_grader_all_wrong(self):
        """Test that all wrong predictions score 0.0 exact accuracy."""
        predicted = ["CRITICAL", "HIGH", "LOW", "MEDIUM"]
        gold = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

        result = self.grader.grade(predicted, gold)

        assert result["friction_accuracy"] == 0.0
        assert result["n_exact"] == 0

    def test_friction_grader_adjacent(self):
        """Test adjacent accuracy (off by one level)."""
        predicted = ["LOW", "MEDIUM", "CRITICAL", "MEDIUM"]
        gold = ["LOW", "MEDIUM", "HIGH", "HIGH"]

        result = self.grader.grade(predicted, gold)

        # First two exact, third is adjacent (HIGH→CRITICAL), fourth is adjacent (MEDIUM→HIGH)
        assert result["n_exact"] == 2
        assert result["n_adjacent"] >= 3  # At least 3 within 1 level
        assert result["adjacent_accuracy"] > result["friction_accuracy"]

    def test_friction_grader_confusion(self):
        """Test confusion matrix generation."""
        predicted = ["LOW", "HIGH", "LOW"]
        gold = ["LOW", "MEDIUM", "HIGH"]

        result = self.grader.grade(predicted, gold)

        # Check confusion matrix keys
        assert "LOW→LOW" in result["confusion"]
        assert result["confusion"]["LOW→LOW"] == 1
        assert result["confusion"]["MEDIUM→HIGH"] == 1
        assert result["confusion"]["HIGH→LOW"] == 1

    def test_friction_grader_case_insensitive(self):
        """Test that grading is case insensitive."""
        predicted = ["low", "medium", "high"]
        gold = ["LOW", "MEDIUM", "HIGH"]

        result = self.grader.grade(predicted, gold)

        assert result["friction_accuracy"] == 1.0

    def test_friction_grader_single_session(self):
        """Test grading with single session."""
        predicted = ["HIGH"]
        gold = ["HIGH"]

        result = self.grader.grade(predicted, gold)

        assert result["n_sessions"] == 1
        assert result["friction_accuracy"] == 1.0


class TestROIGrader:
    """Tests for ROIGrader."""

    def setup_method(self):
        """Set up grader for each test."""
        self.grader = ROIGrader()

    def test_roi_grader_accurate(self):
        """Test that accurate estimates yield low MAPE."""
        outcomes = [
            {"estimated_savings": 100, "actual_savings": 95},  # 5% error
            {"estimated_savings": 200, "actual_savings": 210},  # 5% error
            {"estimated_savings": 150, "actual_savings": 140},  # 6.7% error
        ]

        result = self.grader.grade(outcomes)

        assert result["n_outcomes"] == 3
        assert result["mape"] < 0.10  # Average error < 10%

    def test_roi_grader_inaccurate(self):
        """Test that inaccurate estimates yield high MAPE."""
        outcomes = [
            {"estimated_savings": 100, "actual_savings": 20},  # 80% error
            {"estimated_savings": 200, "actual_savings": 50},  # 75% error
        ]

        result = self.grader.grade(outcomes)

        assert result["n_outcomes"] == 2
        assert result["mape"] > 0.70  # Average error > 70%

    def test_roi_grader_no_outcomes(self):
        """Test grading with no valid outcomes."""
        outcomes = []

        result = self.grader.grade(outcomes)

        assert result["mape"] is None
        assert result["n_outcomes"] == 0
        assert "No valid outcomes" in result["message"]

    def test_roi_grader_invalid_outcomes(self):
        """Test that invalid outcomes are filtered out."""
        outcomes = [
            {"estimated_savings": 0, "actual_savings": 100},  # Invalid
            {"estimated_savings": 100, "actual_savings": 0},  # Invalid
            {"estimated_savings": 100, "actual_savings": 95},  # Valid
        ]

        result = self.grader.grade(outcomes)

        assert result["n_outcomes"] == 1
        assert len(result["per_outcome"]) == 1

    def test_roi_grader_per_outcome_detail(self):
        """Test per-outcome error details."""
        outcomes = [{"estimated_savings": 100, "actual_savings": 80}]

        result = self.grader.grade(outcomes)

        assert len(result["per_outcome"]) == 1
        assert result["per_outcome"][0]["estimated"] == 100
        assert result["per_outcome"][0]["actual"] == 80
        assert result["per_outcome"][0]["error"] == 0.2  # 20% error

    def test_roi_grader_averages(self):
        """Test average savings calculation."""
        outcomes = [
            {"estimated_savings": 100, "actual_savings": 80},
            {"estimated_savings": 200, "actual_savings": 160},
        ]

        result = self.grader.grade(outcomes)

        assert result["avg_estimated_savings_min"] == 150.0
        assert result["avg_actual_savings_min"] == 120.0


class TestEvalRunner:
    """Tests for EvalRunner."""

    def setup_method(self):
        """Set up runner for each test."""
        dataset_path = (
            Path(__file__).parent.parent.parent / "src" / "workflowx" / "eval" / "datasets" / "annotated_sessions.json"
        )
        self.runner = EvalRunner(dataset_path=dataset_path)
        self.dataset = self.runner.load_dataset()

    def test_eval_runner_ci_pass(self):
        """Test that good scores pass CI gates."""
        # Create predictions that should pass thresholds
        predicted_intents = [s["ground_truth"]["intent"] for s in self.dataset]
        predicted_levels = [s["ground_truth"]["friction_level"] for s in self.dataset]

        result = self.runner.run_all(predicted_intents, predicted_levels)

        assert result["ci_pass"] is True
        assert len(result["ci_failures"]) == 0

    def test_eval_runner_ci_fail_intent(self):
        """Test that low intent accuracy fails CI gate."""
        # Create bad intent predictions
        predicted_intents = ["Wrong intent"] * len(self.dataset)
        predicted_levels = [s["ground_truth"]["friction_level"] for s in self.dataset]

        result = self.runner.run_all(predicted_intents, predicted_levels)

        assert result["ci_pass"] is False
        assert any("Intent accuracy" in failure for failure in result["ci_failures"])

    def test_eval_runner_ci_fail_friction(self):
        """Test that low friction accuracy fails CI gate."""
        predicted_intents = [s["ground_truth"]["intent"] for s in self.dataset]
        predicted_levels = ["LOW"] * len(self.dataset)  # All wrong

        result = self.runner.run_all(predicted_intents, predicted_levels)

        assert result["ci_pass"] is False
        assert any("Friction accuracy" in failure for failure in result["ci_failures"])

    def test_eval_runner_ci_fail_roi(self):
        """Test that high ROI MAPE fails CI gate."""
        predicted_intents = [s["ground_truth"]["intent"] for s in self.dataset]
        predicted_levels = [s["ground_truth"]["friction_level"] for s in self.dataset]

        # Create terrible ROI outcomes
        roi_outcomes = [
            {"estimated_savings": 100, "actual_savings": 10},  # 90% error
            {"estimated_savings": 200, "actual_savings": 20},  # 90% error
        ]

        result = self.runner.run_all(
            predicted_intents, predicted_levels, roi_outcomes=roi_outcomes
        )

        assert result["ci_pass"] is False
        assert any("ROI MAPE" in failure for failure in result["ci_failures"])

    def test_eval_runner_load_dataset(self):
        """Test loading the gold dataset."""
        dataset = self.runner.load_dataset()

        assert len(dataset) > 0
        assert all("session_id" in s for s in dataset)
        assert all("ground_truth" in s for s in dataset)


class TestGoldDataset:
    """Tests for the gold dataset itself."""

    def setup_method(self):
        """Set up runner to load dataset."""
        dataset_path = (
            Path(__file__).parent.parent.parent / "src" / "workflowx" / "eval" / "datasets" / "annotated_sessions.json"
        )
        self.runner = EvalRunner(dataset_path=dataset_path)
        self.dataset = self.runner.load_dataset()

    def test_gold_dataset_loads(self):
        """Test that annotated_sessions.json loads and has valid structure."""
        assert len(self.dataset) == 20
        assert all("session_id" in s for s in self.dataset)
        assert all("start_time" in s for s in self.dataset)
        assert all("end_time" in s for s in self.dataset)
        assert all("events" in s for s in self.dataset)
        assert all("ground_truth" in s for s in self.dataset)

    def test_gold_dataset_friction_distribution(self):
        """Test that dataset has 5 sessions per friction level."""
        level_counts = {}

        for session in self.dataset:
            level = session["ground_truth"]["friction_level"]
            level_counts[level] = level_counts.get(level, 0) + 1

        assert len(level_counts) == 4
        assert level_counts.get("LOW") == 5
        assert level_counts.get("MEDIUM") == 5
        assert level_counts.get("HIGH") == 5
        assert level_counts.get("CRITICAL") == 5

    def test_gold_dataset_all_sessions_have_intent(self):
        """Test that all sessions have ground truth intent."""
        for session in self.dataset:
            assert "intent" in session["ground_truth"]
            assert len(session["ground_truth"]["intent"]) > 0

    def test_gold_dataset_all_sessions_have_valid_times(self):
        """Test that all sessions have valid time ranges."""
        from datetime import datetime

        for session in self.dataset:
            start = datetime.fromisoformat(session["start_time"])
            end = datetime.fromisoformat(session["end_time"])
            assert start < end

    def test_gold_dataset_all_sessions_human_validated(self):
        """Test that all sessions are marked as human validated."""
        for session in self.dataset:
            assert session["ground_truth"].get("human_validated") is True

    def test_gold_dataset_all_events_have_required_fields(self):
        """Test that all events have required fields."""
        for session in self.dataset:
            for event in session["events"]:
                assert "timestamp" in event
                assert "app_name" in event
                assert "duration_seconds" in event

    def test_gold_dataset_friction_levels_valid(self):
        """Test that all friction levels are valid enum values."""
        valid_levels = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

        for session in self.dataset:
            level = session["ground_truth"]["friction_level"]
            assert level in valid_levels
