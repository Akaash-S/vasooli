from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.resolver.real_outcomes import get_real_outcome, REAL_OUTCOME_CASE_IDS


def test_real_outcome_bypass_known_case():
    known_id = list(REAL_OUTCOME_CASE_IDS)[0]

    mock_case = MagicMock()
    mock_case.detected_at = datetime(2026, 8, 25, 15, 1, 1, tzinfo=timezone.utc)

    mock_we = MagicMock()
    mock_we.received_at = datetime(2026, 8, 28, 11, 48, 5, tzinfo=timezone.utc)
    mock_we.razorpay_event_id = "TVB8GHU0GvhUjl"

    mock_txn = MagicMock()
    mock_txn.amount_inr = Decimal("1060.67")

    outcome = get_real_outcome(known_id, mock_case, mock_we, mock_txn)

    assert outcome is not None
    assert outcome["outcome"] == "recovered"
    assert outcome["resolution_source"] == "real"
    assert outcome["amount_recovered"] == Decimal("1060.67")
    assert outcome["simulated_attempts"] is None
    assert outcome["time_to_recovery_hours"] == Decimal("68.78")


def test_real_outcome_bypass_other_case():
    other_id = "11111111-2222-3333-4444-555555555555"
    outcome = get_real_outcome(other_id, MagicMock(), MagicMock(), MagicMock())
    assert outcome is None
