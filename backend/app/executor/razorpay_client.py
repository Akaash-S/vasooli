"""
razorpay_client.py — Day 6, Task 4
Real Razorpay Payment Link creation (capped at 5 total calls across batch).
Interacts with Razorpay Test Mode API v1 with rate-limit exponential backoff.
"""
import os
import time
import logging
import requests

logger = logging.getLogger(__name__)

RAZORPAY_BASE = "https://api.razorpay.com/v1"


def create_real_payment_link(case, txn, real_call_budget: dict) -> dict:
    """
    Creates a real Razorpay Payment Link in test mode for a selected demo case.
    Mutates real_call_budget["payment_links_used"] in place upon success.
    Includes exponential backoff retry logic for 429/rate-limiting.
    Falls back to simulated if API call fails after retries.
    """
    key_id = os.environ.get("RAZORPAY_KEY_ID", "")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    auth = (key_id, key_secret)

    payload = {
        "amount": int(txn.amount_inr * 100),  # paise
        "currency": "INR",
        "description": f"Vasooli recovery — case {str(case.id)[:8]}",
        "reference_id": f"vasooli_{str(case.id).replace('-', '')}",
        "notify": {"sms": False, "email": False},  # no real customer notifications
        "reminder_enable": False,
    }

    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        try:
            if attempt > 1:
                time.sleep(2 * attempt)
            resp = requests.post(f"{RAZORPAY_BASE}/payment_links", auth=auth, json=payload, timeout=10)
            if resp.status_code == 429 or (resp.status_code == 400 and "Too many requests" in resp.text):
                logger.warning("Razorpay rate limit hit on attempt %d for case %s, retrying...", attempt, case.id)
                continue

            resp.raise_for_status()
            data = resp.json()
            real_call_budget["payment_links_used"] += 1
            return dict(
                status="executed",
                execution_mode="real",
                razorpay_payment_link_id=data["id"],
                short_url=data["short_url"],
                raw_status=data.get("status", "created"),
            )
        except Exception as exc:
            if attempt == max_attempts:
                logger.error("Razorpay Payment Link API failed for case %s after %d attempts: %s", case.id, attempt, exc)
                from app.executor.executor import simulate_action
                return simulate_action("update_payment_link", case, txn, reason=f"API call failed: {exc}")
            time.sleep(2 * attempt)

    from app.executor.executor import simulate_action
    return simulate_action("update_payment_link", case, txn, reason="API call rate limited")
