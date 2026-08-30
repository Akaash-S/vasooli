import json
import uuid
from decimal import Decimal
from typing import Optional, List, Dict, Any

from sqlalchemy import func
from app.models import (
    RawTransaction, RiskCase, Diagnosis, Intervention,
    RecoveryOutcome, CaseEvent, PromiseToPay
)

from app.metrics.calculations import (
    recovery_rate_pct,
    dollar_recovery_rate_pct,
    median_hours,
    mean_hours,
    derive_exception_reason,
)


def get_batch_summary(session) -> Dict[str, Any]:
    total_cases = session.query(RawTransaction).count()

    outcomes = session.query(RecoveryOutcome).all()
    recovered_count = sum(1 for r in outcomes if r.outcome == "recovered")
    escalated_count = sum(1 for r in outcomes if r.outcome == "escalated")
    abandoned_count = sum(1 for r in outcomes if r.outcome == "abandoned")

    total_risk_result = session.query(func.sum(RawTransaction.amount_inr)).scalar()
    total_amount_at_risk = Decimal(str(total_risk_result)) if total_risk_result else Decimal("0")

    total_rec_result = session.query(func.sum(RecoveryOutcome.amount_recovered)).filter(RecoveryOutcome.outcome == "recovered").scalar()
    total_amount_recovered = Decimal(str(total_rec_result)) if total_rec_result else Decimal("0")

    rec_times = [
        float(r.time_to_recovery_hours)
        for r in outcomes
        if r.outcome == "recovered" and r.time_to_recovery_hours is not None
    ]
    avg_hours = mean_hours(rec_times)
    med_hours = median_hours(rec_times)

    real_source_count = sum(1 for r in outcomes if r.resolution_source == "real")
    simulated_source_count = sum(1 for r in outcomes if r.resolution_source == "simulated")

    rec_rate = recovery_rate_pct(recovered_count, total_cases)
    dollar_rec_rate = dollar_recovery_rate_pct(total_amount_recovered, total_amount_at_risk)

    return {
        "total_cases": total_cases,
        "recovered_count": recovered_count,
        "escalated_count": escalated_count,
        "abandoned_count": abandoned_count,
        "recovery_rate_pct": rec_rate,
        "total_amount_at_risk": float(total_amount_at_risk),
        "total_amount_recovered": float(total_amount_recovered),
        "dollar_recovery_rate_pct": dollar_rec_rate,
        "avg_time_to_recovery_hours": avg_hours,
        "median_time_to_recovery_hours": med_hours,
        "by_resolution_source": {
            "real": real_source_count,
            "simulated": simulated_source_count,
        },
    }


def get_funnel(session) -> Dict[str, Any]:
    detected = session.query(RiskCase).count()
    diagnosed = session.query(Diagnosis).count()
    intervention_decided = session.query(Intervention).count()
    executed = session.query(Intervention).filter(Intervention.status == "executed").count()
    queued_for_human_review = session.query(Intervention).filter(Intervention.status == "queued").count()

    outcomes = session.query(RecoveryOutcome).all()
    resolved_tally = {
        "recovered": sum(1 for r in outcomes if r.outcome == "recovered"),
        "escalated": sum(1 for r in outcomes if r.outcome == "escalated"),
        "abandoned": sum(1 for r in outcomes if r.outcome == "abandoned"),
    }

    return {
        "detected": detected,
        "diagnosed": diagnosed,
        "intervention_decided": intervention_decided,
        "executed": executed,
        "queued_for_human_review": queued_for_human_review,
        "resolved": resolved_tally,
    }


def get_breakdown(session, by: str) -> List[Dict[str, Any]]:
    if by == "risk_status":
        rows = (
            session.query(
                RiskCase.risk_status.label("dimension"),
                RawTransaction.amount_inr,
                RecoveryOutcome.outcome,
                RecoveryOutcome.amount_recovered,
            )
            .join(RawTransaction, RawTransaction.id == RiskCase.transaction_id)
            .join(RecoveryOutcome, RecoveryOutcome.case_id == RiskCase.id)
            .all()
        )
    elif by == "root_cause":
        rows = (
            session.query(
                Diagnosis.root_cause.label("dimension"),
                RawTransaction.amount_inr,
                RecoveryOutcome.outcome,
                RecoveryOutcome.amount_recovered,
            )
            .join(RiskCase, RiskCase.id == Diagnosis.case_id)
            .join(RawTransaction, RawTransaction.id == RiskCase.transaction_id)
            .join(RecoveryOutcome, RecoveryOutcome.case_id == RiskCase.id)
            .all()
        )
    else:
        raise ValueError(f"Invalid breakdown dimension: {by}")

    group_map = {}
    for r in rows:
        dim = r.dimension
        if dim not in group_map:
            group_map[dim] = {
                "count": 0,
                "recovered_count": 0,
                "amount_at_risk": Decimal("0"),
                "amount_recovered": Decimal("0"),
            }
        group_map[dim]["count"] += 1
        group_map[dim]["amount_at_risk"] += Decimal(str(r.amount_inr))
        if r.outcome == "recovered":
            group_map[dim]["recovered_count"] += 1
            group_map[dim]["amount_recovered"] += Decimal(str(r.amount_recovered))

    result = []
    for dim, stats in sorted(group_map.items()):
        rec_rate = recovery_rate_pct(stats["recovered_count"], stats["count"])
        dollar_rate = dollar_recovery_rate_pct(stats["amount_recovered"], stats["amount_at_risk"])
        result.append({
            "dimension": dim,
            "count": stats["count"],
            "recovered_count": stats["recovered_count"],
            "recovery_rate_pct": rec_rate,
            "amount_at_risk": float(stats["amount_at_risk"]),
            "amount_recovered": float(stats["amount_recovered"]),
            "dollar_recovery_rate_pct": dollar_rate,
        })

    return result


def get_exception_list(session) -> Dict[str, Any]:
    rows = (
        session.query(
            RiskCase.id.label("case_id"),
            RawTransaction.id.label("transaction_id"),
            RiskCase.risk_status,
            Diagnosis.root_cause,
            Intervention.action_type,
            RecoveryOutcome.outcome,
            RawTransaction.amount_inr,
            RecoveryOutcome.simulated_attempts,
        )
        .join(RawTransaction, RawTransaction.id == RiskCase.transaction_id)
        .join(Diagnosis, Diagnosis.case_id == RiskCase.id)
        .join(Intervention, Intervention.case_id == RiskCase.id)
        .join(RecoveryOutcome, RecoveryOutcome.case_id == RiskCase.id)
        .filter(RecoveryOutcome.outcome != "recovered")
        .order_by(RiskCase.id)
        .all()
    )

    resolved_events = (
        session.query(CaseEvent.case_id, CaseEvent.event_payload)
        .filter(CaseEvent.event_type == "case_resolved")
        .all()
    )
    event_notes_map = {}
    for case_id, payload_str in resolved_events:
        try:
            p = json.loads(payload_str)
            if "note" in p and p["note"]:
                event_notes_map[str(case_id)] = p["note"]
        except Exception:
            pass

    real_note_count = 0
    fallback_count = 0
    cases_output = []

    for r in rows:
        c_id_str = str(r.case_id)
        note_from_event = event_notes_map.get(c_id_str)
        if note_from_event:
            real_note_count += 1
        else:
            fallback_count += 1

        is_p2p = (r.action_type == "promise_to_pay")
        reason = derive_exception_reason(
            outcome=r.outcome,
            action_type=r.action_type,
            simulated_attempts=r.simulated_attempts,
            resolution_note=note_from_event,
        )

        cases_output.append({
            "case_id": c_id_str,
            "transaction_id": str(r.transaction_id),
            "risk_status": r.risk_status,
            "root_cause": r.root_cause,
            "action_type": r.action_type,
            "outcome": r.outcome,
            "amount_at_risk": float(r.amount_inr),
            "simulated_attempts": r.simulated_attempts,
            "is_awaiting_due_date": is_p2p,
            "reason": reason,
        })

    return {
        "total": len(cases_output),
        "real_note_used": real_note_count,
        "fallback_used": fallback_count,
        "cases": cases_output,
    }


def get_case_audit_trail(session, case_id_str: str) -> Dict[str, Any]:
    try:
        case_uuid = uuid.UUID(case_id_str)
    except ValueError:
        return {"case_id": case_id_str, "events": []}

    events = (
        session.query(CaseEvent)
        .filter(CaseEvent.case_id == case_uuid)
        .order_by(CaseEvent.occurred_at.asc())
        .all()
    )

    formatted_events = []
    for e in events:
        try:
            payload_data = json.loads(e.event_payload)
        except Exception:
            payload_data = e.event_payload

        formatted_events.append({
            "event_type": e.event_type,
            "occurred_at": e.occurred_at.isoformat(),
            "payload": payload_data,
        })

    return {
        "case_id": case_id_str,
        "events": formatted_events,
    }


def list_cases(session, outcome: Optional[str] = None, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    query = (
        session.query(
            RiskCase.id.label("case_id"),
            RiskCase.risk_status,
            Diagnosis.root_cause,
            Intervention.action_type,
            RecoveryOutcome.outcome,
            RawTransaction.amount_inr,
        )
        .join(RawTransaction, RawTransaction.id == RiskCase.transaction_id)
        .join(Diagnosis, Diagnosis.case_id == RiskCase.id)
        .join(Intervention, Intervention.case_id == RiskCase.id)
        .join(RecoveryOutcome, RecoveryOutcome.case_id == RiskCase.id)
    )

    if outcome:
        query = query.filter(RecoveryOutcome.outcome == outcome)

    total = query.count()
    rows = query.order_by(RiskCase.id).offset(offset).limit(limit).all()

    cases_list = [
        {
            "case_id": str(r.case_id),
            "risk_status": r.risk_status,
            "root_cause": r.root_cause,
            "action_type": r.action_type,
            "outcome": r.outcome,
            "amount_inr": float(r.amount_inr),
        }
        for r in rows
    ]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "cases": cases_list,
    }
