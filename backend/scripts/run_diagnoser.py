"""run_diagnoser.py — Day 4, Task 4
Reads all risk_cases (joined to raw_transactions), runs the Diagnoser on each,
writes one Diagnosis row and one case_events row ('case_diagnosed') per case.

Uses same two-session pattern as run_detector.py:
  Session 1 (read): load risk_cases + raw_transactions, make_transient all objects
  Session 2 (write): insert Diagnosis + CaseEvent objects

Idempotency: clears diagnoses and case_diagnosed events before each run (dev only).
LLM calls include basic retry with exponential backoff on 429 rate-limit responses.
"""
import asyncio
import sys
import ssl
import json
import os
import time
import logging
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, make_transient
from sqlalchemy import select, delete
import uuid as _uuid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

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

from app.models import RawTransaction, RiskCase, Diagnosis, CaseEvent  # noqa: E402
from app.diagnoser.diagnoser import diagnose  # noqa: E402
from groq import Groq  # noqa: E402

groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


def groq_diagnose_with_retry(case, txn, latencies: list, max_retries: int = 3) -> dict:
    """Wraps diagnose() with exponential backoff on Groq 429 rate-limit errors."""
    from groq import RateLimitError
    for attempt in range(max_retries):
        try:
            return diagnose(case, txn, groq_client, latencies)
        except RateLimitError:
            wait = 2 ** attempt * 5  # 5s, 10s, 20s
            logger.warning("Groq 429 rate limit hit, waiting %ds (attempt %d/%d)", wait, attempt + 1, max_retries)
            time.sleep(wait)
    # Final attempt — let it propagate or return unclear on failure
    return diagnose(case, txn, groq_client, latencies)


async def run():
    # ── Step 1: wipe downstream tables (idempotent dev re-run safety) ────────
    async with Session() as session:
        # Only delete case_diagnosed events, not case_detected (those belong to detector)
        await session.execute(
            delete(CaseEvent).where(CaseEvent.event_type == "case_diagnosed")
        )
        await session.execute(delete(Diagnosis))
        await session.commit()
    logger.info("Cleared existing diagnoses and case_diagnosed events")

    # ── Step 2: load risk_cases joined to raw_transactions ────────────────────
    async with Session() as read_session:
        result = await read_session.execute(
            select(RiskCase, RawTransaction).join(
                RawTransaction, RawTransaction.id == RiskCase.transaction_id
            )
        )
        rows = result.all()
        cases_and_txns = [(rc, rt) for rc, rt in rows]
        for rc, rt in cases_and_txns:
            make_transient(rc)
            make_transient(rt)
    logger.info("Loaded %d risk_cases", len(cases_and_txns))

    # ── Step 3: diagnose each case (pure Python, no session) ──────────────────
    llm_latencies: list[int] = []
    diagnosis_objects = []
    event_objects = []

    rule_count = 0
    llm_count = 0
    root_cause_tally: dict[str, int] = {}
    llm_event_payloads: list[dict] = []  # for case_events with latency

    for case, txn in cases_and_txns:
        result = groq_diagnose_with_retry(case, txn, llm_latencies) \
            if (not txn.decline_code
                and case.risk_status not in ("subscription_failed",)
                and txn.failure_reason_text) \
            else diagnose(case, txn, groq_client, llm_latencies)

        root_cause = result["root_cause"]
        confidence_source = result["confidence_source"]

        if confidence_source == "rule":
            rule_count += 1
        else:
            llm_count += 1
        root_cause_tally[root_cause] = root_cause_tally.get(root_cause, 0) + 1

        now = now_ist()
        diag_id = _uuid.uuid4()
        diagnosis_objects.append(Diagnosis(
            id=diag_id,
            case_id=case.id,
            root_cause=root_cause,
            confidence_source=confidence_source,
            reasoning=result.get("reasoning", ""),
            diagnosed_at=now,
        ))

        # case_event payload — include latency_ms for LLM calls
        payload = {
            "root_cause": root_cause,
            "confidence_source": confidence_source,
        }
        if confidence_source == "llm" and llm_latencies:
            payload["latency_ms"] = llm_latencies[-1]

        event_objects.append(CaseEvent(
            id=_uuid.uuid4(),
            case_id=case.id,
            event_type="case_diagnosed",
            event_payload=json.dumps(payload),
            occurred_at=now,
        ))

    # ── Step 4: write all new objects in a fresh session ─────────────────────
    async with Session() as write_session:
        for d in diagnosis_objects:
            write_session.add(d)
        await write_session.flush()  # flush diagnoses before events (no FK dep, but good habit)
        for e in event_objects:
            write_session.add(e)
        await write_session.commit()
    logger.info("Wrote %d diagnoses and %d case_diagnosed events", len(diagnosis_objects), len(event_objects))

    # ── Summary ───────────────────────────────────────────────────────────────
    avg_llm_ms = int(sum(llm_latencies) / len(llm_latencies)) if llm_latencies else 0
    total = rule_count + llm_count

    print(f"\nDiagnosed: {total}")
    print(f"By confidence_source: rule={rule_count}, llm={llm_count}")
    print(f"By root_cause:", end="")
    for rc, count in sorted(root_cause_tally.items()):
        print(f" {rc}={count}", end="")
    print()
    print(f"Average LLM latency: {avg_llm_ms}ms (over {len(llm_latencies)} calls)")


if __name__ == "__main__":
    asyncio.run(run())
