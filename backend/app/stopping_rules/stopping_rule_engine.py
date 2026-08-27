"""
stopping_rule_engine.py — Day 5, Task 4
StoppingRuleEngine: Compliance and ethical gate for proposed intervention actions.

Rule 1 — AFA threshold (RBI Digital Payments E-Mandate Framework 2026):
  Any retry-type action ('retry', 'mandate_retry_sequence') on an amount >= ₹15,000
  cannot auto-execute. Downgraded to 'human_review' with stopping_reason.

Rule 2 — Ethical stopping rule (anti-dark-pattern differentiator):
  Card retries ('retry') with prior_attempts >= 2 (CONSECUTIVE_FAILURE_HUMAN_REVIEW)
  are de-escalated to 'human_review' rather than continuing automated retries.
  Checked BEFORE Rule 3, using a lower threshold (2 < 3), so it acts as an earlier off-ramp.

Rule 3 — Hard retry cap:
  For 'mandate_retry_sequence': cap is MAX_MANDATE_RETRIES (8). Checked when prior_attempts >= 8.
  For 'retry': cap is MAX_CARD_RETRIES (3). Checked when prior_attempts >= 3.

Rule 4 — 24h pre-debit notice window:
  Tags retry/mandate_retry_sequence actions with required_notice_hours = 24.
"""
from app.stopping_rules.mandate_retry_sequencer import MandateRetrySequencer

MAX_CARD_RETRIES = 3
MAX_MANDATE_RETRIES = 8
AFA_THRESHOLD_INR = 15000
PRE_DEBIT_NOTICE_HOURS = 24
CONSECUTIVE_FAILURE_HUMAN_REVIEW = 2


def enforce(proposed: dict, case, diagnosis, txn, prior_attempts: int) -> dict:
    """
    Enforces compliance and ethical stopping rules on a proposed intervention.
    Returns a dict with updated action_type, attempt_number, stopping_reason, etc.
    """
    result = dict(proposed)
    action = result["action_type"]
    result["attempt_number"] = prior_attempts + 1

    # Rule 1 — AFA threshold: any retry-type action on an amount >= 15,000
    # cannot auto-execute. Route to human/customer-approval gate instead.
    if action in ("retry", "mandate_retry_sequence") and txn.amount_inr >= AFA_THRESHOLD_INR:
        return dict(
            action_type="human_review",
            attempt_number=prior_attempts + 1,
            stopping_reason=f"AFA threshold: amount {txn.amount_inr} >= {AFA_THRESHOLD_INR}, requires explicit customer approval before retry"
        )

    # Rule 2 — consecutive-failure human-review routing (ethical stopping rule,
    # anti-dark-pattern differentiator). Checked BEFORE the hard retry cap,
    # and uses a strictly lower threshold (2 < 3), so it is demonstrably a distinct,
    # earlier de-escalation — not just a duplicate of Rule 3.
    if action == "retry" and prior_attempts >= CONSECUTIVE_FAILURE_HUMAN_REVIEW:
        return dict(
            action_type="human_review",
            attempt_number=prior_attempts + 1,
            stopping_reason="consecutive-failure threshold reached — de-escalating from automated retry to human review rather than continuing to press"
        )

    # Rule 3 — max retry cap, differentiated by retry type. For "retry" this is a
    # backstop that Rule 2 will normally intercept first (2 < 3); for
    # "mandate_retry_sequence" this is the primary and only retry-count gate,
    # since Rule 2 only applies to plain card "retry" actions.
    cap = MAX_MANDATE_RETRIES if action == "mandate_retry_sequence" else MAX_CARD_RETRIES
    if action in ("retry", "mandate_retry_sequence") and prior_attempts >= cap:
        return dict(
            action_type="human_review",
            attempt_number=prior_attempts + 1,
            stopping_reason=f"max retry cap ({cap}) reached for {action}"
        )

    # Rule 4 — 24h pre-debit notification window requirement
    if action in ("retry", "mandate_retry_sequence"):
        result["required_notice_hours"] = PRE_DEBIT_NOTICE_HOURS

    return result
