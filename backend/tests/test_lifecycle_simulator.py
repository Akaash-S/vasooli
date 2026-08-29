import random
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.resolver.lifecycle_simulator import (
    simulate_lifecycle,
    MAX_CARD_RETRY_ATTEMPTS,
    MAX_MANDATE_RETRY_ATTEMPTS,
)


def test_determinism():
    rng1 = random.Random(42)
    res1 = simulate_lifecycle("retry", Decimal("1000.00"), rng1)

    rng2 = random.Random(42)
    res2 = simulate_lifecycle("retry", Decimal("1000.00"), rng2)

    assert res1 == res2


def test_retry_max_attempts_cap():
    for seed in range(100):
        rng = random.Random(seed)
        res = simulate_lifecycle("retry", Decimal("500.00"), rng)
        if res["simulated_attempts"] is not None:
            assert res["simulated_attempts"] <= MAX_CARD_RETRY_ATTEMPTS


def test_mandate_retry_max_attempts_cap():
    for seed in range(100):
        rng = random.Random(seed)
        res = simulate_lifecycle("mandate_retry_sequence", Decimal("2000.00"), rng)
        if res["simulated_attempts"] is not None:
            assert res["simulated_attempts"] <= MAX_MANDATE_RETRY_ATTEMPTS


def test_promise_to_pay_and_human_review_bypass_rng():
    mock_rng = MagicMock()
    res_p2p = simulate_lifecycle("promise_to_pay", Decimal("1500.00"), mock_rng)
    res_hr = simulate_lifecycle("human_review", Decimal("1500.00"), mock_rng)

    assert res_p2p["outcome"] == "escalated"
    assert res_hr["outcome"] == "escalated"
    assert mock_rng.random.call_count == 0


def test_unrecovered_retry_terminates_as_escalated():
    # Force failure with rng that always returns > p
    mock_rng = MagicMock()
    mock_rng.random.return_value = 0.99
    res = simulate_lifecycle("retry", Decimal("1000.00"), mock_rng)
    assert res["outcome"] == "escalated"


def test_unrecovered_nudge_terminates_as_abandoned():
    mock_rng = MagicMock()
    mock_rng.random.return_value = 0.99
    res = simulate_lifecycle("nudge", Decimal("1000.00"), mock_rng)
    assert res["outcome"] == "abandoned"
