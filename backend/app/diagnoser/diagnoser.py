"""
diagnoser.py — Day 4
Diagnoser layer: determines root cause for each risk_case.

Two-path architecture:
  1. Rule-based (fast, no LLM): covers decline_code matches, subscription halts,
     and cases with no usable free text.
  2. LLM-assisted (Groq, structured tool-calling): only for checkout_abandoned or
     invoice_overdue cases that carry a failure_reason_text free-text note.

Root cause taxonomy (final enum for this stage):
  soft_decline       — decline_code in (insufficient_funds, bank_timeout, temporary_hold)
  hard_decline       — decline_code in (expired_card, card_closed)
  mandate_expired    — decline_code = invalid_mandate
  subscription_halted — risk_status = subscription_failed (rule-based; the halt IS the diagnosis)
  checkout_friction  — checkout_abandoned WITH free text, LLM-classified
  b2b_dispute        — invoice_overdue WITH free text, LLM-classified
  unclear            — no decline_code AND no usable failure_reason_text (rule-based fallback,
                       NEVER guessed by LLM)

`genuine_hardship` is explicitly out of scope for the Diagnoser — it is a Day 5
Stopping-Rule-level status derived from retry exhaustion, not a single-transaction diagnosis.
"""
import json
import os
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Rule-based path ───────────────────────────────────────────────────────────

DECLINE_CODE_MAP = {
    "insufficient_funds": "soft_decline",
    "bank_timeout": "soft_decline",
    "temporary_hold": "soft_decline",
    "expired_card": "hard_decline",
    "card_closed": "hard_decline",
    "invalid_mandate": "mandate_expired",
}

VALID_ROOT_CAUSES = {
    "soft_decline", "hard_decline", "mandate_expired",
    "subscription_halted", "checkout_friction", "b2b_dispute", "unclear",
}


def diagnose_rule_based(case, txn) -> Optional[dict]:
    """
    Rule-based diagnosis. Returns a dict with root_cause/confidence_source/reasoning,
    or None if the case must fall through to the LLM path.
    """
    # 1. decline_code → direct taxonomy match
    if txn.decline_code in DECLINE_CODE_MAP:
        return dict(
            root_cause=DECLINE_CODE_MAP[txn.decline_code],
            confidence_source="rule",
            reasoning=f"decline_code={txn.decline_code} matched known mapping",
        )

    # 2. Subscription halt — the halt status IS the diagnosis
    if case.risk_status == "subscription_failed":
        return dict(
            root_cause="subscription_halted",
            confidence_source="rule",
            reasoning="Razorpay native subscription halt after retry exhaustion",
        )

    # 3. No usable free text — unclear, never guess
    if not txn.failure_reason_text:
        return dict(
            root_cause="unclear",
            confidence_source="rule",
            reasoning="no decline_code and no failure_reason_text available",
        )

    # 4. Falls through to LLM path — checkout_abandoned or invoice_overdue WITH text
    return None


# ── LLM-assisted path ─────────────────────────────────────────────────────────

DIAGNOSIS_TOOL = {
    "type": "function",
    "function": {
        "name": "classify_root_cause",
        "description": "Classify the root cause of a revenue-risk case from its free-text note",
        "parameters": {
            "type": "object",
            "properties": {
                "root_cause": {
                    "type": "string",
                    "enum": ["checkout_friction", "b2b_dispute", "unclear"],
                },
                "reasoning": {"type": "string"},
            },
            "required": ["root_cause", "reasoning"],
        },
    },
}


def diagnose_llm(case, txn, client, latencies: list) -> dict:
    """
    LLM-assisted diagnosis using Groq structured tool-calling.
    tool_choice forces the function call — never falls back to free-text parsing.
    If the API returns a root_cause outside the valid enum, routes to 'unclear'.
    Appends per-call latency_ms to `latencies` list (caller owns the list).

    Return dict includes `llm_event_payload` — a pre-built dict the caller should
    use to write a separate `diagnosis_llm_call` CaseEvent row alongside the normal
    `case_diagnosed` event. This keeps model imports out of this module.
    """
    t0 = time.perf_counter()
    try:
        resp = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{
                "role": "user",
                "content": (
                    f"risk_status={case.risk_status}\n"
                    f"free_text_note: {txn.failure_reason_text}\n"
                    "Classify the root cause."
                ),
            }],
            tools=[DIAGNOSIS_TOOL],
            tool_choice={"type": "function", "function": {"name": "classify_root_cause"}},
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)
        latencies.append(latency_ms)

        args = json.loads(resp.choices[0].message.tool_calls[0].function.arguments)
        root_cause_returned = args.get("root_cause", "unclear")
        reasoning = args.get("reasoning", "")

        # Hard safety: if LLM returns a value outside the valid enum, route to unclear
        root_cause = root_cause_returned
        if root_cause not in VALID_ROOT_CAUSES:
            logger.warning("LLM returned unexpected root_cause=%r, routing to unclear", root_cause)
            root_cause = "unclear"

        return dict(
            root_cause=root_cause,
            confidence_source="llm",
            reasoning=reasoning,
            llm_event_payload={
                "latency_ms": latency_ms,
                "model": "openai/gpt-oss-120b",
                "root_cause_returned": root_cause_returned,
            },
        )

    except Exception as exc:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        latencies.append(latency_ms)
        logger.error("LLM call failed: %s — routing to unclear", exc)
        return dict(
            root_cause="unclear",
            confidence_source="rule",
            reasoning=f"LLM call failed: {type(exc).__name__}",
        )


def diagnose(case, txn, client, latencies: list) -> dict:
    """
    Entry point: tries rule-based first, falls through to LLM only when needed.
    Always returns a dict with root_cause, confidence_source, reasoning.
    """
    result = diagnose_rule_based(case, txn)
    if result is not None:
        return result
    return diagnose_llm(case, txn, client, latencies)
