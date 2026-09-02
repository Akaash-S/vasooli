"""
run_executor.py — Day 6, Task 9
Batch processor for executing pending interventions.
Selects 5 update_payment_link cases for real Razorpay Payment Link creation (capped at 5).
Simulates all other interventions.
Populates idempotency_key, executed_at, execution_mode on interventions.
Emits 'intervention_executed' case_events audit records.
Checks promises_to_pay status resolution.
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
from sqlalchemy import select, delete, update
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

from app.models import RawTransaction, RiskCase, Diagnosis, Intervention, PromiseToPay, CaseEvent, WebhookEvent  # noqa: E402
from app.executor.executor import execute_intervention, build_idempotency_key  # noqa: E402
from app.executor.promise_resolution import resolve_promise  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


async def run():
    # ── Step 1: load pending interventions joined to cases, diagnoses, txns ──
    # Idempotency guard: skip any intervention that has already been executed (executed_at IS NOT NULL)
    async with Session() as read_session:
        result = await read_session.execute(
            select(Intervention, RiskCase, Diagnosis, RawTransaction)
            .join(RiskCase, RiskCase.id == Intervention.case_id)
            .join(Diagnosis, Diagnosis.case_id == RiskCase.id)
            .join(RawTransaction, RawTransaction.id == RiskCase.transaction_id)
            .where(Intervention.status == "pending", Intervention.executed_at.is_(None))
        )
        rows = result.all()
        quads = [(i, rc, d, rt) for i, rc, d, rt in rows]
        for i, rc, d, rt in quads:
            make_transient(i)
            make_transient(rc)
            make_transient(d)
            make_transient(rt)
    logger.info("Loaded %d pending interventions requiring execution", len(quads))

    if not quads:
        logger.info("No pending interventions to process (all interventions already executed).")
        # Query DB tallies for reporting summary when all rows are already executed
        async with Session() as summary_session:
            all_int_res = await summary_session.execute(select(Intervention))
            all_ints = all_int_res.scalars().all()
            executed_cnt = len([i for i in all_ints if i.status == "executed"])
            queued_cnt = len([i for i in all_ints if i.status == "queued"])

            mode_tally: dict[str, int] = {}
            for i in all_ints:
                mode = i.execution_mode or "unknown"
                mode_tally[mode] = mode_tally.get(mode, 0) + 1

            p2p_res = await summary_session.execute(select(PromiseToPay))
            promises_checked = len(p2p_res.scalars().all())

            wh_res = await summary_session.execute(select(WebhookEvent))
            webhook_count = len(wh_res.scalars().all())

        print(f"\nInterventions processed: {len(all_ints)} (executed={executed_cnt}, queued={queued_cnt})")
        print(f"By execution_mode: real={mode_tally.get('real', 0)}, simulated={mode_tally.get('simulated', 0)}")
        print(f"Promises checked: {promises_checked}, resolved honored=0, broken=0, still pending={promises_checked}")
        print(f"Webhook events received today: {webhook_count}")
        return

    # ── Step 3: Select 5 update_payment_link interventions for demo ───────────
    upl_quads = [q for q in quads if q[0].action_type == "update_payment_link"]

    hard_decline_upl = [q for q in upl_quads if q[2].root_cause == "hard_decline"]
    sub_halted_upl = [q for q in upl_quads if q[2].root_cause == "subscription_halted"]

    selected_cases = set()
    selected_quads = []

    if hard_decline_upl:
        chosen = sorted(hard_decline_upl, key=lambda q: str(q[1].id))[0]
        selected_quads.append(chosen)
        selected_cases.add(chosen[1].id)

    if sub_halted_upl:
        chosen = sorted(sub_halted_upl, key=lambda q: str(q[1].id))[0]
        if chosen[1].id not in selected_cases:
            selected_quads.append(chosen)
            selected_cases.add(chosen[1].id)

    remaining_upl = sorted(
        [q for q in upl_quads if q[1].id not in selected_cases],
        key=lambda q: str(q[1].id),
    )
    for q in remaining_upl:
        if len(selected_quads) < 5:
            selected_quads.append(q)
            selected_cases.add(q[1].id)

    for q in quads:
        if q[1].id in selected_cases:
            q[0].selected_for_demo = True

    logger.info("Selected %d cases for real Payment Link demo", len(selected_cases))

    # ── Step 4: Execute interventions ─────────────────────────────────────────
    real_call_budget = {"payment_links_used": 0, "cap": 5}
    executed_interventions = []
    event_objects = []
    real_link_details = []

    action_type_tally: dict[str, int] = {}
    mode_tally: dict[str, int] = {}

    for intervention, case, diag, txn in quads:
        key = build_idempotency_key(case.id, intervention.action_type, intervention.attempt_number)
        result = execute_intervention(intervention, case, txn, real_call_budget)

        now = now_ist()
        status = result.get("status", "executed")
        mode = result.get("execution_mode", "simulated")
        action = intervention.action_type

        executed_interventions.append({
            "id": intervention.id,
            "status": status,
            "execution_mode": mode,
            "idempotency_key": key,
            "executed_at": now,
        })

        mode_tally[mode] = mode_tally.get(mode, 0) + 1
        action_type_tally[action] = action_type_tally.get(action, 0) + 1

        if mode == "real":
            real_link_details.append({
                "case_id": str(case.id),
                "razorpay_payment_link_id": result.get("razorpay_payment_link_id"),
                "short_url": result.get("short_url"),
                "amount_inr": float(txn.amount_inr),
            })

        event_payload = {
            "action_type": action,
            "execution_mode": mode,
            "attempt_number": intervention.attempt_number,
            "idempotency_key": key,
            "note": result.get("note", ""),
        }
        if "razorpay_payment_link_id" in result:
            event_payload["razorpay_payment_link_id"] = result["razorpay_payment_link_id"]
            event_payload["short_url"] = result["short_url"]

        event_objects.append(CaseEvent(
            id=_uuid.uuid4(),
            case_id=case.id,
            event_type="intervention_executed",
            event_payload=json.dumps(event_payload),
            occurred_at=now,
        ))

    # ── Step 5: Promise-to-pay resolution check ──────────────────────────────
    promises_checked = 0
    honored_count = 0
    broken_count = 0
    pending_count = 0

    async with Session() as read_p2p_session:
        p2p_res = await read_p2p_session.execute(select(PromiseToPay))
        promises = p2p_res.scalars().all()
        promises_checked = len(promises)
        for p in promises:
            new_status = resolve_promise(p, payment_received=False)
            if new_status == "honored":
                honored_count += 1
            elif new_status == "broken":
                broken_count += 1
            else:
                pending_count += 1

    # ── Step 6: Query webhook events count ───────────────────────────────────
    webhook_count = 0
    async with Session() as read_wh_session:
        wh_res = await read_wh_session.execute(select(WebhookEvent))
        webhook_count = len(wh_res.scalars().all())

    # ── Step 7: Write updated interventions and case_events ───────────────────
    async with Session() as write_session:
        for i_data in executed_interventions:
            await write_session.execute(
                update(Intervention)
                .where(Intervention.id == i_data["id"])
                .values(
                    status=i_data["status"],
                    execution_mode=i_data["execution_mode"],
                    idempotency_key=i_data["idempotency_key"],
                    executed_at=i_data["executed_at"],
                )
            )
        for e in event_objects:
            write_session.add(e)
        await write_session.commit()

    logger.info("Wrote %d executed interventions and %d case_events", len(executed_interventions), len(event_objects))

    # ── Summary ───────────────────────────────────────────────────────────────
    executed_cnt = len([i for i in executed_interventions if i["status"] == "executed"])
    queued_cnt = len([i for i in executed_interventions if i["status"] == "queued"])

    print(f"\nInterventions processed: {len(executed_interventions)} (executed={executed_cnt}, queued={queued_cnt})")
    print(f"By execution_mode: real={mode_tally.get('real', 0)}, simulated={mode_tally.get('simulated', 0)}")
    print("By action_type:", end="")
    for act, count in sorted(action_type_tally.items()):
        print(f" {act}={count}", end="")
    print()
    print(f"\nReal Payment Links created ({len(real_link_details)}):")
    for link in real_link_details:
        print(f"  case_id={link['case_id']} -> id={link['razorpay_payment_link_id']} url={link['short_url']} (INR {link['amount_inr']})")
    print(f"\nPromises checked: {promises_checked}, resolved honored={honored_count}, broken={broken_count}, still pending={pending_count}")
    print(f"Webhook events received today: {webhook_count}")


if __name__ == "__main__":
    asyncio.run(run())
