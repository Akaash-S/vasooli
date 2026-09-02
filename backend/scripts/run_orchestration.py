"""
run_orchestration.py — Day 7, Task 8
Batch orchestrator for invoking the compiled LangGraph pipeline across all 200 cases.
Deterministic seed (random.Random(42)) and sorted transaction processing.
Pre-loads batch data into _cache for ultra-fast, zero-network-overhead graph execution.
"""
import sys
import json
import os
import random
import logging
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.orchestration.graph import compiled_graph, CaseState
from app.models import (
    RawTransaction, RiskCase, Diagnosis, Intervention,
    RecoveryOutcome, WebhookEvent, CaseEvent
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

raw_url = os.environ["DATABASE_URL"]
if "sslmode=" not in raw_url:
    connect_args = {"sslmode": "require"}
else:
    connect_args = {}

engine = create_engine(raw_url, connect_args=connect_args, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def run():
    session = SessionLocal()
    batch_rng = random.Random(42)

    logger.info("Pre-loading batch data into in-memory cache...")
    raw_txns = session.query(RawTransaction).all()
    risk_cases = session.query(RiskCase).all()
    diagnoses = session.query(Diagnosis).all()
    interventions = session.query(Intervention).all()
    outcomes = session.query(RecoveryOutcome).all()
    we = session.query(WebhookEvent).filter(WebhookEvent.razorpay_event_id == "TVB8GHU0GvhUjl").first()

    cache_dict = {
        "txns": {str(t.id): t for t in raw_txns},
        "cases": {str(rc.transaction_id): rc for rc in risk_cases},
        "diagnoses": {str(d.case_id): d for d in diagnoses},
        "interventions": {str(i.case_id): i for i in interventions},
        "outcomes": {str(ro.case_id): ro for ro in outcomes},
        "we": we,
        "pending_writes": [],
    }

    # Sort transaction IDs deterministically
    txn_ids = sorted(list(cache_dict["txns"].keys()))
    logger.info("Loaded %d transactions for orchestration graph invocation", len(txn_ids))

    mismatch_flags_total = 0
    outcomes_tally = {"recovered": 0, "escalated": 0, "abandoned": 0}
    source_tally = {"real": 0, "simulated": 0}
    total_amount_recovered = Decimal("0")
    real_case_info = None

    for txn_id in txn_ids:
        initial_state: CaseState = {
            "transaction_id": txn_id,
            "case_id": None,
            "risk_status": None,
            "diagnosis": None,
            "proposed_intervention": None,
            "final_intervention": None,
            "execution_result": None,
            "resolution": None,
            "mismatch_flags": [],
            "_session": session,
            "_rng": batch_rng,
            "_cache": cache_dict,
        }

        final_state = compiled_graph.invoke(initial_state)

        mismatches = final_state.get("mismatch_flags", [])
        mismatch_flags_total += len(mismatches)
        if mismatches:
            logger.warning("Case %s generated mismatches: %s", final_state.get("case_id"), mismatches)

        res = final_state.get("resolution", {})
        if res:
            outcome = res.get("outcome", "unknown")
            outcomes_tally[outcome] = outcomes_tally.get(outcome, 0) + 1

            source = res.get("resolution_source", "simulated")
            source_tally[source] = source_tally.get(source, 0) + 1

            amt = Decimal(str(res.get("amount_recovered", 0)))
            total_amount_recovered += amt

            if source == "real":
                real_case_info = {
                    "case_id": final_state.get("case_id"),
                    "amount_recovered": amt,
                    "resolution_source": source,
                    "note": res.get("note"),
                }

    # Persist pending writes in single bulk commit
    if cache_dict["pending_writes"]:
        logger.info("Bulk persisting %d recovery_outcomes and case_events...", len(cache_dict["pending_writes"]))
        for ro_row, ce_row in cache_dict["pending_writes"]:
            session.add(ro_row)
            session.add(ce_row)
        session.commit()

    session.close()

    # Print Summary
    print("\n======================================================================")
    print("                VASOOLI ORCHESTRATION PIPELINE SUMMARY                 ")
    print("======================================================================")
    print(f"Graph invocations: {len(txn_ids)}")
    print(f"Mismatch flags raised: {mismatch_flags_total}")
    print(f"Resolve outcomes: recovered={outcomes_tally.get('recovered', 0)}, escalated={outcomes_tally.get('escalated', 0)}, abandoned={outcomes_tally.get('abandoned', 0)}")
    print(f"By resolution_source: real={source_tally.get('real', 0)}, simulated={source_tally.get('simulated', 0)}")
    print(f"Total amount_recovered: INR {total_amount_recovered:,.2f}")
    if real_case_info:
        print(f"Real recovered case confirmed: case_id={real_case_info['case_id']}, amount=INR {real_case_info['amount_recovered']}, resolution_source={real_case_info['resolution_source']}")

    print("======================================================================\n")


if __name__ == "__main__":
    run()
