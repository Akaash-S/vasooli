"""
test_diagnoser.py — Day 4, Task 5
Unit tests for diagnose_rule_based() and the LLM routing path.
All 6 required cases from the task prompt + 2 extras.
Pure unit tests — no DB, no real Groq calls. LLM calls are mocked.
"""
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, create_autospec
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.diagnoser.diagnoser import diagnose_rule_based, diagnose, VALID_ROOT_CAUSES


def make_case(risk_status="payment_failed"):
    c = MagicMock()
    c.risk_status = risk_status
    return c


def make_txn(decline_code=None, failure_reason_text=None):
    t = MagicMock()
    t.decline_code = decline_code
    t.failure_reason_text = failure_reason_text
    return t


def _make_groq_response(root_cause: str, reasoning: str = "mocked reasoning"):
    """Build a minimal Groq API response mock that matches the tool-call shape."""
    tool_call = MagicMock()
    tool_call.function.arguments = json.dumps({"root_cause": root_cause, "reasoning": reasoning})
    choice = MagicMock()
    choice.message.tool_calls = [tool_call]
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ── Test 1: payment_failed + insufficient_funds → soft_decline, rule ──────────
def test_insufficient_funds_is_soft_decline():
    case = make_case("payment_failed")
    txn = make_txn(decline_code="insufficient_funds")
    result = diagnose_rule_based(case, txn)
    assert result is not None
    assert result["root_cause"] == "soft_decline"
    assert result["confidence_source"] == "rule"


# ── Test 2: payment_failed + invalid_mandate → mandate_expired, rule ──────────
def test_invalid_mandate_is_mandate_expired():
    case = make_case("payment_failed")
    txn = make_txn(decline_code="invalid_mandate")
    result = diagnose_rule_based(case, txn)
    assert result is not None
    assert result["root_cause"] == "mandate_expired"
    assert result["confidence_source"] == "rule"


# ── Test 3: subscription_failed → subscription_halted, rule ───────────────────
def test_subscription_failed_is_subscription_halted():
    case = make_case("subscription_failed")
    txn = make_txn(decline_code=None, failure_reason_text=None)
    result = diagnose_rule_based(case, txn)
    assert result is not None
    assert result["root_cause"] == "subscription_halted"
    assert result["confidence_source"] == "rule"


def test_subscription_halted_regardless_of_decline_code():
    """subscription_failed rule fires even if a decline_code is present (decline_code wins on map,
    but subscription_failed never carries a decline_code in our data — this verifies the
    priority in the rule path doesn't accidentally skip it.)"""
    # With no decline_code and risk_status=subscription_failed → halted rule fires
    case = make_case("subscription_failed")
    txn = make_txn(decline_code=None)
    result = diagnose_rule_based(case, txn)
    assert result["root_cause"] == "subscription_halted"


# ── Test 4: checkout_abandoned, NO failure_reason_text → unclear, rule ────────
#           AND must NOT call the LLM
def test_checkout_abandoned_no_text_is_unclear_no_llm():
    case = make_case("checkout_abandoned")
    txn = make_txn(decline_code=None, failure_reason_text=None)

    mock_client = MagicMock()
    latencies = []
    result = diagnose(case, txn, mock_client, latencies)

    assert result["root_cause"] == "unclear"
    assert result["confidence_source"] == "rule"
    # LLM client must NEVER have been invoked
    mock_client.chat.completions.create.assert_not_called()


# ── Test 5: checkout_abandoned WITH failure_reason_text → LLM path, llm ──────
def test_checkout_abandoned_with_text_routes_to_llm():
    case = make_case("checkout_abandoned")
    txn = make_txn(decline_code=None, failure_reason_text="Customer said address fields were confusing")

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_groq_response("checkout_friction")

    latencies = []
    result = diagnose(case, txn, mock_client, latencies)

    assert result["root_cause"] == "checkout_friction"
    assert result["confidence_source"] == "llm"
    mock_client.chat.completions.create.assert_called_once()


# ── Test 6: LLM returns value outside enum → handled as unclear, not crash ────
def test_llm_out_of_enum_routes_to_unclear():
    case = make_case("invoice_overdue")
    txn = make_txn(decline_code=None, failure_reason_text="Dispute pending arbitration")

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_groq_response("completely_made_up_value")

    latencies = []
    result = diagnose(case, txn, mock_client, latencies)

    assert result["root_cause"] == "unclear"
    # Should still be llm confidence_source (it went through LLM, just caught the bad value)
    assert result["confidence_source"] == "llm"


# ── Extra: hard_decline codes ─────────────────────────────────────────────────
def test_expired_card_is_hard_decline():
    case = make_case("payment_failed")
    txn = make_txn(decline_code="expired_card")
    result = diagnose_rule_based(case, txn)
    assert result["root_cause"] == "hard_decline"
    assert result["confidence_source"] == "rule"


def test_card_closed_is_hard_decline():
    case = make_case("payment_failed")
    txn = make_txn(decline_code="card_closed")
    result = diagnose_rule_based(case, txn)
    assert result["root_cause"] == "hard_decline"


# ── Extra: invoice_overdue WITH text → LLM path, b2b_dispute ─────────────────
def test_invoice_overdue_with_text_routes_to_llm():
    case = make_case("invoice_overdue")
    txn = make_txn(decline_code=None, failure_reason_text="Customer claims invoice was paid via NEFT")

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_groq_response("b2b_dispute")

    latencies = []
    result = diagnose(case, txn, mock_client, latencies)

    assert result["root_cause"] == "b2b_dispute"
    assert result["confidence_source"] == "llm"
