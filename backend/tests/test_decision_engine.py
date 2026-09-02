"""
test_decision_engine.py — Day 5, Task 8
Unit tests for Decision Engine mapping, aging-bucket escalation ladder, and promise_to_pay creation.
"""
import sys
from pathlib import Path
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.decision_engine.decision_engine import (
    decide_intervention,
    decide_by_aging_bucket,
    create_promise_to_pay,
)


def make_case(risk_status="payment_failed"):
    c = MagicMock()
    c.risk_status = risk_status
    return c


def make_diagnosis(root_cause="soft_decline"):
    d = MagicMock()
    d.root_cause = root_cause
    return d


def make_txn(invoice_due_date=None):
    t = MagicMock()
    t.invoice_due_date = invoice_due_date
    return t


# ── Test 1: root_cause mapping ────────────────────────────────────────────────
@pytest.mark.parametrize(
    "root_cause, risk_status, expected_action",
    [
        ("soft_decline", "payment_failed", "retry"),
        ("hard_decline", "payment_failed", "update_payment_link"),
        ("mandate_expired", "payment_failed", "mandate_retry_sequence"),
        ("subscription_halted", "subscription_failed", "update_payment_link"),
        ("checkout_friction", "checkout_abandoned", "nudge"),
        ("b2b_dispute", "invoice_overdue", "promise_to_pay"),
        ("unclear", "checkout_abandoned", "nudge"),
    ],
)
def test_decision_engine_root_cause_mapping(root_cause, risk_status, expected_action):
    case = make_case(risk_status)
    diag = make_diagnosis(root_cause)
    txn = make_txn()
    res = decide_intervention(case, diag, txn)
    assert res["action_type"] == expected_action


# ── Test 2: aging-bucket escalation ladder (unclear + invoice_overdue) ──────
@pytest.mark.parametrize(
    "days_overdue, expected_action",
    [
        (10, "nudge"),           # <= 30
        (30, "nudge"),           # boundary <= 30
        (45, "promise_to_pay"),  # 31-60
        (60, "promise_to_pay"),  # boundary <= 60
        (75, "escalate"),        # 61-90
        (90, "escalate"),        # boundary <= 90
        (91, "human_review"),    # > 90
        (120, "human_review"),
    ],
)
def test_aging_bucket_ladder(days_overdue, expected_action):
    due_date = date.today() - timedelta(days=days_overdue)
    res = decide_by_aging_bucket(due_date)
    assert res["action_type"] == expected_action

    # Also test via decide_intervention
    case = make_case("invoice_overdue")
    diag = make_diagnosis("unclear")
    txn = make_txn(invoice_due_date=due_date)
    res_interv = decide_intervention(case, diag, txn)
    assert res_interv["action_type"] == expected_action


# ── Test 3: create_promise_to_pay ──────────────────────────────────────────────
def test_create_promise_to_pay():
    dummy_case_id = "test_uuid_123"
    res = create_promise_to_pay(dummy_case_id)
    assert res["case_id"] == dummy_case_id
    assert res["promised_date"] == date.today() + timedelta(days=7)
    assert res["promised_via"] == "portal"
    assert res["status"] == "pending"
