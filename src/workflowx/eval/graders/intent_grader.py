"""Grades intent inference accuracy against annotated ground truth."""

from difflib import SequenceMatcher


class IntentGrader:
    """Evaluates LLM intent inference accuracy against annotated ground truth."""

    def __init__(self, similarity_threshold: float = 0.60):
        self.similarity_threshold = similarity_threshold

    def grade(self, predicted_intents: list[str], gold_intents: list[str]) -> dict:
        """
        Soft accuracy: prediction matches if SequenceMatcher similarity >= threshold.

        Args:
            predicted_intents: List of predicted intent strings
            gold_intents: List of ground truth intent strings

        Returns:
            Dict with intent_accuracy, per-session details, and match breakdown
        """
        assert len(predicted_intents) == len(
            gold_intents
        ), "Predicted and gold intent lists must have same length"

        matches = []
        per_session = []

        for pred, gold in zip(predicted_intents, gold_intents):
            sim = SequenceMatcher(None, pred.lower(), gold.lower()).ratio()
            match = sim >= self.similarity_threshold
            matches.append(match)
            per_session.append(
                {
                    "predicted": pred,
                    "gold": gold,
                    "similarity": round(sim, 3),
                    "match": match,
                }
            )

        accuracy = sum(matches) / len(matches) if matches else 0.0

        return {
            "intent_accuracy": round(accuracy, 4),
            "n_sessions": len(gold_intents),
            "n_correct": sum(matches),
            "threshold": self.similarity_threshold,
            "per_session": per_session,
        }
