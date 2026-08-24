"""
load_to_db.py — Day 2, Task 4
Loads data/injected_batch.csv into raw_transactions on Neon dev.
Reads DATABASE_URL from backend/.env via python-dotenv.

Neon connection strings include sslmode=require&channel_binding=require which
asyncpg does not accept as query params — stripped, ssl passed via connect_args.
Date/datetime columns are parsed explicitly since CSV round-trips them as strings.
"""
import asyncio
import sys
import ssl
from pathlib import Path
from urllib.parse import urlparse, urlunparse
import pandas as pd
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv
from datetime import datetime, date, timezone, timedelta

# Ensure app package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv()

raw_url = os.environ["DATABASE_URL"]

# Rewrite scheme for asyncpg
if raw_url.startswith("postgresql://"):
    async_url = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif raw_url.startswith("postgres://"):
    async_url = raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
else:
    async_url = raw_url

# Strip ALL query params — asyncpg handles SSL via connect_args, not URL params
parsed = urlparse(async_url)
clean_url = urlunparse(parsed._replace(query=""))

from app.models import RawTransaction  # noqa: E402

ssl_ctx = ssl.create_default_context()
engine = create_async_engine(
    clean_url,
    echo=False,
    connect_args={"ssl": ssl_ctx},
)
Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

IST = timezone(timedelta(hours=5, minutes=30))


def parse_created_at(val):
    """Parse created_at string from CSV into a timezone-aware datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    # Try common formats
    for fmt in ("%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(str(val).strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=IST)
            return dt
        except ValueError:
            continue
    return None


def parse_invoice_due_date(val):
    """Parse invoice_due_date string from CSV into a date object."""
    if val is None:
        return None
    if isinstance(val, date):
        return val
    try:
        return datetime.strptime(str(val).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


async def load():
    df = pd.read_csv(Path(__file__).parents[1] / "data" / "injected_batch.csv")
    df = df.where(pd.notnull(df), None)

    async with Session() as session:
        for _, row in df.iterrows():
            row_dict = row.to_dict()

            # Parse temporal columns explicitly
            row_dict["created_at"] = parse_created_at(row_dict.get("created_at"))
            row_dict["invoice_due_date"] = parse_invoice_due_date(row_dict.get("invoice_due_date"))

            session.add(RawTransaction(**row_dict))

        await session.commit()

    print(f"Loaded {len(df)} rows into raw_transactions")


if __name__ == "__main__":
    asyncio.run(load())
