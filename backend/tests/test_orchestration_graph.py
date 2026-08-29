from unittest.mock import MagicMock, patch
from decimal import Decimal

from app.orchestration.graph import (
    detect_node,
    route_after_decide,
    execute_node,
    CaseState,
)


def test_detect_node_mismatch_flagging():
    mock_txn = MagicMock()
    mock_txn.subscription_id = None
    mock_txn.invoice_due_date = None
    mock_txn.checkout_completed = True
    mock_txn.payment_status = "failed"  # detect(txn) returns "payment_failed"

    mock_rc = MagicMock()
    mock_rc.id = "test-case-id"
    mock_rc.risk_status = "checkout_abandoned"  # mismatch with stored

    cache = {
        "txns": {"tx-1": mock_txn},
        "cases": {"tx-1": mock_rc},
    }

    state: CaseState = {
        "transaction_id": "tx-1",
        "case_id": None,
        "risk_status": None,
        "diagnosis": None,
        "proposed_intervention": None,
        "final_intervention": None,
        "execution_result": None,
        "resolution": None,
        "mismatch_flags": [],
        "_session": None,
        "_rng": None,
        "_cache": cache,
    }

    res_state = detect_node(state)
    assert len(res_state["mismatch_flags"]) == 1
    assert "detect mismatch" in res_state["mismatch_flags"][0]
    assert res_state["risk_status"] == "checkout_abandoned"  # stored row is NOT overwritten


def test_routing_after_decide():
    human_review_state: CaseState = {
        "transaction_id": "tx-1",
        "case_id": "c-1",
        "risk_status": None,
        "diagnosis": None,
        "proposed_intervention": None,
        "final_intervention": {"action_type": "human_review"},
        "execution_result": None,
        "resolution": None,
        "mismatch_flags": [],
        "_session": None,
        "_rng": None,
        "_cache": None,
    }
    assert route_after_decide(human_review_state) == "resolve"

    retry_state: CaseState = {
        "transaction_id": "tx-1",
        "case_id": "c-1",
        "risk_status": None,
        "diagnosis": None,
        "proposed_intervention": None,
        "final_intervention": {"action_type": "retry"},
        "execution_result": None,
        "resolution": None,
        "mismatch_flags": [],
        "_session": None,
        "_rng": None,
        "_cache": None,
    }
    assert route_after_decide(retry_state) == "execute"


def test_execute_node_is_read_only_and_never_calls_razorpay():
    mock_interv = MagicMock()
    mock_interv.status = "executed"
    mock_interv.execution_mode = "simulated"
    mock_interv.idempotency_key = "idemp-key-1"
    mock_interv.executed_at = None

    cache = {
        "interventions": {"c-1": mock_interv},
    }

    state: CaseState = {
        "transaction_id": "tx-1",
        "case_id": "c-1",
        "risk_status": None,
        "diagnosis": None,
        "proposed_intervention": None,
        "final_intervention": None,
        "execution_result": None,
        "resolution": None,
        "mismatch_flags": [],
        "_session": None,
        "_rng": None,
        "_cache": cache,
    }

    with patch("app.executor.executor.create_real_payment_link") as mock_create_link:
        res_state = execute_node(state)
        assert mock_create_link.call_count == 0
        assert res_state["execution_result"]["status"] == "executed"
        assert res_state["execution_result"]["idempotency_key"] == "idemp-key-1"
