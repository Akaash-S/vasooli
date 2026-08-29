import random
from decimal import Decimal

RECOVERY_PROBABILITY = {
    "retry": 0.55,                 # soft_decline card retry
    "update_payment_link": 0.35,   # hard_decline / subscription_halted — needs customer action
    "mandate_retry_sequence": 0.30,
    "nudge": 0.20,                 # checkout_friction / unclear
    "escalate": 0.15,              # B2B aging-ladder formal escalation
}

ATTEMPT_INTERVAL_HOURS = {
    "retry": 24,
    "mandate_retry_sequence": 24,
    "update_payment_link": 48,   # customer needs time to act on a payment link
    "nudge": 24,
    "escalate": 72,              # formal B2B escalation
}

MAX_CARD_RETRY_ATTEMPTS = 2      # matches CONSECUTIVE_FAILURE_HUMAN_REVIEW
MAX_MANDATE_RETRY_ATTEMPTS = 8   # matches MAX_MANDATE_RETRIES


def simulate_lifecycle(action_type: str, amount_inr: Decimal, rng: random.Random) -> dict:
    """Returns dict(outcome, amount_recovered, simulated_attempts, time_to_recovery_hours, note)."""

    if action_type == "promise_to_pay":
        return dict(
            outcome="escalated",
            amount_recovered=Decimal("0"),
            simulated_attempts=None,
            time_to_recovery_hours=None,
            note="awaiting promised_date, not yet due — not a terminal failure",
        )

    if action_type == "human_review":
        return dict(
            outcome="escalated",
            amount_recovered=Decimal("0"),
            simulated_attempts=None,
            time_to_recovery_hours=None,
            note="routed to human review, no automated resolution",
        )

    if action_type not in RECOVERY_PROBABILITY:
        raise ValueError(f"no recovery model defined for action_type={action_type}")

    p = RECOVERY_PROBABILITY[action_type]
    interval = ATTEMPT_INTERVAL_HOURS[action_type]
    max_attempts = {
        "retry": MAX_CARD_RETRY_ATTEMPTS,
        "mandate_retry_sequence": MAX_MANDATE_RETRY_ATTEMPTS,
    }.get(action_type, 1)

    for attempt in range(1, max_attempts + 1):
        if rng.random() < p:
            return dict(
                outcome="recovered",
                amount_recovered=Decimal(str(amount_inr)),
                simulated_attempts=attempt,
                time_to_recovery_hours=Decimal(str(attempt * interval)),
                note=f"recovered on simulated attempt {attempt}/{max_attempts}",
            )

    # exhausted without recovery
    terminal = "escalated" if action_type in ("mandate_retry_sequence", "retry") else "abandoned"
    return dict(
        outcome=terminal,
        amount_recovered=Decimal("0"),
        simulated_attempts=max_attempts,
        time_to_recovery_hours=None,
        note=f"exhausted {max_attempts} simulated attempts without recovery",
    )
