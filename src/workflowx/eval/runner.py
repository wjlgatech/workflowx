"""Runs evaluation suite against gold dataset."""

import json
from pathlib import Path

from .graders.friction_grader import FrictionGrader
from .graders.intent_grader import IntentGrader
from .graders.roi_grader import ROIGrader


class EvalRunner:
    """Runs eval suite against gold dataset."""

    # CI gate thresholds
    INTENT_THRESHOLD = 0.80
    FRICTION_THRESHOLD = 0.70
    ROI_MAPE_THRESHOLD = 0.30

    def __init__(self, dataset_path: str | Path = None):
        if dataset_path is None:
            dataset_path = Path(__file__).parent / "datasets" / "annotated_sessions.json"
        self.dataset_path = Path(dataset_path)
        self.intent_grader = IntentGrader()
        self.friction_grader = FrictionGrader()
        self.roi_grader = ROIGrader()

    def load_dataset(self) -> list[dict]:
        """Load annotated gold dataset."""
        with open(self.dataset_path) as f:
            return json.load(f)

    def run_intent_eval(self, predicted_intents: list[str]) -> dict:
        """Grade intent predictions against gold dataset."""
        dataset = self.load_dataset()
        gold_intents = [s["ground_truth"]["intent"] for s in dataset]
        return self.intent_grader.grade(predicted_intents, gold_intents)

    def run_friction_eval(self, predicted_levels: list[str]) -> dict:
        """Grade friction predictions against gold dataset."""
        dataset = self.load_dataset()
        gold_levels = [s["ground_truth"]["friction_level"] for s in dataset]
        return self.friction_grader.grade(predicted_levels, gold_levels)

    def run_roi_eval(self, outcomes: list[dict]) -> dict:
        """Grade ROI predictions."""
        return self.roi_grader.grade(outcomes)

    def run_all(
        self,
        predicted_intents: list[str],
        predicted_levels: list[str],
        roi_outcomes: list[dict] = None,
    ) -> dict:
        """Run all graders and check CI thresholds."""
        intent_result = self.run_intent_eval(predicted_intents)
        friction_result = self.run_friction_eval(predicted_levels)
        roi_result = self.run_roi_eval(roi_outcomes or [])

        ci_pass = True
        ci_failures = []

        if intent_result["intent_accuracy"] < self.INTENT_THRESHOLD:
            ci_pass = False
            ci_failures.append(
                f"Intent accuracy {intent_result['intent_accuracy']} < {self.INTENT_THRESHOLD}"
            )

        if friction_result["friction_accuracy"] < self.FRICTION_THRESHOLD:
            ci_pass = False
            ci_failures.append(
                f"Friction accuracy {friction_result['friction_accuracy']} < {self.FRICTION_THRESHOLD}"
            )

        if (
            roi_result.get("mape") is not None
            and roi_result["mape"] > self.ROI_MAPE_THRESHOLD
        ):
            ci_pass = False
            ci_failures.append(
                f"ROI MAPE {roi_result['mape']} > {self.ROI_MAPE_THRESHOLD}"
            )

        return {
            "intent": intent_result,
            "friction": friction_result,
            "roi": roi_result,
            "ci_pass": ci_pass,
            "ci_failures": ci_failures,
        }
