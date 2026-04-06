"""Grades ROI accuracy against replacement outcomes."""


class ROIGrader:
    """Measures whether claimed savings match actual savings. Primary metric: MAPE."""

    def grade(self, outcomes: list[dict]) -> dict:
        """
        MAPE (Mean Absolute Percentage Error) scoring for ROI estimates.

        Args:
            outcomes: List of dicts with 'estimated_savings' and 'actual_savings' keys

        Returns:
            Dict with MAPE score, valid outcome count, and per-outcome errors
        """
        valid = [
            o
            for o in outcomes
            if o.get("actual_savings", 0) > 0 and o.get("estimated_savings", 0) > 0
        ]

        if not valid:
            return {
                "mape": None,
                "n_outcomes": 0,
                "message": "No valid outcomes to grade",
            }

        errors = []
        for o in valid:
            estimated = o["estimated_savings"]
            actual = o["actual_savings"]
            errors.append(abs(estimated - actual) / estimated)

        mape = sum(errors) / len(errors) if errors else 0.0

        return {
            "mape": round(mape, 4),
            "n_outcomes": len(valid),
            "avg_actual_savings_min": round(
                sum(o["actual_savings"] for o in valid) / len(valid), 1
            ),
            "avg_estimated_savings_min": round(
                sum(o["estimated_savings"] for o in valid) / len(valid), 1
            ),
            "per_outcome": [
                {
                    "estimated": o["estimated_savings"],
                    "actual": o["actual_savings"],
                    "error": round(
                        abs(o["estimated_savings"] - o["actual_savings"])
                        / o["estimated_savings"],
                        3,
                    ),
                }
                for o in valid
            ],
        }
