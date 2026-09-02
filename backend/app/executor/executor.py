"""
executor.py — Day 6, Tasks 3, 5, 6
Core executor module: dispatches pending interventions to real or simulated handlers.
Enforces idempotency key format: "{case_id}:{action_type}:{attempt_number}".
"""
from datetime import datetime, timezone, timedelta
from app.stopping_rules.mandate_retry_sequencer import MandateRetrySequencer
from app.executor.razorpay_client import create_real_payment_link

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


def build_idempotency_key(case_id, action_type, attempt_number) -> str:
    """Returns deterministic idempotency key for an intervention attempt."""
    return f"{case_id}:{action_type}:{attempt_number}"


def simulate_action(action_type, case, txn, **detail) -> dict:
    """Centralized simulation handler for non-real intervention paths."""
    return dict(
        status="executed",
        execution_mode="simulated",
        note=f"SIMULATED: would have executed '{action_type}' for case {case.id}, amount INR {txn.amount_inr}",
        detail=detail,
    )


def execute_mandate_retry(intervention, case, txn) -> dict:
    """Executes mandate retry logic using MandateRetrySequencer."""
    sequencer = MandateRetrySequencer()
    scheduled_time = intervention.scheduled_at or now_ist()
    slot = sequencer.next_retry_slot(last_attempt_at=scheduled_time, attempt_number=intervention.attempt_number or 1)
    return dict(
        status="executed",
        execution_mode="simulated",
        note=f"SIMULATED: mandate retry scheduled not-before {slot.get('scheduled_not_before')}",
        detail=slot,
    )


def execute_intervention(intervention, case, txn, real_call_budget: dict) -> dict:
    """
    Main dispatcher for executing an intervention.
    Enforces real API call cap via real_call_budget dict.
    """
    action = intervention.action_type
    selected_for_demo = getattr(intervention, "selected_for_demo", False)

    if action == "update_payment_link":
        if real_call_budget["payment_links_used"] < real_call_budget["cap"] and selected_for_demo:
            return create_real_payment_link(case, txn, real_call_budget)
        return simulate_action(action, case, txn, reason="over demo budget or not selected")

    if action == "retry":
        return simulate_action(action, case, txn, note="card retry — no stored payment method to actually charge in test mode")

    if action == "mandate_retry_sequence":
        return execute_mandate_retry(intervention, case, txn)

    if action == "nudge":
        return simulate_action(action, case, txn, channel="sms")

    if action == "escalate":
        return simulate_action(action, case, txn, channel="formal_notice")

    if action == "promise_to_pay":
        return dict(
            status="executed",
            execution_mode="simulated",
            note="promise already recorded Day 5; resolution checked separately",
        )

    if action == "human_review":
        return dict(
            status="queued",
            execution_mode="simulated",
            note="queued for human review, no automated action taken",
        )

    raise ValueError(f"unhandled action_type: {action}")
