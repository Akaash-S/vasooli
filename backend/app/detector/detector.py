"""
detector.py — Day 3
Rule-based detector: reads RawTransaction rows and classifies each into a risk_status.
Pure deterministic logic — no LLM, no external API calls.
Note: RiskCase.id is assigned explicitly via uuid.uuid4() at Python object creation
time (not relying on the SQLAlchemy column default), so that CaseEvent.case_id can
reference it within the same uncommitted session without a flush in between.

Priority order is critical:
  1. subscription_failed  — most specific, checked FIRST to avoid misclassifying
                            subscription rows as generic payment_failed
  2. invoice_overdue      — B2B invoices, checked before generic payment checks
  3. checkout_abandoned   — incomplete checkout, payment_status may be 'pending'
  4. payment_failed       — broadest, checked LAST

The invoice_overdue check uses <= (not <) on due date:
  An invoice due exactly today is still at risk and must be caught.
  Using < would silently drop age_days=0 invoices — they would fall through
  all branches and produce no risk_case, creating an invisible audit gap.
"""
import json
from datetime import date, datetime, timezone, timedelta
from typing import Optional

from app.models import RawTransaction, RiskCase, CaseEvent

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


def detect(txn: RawTransaction) -> Optional[str]:
    """
    Returns risk_status string, or None if the transaction is healthy.
    Evaluated in priority order — stop at first match.
    """
    # 1. Subscription-specific — most specific, check FIRST
    if txn.subscription_id is not None and txn.subscription_status == "halted":
        return "subscription_failed"

    # 2. B2B invoice overdue — use <= so invoices due TODAY are caught
    if (
        txn.invoice_due_date is not None
        and txn.invoice_due_date <= date.today()
        and txn.invoice_status != "paid"
    ):
        return "invoice_overdue"

    # 3. Checkout abandonment — incomplete checkouts
    if txn.checkout_completed is False:
        return "checkout_abandoned"

    # 4. Generic payment failure — broadest condition, check LAST
    if txn.payment_status in ("failed", "declined"):
        return "payment_failed"

    # 5. Healthy — no risk case created
    return None


def _matched_rule(risk_status: str) -> str:
    """Human-readable label for which condition fired — goes into case_event payload."""
    return {
        "subscription_failed": "subscription_id IS NOT NULL AND subscription_status = 'halted'",
        "invoice_overdue": "invoice_due_date IS NOT NULL AND invoice_due_date <= today AND invoice_status != 'paid'",
        "checkout_abandoned": "checkout_completed IS FALSE",
        "payment_failed": "payment_status IN ('failed', 'declined')",
    }.get(risk_status, "unknown")


def build_risk_case_and_event(
    txn: RawTransaction, risk_status: str
) -> tuple[RiskCase, CaseEvent]:
    """Create a RiskCase and its initial CaseEvent for the given transaction.
    The RiskCase.id is assigned explicitly (not via column default) so the
    CaseEvent can reference it before any DB flush occurs.
    """
    import uuid as _uuid
    now = now_ist()
    case_id = _uuid.uuid4()
    risk_case = RiskCase(
        id=case_id,
        transaction_id=txn.id,
        risk_status=risk_status,
        detected_at=now,
    )
    case_event = CaseEvent(
        case_id=case_id,
        event_type="case_detected",
        event_payload=json.dumps({
            "risk_status": risk_status,
            "matched_rule": _matched_rule(risk_status),
            "order_id": txn.order_id,
            "amount_inr": str(txn.amount_inr),
        }),
        occurred_at=now,
    )
    return risk_case, case_event
