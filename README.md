# Vasooli — Autonomous AI Revenue Recovery Agent

[![Build Status](https://img.shields.io/badge/Build-Passing-brightgreen)]()
[![Track](https://img.shields.io/badge/Razorpay_Buildathon-Track_03:_AI_Revenue_Recovery-blue)]()
[![Stack](https://img.shields.io/badge/Stack-FastAPI_%7C_LangGraph_%7C_Next.js_15_%7C_Neon_Postgres-teal)]()

**Vasooli** is an autonomous AI Revenue Recovery pipeline built for Razorpay's AI Buildathon Track 03 (AI Revenue Recovery). It systematically detects revenue at risk across payment failures, abandoned checkouts, failed recurring subscriptions, and overdue B2B invoices, diagnoses root causes via rule engines and LLM-assisted analysis, enforces strict compliance and ethical stopping rules, executes recovery interventions, and measures dollar recovery performance across transactional batches.

---

## Architecture

Vasooli is structured as a compiled 5-stage state graph operating over a relational ledger:

```mermaid
graph TD
    A[1. Detect Stage] -->|Flagged Risk Cases| B[2. Diagnose Stage]
    B -->|Rule / LLM Root Cause| C[3. Decide & Enforce Stage]
    C -->|Stopping Rules Passed| D[4. Execute Stage]
    C -->|Human Review Escalation| E[Human Review Queue]
    D -->|Interventions Triggered| F[5. Resolve Stage]
    E -->|Manual Context Note| F
    F -->|Recovery Outcomes & Metrics| G[Vasooli Dashboard]
```

### Core Pipeline Stages:
1. **Detect**: Scans raw transaction feeds (`raw_transactions`) for 4 revenue-at-risk patterns (`payment_failed`, `checkout_abandoned`, `subscription_failed`, `invoice_overdue`).
2. **Diagnose**: Classifies failure root causes using deterministic rule matching (e.g. decline codes) and LLM-assisted classification (`openai/gpt-oss-120b` via Groq) for ambiguous free-text notes into 7 standard root causes (`soft_decline`, `hard_decline`, `mandate_expired`, `subscription_halted`, `checkout_friction`, `b2b_dispute`, `unclear`).
3. **Decide & Enforce**: Maps root causes to intervention actions (`retry`, `update_payment_link`, `mandate_retry_sequence`, `nudge`, `promise_to_pay`, `human_review`) bounded by **StoppingRuleEngine** compliance checks.
4. **Execute**: Dispatches interventions via Razorpay API (Payment Links creation) or simulated execution drivers with budget caps and rate limiting.
5. **Resolve**: Tracks payment lifecycle outcomes, processes real Razorpay webhooks (`payment_link.paid`), and aggregates batch recovery analytics.

---

## Setup & Local Development

### Prerequisites
- Python 3.12+
- Node.js 20+ & npm 10+
- PostgreSQL database (or Neon serverless Postgres connection string)

### 1. Backend Setup
```bash
cd backend
python -m venv .venv
# On Windows: .venv\Scripts\activate | On Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Create `backend/.env`:
```env
DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require
GROQ_API_KEY=your_groq_api_key
RAZORPAY_KEY_ID=your_razorpay_key_id
RAZORPAY_KEY_SECRET=your_razorpay_key_secret
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret
```

Apply database migrations:
```bash
alembic upgrade head
```

Run backend server:
```bash
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend Setup
```bash
cd frontend
npm install
```

Create `frontend/.env.local`:
```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Run frontend dev server:
```bash
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) to view the Vasooli Operations Console.

---

## What We Built

- **Batch Ingestion & Detection**: Processed a 200-transaction test batch comprising 120 payment failures, 30 checkout abandonments, 30 subscription failures, and 20 overdue B2B invoices.
- **LangGraph State Orchestration**: Implemented deterministic state graph execution with conditional edge routing for human escalation.
- **Razorpay API Integration**: Integrated test-mode Payment Links creation and live webhook event processing (`/webhooks/razorpay`) featuring HMAC-SHA256 signature verification and idempotent deduplication.
- **Metrics & Operations Console**: Next.js 15 App Router dashboard rendering overview stats, 5-stage funnel visualization, root cause breakdown, exception queue with resolution notes, and case audit trails.

---

## Compliance & Ethical Stopping Rules

Vasooli natively enforces regulatory compliance and ethical collection rules via a dedicated **StoppingRuleEngine**:

1. **RBI E-Mandate Framework 2026**:
   - Enforces a 24-hour pre-debit notice requirement for automated recurring debits.
   - Mandates Additional Factor of Authentication (AFA) step-up for transaction amounts exceeding **₹15,000**.
2. **Hard Cap Retry Limits**:
   - Caps automated retry attempts to a maximum of **3 retries** per transaction.
   - Caps e-mandate retry sequences to **8 attempts** isolated to valid mandate windows.
3. **Ethical Off-Ramp (`CONSECUTIVE_FAILURE_HUMAN_REVIEW`)**:
   - Automatically downgrades any case encountering 2 consecutive failure attempts to `human_review` **before** reaching the hard cap, preventing customer harassment and dark-pattern retry loops.

---

## What We Measured

Across the 200-case evaluation batch:

| Metric | Measured Value |
| :--- | :--- |
| **Total Batch Cases** | 200 cases |
| **Total Amount at Risk** | ₹4,362,973.99 |
| **Total Amount Recovered** | **₹1,037,933.99** |
| **Recovered Case Count** | **104 cases** (52.0% recovery rate) |
| **Escalated Case Count** | **28 cases** (14.0%) |
| **Abandoned Case Count** | **68 cases** (34.0%) |
| **Dollar Recovery Rate** | **23.8%** |
| **Live Webhook Validated Case** | 1 real Razorpay test-mode payment (`pay_TVB82bULQTSobg`) |

---

## Limitations & What We'd Build Next

### Current Limitations:
1. **Synthetic B2B Ledger**: B2B invoice dataset is synthetically generated due to the absence of public Indian B2B payment failure benchmarks.
2. **Simulated Communication Drivers**: WhatsApp/SMS nudges and IVR voice outreach actions generate audit log entries rather than initiating live telecommunications provider calls.
3. **LLM Ambiguity Handling**: Non-deterministic LLM classification is strictly isolated to ambiguous free-text notes (`unclear` category) to protect overall pipeline determinism.

### Future Roadmap:
- **DPDP Act 2023 Compliance Layer**: Native consent management and explicit data-erasure handlers for customer PII.
- **Multilingual Hinglish Voice Agent**: Conversational AI voice assistant for automated outbound payment resolution calls.
- **NLP Promise-to-Pay Parser**: Automated extraction and validation of promise-to-pay commitment dates from customer chat responses.
