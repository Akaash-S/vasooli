"""
inject_failures.py — Day 2, Task 3
Generates 200 failure-injected records from Olist data + synthetic B2B invoices.
Random seed is fixed at 42 for full reproducibility across runs.
Output: data/injected_batch.csv  (gitignored path)
"""
import pandas as pd
import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

random.seed(42)
IST = timezone(timedelta(hours=5, minutes=30))


def load_olist_sample(n=180):
    orders = pd.read_csv("data/raw/olist_orders_dataset.csv")
    payments = pd.read_csv("data/raw/olist_order_payments_dataset.csv")
    merged = orders.merge(payments, on="order_id").dropna(subset=["payment_value"])
    return merged.sample(n=n, random_state=42).reset_index(drop=True)


def rescale_amount(brl_value) -> Decimal:
    return Decimal(round(float(brl_value) * 15.5, 2))


def build_payment_failed(row, decline_bucket) -> dict:
    codes = {
        "soft": ["insufficient_funds", "bank_timeout", "temporary_hold"],
        "hard": ["expired_card", "card_closed"],
        "mandate": ["invalid_mandate"],
    }
    return dict(
        source="olist", order_id=row["order_id"], customer_id=str(uuid.uuid4())[:8],
        amount_inr=rescale_amount(row["payment_value"]),
        payment_method=random.choice(["card", "upi", "netbanking"]),
        payment_status="failed",
        decline_code=random.choice(codes[decline_bucket]),
        checkout_completed=True,
        created_at=datetime.now(IST) - timedelta(days=random.randint(0, 25)),
    )


def build_checkout_abandoned(row, with_note: bool) -> dict:
    notes = ["dropped after OTP screen, unclear if network or user exit",
              "cart abandoned, session timeout, no further data"]
    return dict(
        source="olist", order_id=row["order_id"], customer_id=str(uuid.uuid4())[:8],
        amount_inr=rescale_amount(row["payment_value"]),
        payment_method=random.choice(["card", "upi"]),
        payment_status="pending",
        checkout_completed=False,
        failure_reason_text=random.choice(notes) if with_note else None,
        created_at=datetime.now(IST) - timedelta(days=random.randint(0, 20)),
    )


def build_subscription_failed(row) -> dict:
    return dict(
        source="olist", order_id=row["order_id"], customer_id=str(uuid.uuid4())[:8],
        amount_inr=rescale_amount(row["payment_value"]),
        payment_method="card",
        payment_status="failed",
        checkout_completed=True,
        subscription_id=f"sub_{uuid.uuid4().hex[:12]}",
        subscription_status="halted",
        created_at=datetime.now(IST) - timedelta(days=random.randint(4, 15)),
    )


def build_b2b_invoice(i: int) -> dict:
    aging_bucket = random.choice([(0, 30), (31, 60), (61, 90), (91, 150)])
    age_days = random.randint(*aging_bucket)
    notes = ["client says cheque in transit, unconfirmed",
              "awaiting internal approval on client side, no firm date", None, None]
    return dict(
        source="synthetic_b2b", order_id=f"INV-{1000 + i}", customer_id=f"biz_{uuid.uuid4().hex[:6]}",
        amount_inr=Decimal(random.randint(15000, 400000)),
        payment_method="bank_transfer",
        payment_status="pending",
        checkout_completed=True,
        invoice_due_date=(datetime.now(IST) - timedelta(days=age_days)).date(),
        invoice_status="unpaid",
        failure_reason_text=random.choice(notes),
        created_at=datetime.now(IST) - timedelta(days=age_days + 5),
    )


def main():
    sample = load_olist_sample(n=180)
    idx = 0
    records = []

    # payment_failed: 84 soft + 24 hard + 12 mandate = 120 total (60%)
    for _ in range(84):
        records.append(build_payment_failed(sample.iloc[idx], "soft")); idx += 1
    for _ in range(24):
        records.append(build_payment_failed(sample.iloc[idx], "hard")); idx += 1
    for _ in range(12):
        records.append(build_payment_failed(sample.iloc[idx], "mandate")); idx += 1

    # checkout_abandoned: 30 (15%), half with free-text note
    for i in range(30):
        records.append(build_checkout_abandoned(sample.iloc[idx], with_note=(i % 2 == 0))); idx += 1

    # subscription_failed: 30 (15%)
    for _ in range(30):
        records.append(build_subscription_failed(sample.iloc[idx])); idx += 1

    # synthetic B2B invoices: 20 (10%)
    for i in range(20):
        records.append(build_b2b_invoice(i))

    df = pd.DataFrame(records)
    print(f"Total rows: {df.shape[0]}")
    print("\npayment_status value counts:")
    print(df["payment_status"].value_counts().to_string())
    print("\ncheckout_completed value counts:")
    print(df["checkout_completed"].value_counts().to_string())
    print("\ndecline_code value counts (non-null):")
    print(df["decline_code"].value_counts().to_string())
    print("\nsubscription_status non-null count:", df["subscription_status"].notna().sum())
    print("invoice_due_date non-null count:", df["invoice_due_date"].notna().sum())

    df.to_csv("data/injected_batch.csv", index=False)
    print("\nWritten: data/injected_batch.csv")
    return df


if __name__ == "__main__":
    main()
