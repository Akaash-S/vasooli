"""
test_webhook_idempotency.py — Day 6, Task 10
Unit tests for Razorpay webhook signature verification and idempotency logic.
"""
import hmac
import hashlib
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.webhooks import verify_signature


def test_verify_signature_valid():
    secret = "test_secret_12345"
    raw_body = b'{"event":"payment_link.paid","payload":{}}'
    expected_sig = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    assert verify_signature(raw_body, expected_sig, secret) is True


def test_verify_signature_invalid_signature():
    secret = "test_secret_12345"
    raw_body = b'{"event":"payment_link.paid","payload":{}}'
    bad_sig = "invalid_signature_hash"

    assert verify_signature(raw_body, bad_sig, secret) is False


def test_verify_signature_tampered_payload():
    secret = "test_secret_12345"
    raw_body = b'{"event":"payment_link.paid","payload":{}}'
    sig = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    tampered_body = b'{"event":"payment_link.paid","payload":{"hacked":true}}'
    assert verify_signature(tampered_body, sig, secret) is False


def test_verify_signature_empty_secret():
    raw_body = b'{"event":"payment_link.paid"}'
    assert verify_signature(raw_body, "sig", "") is False
