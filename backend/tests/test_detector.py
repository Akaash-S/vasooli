"""
test_detector.py — Day 3, Task 4
Unit tests for the detector's classify logic (detect() function).
Tests are pure unit tests — no DB, no async — using simple mock objects.
All 6 required cases from the task prompt are covered.
"""
import sys
from pathlib import Path
from datetime import date, datetime, timezone, timedelta
from unittest.mock import MagicMock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.detector.detector import detect

IST = timezone(timedelta(hours=5, minutes=30))


def make_txn(**kwargs) -> MagicMock:
    """Build a mock RawTransaction with safe defaults for fields not specified."""
    defaults = dict(
        subscription_id=None,
        subscription_status=None,
        invoice_due_date=None,
        invoice_status=None,
        checkout_completed=True,
        payment_status="success",
    )
    defaults.update(kwargs)
    txn = MagicMock()
    for k, v in defaults.items():
        setattr(txn, k, v)
    return txn


# ── Test 1: subscription_failed — priority regression test ─────────────────
def test_subscription_failed_not_misclassified_as_payment_failed():
    """
    Regression: a halted subscription with payment_status='failed' must
    classify as subscription_failed, not payment_failed.
    This is the explicit priority-order test the prompt requires.
    """
    txn = make_txn(
        subscription_id="sub_abc123",
        subscription_status="halted",
        payment_status="failed",   # would match payment_failed if order is wrong
        checkout_completed=True,
    )
    assert detect(txn) == "subscription_failed"


# ── Test 2: plain payment_failed ────────────────────────────────────────────
def test_payment_failed():
    txn = make_txn(
        subscription_id=None,
        payment_status="failed",
        checkout_completed=True,
    )
    assert detect(txn) == "payment_failed"


# ── Test 3: checkout_abandoned ──────────────────────────────────────────────
def test_checkout_abandoned():
    txn = make_txn(
        checkout_completed=False,
        payment_status="pending",
        subscription_id=None,
        invoice_due_date=None,
    )
    assert detect(txn) == "checkout_abandoned"


# ── Test 4: invoice_overdue ─────────────────────────────────────────────────
def test_invoice_overdue():
    txn = make_txn(
        invoice_due_date=date.today() - timedelta(days=45),
        invoice_status="unpaid",
        payment_status="pending",
        checkout_completed=True,
        subscription_id=None,
    )
    assert detect(txn) == "invoice_overdue"


# ── Test 5: healthy transaction → None ──────────────────────────────────────
def test_healthy_returns_none():
    txn = make_txn(
        payment_status="success",
        checkout_completed=True,
        subscription_id=None,
        invoice_due_date=None,
    )
    assert detect(txn) is None


# ── Test 6: boundary condition — invoice due exactly TODAY ──────────────────
def test_invoice_due_today_is_overdue():
    """
    Regression for < vs <= bug:
    An invoice with invoice_due_date == date.today() (age_days=0) MUST
    classify as invoice_overdue. Using < instead of <= would silently drop
    this case — it would fall through all branches and return None,
    producing no risk_case and no audit trail entry.
    """
    txn = make_txn(
        invoice_due_date=date.today(),   # age_days = 0, due exactly today
        invoice_status="unpaid",
        payment_status="pending",
        checkout_completed=True,
        subscription_id=None,
    )
    assert detect(txn) == "invoice_overdue", (
        "Invoice due today must be detected as overdue. "
        "Check that detector uses <= not < on invoice_due_date comparison."
    )


# ── Extra: 'declined' is treated same as 'failed' ───────────────────────────
def test_declined_status_caught_as_payment_failed():
    txn = make_txn(payment_status="declined", subscription_id=None)
    assert detect(txn) == "payment_failed"


# ── Extra: paid invoice is NOT flagged ──────────────────────────────────────
def test_paid_invoice_not_flagged():
    txn = make_txn(
        invoice_due_date=date.today() - timedelta(days=10),
        invoice_status="paid",
        payment_status="success",
        checkout_completed=True,
        subscription_id=None,
    )
    assert detect(txn) is None


# ── Extra: active subscription (not halted) is NOT flagged ──────────────────
def test_active_subscription_not_flagged():
    txn = make_txn(
        subscription_id="sub_xyz",
        subscription_status="active",
        payment_status="success",
        checkout_completed=True,
    )
    assert detect(txn) is None
