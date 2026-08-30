import statistics
from decimal import Decimal
from typing import Optional, List


def recovery_rate_pct(recovered_count: int, total_count: int) -> float:
    return round(100.0 * recovered_count / total_count, 2) if total_count else 0.0


def dollar_recovery_rate_pct(amount_recovered: Decimal, amount_at_risk: Decimal) -> float:
    return round(100.0 * float(amount_recovered) / float(amount_at_risk), 2) if amount_at_risk else 0.0


def median_hours(values: List[float]) -> Optional[float]:
    return round(float(statistics.median(values)), 2) if values else None


def mean_hours(values: List[float]) -> Optional[float]:
    return round(float(statistics.mean(values)), 2) if values else None


def derive_exception_reason(
    outcome: str,
    action_type: str,
    simulated_attempts: Optional[int],
    resolution_note: Optional[str],
) -> str:
    """
    Returns resolution note if present; otherwise derives structured exception reason string.
    """
    if resolution_note and resolution_note.strip():
        return resolution_note.strip()
    if action_type == "promise_to_pay":
        return "B2B promise-to-pay recorded, not yet due — not a failure, pending resolution"
    if action_type == "human_review":
        return "routed to human review, no automated resolution attempted"
    if simulated_attempts:
        return f"exhausted {simulated_attempts} simulated attempt(s) without recovery"
    return f"no recovery within single-shot {action_type} action"
