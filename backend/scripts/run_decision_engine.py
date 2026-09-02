"""run_decision_engine.py — Day 5, Task 7
Reads all 200 risk_cases (joined to diagnoses and raw_transactions),
runs DecisionEngine then StoppingRuleEngine (with prior_attempts=0),
populates interventions, promises_to_pay, and case_events (intervention_decided).

Uses two-session pattern (same as run_detector.py & run_diagnoser.py) for ORM safety.
Idempotency: clears interventions, promises_to_pay, and intervention_decided events before run.
"""
import asyncio
import sys
import ssl
import json
import os
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

from app.models import RawTransaction, RiskCase, Diagnosis, Intervention, PromiseToPay, CaseEvent  # noqa: E402
from app.decision_engine.decision_engine import decide_intervention, create_promise_to_pay  # noqa: E402
from app.stopping_rules.stopping_rule_engine import enforce  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


async def run():
    # ── Step 1: wipe downstream tables (idempotent dev re-run safety) ────────
    async with Session() as session:
        await session.execute(
            delete(CaseEvent).where(CaseEvent.event_type == "intervention_decided")
        )
        await session.execute(delete(PromiseToPay))
        await session.execute(delete(Intervention))
        await session.commit()
    logger.info("Cleared existing interventions, promises_to_pay, and intervention_decided events")

    # ── Step 2: load risk_cases joined to diagnoses and raw_transactions ──────
    async with Session() as read_session:
        result = await read_session.execute(
            select(RiskCase, Diagnosis, RawTransaction)
            .join(Diagnosis, Diagnosis.case_id == RiskCase.id)
            .join(RawTransaction, RawTransaction.id == RiskCase.transaction_id)
        )
        rows = result.all()
        cases_diag_txns = [(rc, diag, rt) for rc, diag, rt in rows]
        for rc, diag, rt in cases_diag_txns:
            make_transient(rc)
            make_transient(diag)
            make_transient(rt)
    logger.info("Loaded %d risk_cases with diagnoses and transactions", len(cases_diag_txns))

    # ── Step 3: decide and enforce for each case ─────────────────────────────
    intervention_objects = []
    promise_objects = []
    event_objects = []

    action_type_tally: dict[str, int] = {}
    downgraded_count = 0
    afa_gate_count = 0

    for case, diagnosis, txn in cases_diag_txns:
        proposed = decide_intervention(case, diagnosis, txn)
        enforced = enforce(proposed, case, diagnosis, txn, prior_attempts=0)

        is_downgraded = proposed["action_type"] != enforced["action_type"]
        if is_downgraded:
            downgraded_count += 1
            if "AFA threshold" in enforced.get("stopping_reason", ""):
                afa_gate_count += 1

        action_type = enforced["action_type"]
        action_type_tally[action_type] = action_type_tally.get(action_type, 0) + 1

        now = now_ist()
        interv_id = _uuid.uuid4()
        intervention_objects.append(Intervention(
            id=interv_id,
            case_id=case.id,
            action_type=action_type,
            scheduled_at=enforced.get("scheduled_not_before"),
            attempt_number=enforced.get("attempt_number", 1),
            status="pending",
        ))

        if action_type == "promise_to_pay":
            p2p_data = create_promise_to_pay(case.id)
            promise_objects.append(PromiseToPay(
                id=_uuid.uuid4(),
                case_id=p2p_data["case_id"],
                promised_date=p2p_data["promised_date"],
                promised_via=p2p_data["promised_via"],
                status=p2p_data["status"],
                recorded_at=p2p_data["recorded_at"],
            ))

        event_payload = {
            "proposed_action": proposed["action_type"],
            "enforced_action": action_type,
            "stopping_reason": enforced.get("stopping_reason"),
            "downgraded": is_downgraded,
        }
        if "required_notice_hours" in enforced:
            event_payload["required_notice_hours"] = enforced["required_notice_hours"]

        event_objects.append(CaseEvent(
            id=_uuid.uuid4(),
            case_id=case.id,
            event_type="intervention_decided",
            event_payload=json.dumps(event_payload),
            occurred_at=now,
        ))

    # ── Step 4: write all new objects in a fresh session ─────────────────────
    async with Session() as write_session:
        for i in intervention_objects:
            write_session.add(i)
        await write_session.flush()
        for p in promise_objects:
            write_session.add(p)
        for e in event_objects:
            write_session.add(e)
        await write_session.commit()

    logger.info(
        "Wrote %d interventions, %d promises_to_pay, and %d intervention_decided events",
        len(intervention_objects),
        len(promise_objects),
        len(event_objects),
    )

    # ── Summary ───────────────────────────────────────────────────────────────
    total = len(intervention_objects)
    print(f"\nInterventions created: {total}")
    print("By action_type:", end="")
    for act, count in sorted(action_type_tally.items()):
        print(f" {act}={count}", end="")
    print()
    print(f"Cases downgraded by StoppingRuleEngine: {downgraded_count}")
    print(f"Cases hitting the AFA threshold gate: {afa_gate_count}")
    print(f"promises_to_pay rows created: {len(promise_objects)}")


if __name__ == "__main__":
    asyncio.run(run())
