"""
test_promise_resolution.py — Day 6, Task 10
Unit tests for Promise-to-Pay resolution logic.
"""
import sys
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import MagicMock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.executor.promise_resolution import resolve_promise


def make_promise(promised_date):
    p = MagicMock()
    p.promised_date = promised_date
    return p


def test_resolve_promise_payment_received_honored():
    p = make_promise(date.today() + timedelta(days=7))
    assert resolve_promise(p, payment_received=True) == "honored"


def test_resolve_promise_before_due_date_pending():
    promised = date(2026, 9, 3)
    p = make_promise(promised)
    today = date(2026, 8, 28)
    assert resolve_promise(p, payment_received=False, today=today) == "pending"


def test_resolve_promise_after_due_date_broken():
    promised = date(2026, 8, 25)
    p = make_promise(promised)
    today = date(2026, 8, 28)
    assert resolve_promise(p, payment_received=False, today=today) == "broken"
