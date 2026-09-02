"""
decision_engine.py — Day 5
Decision Engine: maps diagnosis + transaction context to proposed intervention action.
Deterministic mapping — no LLM.

All proposed interventions MUST pass through StoppingRuleEngine before being written
to the database as Intervention rows.
"""
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


def decide_by_aging_bucket(invoice_due_date) -> dict:
    """
    Aging-bucket escalation ladder for invoice_overdue cases where root_cause = 'unclear'.
      <= 30 days: nudge
      31-60 days: promise_to_pay
      61-90 days: escalate
      > 90 days : human_review
    """
    if isinstance(invoice_due_date, datetime):
        due = invoice_due_date.date()
    elif isinstance(invoice_due_date, date):
        due = invoice_due_date
    else:
        due = date.today()

    age_days = (date.today() - due).days

    if age_days <= 30:
        return dict(action_type="nudge", attempt_number=1)
    elif age_days <= 60:
        return dict(action_type="promise_to_pay", attempt_number=1)
    elif age_days <= 90:
        return dict(action_type="escalate", attempt_number=1)
    else:
        return dict(action_type="human_review", attempt_number=1)


def decide_intervention(case, diagnosis, txn) -> dict:
    """
    Proposes an intervention action dict based on diagnosis.root_cause and context.
    Every proposal must subsequently pass through StoppingRuleEngine.enforce().
    """
    root_cause = diagnosis.root_cause

    if root_cause == "soft_decline":
        return dict(action_type="retry", attempt_number=1)

    if root_cause == "hard_decline":
        return dict(action_type="update_payment_link", attempt_number=1)

    if root_cause == "mandate_expired":
        return dict(action_type="mandate_retry_sequence", attempt_number=1)

    if root_cause == "subscription_halted":
        # Razorpay already exhausted native retries before halting —
        # prompt for updated payment method instead of blind retry.
        return dict(action_type="update_payment_link", attempt_number=1)

    if root_cause == "checkout_friction":
        return dict(action_type="nudge", attempt_number=1)

    if root_cause == "b2b_dispute":
        return dict(action_type="promise_to_pay", attempt_number=1)

    if root_cause == "unclear" and case.risk_status == "invoice_overdue":
        return decide_by_aging_bucket(txn.invoice_due_date)

    if root_cause == "unclear":
        return dict(action_type="nudge", attempt_number=1)

    raise ValueError(f"unhandled root_cause: {root_cause}")


def create_promise_to_pay(case_id) -> dict:
    """
    Creates a dict for PromiseToPay row when intervention is 'promise_to_pay'.
    Follow-up window: fixed 7 days from today.
    """
    return dict(
        case_id=case_id,
        promised_date=date.today() + timedelta(days=7),
        promised_via="portal",
        status="pending",
        recorded_at=now_ist(),
    )
