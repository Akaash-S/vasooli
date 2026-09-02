"""
test_stopping_rules.py — Day 5, Task 8
Unit tests for StoppingRuleEngine and MandateRetrySequencer.
Covers all 7 required test cases from Task 8, explicitly proving that
Rule 2 (ethical stopping rule, prior_attempts=2) and Rule 3 (hard retry cap)
are independently reachable and fire under distinct conditions.
"""
import sys
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.stopping_rules.stopping_rule_engine import (
    enforce,
    MAX_CARD_RETRIES,
    MAX_MANDATE_RETRIES,
    AFA_THRESHOLD_INR,
    CONSECUTIVE_FAILURE_HUMAN_REVIEW,
)
from app.stopping_rules.mandate_retry_sequencer import MandateRetrySequencer


def make_txn(amount_inr=1000):
    t = MagicMock()
    t.amount_inr = amount_inr
    return t


def make_case(risk_status="payment_failed"):
    c = MagicMock()
    c.risk_status = risk_status
    return c


def make_diagnosis(root_cause="soft_decline"):
    d = MagicMock()
    d.root_cause = root_cause
    return d


# ── Test 1: soft_decline retry < 15,000 at prior_attempts=0 → passes through ─
def test_rule1_afa_under_threshold_passes():
    proposed = dict(action_type="retry", attempt_number=1)
    case = make_case()
    diag = make_diagnosis("soft_decline")
    txn = make_txn(amount_inr=5000)

    result = enforce(proposed, case, diag, txn, prior_attempts=0)
    assert result["action_type"] == "retry"
    assert result["required_notice_hours"] == 24
    assert "stopping_reason" not in result


# ── Test 2: retry at >= 15,000 → downgraded to human_review with AFA reason ────
def test_rule1_afa_over_threshold_downgraded():
    proposed = dict(action_type="retry", attempt_number=1)
    case = make_case()
    diag = make_diagnosis("soft_decline")
    txn = make_txn(amount_inr=15000)

    result = enforce(proposed, case, diag, txn, prior_attempts=0)
    assert result["action_type"] == "human_review"
    assert "AFA threshold" in result["stopping_reason"]


# ── Test 3: retry at prior_attempts=2 (< 15k) → Rule 2 ethical stopping rule ─
def test_rule2_ethical_consecutive_failure_threshold():
    """
    Proves Rule 2 (ethical stopping rule) fires independently at prior_attempts=2
    (CONSECUTIVE_FAILURE_HUMAN_REVIEW) with the ethical de-escalation stopping_reason,
    before the hard cap (Rule 3 at MAX_CARD_RETRIES=3) is reached.
    """
    proposed = dict(action_type="retry", attempt_number=1)
    case = make_case()
    diag = make_diagnosis("soft_decline")
    txn = make_txn(amount_inr=5000)

    result = enforce(proposed, case, diag, txn, prior_attempts=2)
    assert result["action_type"] == "human_review"
    assert "consecutive-failure threshold reached" in result["stopping_reason"]


# ── Test 4: retry at prior_attempts=3 (< 15k) → downgraded to human_review ───
def test_rule2_and_3_retry_at_hard_cap():
    proposed = dict(action_type="retry", attempt_number=1)
    case = make_case()
    diag = make_diagnosis("soft_decline")
    txn = make_txn(amount_inr=5000)

    result = enforce(proposed, case, diag, txn, prior_attempts=3)
    assert result["action_type"] == "human_review"
    # Rule 2 handles prior_attempts >= 2, so it intercepts prior_attempts=3 as well
    assert "stopping_reason" in result


# ── Test 5: mandate_retry_sequence at prior_attempts=8 → Rule 3 max retry cap ─
def test_rule3_mandate_max_retry_cap_isolated():
    """
    Isolated test for Rule 3 (hard retry cap). Rule 2 only targets 'retry' actions,
    so 'mandate_retry_sequence' bypasses Rule 2 completely and is gated purely
    by Rule 3 at MAX_MANDATE_RETRIES=8.
    """
    proposed = dict(action_type="mandate_retry_sequence", attempt_number=1)
    case = make_case()
    diag = make_diagnosis("mandate_expired")
    txn = make_txn(amount_inr=5000)

    # prior_attempts=7 passes
    res_pass = enforce(proposed, case, diag, txn, prior_attempts=7)
    assert res_pass["action_type"] == "mandate_retry_sequence"

    # prior_attempts=8 hits Rule 3 cap
    res_cap = enforce(proposed, case, diag, txn, prior_attempts=8)
    assert res_cap["action_type"] == "human_review"
    assert "max retry cap (8) reached for mandate_retry_sequence" in res_cap["stopping_reason"]


# ── Test 6: non-retry actions (promise_to_pay, escalate) at >= 15k → pass ────
def test_rule1_ignores_non_retry_actions():
    case = make_case("invoice_overdue")
    diag = make_diagnosis("b2b_dispute")
    txn = make_txn(amount_inr=50000)

    p2p_prop = dict(action_type="promise_to_pay", attempt_number=1)
    res_p2p = enforce(p2p_prop, case, diag, txn, prior_attempts=0)
    assert res_p2p["action_type"] == "promise_to_pay"
    assert "stopping_reason" not in res_p2p

    esc_prop = dict(action_type="escalate", attempt_number=1)
    res_esc = enforce(esc_prop, case, diag, txn, prior_attempts=0)
    assert res_esc["action_type"] == "escalate"
    assert "stopping_reason" not in res_esc


# ── Test 7: MandateRetrySequencer.next_retry_slot at attempt_number=9 ────────
def test_mandate_retry_sequencer_exhausted():
    sequencer = MandateRetrySequencer()
    now = datetime.now(timezone.utc)

    # attempt_number=1 -> valid next slot 24h later
    slot = sequencer.next_retry_slot(now, attempt_number=1)
    assert slot["action_type"] == "mandate_retry_sequence"
    assert slot["attempt_number"] == 2

    # attempt_number=9 (> MAX_ATTEMPTS=8) -> human_review
    exhausted = sequencer.next_retry_slot(now, attempt_number=9)
    assert exhausted["action_type"] == "human_review"
    assert "mandate retry attempts exhausted" in exhausted["stopping_reason"]
