"""
webhooks.py — Day 6, Task 7
Razorpay Webhook receiver endpoint:
- Validates x-razorpay-signature header using RAZORPAY_WEBHOOK_SECRET
- Deduplicates using x-razorpay-event-id in webhook_events table
- Idempotent: returns {"status": "duplicate_ignored"} on repeated event_id
"""
import os
import hmac
import hashlib
import json
import logging
import ssl
from urllib.parse import urlparse, urlunparse
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
import uuid as _uuid

from app.models import WebhookEvent

logger = logging.getLogger(__name__)

router = APIRouter()

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    return datetime.now(IST)


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def get_async_session():
    raw_url = os.environ.get("DATABASE_URL", "")
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
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)()


@router.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")

    if not verify_signature(raw_body, signature, secret):
        logger.warning("Invalid webhook signature received")
        raise HTTPException(status_code=400, detail="invalid signature")

    event_id = request.headers.get("x-razorpay-event-id")
    if not event_id:
        raise HTTPException(status_code=400, detail="missing x-razorpay-event-id")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
        event_type = payload.get("event", "unknown")
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json payload")

    async with get_async_session() as session:
        # Check if event_id already exists (deduplication)
        result = await session.execute(
            select(WebhookEvent).where(WebhookEvent.razorpay_event_id == event_id)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            logger.info("Duplicate webhook event ignored: %s", event_id)
            return {"status": "duplicate_ignored"}

        try:
            webhook_obj = WebhookEvent(
                id=_uuid.uuid4(),
                razorpay_event_id=event_id,
                event_type=event_type,
                payload=raw_body.decode("utf-8"),
                received_at=now_ist(),
                processed=True,
            )
            session.add(webhook_obj)
            await session.commit()
        except IntegrityError:
            logger.info("Duplicate webhook event caught by DB constraint: %s", event_id)
            return {"status": "duplicate_ignored"}

    logger.info("Recorded webhook event: %s (%s)", event_id, event_type)
    return {"status": "received"}
