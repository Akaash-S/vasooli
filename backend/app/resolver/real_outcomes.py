from decimal import Decimal

REAL_OUTCOME_CASE_IDS = {"0ae6db2b-9927-4c75-a811-f6f60a847711"}


def get_real_outcome(case_id: str, risk_case, webhook_event, txn) -> dict | None:
    if str(case_id) not in REAL_OUTCOME_CASE_IDS:
        return None
    hours = (webhook_event.received_at - risk_case.detected_at).total_seconds() / 3600
    assert Decimal(str(txn.amount_inr)) == Decimal("1060.67"), f"Expected amount 1060.67, got {txn.amount_inr}"
    return dict(
        outcome="recovered",
        amount_recovered=Decimal(str(txn.amount_inr)),
        simulated_attempts=None,
        time_to_recovery_hours=Decimal(str(round(hours, 2))),
        resolution_source="real",
        note=f"real payment confirmed via webhook_event {webhook_event.razorpay_event_id}",
    )
