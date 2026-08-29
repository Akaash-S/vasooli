import json
import uuid
import random
from datetime import datetime, timezone
from decimal import Decimal
from typing import TypedDict, Optional, List, Any

from langgraph.graph import StateGraph, END

from app.detector.detector import detect
from app.diagnoser.diagnoser import diagnose_rule_based
from app.decision_engine.decision_engine import decide_intervention
from app.stopping_rules.stopping_rule_engine import enforce
from app.resolver.lifecycle_simulator import simulate_lifecycle
from app.resolver.real_outcomes import get_real_outcome
from app.models import (
    RawTransaction, RiskCase, Diagnosis, Intervention,
    RecoveryOutcome, WebhookEvent, CaseEvent
)


class CaseState(TypedDict):
    transaction_id: str
    case_id: Optional[str]
    risk_status: Optional[str]
    diagnosis: Optional[dict]
    proposed_intervention: Optional[dict]
    final_intervention: Optional[dict]
    execution_result: Optional[dict]
    resolution: Optional[dict]
    mismatch_flags: list
    _session: Optional[Any]
    _rng: Optional[Any]
    _cache: Optional[dict]


def detect_node(state: CaseState) -> CaseState:
    session = state.get("_session")
    cache = state.get("_cache")
    flags = list(state.get("mismatch_flags", []))
    txn_id_str = str(state["transaction_id"])
    try:
        txn_uuid = uuid.UUID(txn_id_str) if isinstance(state["transaction_id"], str) else state["transaction_id"]
    except ValueError:
        txn_uuid = state["transaction_id"]


    if cache:
        txn = cache["txns"].get(txn_id_str)
        rc = cache["cases"].get(txn_id_str)
    elif session:
        txn = session.query(RawTransaction).filter(RawTransaction.id == txn_uuid).first()
        rc = session.query(RiskCase).filter(RiskCase.transaction_id == txn_uuid).first()
    else:
        txn = None
        rc = None

    if txn:
        fresh_status = detect(txn)
        if rc and fresh_status != rc.risk_status:
            flags.append(f"detect mismatch: fresh={fresh_status} vs stored={rc.risk_status}")

    return {
        **state,
        "case_id": str(rc.id) if rc else None,
        "risk_status": rc.risk_status if rc else None,
        "mismatch_flags": flags,
    }


def diagnose_node(state: CaseState) -> CaseState:
    session = state.get("_session")
    cache = state.get("_cache")
    flags = list(state.get("mismatch_flags", []))
    case_id_str = state.get("case_id")
    txn_id_str = str(state["transaction_id"])

    if not case_id_str:
        return {**state, "diagnosis": None, "mismatch_flags": flags}

    if cache:
        diag = cache["diagnoses"].get(case_id_str)
        rc = cache["cases"].get(txn_id_str)
        txn = cache["txns"].get(txn_id_str)
    elif session:
        case_uuid = uuid.UUID(case_id_str)
        diag = session.query(Diagnosis).filter(Diagnosis.case_id == case_uuid).first()
        rc = session.query(RiskCase).filter(RiskCase.id == case_uuid).first()
        txn = session.query(RawTransaction).filter(RawTransaction.id == rc.transaction_id).first() if rc else None
    else:
        diag = None
        rc = None
        txn = None

    diag_dict = None
    if diag:
        if diag.confidence_source == "rule" and rc and txn:
            fresh_diag = diagnose_rule_based(rc, txn)
            if not fresh_diag or fresh_diag.get("root_cause") != diag.root_cause:
                flags.append(f"diagnose mismatch: fresh={fresh_diag.get('root_cause') if fresh_diag else None} vs stored={diag.root_cause}")
        
        diag_dict = dict(
            root_cause=diag.root_cause,
            confidence_source=diag.confidence_source,
            reasoning=diag.reasoning,
        )

    return {
        **state,
        "diagnosis": diag_dict,
        "mismatch_flags": flags,
    }


def decide_and_enforce_node(state: CaseState) -> CaseState:
    session = state.get("_session")
    cache = state.get("_cache")
    flags = list(state.get("mismatch_flags", []))
    case_id_str = state.get("case_id")
    txn_id_str = str(state["transaction_id"])

    if not case_id_str:
        return {**state, "proposed_intervention": None, "final_intervention": None, "mismatch_flags": flags}

    if cache:
        rc = cache["cases"].get(txn_id_str)
        diag = cache["diagnoses"].get(case_id_str)
        txn = cache["txns"].get(txn_id_str)
        interv = cache["interventions"].get(case_id_str)
    elif session:
        case_uuid = uuid.UUID(case_id_str)
        rc = session.query(RiskCase).filter(RiskCase.id == case_uuid).first()
        diag = session.query(Diagnosis).filter(Diagnosis.case_id == case_uuid).first()
        txn = session.query(RawTransaction).filter(RawTransaction.id == rc.transaction_id).first() if rc else None
        interv = session.query(Intervention).filter(Intervention.case_id == case_uuid).first()
    else:
        rc = None
        diag = None
        txn = None
        interv = None

    proposed = None
    final_plan = None
    if rc and diag and txn:
        proposed = decide_intervention(rc, diag, txn)
        final_plan = enforce(proposed, rc, diag, txn, prior_attempts=0)

        if interv and final_plan.get("action_type") != interv.action_type:
            flags.append(f"decide mismatch: fresh={final_plan.get('action_type')} vs stored={interv.action_type}")

    return {
        **state,
        "proposed_intervention": proposed,
        "final_intervention": final_plan,
        "mismatch_flags": flags,
    }


def execute_node(state: CaseState) -> CaseState:
    session = state.get("_session")
    cache = state.get("_cache")
    case_id_str = state.get("case_id")

    if not case_id_str:
        return {**state, "execution_result": None}

    if cache:
        interv = cache["interventions"].get(case_id_str)
    elif session:
        case_uuid = uuid.UUID(case_id_str)
        interv = session.query(Intervention).filter(Intervention.case_id == case_uuid).first()
    else:
        interv = None

    exec_res = None
    if interv:
        exec_res = dict(
            status=interv.status,
            execution_mode=interv.execution_mode,
            idempotency_key=interv.idempotency_key,
            executed_at=interv.executed_at.isoformat() if interv.executed_at else None,
        )

    return {
        **state,
        "execution_result": exec_res,
    }


def resolve_node(state: CaseState) -> CaseState:
    session = state.get("_session")
    cache = state.get("_cache")
    rng = state.get("_rng") or random.Random(42)
    case_id_str = state.get("case_id")
    txn_id_str = str(state["transaction_id"])

    if not case_id_str:
        return {**state, "resolution": None}

    if cache:
        rc = cache["cases"].get(txn_id_str)
        txn = cache["txns"].get(txn_id_str)
        we = cache.get("we")
        existing_ro = cache["outcomes"].get(case_id_str)
    elif session:
        case_uuid = uuid.UUID(case_id_str)
        rc = session.query(RiskCase).filter(RiskCase.id == case_uuid).first()
        txn = session.query(RawTransaction).filter(RawTransaction.id == rc.transaction_id).first() if rc else None
        we = session.query(WebhookEvent).filter(WebhookEvent.razorpay_event_id == "TVB8GHU0GvhUjl").first()
        existing_ro = session.query(RecoveryOutcome).filter(RecoveryOutcome.case_id == case_uuid).first()
    else:
        rc = None
        txn = None
        we = None
        existing_ro = None

    # 1. Check real outcome bypass first
    real_res = get_real_outcome(case_id_str, rc, we, txn) if (rc and we and txn) else None

    if real_res:
        res = real_res
    else:
        if existing_ro:
            res = dict(
                outcome=existing_ro.outcome,
                amount_recovered=Decimal(str(existing_ro.amount_recovered)),
                time_to_recovery_hours=Decimal(str(existing_ro.time_to_recovery_hours)) if existing_ro.time_to_recovery_hours is not None else None,
                resolution_source=existing_ro.resolution_source,
                simulated_attempts=existing_ro.simulated_attempts,
                note="carried forward from existing DB outcome",
            )
        else:
            action_type = state["final_intervention"]["action_type"] if state.get("final_intervention") else "human_review"
            sim_res = simulate_lifecycle(action_type, txn.amount_inr, rng)
            sim_res["resolution_source"] = "simulated"
            res = sim_res

    # Record in cache or write queue for bulk insert
    if cache is not None and not existing_ro:
        now_utc = datetime.now(timezone.utc)
        case_uuid = uuid.UUID(case_id_str)
        ro_row = RecoveryOutcome(
            id=uuid.uuid4(),
            case_id=case_uuid,
            outcome=res["outcome"],
            amount_recovered=res["amount_recovered"],
            time_to_recovery_hours=res["time_to_recovery_hours"],
            resolution_source=res["resolution_source"],
            simulated_attempts=res.get("simulated_attempts"),
            resolved_at=now_utc,
        )
        event_payload = {
            "outcome": res["outcome"],
            "amount_recovered": float(res["amount_recovered"]),
            "resolution_source": res["resolution_source"],
            "simulated_attempts": res.get("simulated_attempts"),
            "time_to_recovery_hours": float(res["time_to_recovery_hours"]) if res.get("time_to_recovery_hours") is not None else None,
            "note": res.get("note", ""),
        }
        ce_row = CaseEvent(
            id=uuid.uuid4(),
            case_id=case_uuid,
            event_type="case_resolved",
            event_payload=json.dumps(event_payload),
            occurred_at=now_utc,
        )
        cache["pending_writes"].append((ro_row, ce_row))
    elif session and not existing_ro:
        now_utc = datetime.now(timezone.utc)
        case_uuid = uuid.UUID(case_id_str)
        ro_row = RecoveryOutcome(
            id=uuid.uuid4(),
            case_id=case_uuid,
            outcome=res["outcome"],
            amount_recovered=res["amount_recovered"],
            time_to_recovery_hours=res["time_to_recovery_hours"],
            resolution_source=res["resolution_source"],
            simulated_attempts=res.get("simulated_attempts"),
            resolved_at=now_utc,
        )
        session.add(ro_row)
        event_payload = {
            "outcome": res["outcome"],
            "amount_recovered": float(res["amount_recovered"]),
            "resolution_source": res["resolution_source"],
            "simulated_attempts": res.get("simulated_attempts"),
            "time_to_recovery_hours": float(res["time_to_recovery_hours"]) if res.get("time_to_recovery_hours") is not None else None,
            "note": res.get("note", ""),
        }
        ce_row = CaseEvent(
            id=uuid.uuid4(),
            case_id=case_uuid,
            event_type="case_resolved",
            event_payload=json.dumps(event_payload),
            occurred_at=now_utc,
        )
        session.add(ce_row)
        session.commit()

    return {
        **state,
        "resolution": res,
    }


def route_after_decide(state: CaseState) -> str:
    if state.get("final_intervention") and state["final_intervention"].get("action_type") == "human_review":
        return "resolve"
    return "execute"


# Graph construction
builder = StateGraph(CaseState)
builder.add_node("detect", detect_node)
builder.add_node("diagnose", diagnose_node)
builder.add_node("decide_enforce", decide_and_enforce_node)
builder.add_node("execute", execute_node)
builder.add_node("resolve", resolve_node)

builder.set_entry_point("detect")
builder.add_edge("detect", "diagnose")
builder.add_edge("diagnose", "decide_enforce")
builder.add_conditional_edges("decide_enforce", route_after_decide, {"execute": "execute", "resolve": "resolve"})
builder.add_edge("execute", "resolve")
builder.add_edge("resolve", END)

compiled_graph = builder.compile()
