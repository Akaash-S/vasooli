"""
promise_resolution.py — Day 6, Task 8
Promise-to-pay resolution logic.
Determines whether a promise status is 'honored', 'broken', or remains 'pending'.
"""
from datetime import date, datetime


def resolve_promise(promise, payment_received: bool, today=None) -> str:
    """
    Returns new promise status: 'honored' | 'broken' | 'pending' (unchanged).
    """
    if isinstance(today, datetime):
        check_date = today.date()
    elif isinstance(today, date):
        check_date = today
    else:
        check_date = date.today()

    if payment_received:
        return "honored"

    promised = promise.promised_date
    if isinstance(promised, datetime):
        promised = promised.date()

    if check_date > promised:
        return "broken"

    return "pending"
