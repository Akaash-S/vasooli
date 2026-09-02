"""
test_executor.py — Day 6, Task 10
Unit tests for Executor module and Razorpay client interactions.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.executor.executor import (
    execute_intervention,
    build_idempotency_key,
    simulate_action,
    execute_mandate_retry,
)
from app.executor.razorpay_client import create_real_payment_link


def make_txn(amount_inr=1500.0):
    t = MagicMock()
    t.amount_inr = amount_inr
    return t


def make_case(case_id="case_uuid_123"):
    c = MagicMock()
    c.id = case_id
    return c


def make_intervention(action_type="update_payment_link", attempt_number=1, selected_for_demo=False):
    i = MagicMock()
    i.action_type = action_type
    i.attempt_number = attempt_number
    i.scheduled_at = None
    i.selected_for_demo = selected_for_demo
    return i


# ── Test 1: update_payment_link selected for demo with budget → real API call ────
@patch("requests.post")
def test_update_payment_link_real_api_call(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "id": "plink_test123",
        "short_url": "https://rzp.io/i/test123",
        "status": "created",
    }
    mock_post.return_value = mock_resp

    case = make_case()
    txn = make_txn(amount_inr=2500.0)
    intervention = make_intervention(selected_for_demo=True)
    budget = {"payment_links_used": 0, "cap": 5}

    res = execute_intervention(intervention, case, txn, budget)
    assert res["status"] == "executed"
    assert res["execution_mode"] == "real"
    assert res["razorpay_payment_link_id"] == "plink_test123"
    assert res["short_url"] == "https://rzp.io/i/test123"
    assert budget["payment_links_used"] == 1

    # Verify amount in paise (2500 * 100 = 250000)
    mock_post.assert_called_once()
    kwargs = mock_post.call_args.kwargs
    assert kwargs["json"]["amount"] == 250000


# ── Test 2: update_payment_link NOT selected for demo → simulated ──────────
@patch("requests.post")
def test_update_payment_link_not_selected_simulated(mock_post):
    case = make_case()
    txn = make_txn()
    intervention = make_intervention(selected_for_demo=False)
    budget = {"payment_links_used": 0, "cap": 5}

    res = execute_intervention(intervention, case, txn, budget)
    assert res["execution_mode"] == "simulated"
    assert budget["payment_links_used"] == 0
    mock_post.assert_not_called()


# ── Test 3: Budget exhausted → falls back to simulated ───────────────────────
@patch("requests.post")
def test_budget_exhausted_falls_back_to_simulated(mock_post):
    case = make_case()
    txn = make_txn()
    intervention = make_intervention(selected_for_demo=True)
    budget = {"payment_links_used": 5, "cap": 5}

    res = execute_intervention(intervention, case, txn, budget)
    assert res["execution_mode"] == "simulated"
    assert budget["payment_links_used"] == 5
    mock_post.assert_not_called()


# ── Test 4: retry action always simulated ──────────────────────────────────────
@patch("requests.post")
def test_retry_always_simulated(mock_post):
    case = make_case()
    txn = make_txn(amount_inr=50000.0)
    intervention = make_intervention(action_type="retry")
    budget = {"payment_links_used": 0, "cap": 5}

    res = execute_intervention(intervention, case, txn, budget)
    assert res["execution_mode"] == "simulated"
    assert res["status"] == "executed"
    mock_post.assert_not_called()


# ── Test 5: mandate_retry_sequence calls sequencer ───────────────────────────
def test_mandate_retry_sequence_calls_sequencer():
    case = make_case()
    txn = make_txn()
    intervention = make_intervention(action_type="mandate_retry_sequence")
    budget = {"payment_links_used": 0, "cap": 5}

    res = execute_intervention(intervention, case, txn, budget)
    assert res["execution_mode"] == "simulated"
    assert "scheduled_not_before" in res["detail"]


# ── Test 6: human_review and promise_to_pay return no-op/queued without API ───
@patch("requests.post")
def test_noop_actions(mock_post):
    case = make_case()
    txn = make_txn()
    budget = {"payment_links_used": 0, "cap": 5}

    res_p2p = execute_intervention(make_intervention("promise_to_pay"), case, txn, budget)
    assert res_p2p["execution_mode"] == "simulated"

    res_hr = execute_intervention(make_intervention("human_review"), case, txn, budget)
    assert res_hr["status"] == "queued"

    mock_post.assert_not_called()


# ── Test 7: build_idempotency_key is deterministic ───────────────────────────
def test_build_idempotency_key_format():
    key1 = build_idempotency_key("c1", "retry", 1)
    key2 = build_idempotency_key("c1", "retry", 2)
    key3 = build_idempotency_key("c1", "retry", 1)

    assert key1 == "c1:retry:1"
    assert key2 == "c1:retry:2"
    assert key1 == key3
    assert key1 != key2
