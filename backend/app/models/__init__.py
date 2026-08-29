from sqlalchemy import (Column, String, Numeric, Boolean, DateTime, Date,
                         ForeignKey, Text, Integer)
from sqlalchemy.orm import declarative_base
from sqlalchemy.dialects.postgresql import UUID
import uuid

Base = declarative_base()


class RawTransaction(Base):
    __tablename__ = "raw_transactions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String, nullable=False)           # 'olist' | 'synthetic_b2b'
    order_id = Column(String, nullable=False, unique=True)
    customer_id = Column(String)
    amount_inr = Column(Numeric(12, 2), nullable=False)
    payment_method = Column(String)                    # card | upi | netbanking | nach
    payment_status = Column(String, nullable=False)    # success | failed | pending
    decline_code = Column(String, nullable=True)
    failure_reason_text = Column(Text, nullable=True)
    checkout_completed = Column(Boolean, nullable=False, default=True)
    subscription_id = Column(String, nullable=True)
    subscription_status = Column(String, nullable=True)  # active | halted
    invoice_due_date = Column(Date, nullable=True)
    invoice_status = Column(String, nullable=True)       # paid | unpaid
    created_at = Column(DateTime(timezone=True), nullable=False)


class RiskCase(Base):
    __tablename__ = "risk_cases"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id = Column(UUID(as_uuid=True), ForeignKey("raw_transactions.id"), nullable=False)
    risk_status = Column(String, nullable=False)  # payment_failed | checkout_abandoned | subscription_failed | invoice_overdue
    detected_at = Column(DateTime(timezone=True), nullable=False)


class Diagnosis(Base):
    __tablename__ = "diagnoses"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("risk_cases.id"), nullable=False)
    root_cause = Column(String, nullable=False)
    confidence_source = Column(String, nullable=False)  # rule | llm
    reasoning = Column(Text)
    diagnosed_at = Column(DateTime(timezone=True), nullable=False)


class Intervention(Base):
    __tablename__ = "interventions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("risk_cases.id"), nullable=False)
    action_type = Column(String, nullable=False)  # retry | update_payment_link | nudge | escalate | human_review
    scheduled_at = Column(DateTime(timezone=True))
    attempt_number = Column(Integer, default=1)
    status = Column(String, nullable=False, default="pending")  # pending | executed | cancelled
    idempotency_key = Column(String, nullable=True, unique=True)
    executed_at = Column(DateTime(timezone=True), nullable=True)
    execution_mode = Column(String, nullable=True)  # 'real' | 'simulated'


class CaseEvent(Base):
    __tablename__ = "case_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("risk_cases.id"), nullable=False)
    event_type = Column(String, nullable=False)
    event_payload = Column(Text)   # JSON-serialized detail -- this IS the audit trail
    occurred_at = Column(DateTime(timezone=True), nullable=False)


class RecoveryOutcome(Base):
    __tablename__ = "recovery_outcomes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("risk_cases.id"), nullable=False)
    outcome = Column(String, nullable=False)  # recovered | escalated | abandoned
    amount_recovered = Column(Numeric(12, 2), default=0)
    time_to_recovery_hours = Column(Numeric(10, 2), nullable=True)
    resolved_at = Column(DateTime(timezone=True))
    resolution_source = Column(String, nullable=False, default="simulated")  # 'real' | 'simulated'
    simulated_attempts = Column(Integer, nullable=True)  # number of simulated retry rounds before terminal outcome, null for single-shot actions



class PromiseToPay(Base):
    __tablename__ = "promises_to_pay"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("risk_cases.id"), nullable=False)
    promised_date = Column(Date, nullable=False)
    promised_via = Column(String, nullable=False)  # 'email' | 'call' | 'portal'
    status = Column(String, nullable=False, default="pending")  # pending | honored | broken
    recorded_at = Column(DateTime(timezone=True), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    razorpay_event_id = Column(String, nullable=False, unique=True)  # x-razorpay-event-id header value
    event_type = Column(String, nullable=False)
    payload = Column(Text, nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False)
    processed = Column(Boolean, nullable=False, default=False)


