"""Grades friction level classification accuracy."""


class FrictionGrader:
    """Evaluates friction level classification accuracy."""

    LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

    def grade(self, predicted_levels: list[str], gold_levels: list[str]) -> dict:
        """
        Exact accuracy: prediction must match gold level exactly.
        Adjacent accuracy: off by one level gets partial credit.

        Args:
            predicted_levels: List of predicted friction level strings
            gold_levels: List of ground truth friction level strings

        Returns:
            Dict with exact and adjacent accuracies, confusion matrix, and per-session breakdown
        """
        assert len(predicted_levels) == len(
            gold_levels
        ), "Predicted and gold level lists must have same length"

        exact_matches = sum(
            1 for p, g in zip(predicted_levels, gold_levels) if p.upper() == g.upper()
        )
        accuracy = exact_matches / len(gold_levels) if gold_levels else 0.0

        # Adjacent accuracy (off by one level is partial credit)
        adjacent_matches = 0
        for p, g in zip(predicted_levels, gold_levels):
            try:
                p_idx = self.LEVELS.index(p.upper())
                g_idx = self.LEVELS.index(g.upper())
                if abs(p_idx - g_idx) <= 1:
                    adjacent_matches += 1
            except ValueError:
                # Handle invalid level names
                pass

        adjacent_accuracy = (
            adjacent_matches / len(gold_levels) if gold_levels else 0.0
        )

        # Confusion matrix
        confusion = {}
        for p, g in zip(predicted_levels, gold_levels):
            key = f"{g.upper()}→{p.upper()}"
            confusion[key] = confusion.get(key, 0) + 1

        return {
            "friction_accuracy": round(accuracy, 4),
            "adjacent_accuracy": round(adjacent_accuracy, 4),
            "n_sessions": len(gold_levels),
            "n_exact": exact_matches,
            "n_adjacent": adjacent_matches,
            "confusion": confusion,
        }
