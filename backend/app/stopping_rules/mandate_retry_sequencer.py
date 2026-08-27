"""
mandate_retry_sequencer.py — Day 5, Task 5
MandateRetrySequencer: Submodule for e-mandate retry cadence per RBI Digital Payments E-Mandate Framework 2026.
Called by StoppingRuleEngine specifically for mandate_expired cases —
kept separate from generic card-decline retry logic because e-mandate
rules (24h notice, AFA threshold, up to 8 attempts) are a distinct
regulatory regime.
"""
from datetime import datetime, timedelta, date


class MandateRetrySequencer:
    """RBI Digital Payments E-Mandate Framework 2026 compliant retry cadence."""

    MAX_ATTEMPTS = 8
    PRE_DEBIT_NOTICE_HOURS = 24

    def next_retry_slot(self, last_attempt_at, attempt_number: int) -> dict:
        """
        Determines next retry slot or returns human_review if attempts exhausted (> MAX_ATTEMPTS).
        """
        if attempt_number > self.MAX_ATTEMPTS:
            return dict(
                action_type="human_review",
                stopping_reason="mandate retry attempts exhausted"
            )

        earliest = None
        if isinstance(last_attempt_at, (datetime, date)):
            if isinstance(last_attempt_at, date) and not isinstance(last_attempt_at, datetime):
                last_attempt_at = datetime.combine(last_attempt_at, datetime.min.time())
            earliest = last_attempt_at + timedelta(hours=self.PRE_DEBIT_NOTICE_HOURS)

        return dict(
            action_type="mandate_retry_sequence",
            scheduled_not_before=earliest,
            attempt_number=attempt_number + 1,
            required_notice_hours=self.PRE_DEBIT_NOTICE_HOURS,
        )
