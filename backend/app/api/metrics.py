import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.metrics import aggregations

router = APIRouter(prefix="/api")

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        raw_url = os.environ.get("DATABASE_URL", "sqlite:///:memory:")
        if "sslmode=" not in raw_url and "sqlite" not in raw_url:
            connect_args = {"sslmode": "require"}
        else:
            connect_args = {}
        _engine = create_engine(raw_url, connect_args=connect_args, echo=False)
    return _engine


def get_db():
    engine = get_engine()
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/metrics/summary")
def summary(db: Session = Depends(get_db)):
    return aggregations.get_batch_summary(db)


@router.get("/metrics/funnel")
def funnel(db: Session = Depends(get_db)):
    return aggregations.get_funnel(db)


@router.get("/metrics/breakdown")
def breakdown(
    by: str = Query(..., pattern="^(risk_status|root_cause)$"),
    db: Session = Depends(get_db),
):
    try:
        return aggregations.get_breakdown(db, by=by)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/cases/exceptions")
def exceptions(db: Session = Depends(get_db)):
    return aggregations.get_exception_list(db)


@router.get("/cases/{case_id}/audit-trail")
def audit_trail(case_id: str, db: Session = Depends(get_db)):
    return aggregations.get_case_audit_trail(db, case_id)


@router.get("/cases")
def list_cases(
    outcome: Optional[str] = Query(None, pattern="^(recovered|escalated|abandoned)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return aggregations.list_cases(db, outcome=outcome, limit=limit, offset=offset)
