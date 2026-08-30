from decimal import Decimal
import pytest

from app.metrics.calculations import (
    recovery_rate_pct,
    dollar_recovery_rate_pct,
    median_hours,
    mean_hours,
    derive_exception_reason,
)


def test_recovery_rate_pct_math():
    assert recovery_rate_pct(104, 200) == 52.0
    assert recovery_rate_pct(0, 0) == 0.0


def test_dollar_recovery_rate_pct_math():
    assert dollar_recovery_rate_pct(Decimal("1037933.99"), Decimal("2000000.00")) == 51.90
    assert dollar_recovery_rate_pct(Decimal("0"), Decimal("0")) == 0.0


def test_median_and_mean_hours():
    vals = [24.0, 48.0, 72.0]
    assert mean_hours(vals) == 48.0
    assert median_hours(vals) == 48.0

    assert mean_hours([]) is None
    assert median_hours([]) is None


def test_derive_exception_reason_prefers_resolution_note():
    note = "Customer updated payment method successfully"
    reason = derive_exception_reason("recovered", "update_payment_link", 1, note)
    assert reason == note


def test_derive_exception_reason_fallbacks():
    p2p_reason = derive_exception_reason("escalated", "promise_to_pay", None, None)
    assert "promise-to-pay recorded" in p2p_reason

    hr_reason = derive_exception_reason("escalated", "human_review", None, None)
    assert "human review" in hr_reason

    exhausted_reason = derive_exception_reason("abandoned", "retry", 2, None)
    assert "exhausted 2 simulated attempt(s)" in exhausted_reason

    single_shot_reason = derive_exception_reason("abandoned", "nudge", None, None)
    assert "single-shot nudge action" in single_shot_reason
