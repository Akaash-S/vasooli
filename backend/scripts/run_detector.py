"""run_detector.py — Day 3, Task 3
Reads all raw_transactions from Neon dev, runs detect() on each,
writes risk_cases + case_events for every at-risk transaction.

Read path uses scalars with explicit make_transient() to detach objects.
Write path uses a completely fresh session with only new objects.

Idempotency: clears risk_cases and case_events before each run (dev only).
"""
import asyncio
import sys
import ssl
from pathlib import Path
from urllib.parse import urlparse, urlunparse
import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, make_transient
from sqlalchemy import select, delete

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

raw_url = os.environ["DATABASE_URL"]
if raw_url.startswith("postgresql://"):
    async_url = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif raw_url.startswith("postgres://"):
    async_url = raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
else:
    async_url = raw_url
parsed = urlparse(async_url)
clean_url = urlunparse(parsed._replace(query=""))

ssl_ctx = ssl.create_default_context()
engine = create_async_engine(clean_url, echo=False, connect_args={"ssl": ssl_ctx})
Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

from app.models import RawTransaction, RiskCase, CaseEvent  # noqa: E402
from app.detector.detector import detect, build_risk_case_and_event  # noqa: E402


async def run():
    # Step 1: wipe downstream tables (idempotent re-run safety)
    async with Session() as session:
        await session.execute(delete(CaseEvent))
        await session.execute(delete(RiskCase))
        await session.commit()

    # Step 2: read transactions — use make_transient to fully detach from any session
    async with Session() as read_session:
        result = await read_session.execute(select(RawTransaction))
        transactions = result.scalars().all()
        for txn in transactions:
            make_transient(txn)  # detach: clears session identity map reference

    # Step 3: detect (pure Python, no session)
    detected = 0
    healthy = 0
    by_status: dict[str, int] = {}
    new_risk_cases = []
    new_case_events = []

    for txn in transactions:
        risk_status = detect(txn)
        if risk_status is None:
            healthy += 1
            continue
        risk_case, case_event = build_risk_case_and_event(txn, risk_status)
        new_risk_cases.append(risk_case)
        new_case_events.append(case_event)
        detected += 1
        by_status[risk_status] = by_status.get(risk_status, 0) + 1

    # Step 4: write only the new objects in a fresh session
    async with Session() as write_session:
        for rc in new_risk_cases:
            write_session.add(rc)
        await write_session.flush()  # flush risk_cases first so FKs resolve
        for ce in new_case_events:
            write_session.add(ce)
        await write_session.commit()

    print(f"Detector run complete.")
    print(f"  Detected (risk cases created): {detected}")
    print(f"  Healthy (no risk case):        {healthy}")
    print(f"  Breakdown by risk_status:")
    for status, count in sorted(by_status.items()):
        print(f"    {status}: {count}")


if __name__ == "__main__":
    asyncio.run(run())
